# Facebook Ad Library scraper

A dependency-light scraper for the public [Meta Ad Library](https://www.facebook.com/ads/library/).
It replays the same HTTP calls the website makes, using
[`curl_cffi`](https://github.com/lexiforest/curl_cffi) to mimic a real Chrome TLS
fingerprint, and is designed to be debugged with [HTTP Toolkit](https://httptoolkit.com).

No browser automation and no API key: the client solves Facebook's lightweight
`__rd_verify` challenge, reads the `lsd`/`hsi`/`jazoest` tokens out of the landing
page, takes the first page of ads from the server-rendered HTML, then paginates
through the `AdLibrarySearchPaginationQuery` GraphQL operation.

## Install

```bash
uv sync                 # in this repo
pip install .           # as a package
uv build                # wheel + sdist in dist/
```

## Documentation

Full docs live in [`docs/`](docs/index.md):

| Page | Contents |
| --- | --- |
| [Library usage](docs/library.md) | Client API, `SearchFilters`, streaming, errors |
| [CLI](docs/cli.md) | Commands, every option, output modes |
| [Proxies](docs/proxies.md) | HTTP/HTTPS/SOCKS4/4a/5/5h, auth, lists, rotation, failover |
| [Data schema](docs/data.md) | All 39 output fields |
| [HTTP Toolkit](docs/http-toolkit.md) | Capture, compare and debug requests |
| [Troubleshooting](docs/troubleshooting.md) | 403 challenge, 429, `1675004`, stale doc ids |
| [Development](docs/development.md) | Tests, build, layout, release checklist |

## Library usage

The package works standalone — no CLI required:

```python
from ads_library import AdsLibraryClient, AdsLibraryError, RateLimitedError

with AdsLibraryClient() as client:                 # closes the HTTP session
    ads = client.search("nike", limit=100, country="US")
    print(len(ads), ads[0]["ad_archive_id"], ads[0]["page_name"])
    print("Meta reports", client.result_count, "matching ads")
```

Stream ads instead of materialising a list:

```python
client = AdsLibraryClient(request_delay=1.5)
for ad in client.iter_ads("running shoes", country="DE", media_type="video", limit=500):
    print(ad["ad_archive_id"], ad["start_date"], ad["body"])
```

One advertiser:

```python
ads = client.advertiser("113728961341467", country="ALL")
# or stream it
for ad in client.iter_advertiser_ads("113728961341467", country="ALL", limit=2000):
    ...
```

Paged access (memory-flat, exposes `page_info` semantics):

```python
from ads_library import SearchFilters

filters = SearchFilters(query="nike", country="US", media_type="all")
for page in client.iter_pages(filters, limit=200, page_size=10):
    ...
```

Proxies and rotation work the same as the CLI:

```python
client = AdsLibraryClient(
    proxies=[
        "socks5h://user:pass@10.0.0.5:1080",
        "http://user:pass@proxy.example:8080",
    ],
    proxy_strategy="random",
    verify="/path/to/intercepting-proxy-ca.pem",   # optional CA bundle
)
```

Error handling:

```python
try:
    ads = client.search("nike", limit=50)
except RateLimitedError as exc:
    ...   # Facebook returned 1675004/429 and retries were exhausted
except AdsLibraryError as exc:
    ...   # blocked, login wall, proxy exhausted, ...
```

Everything public is exported from `ads_library`:

```python
from ads_library import (
    AdsLibraryClient, SearchFilters, Proxy, ProxyPool, load_proxies, parse_proxy,
    flatten_ad, load_cookies, AdsLibraryError, RateLimitedError,
    ProxyConnectionError, BlockedError,
)
```

## CLI usage

```bash
# keyword search
uv run main.py search nike --limit 100

# only video ads in the EU, started after a date
uv run main.py search "running shoes" --country DE --media-type video --start-date 2025-01-01 --limit 200

# everything an advertiser is running (page id), worldwide
uv run main.py page 15087023444 --country ALL --limit 300

# page search sorted by impressions; also supports --sort-mode time_active
uv run main.py page 113728961341467 --country ALL --sort-mode total_impressions

# save to JSON Lines and CSV
uv run main.py search nike --limit 500 --jsonl nike.jsonl --csv nike.csv

# pretty JSON on stdout
uv run main.py search nike --limit 5 --pretty
```

Run `uv run main.py search --help` for every flag.

### Reusing a browser session

Logged-out sessions are fine for public ads, but Facebook throttles pagination
(`Rate limit exceeded`, error code `1675004`) fairly aggressively. The client
retries with exponential backoff; for heavier scraping, export cookies from a
browser and pass them in (Netscape `cookies.txt` or a JSON object/array):

```bash
uv run main.py search nike --cookies cookies.txt --limit 1000
```

Use `--delay` to slow down pagination (default 1s) and `--retries` to change the
number of backoff attempts (default 5).

## Proxies

Every libcurl transport is supported:

| Scheme | Notes |
|---|---|
| `http://` | HTTP proxy, including CONNECT tunnelling for HTTPS |
| `https://` | TLS to the proxy itself |
| `socks4://` | SOCKS4 (local DNS) |
| `socks4a://` | SOCKS4a (remote DNS) |
| `socks5://` | SOCKS5, credentials supported |
| `socks5h://` | SOCKS5 with remote DNS (alias: `socks://`) |

```bash
# one proxy, credentials in the URL
uv run main.py search nike --proxy http://user:pass@proxy.example:8080

# SOCKS5 with remote DNS
uv run main.py search nike --proxy socks5h://user:pass@10.0.0.5:1080

# bare host:port entries default to HTTP
uv run main.py search nike --proxy 10.0.0.5:8080

# credentials separately
uv run main.py search nike --proxy socks5://10.0.0.5:1080 --proxy-user user:pass

# a pool, tried in order; dead proxies are skipped automatically
uv run main.py search nike --proxy-file proxies.txt --proxy-strategy round_robin

# read HTTPS_PROXY / ALL_PROXY / HTTP_PROXY
uv run main.py search nike --proxy env
```

`--proxy` is repeatable, and `proxies.txt` accepts any of:

```
http://user:pass@a.example:8080
socks5://b.example:1080
c.example:3128
d.example:3128:user:pass
proxy5: https://e.example:8443
```

Rotation is **sticky**: one proxy is used for an entire search session, because
Ad Library cookies and pagination cursors are bound to that session. If a proxy
fails (connection error, 407, repeated 429/rate-limit), the client re-warms a
fresh session on the next proxy and restarts pagination, de-duplicating ads it
already collected. `--proxy-strategy random` shuffles the pool first.

For intercepting proxies that re-sign TLS (HTTP Toolkit, mitmproxy, Burp), pass
their CA with `--ca`:

```bash
uv run main.py search nike --proxy http://127.0.0.1:8080 --ca ~/mitmproxy-ca-cert.pem
```

Environment variables are honoured by default (`--ignore-env-proxy` disables
that) when no explicit proxy is given.

Facebook throttles requests that look like an outdated browser. The client sends
a complete Chrome 157 fingerprint (UA plus `Sec-CH-UA-*` client hints); bump it
when Chrome moves on:

```bash
uv run main.py search nike --chrome-version 160 --limit 100
# or be fully explicit
uv run main.py search nike --user-agent "Mozilla/5.0 (...) Chrome/160.0.0.0 Safari/537.36"
```

## Debugging with HTTP Toolkit

Every request is a plain `requests` call, so pointing the scraper at HTTP
Toolkit's proxy captures it in the HTTP Toolkit UI:

```bash
uv run main.py search nike --limit 5 --httptoolkit
```

`--httptoolkit` sets the proxy to `http://127.0.0.1:8000` and trusts the HTTP
Toolkit CA (`~/Library/Preferences/httptoolkit/ca.pem` on macOS,
`~/.config/httptoolkit/ca.pem` on Linux, `%APPDATA%\httptoolkit\ca.pem` on
Windows). You can also do it manually:

```bash
uv run main.py search nike --proxy http://127.0.0.1:8000 --ca /path/to/httptoolkit/ca.pem
```

In the UI you will see:

| Request | Purpose |
| --- | --- |
| `GET /ads/library/?...` | HTML shell, cookies, `lsd` token, SSR first page |
| `POST /__rd_verify_...` | challenge solved with the cookie jar |
| `POST /api/graphql/` (`AdLibrarySearchPaginationQuery`) | page 2, 3, ... |

### Capturing from a real browser

To compare against the client, start a Chrome instance through the proxy:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --proxy-server=http://127.0.0.1:8000 \
  --ignore-certificate-errors \
  "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q=nike&search_type=keyword_unordered&media_type=all"
```

The web UI sends the same `AdLibrarySearchPaginationQuery` with
`doc_id=29554948227445166`; if Meta rotates it, the client can re-discover it
from the page's JS bundles:

```python
from ads_library import AdsLibraryClient

print(AdsLibraryClient().discover_pagination_doc_id())
```

or pass a known id with `--doc-id`.

## Output

Each ad is a flat dict (JSONL) with one row per ad archive entry:

- identity: `ad_archive_id`, `page_id`, `page_name`, `page_profile_uri`
- creative: `title`, `body`, `cta_text`, `link_url`, `caption`, `display_format`,
  `titles`, `bodies`, `cta_texts`, `link_urls`, `images`, `videos`, `video_thumbnails`
- delivery: `is_active`, `start_date`, `end_date`, `publisher_platforms`,
  `impressions_text`, `spend`, `currency`, `reach_estimate`, `total_active_time`,
  `targeted_or_reached_countries`
- extras: `ad_snapshot_url`, `page_categories`, `page_like_count`,
  `contains_digital_created_media`, `gated_type`, `collation_count`

CSV output joins list fields with `" | "`.

## Python API

```python
from ads_library import AdsLibraryClient, SearchFilters

client = AdsLibraryClient(request_delay=2.0)
ads = client.search("nike", limit=50, media_type="video")
for ad in ads:
    print(ad["ad_archive_id"], ad["page_name"], ad["body"])

# iterate pages as they arrive (keeps memory flat)
for page in client.iter_pages(SearchFilters(query="nike"), limit=200):
    ...

# same, with search metadata attached
for page in client.iter_pages_detailed(SearchFilters(query="nike"), limit=200):
    print(page.number, len(page.ads), page.result_count)

print("Meta reports", client.result_count, "matching ads")
```

`AdsLibraryClient(...)` also accepts `proxy`, `proxies`, `proxy_strategy`,
`proxy_auth`, `trust_env`, `verify` (CA bundle path), `cookies`, `user_agent`,
`chrome_version`, `rate_limit_retries` and `rate_limit_base_delay`.

## How it works

1. **Warm-up** – `GET /ads/library/` with the search filters. If Facebook returns
   its `403` JS challenge, the client `POST`s to the challenge URL and retries
   with the `rd_challenge` cookie.
2. **Tokens** – `lsd`, `__spin_*`, `hsi`, `jazoest` and the search `sessionID`
   are extracted from the HTML, together with the SSR `search_results_connection`.
3. **Pagination** – `POST /api/graphql/` with
   `fb_api_req_friendly_name=AdLibrarySearchPaginationQuery`,
   `doc_id=29554948227445166` and the full filter variables, following
   `page_info.end_cursor` until `has_next_page` is false or the limit is hit.
4. **Throttling** – `1675004` responses are retried with exponential backoff.
   The biggest cause of throttling is a stale browser fingerprint: the client
   always sends a current Chrome user agent *and* matching `Sec-CH-UA-*` hints,
   which is what lets pagination work without a login.

## Notes

- Public, logged-out Ad Library data only. Respect Meta's terms and applicable
  law; this is intended for research and monitoring.
- The GraphQL `doc_id` and some anti-bot fields are versioned by Meta. If
  pagination starts failing with a query error, run the doc-id discovery above
  or capture a fresh request with HTTP Toolkit.
