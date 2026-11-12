"""A small curl_cffi client for the Facebook Ad Library.

It talks to the same endpoints the website uses:

* ``GET /ads/library/`` - HTML shell with cookies, the ``lsd`` token and the
  server-rendered first page of results.
* ``POST /api/graphql/`` - ``AdLibrarySearchPaginationQuery`` for every
  following page (doc_id is resolved dynamically when needed).
"""

from __future__ import annotations

import json
import logging
import random
import re
import secrets
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import urlencode

from curl_cffi import requests
from curl_cffi.requests.exceptions import (
    ConnectionError as CurlConnectionError,
    ProxyError as CurlProxyError,
    Timeout as CurlTimeout,
)

from .parsing import (
    BASE_URL,
    connection_ads,
    operation_doc_id,
    parse_initial_results,
    parse_json_payload,
)
from .proxies import Proxy, ProxyPool, load_proxies

ADS_LIBRARY_URL = f"{BASE_URL}/ads/library/"
GRAPHQL_URL = f"{BASE_URL}/api/graphql/"

ROOT_QUERY = "AdLibraryFoundationRootQuery"
PAGINATION_QUERY = "AdLibrarySearchPaginationQuery"
PAGINATION_DOC_ID = "29554948227445166"
RATE_LIMIT_CODE = 1675004

# A current desktop Chrome fingerprint. Facebook throttles pagination for stale
# or incomplete client hints, so these are sent with every request and can be
# overridden through the constructor / CLI.
DEFAULT_CHROME_VERSION = "157"
DEFAULT_CHROME_FULL_VERSION = "157.0.8103.51"
DEFAULT_PLATFORM_VERSION = "26.5.2"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) HeadlessChrome/157.0.0.0 Safari/537.36"
)

SORT_MODES = {
    "total_impressions": "SORT_BY_TOTAL_IMPRESSIONS",
    "time_active": "SORT_BY_TIME_ACTIVE",
    "relevancy_monthly_grouped": "SORT_BY_RELEVANCY_MONTHLY_GROUPED",
}


def browser_headers(
    user_agent: str | None = None,
    chrome_version: str = DEFAULT_CHROME_VERSION,
    chrome_full_version: str = DEFAULT_CHROME_FULL_VERSION,
    platform: str = "macOS",
    platform_version: str = DEFAULT_PLATFORM_VERSION,
) -> dict[str, str]:
    """Client hint headers matching ``user_agent``."""
    major = chrome_version
    if user_agent is None:
        user_agent = DEFAULT_USER_AGENT.replace(
            f"/{DEFAULT_CHROME_VERSION}.0.0.0", f"/{major}.0.0.0"
        )
    return {
        "user-agent": user_agent,
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": f'"Not-A.Brand";v="99", "Google Chrome";v="{major}", "Chromium";v="{major}"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": f'"{platform}"',
        "sec-ch-ua-platform-version": f'"{platform_version}"',
        "sec-ch-ua-model": '""',
        "sec-ch-ua-full-version-list": (
            f'"Not-A.Brand";v="99.0.0.0", "Google Chrome";v="{chrome_full_version}", '
            f'"Chromium";v="{chrome_full_version}"'
        ),
        "sec-ch-prefers-color-scheme": "light",
    }


class AdsLibraryError(RuntimeError):
    """Base error for the Ad Library client."""


class BlockedError(AdsLibraryError):
    """Facebook answered with a challenge or a login wall we could not pass."""


class RateLimitedError(AdsLibraryError):
    """The Ad Library throttled this session."""


class ProxyConnectionError(AdsLibraryError):
    """The active proxy could not carry the request."""


logger = logging.getLogger("ads_library")


