"""Parsing helpers for Facebook Ad Library payloads.

The Ad Library ships two shapes of the same data:

* server-rendered JSON embedded in the HTML (first page only), and
* GraphQL JSON returned by ``/api/graphql/`` (pagination).

Both contain a ``search_results_connection`` object whose ``edges`` hold
``collated_results``. This module turns those into flat, JSON/CSV friendly dicts.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable

BASE_URL = "https://www.facebook.com"

_JSON_START = re.compile(r'"search_results_connection"\s*:\s*')


def extract_balanced_json(text: str, start: int) -> str | None:
    """Return the balanced ``{...}`` object starting at/after ``start``."""
    index = text.find("{", start)
    if index == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for pos in range(index, len(text)):
        char = text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[index : pos + 1]
    return None


def parse_initial_results(html: str) -> dict[str, Any] | None:
    """Extract the server-rendered search results connection from the HTML."""
    best: dict[str, Any] | None = None
    for match in _JSON_START.finditer(html):
        raw = extract_balanced_json(html, match.end())
        if not raw:
            continue
        try:
            connection = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(connection, dict) or "edges" not in connection:
            continue
        if best is None or len(connection.get("edges") or []) > len(best.get("edges") or []):
            best = connection
    return best


def parse_json_payload(text: str) -> dict[str, Any]:
    """Parse GraphQL responses, which may contain several concatenated objects."""
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index] in " \r\n\t":
            index += 1
        if index >= length:
            break
        try:
            obj, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            break
        if isinstance(obj, dict):
            objects.append(obj)
    if not objects:
        raise ValueError("response is not valid JSON")
    for obj in objects:
        if "data" in obj:
            return obj
    return objects[0]


def operation_doc_id(js: str, operation: str) -> str | None:
    """Find the numeric doc_id of a Relay operation inside a JS bundle."""
    pattern = (
        re.escape(operation)
        + r'_facebookRelayOperation"[\s\S]{0,200}?exports\s*=\s*"(\d+)"'
    )
    match = re.search(pattern, js)
    if match:
        return match.group(1)
    pattern = (
        r'params\s*:\s*\{[^{}]*?id\s*:\s*[^,{}]*?,\s*[^{}]*?name\s*:\s*"'
        + re.escape(operation)
        + r'"'
    )
    return None


def _text(value: Any) -> str | None:
    """Snapshots store body/title either as a string or as ``{"text": ...}``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("text", "title", "body", "markup"):
            if value.get(key):
                return str(value[key]).strip() or None
    if isinstance(value, list):
        parts = [_text(item) for item in value]
        joined = " ".join(part for part in parts if part)
        return joined or None
    return str(value).strip() or None


def _iso(epoch: Any) -> str | None:
    try:
        stamp = int(epoch)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()


def _media_urls(items: Iterable[Any] | None, *keys: str) -> list[str]:
    urls: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            for key in keys:
                value = item.get(key)
                if isinstance(value, str) and value:
                    urls.append(value)
                    break
    return _unique(urls)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def flatten_ad(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten one ``collated_results`` entry into a single row."""
    snapshot = item.get("snapshot") or {}
    cards = snapshot.get("cards") or []
    page_name = snapshot.get("page_name") or item.get("page_name")

    titles = _unique(
        [_text(snapshot.get("title")) or ""]
        + [_text(card.get("title")) or "" for card in cards]
    )
    bodies = _unique(
        [_text(snapshot.get("body")) or ""]
        + [_text(card.get("body")) or "" for card in cards]
    )
    cta_texts = _unique(
        [snapshot.get("cta_text") or ""] + [card.get("cta_text") or "" for card in cards]
    )
    link_urls = _unique(
        [snapshot.get("link_url") or ""] + [card.get("link_url") or "" for card in cards]
    )

    images = _media_urls(
        cards,
        "original_image_url",
        "resized_image_url",
        "watermarked_resized_image_url",
    )
    images += _media_urls(snapshot.get("images"), "original_image_url", "resized_image_url", "url")

    videos = _media_urls(
        cards,
        "video_hd_url",
        "video_sd_url",
        "watermarked_video_hd_url",
        "watermarked_video_sd_url",
    )
    videos += _media_urls(snapshot.get("videos"), "video_hd_url", "video_sd_url")

    thumbnails = _unique(
        [card.get("video_preview_image_url") or "" for card in cards]
        + [video.get("video_preview_image_url") or "" for video in (snapshot.get("videos") or []) if isinstance(video, dict)]
    )

    ad_archive_id = str(item.get("ad_archive_id") or "")
    body = _text(snapshot.get("body")) or (bodies[0] if bodies else None)
    title = _text(snapshot.get("title")) or (titles[0] if titles else None)

    return {
        "ad_archive_id": ad_archive_id,
        "page_id": str(snapshot.get("page_id") or item.get("page_id") or ""),
        "page_name": page_name,
        "page_profile_uri": snapshot.get("page_profile_uri"),
        "page_profile_picture_url": snapshot.get("page_profile_picture_url"),
        "page_categories": snapshot.get("page_categories") or item.get("categories") or [],
        "page_like_count": snapshot.get("page_like_count"),
        "byline": snapshot.get("byline") or item.get("byline"),
        "disclaimer_label": snapshot.get("disclaimer_label"),
        "is_active": item.get("is_active"),
        "start_date": _iso(item.get("start_date")),
        "end_date": _iso(item.get("end_date")),
        "display_format": snapshot.get("display_format"),
        "cta_text": snapshot.get("cta_text") or (cta_texts[0] if cta_texts else None),
        "cta_type": snapshot.get("cta_type"),
        "caption": snapshot.get("caption"),
        "title": title,
        "body": body,
        "link_url": snapshot.get("link_url") or (link_urls[0] if link_urls else None),
        "link_description": _text(snapshot.get("link_description")),
        "titles": titles,
        "bodies": bodies,
        "cta_texts": cta_texts,
        "link_urls": link_urls,
        "images": images,
        "video_thumbnails": thumbnails,
        "videos": videos,
        "publisher_platforms": item.get("publisher_platform") or [],
        "currency": item.get("currency") or None,
        "spend": item.get("spend"),
        "impressions_text": (item.get("impressions_with_index") or {}).get("impressions_text"),
        "reach_estimate": item.get("reach_estimate"),
        "total_active_time": item.get("total_active_time"),
        "targeted_or_reached_countries": item.get("targeted_or_reached_countries") or [],
        "collation_count": item.get("collation_count"),
        "collation_id": item.get("collation_id"),
        "gated_type": item.get("gated_type"),
        "contains_digital_created_media": item.get("contains_digital_created_media"),
        "ad_snapshot_url": (
            f"{BASE_URL}/ads/archive/render_ad/?id={ad_archive_id}" if ad_archive_id else None
        ),
    }


def connection_ads(connection: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten every ad in a ``search_results_connection``."""
    ads: list[dict[str, Any]] = []
    for edge in (connection or {}).get("edges") or []:
        node = (edge or {}).get("node") or {}
        for item in node.get("collated_results") or []:
            if isinstance(item, dict):
                ads.append(flatten_ad(item))
    return ads


def connection_result_count(connection: dict[str, Any] | None) -> int | None:
    """Meta's approximate number of results for a search, when present."""
    if not connection:
        return None
    try:
        return int(connection.get("count"))
    except (TypeError, ValueError):
        return None
