"""Command line interface for the Ad Library scraper."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import platform
import sys
from typing import Any

from .client import (
    AdsLibraryClient,
    AdsLibraryError,
    SORT_MODES,
    SearchFilters,
    load_cookies,
)
from .proxies import PROXY_SCHEMES

LIST_FIELDS = {
    "page_categories",
    "titles",
    "bodies",
    "cta_texts",
    "link_urls",
    "images",
    "video_thumbnails",
    "videos",
    "publisher_platforms",
    "targeted_or_reached_countries",
}


def httptoolkit_ca_path() -> str | None:
    system = platform.system()
    if system == "Darwin":
        candidate = os.path.expanduser("~/Library/Preferences/httptoolkit/ca.pem")
    elif system == "Windows":
        candidate = os.path.join(os.environ.get("APPDATA", ""), "httptoolkit", "ca.pem")
    else:
        candidate = os.path.expanduser("~/.config/httptoolkit/ca.pem")
    return candidate if os.path.exists(candidate) else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ads-library-scraper",
        description="Scrape the public Facebook Ad Library through its GraphQL API.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--country", default="US", help="Two-letter country code (default: US)")
        target.add_argument(
            "--active-status",
            default="active",
            choices=["active", "inactive", "all"],
            help="Ad status filter (default: active)",
        )
        target.add_argument(
            "--ad-type",
            default="all",
            choices=["all", "political_and_issue_ads"],
            help="Ad type filter (default: all)",
        )
        target.add_argument(
            "--media-type",
            default="all",
            choices=["all", "image", "video", "meme"],
            help="Creative type filter (default: all)",
        )
        target.add_argument("--start-date", help="Only ads started after this date (YYYY-MM-DD)")
        target.add_argument(
            "--sort-mode",
            default="total_impressions",
            choices=sorted(SORT_MODES),
            help="Result ordering (default: total_impressions)",
        )
        target.add_argument(
            "--sort-direction",
            default="desc",
            choices=["desc", "asc"],
            help="Sort direction (default: desc)",
        )
        target.add_argument("--limit", type=int, help="Maximum number of ads to return")
        target.add_argument("--max-pages", type=int, help="Maximum number of result pages")
        target.add_argument("--page-size", type=int, default=10, help="Ads per GraphQL page")
        target.add_argument("--doc-id", help="Override the pagination GraphQL doc_id")
        target.add_argument("--cookies", metavar="PATH", help="cookies.txt or JSON cookies to reuse")
        target.add_argument(
            "--proxy",
            action="append",
            metavar="URL",
            help=(
                "Proxy URL or host:port, repeatable; schemes: "
                + ", ".join(sorted(PROXY_SCHEMES))
                + ". Use 'env' to read HTTPS_PROXY/ALL_PROXY."
            ),
        )
        target.add_argument(
            "--proxy-file",
            action="append",
            metavar="PATH",
            help="File with one proxy per line (repeatable)",
        )
        target.add_argument(
            "--proxy-strategy",
            default="round_robin",
            choices=["round_robin", "random"],
            help="Order in which proxies are tried (default: round_robin)",
        )
        target.add_argument(
            "--proxy-user",
            metavar="USER:PASS",
            help="Proxy credentials when they are not part of the proxy URL",
        )
        target.add_argument(
            "--ignore-env-proxy",
            action="store_true",
            help="Do not fall back to HTTP(S)_PROXY / ALL_PROXY environment variables",
        )
        target.add_argument(
            "--ca",
            metavar="PATH",
            help="CA bundle to trust (e.g. an intercepting proxy's CA)",
        )
        target.add_argument(
            "--httptoolkit",
            action="store_true",
            help="Route requests through HTTP Toolkit (127.0.0.1:8000 + its CA)",
        )
        target.add_argument("-v", "--verbose", action="store_true", help="Log proxy and retry activity")
        target.add_argument(
            "--impersonate",
            default="chrome",
            help="curl_cffi browser profile (default: chrome)",
        )
        target.add_argument(
            "--chrome-version",
            default="157",
            help="Chrome major version advertised in the UA/client hints (default: 157)",
        )
        target.add_argument("--user-agent", help="Override the Chrome user agent string")
        target.add_argument(
            "--delay",
            type=float,
            default=1.0,
            help="Seconds to wait between pages (default: 1)",
        )
        target.add_argument(
            "--retries",
            type=int,
            default=5,
            help="Retries when Facebook rate limits pagination (default: 5)",
        )
        target.add_argument("--jsonl", metavar="PATH", help="Write results as JSON Lines")
        target.add_argument("--csv", metavar="PATH", help="Write results as CSV")
        target.add_argument("--pretty", action="store_true", help="Pretty-print JSON to stdout")

    search = sub.add_parser("search", help="Search ads by keyword")
    search.add_argument("query", help="Keyword to search for")
    search.add_argument(
        "--search-type",
        default="keyword_unordered",
        choices=["keyword_unordered", "keyword_exact"],
        help="Keyword matching mode (default: keyword_unordered)",
    )
    add_common(search)

    page = sub.add_parser("page", help="Get ads from one advertiser (page id)")
    page.add_argument("page_id", help="Facebook page id")
    add_common(page)

    return parser


def _csv_value(value: Any) -> Any:
    if isinstance(value, list):
        return " | ".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_jsonl(rows: list[dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(rows: list[dict[str, Any]], path: str) -> None:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in columns})


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

    proxy_sources: list[str] = list(args.proxy or [])
    for path in args.proxy_file or []:
        proxy_sources.append(path)

    verify: str | bool = args.ca or True
    if args.httptoolkit:
        proxy_sources.insert(0, "http://127.0.0.1:8000")
        ca_path = httptoolkit_ca_path()
        if ca_path and verify is True:
            verify = ca_path
        elif not ca_path:
            print(
                "warning: HTTP Toolkit CA not found; pass --ca or use --proxy manually",
                file=sys.stderr,
            )

    proxy_auth = None
    if args.proxy_user:
        if ":" not in args.proxy_user:
            print("error: --proxy-user must be USER:PASS", file=sys.stderr)
            return 2
        user, password = args.proxy_user.split(":", 1)
        proxy_auth = (user, password)

    cookies = load_cookies(args.cookies) if args.cookies else None

    try:
        client = AdsLibraryClient(
            impersonate=args.impersonate,
            proxies=proxy_sources or None,
            proxy_strategy=args.proxy_strategy,
            proxy_auth=proxy_auth,
            trust_env=not args.ignore_env_proxy,
            verify=verify,
            cookies=cookies,
            request_delay=args.delay,
            rate_limit_retries=args.retries,
            doc_id=args.doc_id,
            user_agent=args.user_agent,
            chrome_version=args.chrome_version,
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    filters = {
        "country": args.country,
        "active_status": args.active_status,
        "ad_type": args.ad_type,
        "media_type": args.media_type,
        "start_date": args.start_date,
        "sort_mode": args.sort_mode,
        "sort_direction": args.sort_direction,
    }

    try:
        if args.command == "search":
            search_filters = SearchFilters(
                query=args.query, search_type=args.search_type, **filters
            )
        else:
            search_filters = SearchFilters(
                search_type="page", view_all_page_id=str(args.page_id), **filters
            )

        rows: list[dict[str, Any]] = []
        for page in client.iter_pages(
            search_filters,
            limit=args.limit,
            max_pages=args.max_pages,
            page_size=args.page_size,
        ):
            rows.extend(page)
            print(f"\r{len(rows)} ads captured", end="", file=sys.stderr, flush=True)
        if args.limit:
            rows = rows[: args.limit]
        if rows:
            print("", file=sys.stderr)
    except AdsLibraryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130

    if args.jsonl:
        write_jsonl(rows, args.jsonl)
    if args.csv:
        write_csv(rows, args.csv)

    if not args.jsonl and not args.csv:
        if args.pretty:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                print(json.dumps(row, ensure_ascii=False))

    advertisers = {row.get("page_name") for row in rows if row.get("page_name")}
    print(
        f"{len(rows)} ads from {len(advertisers)} advertisers",
        file=sys.stderr,
    )
    return 0