@dataclass
class PageTokens:
    lsd: str
    spin_r: str
    spin_b: str
    spin_t: str
    hsi: str | None = None
    jazoest: str | None = None
    revision: str | None = None
    haste_session: str | None = None
    version: str | None = None
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class SearchFilters:
    query: str | None = None
    country: str = "US"
    active_status: str = "active"
    ad_type: str = "all"
    media_type: str = "all"
    search_type: str = "keyword_unordered"
    page_ids: list[str] = field(default_factory=list)
    view_all_page_id: str | None = None
    start_date: str | None = None
    sort_mode: str = "total_impressions"
    sort_direction: str = "desc"
    page_size: int = 10

    @property
    def is_page_search(self) -> bool:
        return self.search_type == "page" or bool(self.page_ids or self.view_all_page_id)

    def url_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "active_status": self.active_status,
            "ad_type": self.ad_type,
            "country": self.country,
            "is_targeted_country": "false",
            "media_type": self.media_type,
            "search_type": self.search_type,
            "sort_data[mode]": self.sort_mode,
            "sort_data[direction]": self.sort_direction,
        }
        if self.query:
            params["q"] = self.query
        if self.view_all_page_id:
            params["view_all_page_id"] = self.view_all_page_id
        elif self.page_ids:
            params["view_all_page_id"] = self.page_ids[0]
        if self.start_date:
            params["start_date"] = self.start_date
        return params

    def graphql_variables(self, tokens: PageTokens, cursor: str | None) -> dict[str, Any]:
        sort_data = None
        mode = SORT_MODES.get(self.sort_mode)
        if mode:
            sort_data = {
                "direction": "DESCENDING"
                if self.sort_direction.lower() == "desc"
                else "ASCENDING",
                "mode": mode,
            }
        return {
            "activeStatus": self.active_status,
            "adType": self.ad_type.upper(),
            "bylines": [],
            "collationToken": None,
            "contentLanguages": [],
            "countries": [self.country],
            "cursor": cursor,
            "excludedIDs": None,
            "first": self.page_size,
            "isTargetedCountry": False,
            "location": None,
            "mediaType": self.media_type,
            "multiCountryFilterMode": None,
            "pageIDs": self.page_ids,
            "potentialReachInput": None,
            "publisherPlatforms": [],
            "queryString": self.query or "",
            "regions": None,
            "searchType": self.search_type,
            "sessionID": tokens.session_id,
            "sortData": sort_data,
            "source": None,
            "startDate": self.start_date,
            "v": tokens.version,
            "viewAllPageID": self.view_all_page_id
            or (self.page_ids[0] if self.page_ids else "0"),
        }


def _first(pattern: str, text: str, default: str | None = None) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else default


def load_cookies(path: str) -> dict[str, str]:
    """Load cookies from a Netscape ``cookies.txt`` or a JSON object/array."""
    with open(path, encoding="utf-8") as handle:
        raw = handle.read()
    stripped = raw.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict):
            if "cookies" in data and isinstance(data["cookies"], list):
                data = data["cookies"]
            else:
                return {str(k): str(v) for k, v in data.items()}
        cookies: dict[str, str] = {}
        for item in data:
            if isinstance(item, dict) and item.get("name"):
                cookies[str(item["name"])] = str(item.get("value", ""))
        return cookies

    cookies = {}
    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5]] = parts[6]
    return cookies


class AdsLibraryClient:
    """Scrape public ads from the Facebook Ad Library.

    >>> client = AdsLibraryClient()
    >>> ads = client.search("nike", limit=30)
    """

    def __init__(
        self,
        *,
        impersonate: str = "chrome",
        proxy: str | None = None,
        proxies: str | Iterable[str] | None = None,
        proxy_strategy: str = "round_robin",
        proxy_auth: tuple[str, str] | None = None,
        trust_env: bool = True,
        verify: str | bool = True,
        timeout: float = 60.0,
        request_delay: float = 1.0,
        rate_limit_retries: int = 5,
        rate_limit_base_delay: float = 20.0,
        doc_id: str | None = None,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        user_agent: str | None = None,
        chrome_version: str = DEFAULT_CHROME_VERSION,
        chrome_full_version: str = DEFAULT_CHROME_FULL_VERSION,
        platform: str = "macOS",
        platform_version: str = DEFAULT_PLATFORM_VERSION,
    ) -> None:
        sources: list[str] = []
        if proxy:
            sources.append(proxy)
        if proxies is not None:
            if isinstance(proxies, str):
                sources.append(proxies)
            else:
                sources.extend(proxies)
        self.proxy_pool = ProxyPool(
            load_proxies(sources), strategy=proxy_strategy
        )
        self.current_proxy: Proxy | None = None

        kwargs: dict[str, Any] = {
            "impersonate": impersonate,
            "timeout": timeout,
            "trust_env": trust_env,
        }
        if proxy_auth:
            kwargs["proxy_auth"] = proxy_auth
        if verify is not True:
            kwargs["verify"] = verify
        self.session = requests.Session(**kwargs)
        self._apply_proxy(self.proxy_pool.lease())
        self.session.headers.update(
            browser_headers(
                user_agent=user_agent,
                chrome_version=chrome_version,
                chrome_full_version=chrome_full_version,
                platform=platform,
                platform_version=platform_version,
            )
        )
        if cookies:
            for name, value in cookies.items():
                self.session.cookies.set(name, value, domain=".facebook.com")
        if headers:
            self.session.headers.update(headers)

        self.timeout = timeout
        self.request_delay = request_delay
        self.rate_limit_retries = rate_limit_retries
        self.rate_limit_base_delay = rate_limit_base_delay
        self.doc_id = doc_id or PAGINATION_DOC_ID

        self._tokens: PageTokens | None = None
        self._filters: SearchFilters | None = None
        self._referer: str = ADS_LIBRARY_URL
        self._landing_html: str = ""
        self._request_counter = 0

    # --------------------------------------------------------------- proxying

    def _apply_proxy(self, proxy: Proxy | None) -> None:
        self.current_proxy = proxy
        if proxy is None:
            self.session.proxies = {}
        else:
            self.session.proxies = {"all": proxy.url}
            logger.info("using proxy %s", proxy.masked)

    def _reset_session(self) -> None:
        """Forget cookies and tokens so the next request starts a new session."""
        self.session.cookies.clear()
        self._tokens = None
        self._filters = None
        self._referer = ADS_LIBRARY_URL
        self._landing_html = ""
        self._request_counter = 0

    def use_next_proxy(self) -> bool:
        """Switch to the next untried proxy. Returns False when the pool is exhausted."""
        if not self.proxy_pool:
            return False
        proxy = self.proxy_pool.rotate()
        if proxy is None:
            logger.error("all proxies failed")
            return False
        self._apply_proxy(proxy)
        self._reset_session()
        return True

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        try:
            return self.session.request(method, url, **kwargs)
        except (CurlProxyError, CurlConnectionError, CurlTimeout) as exc:
            if self.current_proxy is not None:
                raise ProxyConnectionError(
                    f"proxy {self.current_proxy.masked} failed: {exc}"
                ) from exc
            raise AdsLibraryError(f"network error: {exc}") from exc

    # ------------------------------------------------------------------ HTTP

    def _solve_challenge(self, html: str, referer: str) -> bool:
        match = re.search(r"fetch\('([^']+)'", html)
        if not match:
            return False
        challenge_url = match.group(1)
        if challenge_url.startswith("/"):
            challenge_url = BASE_URL + challenge_url
        for attempt in range(2):
            response = self._request(
                "POST",
                challenge_url,
                headers={
                    "referer": referer,
                    "content-type": "application/x-www-form-urlencoded",
                },
                timeout=self.timeout,
            )
            if response.status_code != 429:
                return response.status_code < 400
            if attempt == 0:
                time.sleep(10)
        raise RateLimitedError("Facebook rate limited the challenge endpoint (HTTP 429)")

    def _get(self, url: str, *, params: dict[str, str] | None = None) -> str:
        last_status = None
        for _ in range(5):
            response = self._request("GET", url, params=params, timeout=self.timeout)
            last_status = response.status_code
            final_url = str(response.url)
            if response.status_code == 407:
                raise ProxyConnectionError(
                    f"proxy {self.current_proxy.masked if self.current_proxy else ''} "
                    "requires authentication (HTTP 407)"
                )
            if re.search(r"/(login|checkpoint)(/|\?|$)", final_url):
                raise BlockedError(
                    "Facebook redirected to a login page. Pass browser cookies with --cookies."
                )
            if response.status_code == 200:
                return response.text
            if response.status_code == 403 and "__rd_verify" in response.text:
                if self._solve_challenge(response.text, final_url):
                    continue
            if response.status_code == 429:
                time.sleep(self.rate_limit_base_delay)
                last_status = 429
                continue
            break
        if last_status == 429:
            raise RateLimitedError(f"Facebook rate limited {url} (HTTP 429)")
        raise BlockedError(
            f"Could not load {url} (last status {last_status}). "
            "Try a different --impersonate target or pass --cookies."
        )

    def _warmup(self, filters: SearchFilters) -> None:
        params = filters.url_params()
        self._referer = f"{ADS_LIBRARY_URL}?{urlencode(params)}"
        html = self._get(ADS_LIBRARY_URL, params=params)
        self._landing_html = html
        self.session.cookies.set("dpr", "1", domain=".facebook.com")
        self.session.cookies.set("wd", "1440x757", domain=".facebook.com")

        lsd = _first(r'\["LSD",\[\],\{"token":"([^"]+)"\}', html)
        if not lsd:
            raise BlockedError("Could not find the lsd token in the Ad Library page.")
        spin_r = _first(r'"__spin_r":(\d+)', html, "0") or "0"
        spin_b = _first(r'"__spin_b":"([^"]+)"', html, "trunk") or "trunk"
        spin_t = _first(r'"__spin_t":(\d+)', html, "0") or "0"

        preloader = re.search(
            r'"preloaders":\[\{"actorID":"0","preloaderID":"[^"]+","queryID":"(\d+)",'
            r'"variables":(\{.*?\}),"queryName":"' + re.escape(ROOT_QUERY) + r'"',
            html,
        )
        version = None
        session_id = None
        if preloader:
            try:
                root_vars = json.loads(preloader.group(2))
            except json.JSONDecodeError:
                root_vars = {}
            version = root_vars.get("v")
            session_id = root_vars.get("sessionID")

        self._tokens = PageTokens(
            lsd=lsd,
            spin_r=spin_r,
            spin_b=spin_b,
            spin_t=spin_t,
            hsi=_first(r'"hsi":"(\d+)"', html),
            jazoest=_first(r"jazoest=(\d+)", html),
            revision=_first(r'"server_revision":(\d+)', html),
            haste_session=_first(r'"haste_session":"([^"]+)"', html),
            version=version,
            session_id=session_id or str(uuid.uuid4()),
        )
        self._filters = filters

    def _next_req(self) -> str:
        self._request_counter += 1
        number = self._request_counter
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        encoded = ""
        while number:
            number, remainder = divmod(number, 36)
            encoded = digits[remainder] + encoded
        return encoded or "1"

    def _graphql(self, friendly_name: str, variables: dict[str, Any]) -> dict[str, Any]:
        tokens = self._tokens
        assert tokens is not None

        data: dict[str, str] = {
            "av": "0",
            "__aaid": "0",
            "__user": "0",
            "__a": "1",
            "__req": self._next_req(),
            "dpr": "2",
            "__ccg": "GOOD",
            "lsd": tokens.lsd,
            "__comet_req": "94",
            "__spin_r": tokens.spin_r,
            "__spin_b": tokens.spin_b,
            "__spin_t": tokens.spin_t,
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": friendly_name,
            "server_timestamps": "true",
            "variables": json.dumps(variables, separators=(",", ":")),
            "doc_id": self.doc_id,
        }
        if tokens.jazoest:
            data["jazoest"] = tokens.jazoest
        if tokens.haste_session:
            data["__hs"] = tokens.haste_session
            data["__jssesw"] = "1"
        if tokens.hsi:
            data["__hsi"] = tokens.hsi
        if tokens.revision:
            data["__rev"] = tokens.revision

        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "x-fb-friendly-name": friendly_name,
            "x-fb-lsd": tokens.lsd,
            "x-asbd-id": "359341",
            "x-fb-entry-nonce": secrets.token_urlsafe(6),
            "origin": BASE_URL,
            "referer": self._referer,
            "accept": "*/*",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        }
        response = self._request(
            "POST", GRAPHQL_URL, data=data, headers=headers, timeout=self.timeout
        )
        if response.status_code == 407:
            raise ProxyConnectionError("proxy authentication failed (HTTP 407)")
        if response.status_code != 200:
            raise AdsLibraryError(f"GraphQL request failed with HTTP {response.status_code}")
        payload = parse_json_payload(response.text)
        errors = payload.get("errors") or []
        if errors:
            messages = "; ".join(str(item.get("message")) for item in errors)
            rate_limited = any(
                "rate limit" in str(item.get("message", "")).lower()
                or item.get("code") == RATE_LIMIT_CODE
                for item in errors
            )
            if rate_limited:
                raise RateLimitedError(messages)
            raise AdsLibraryError(messages)
        return payload

    # --------------------------------------------------------------- discovery

    def discover_pagination_doc_id(self) -> str | None:
        """Resolve the current ``AdLibrarySearchPaginationQuery`` doc_id from JS bundles."""
        if not self._landing_html:
            self._landing_html = self._get(ADS_LIBRARY_URL)
        urls = set(
            re.findall(
                r'https://static\.xx\.fbcdn\.net/rsrc\.php/[^"\'\\ ]+?\.js',
                self._landing_html,
            )
        )
        for url in sorted(urls, key=len, reverse=True)[:12]:
            try:
                response = self._request("GET", url, timeout=self.timeout)
            except ProxyConnectionError:
                raise
            except Exception:
                continue
            if response.status_code != 200:
                continue
            found = operation_doc_id(response.text, PAGINATION_QUERY)
            if found:
                self.doc_id = found
                return found
        return None

    # ----------------------------------------------------------------- search

    def _fetch_page(self, filters: SearchFilters, cursor: str | None) -> dict[str, Any]:
        tokens = self._tokens
        assert tokens is not None
        variables = filters.graphql_variables(tokens, cursor)

        attempt = 0
        discovered = False
        while True:
            try:
                payload = self._graphql(PAGINATION_QUERY, variables)
                break
            except RateLimitedError:
                if attempt >= self.rate_limit_retries:
                    raise
                wait = self.rate_limit_base_delay * (1.5**attempt)
                wait += random.uniform(0, 5)
                time.sleep(wait)
                attempt += 1
            except ProxyConnectionError:
                raise
            except AdsLibraryError:
                if discovered or not self.discover_pagination_doc_id():
                    raise
                discovered = True
                variables = filters.graphql_variables(tokens, cursor)

        connection = (
            payload.get("data", {}).get("ad_library_main", {}).get("search_results_connection")
        )
        if connection is None:
            raise AdsLibraryError("Ad Library returned no search_results_connection.")
        return connection

    def iter_pages(
        self,
        filters: SearchFilters,
        *,
        limit: int | None = None,
        max_pages: int | None = None,
        page_size: int = 10,
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of flattened ads, failing over between proxies if needed."""
        seen: set[str] = set()
        yielded = 0
        pages = 0

        while True:
            try:
                for page in self._iter_pages_once(filters, seen, page_size):
                    if limit is not None:
                        remaining = limit - yielded
                        if remaining <= 0:
                            return
                        page = page[:remaining]
                    if not page:
                        continue
                    yielded += len(page)
                    pages += 1
                    yield page
                    if limit is not None and yielded >= limit:
                        return
                    if max_pages is not None and pages >= max_pages:
                        return
                return
            except (ProxyConnectionError, RateLimitedError) as exc:
                logger.warning("%s", exc)
                if not self.use_next_proxy():
                    raise

    def _iter_pages_once(
        self,
        filters: SearchFilters,
        seen: set[str],
        page_size: int,
    ) -> Iterator[list[dict[str, Any]]]:
        if self._tokens is None or self._filters != filters:
            self._warmup(filters)
        filters.page_size = page_size

        cursor: str | None = None
        initial = parse_initial_results(self._landing_html)

        if initial and (initial.get("edges") or initial.get("page_info")):
            ads = []
            for ad in connection_ads(initial):
                if ad["ad_archive_id"] not in seen:
                    seen.add(ad["ad_archive_id"])
                    ads.append(ad)
            if ads:
                yield ads
            page_info = initial.get("page_info") or {}
            cursor = page_info.get("end_cursor") if page_info.get("has_next_page") else None

        while cursor is not None:
            if self.request_delay:
                time.sleep(self.request_delay)

            connection = self._fetch_page(filters, cursor)
            ads = []
            for ad in connection_ads(connection):
                key = ad["ad_archive_id"]
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                ads.append(ad)
            if ads:
                yield ads

            page_info = connection.get("page_info") or {}
            if not page_info.get("has_next_page"):
                return
            cursor = page_info.get("end_cursor") or None

    def iter_ads(
        self,
        query: str | None = None,
        *,
        limit: int | None = None,
        max_pages: int | None = None,
        page_size: int = 10,
        **filters: Any,
    ) -> Iterator[dict[str, Any]]:
        """Yield individual ads for a keyword search, page by page."""
        search_filters = SearchFilters(query=query, **filters)
        for page in self.iter_pages(
            search_filters, limit=limit, max_pages=max_pages, page_size=page_size
        ):
            yield from page

    def iter_advertiser_ads(
        self,
        page_id: str,
        *,
        limit: int | None = None,
        max_pages: int | None = None,
        page_size: int = 10,
        **filters: Any,
    ) -> Iterator[dict[str, Any]]:
        """Yield individual ads for one Facebook page."""
        search_filters = SearchFilters(
            query=filters.pop("query", None),
            search_type="page",
            view_all_page_id=str(page_id),
            **filters,
        )
        for page in self.iter_pages(
            search_filters, limit=limit, max_pages=max_pages, page_size=page_size
        ):
            yield from page

    def search(
        self,
        query: str | None = None,
        *,
        limit: int | None = None,
        max_pages: int | None = None,
        page_size: int = 10,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` ads for a keyword search."""
        return list(
            self.iter_ads(
                query,
                limit=limit,
                max_pages=max_pages,
                page_size=page_size,
                **filters,
            )
        )

    def advertiser(
        self,
        page_id: str,
        *,
        limit: int | None = None,
        max_pages: int | None = None,
        page_size: int = 10,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """Return ads run by a Facebook page."""
        return list(
            self.iter_advertiser_ads(
                page_id,
                limit=limit,
                max_pages=max_pages,
                page_size=page_size,
                **filters,
            )
        )

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> AdsLibraryClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
