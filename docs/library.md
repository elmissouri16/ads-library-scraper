# Library usage

Everything is exported from the top-level package:

```python
from ads_library import (
    AdsLibraryClient, SearchFilters,
    Proxy, ProxyPool, load_proxies, parse_proxy,
    flatten_ad, load_cookies,
    AdsLibraryError, RateLimitedError, ProxyConnectionError, BlockedError,
)
```

## Client

```python
AdsLibraryClient(
    *,
    impersonate="chrome",          # curl_cffi TLS profile
    proxy=None,                    # one proxy
    proxies=None,                  # proxy / proxy list / file / "env"
    proxy_strategy="round_robin",  # or "random"
    proxy_auth=None,               # (user, password)
    trust_env=True,                # honour HTTPS_PROXY etc.
    verify=True,                   # True, False or a CA bundle path
    timeout=60.0,
    request_delay=1.0,             # seconds between result pages
    rate_limit_retries=5,
    rate_limit_base_delay=20.0,
    doc_id=None,                   # override pagination GraphQL doc_id
    cookies=None,                  # dict of cookies
    headers=None,                  # extra HTTP headers
    user_agent=None,               # override Chrome UA
    chrome_version="157",
    chrome_full_version="157.0.8103.51",
    platform="macOS",
    platform_version="26.5.2",
)
```

Use it as a context manager to close the HTTP session:

```python
with AdsLibraryClient() as client:
    ads = client.search("nike", limit=20)
```

### Methods

| Method | Returns | Description |
| --- | --- | --- |
| `search(query, *, limit=None, max_pages=None, page_size=10, **filters)` | `list[dict]` | Keyword search |
| `iter_ads(query, *, ...)` | iterator of `dict` | Same, streamed ad by ad |
| `advertiser(page_id, *, ...)` | `list[dict]` | Ads from one Facebook page |
| `iter_advertiser_ads(page_id, *, ...)` | iterator of `dict` | Same, streamed |
| `iter_pages(filters, *, limit=None, max_pages=None, page_size=10)` | iterator of `list[dict]` | Page-at-a-time access |
| `discover_pagination_doc_id()` | `str \| None` | Re-read the GraphQL `doc_id` from JS bundles |
| `use_next_proxy()` | `bool` | Manually advance the proxy pool and reset the session |
| `close()` | `None` | Close the session |

`**filters` are `SearchFilters` fields (below), e.g. `country="DE"`,
`media_type="video"`, `active_status="all"`.

### SearchFilters

```python
from ads_library import SearchFilters

filters = SearchFilters(
    query="nike",
    country="US",                 # "ALL" for worldwide page searches
    active_status="active",       # active | inactive | all
    ad_type="all",                # all | political_and_issue_ads
    media_type="all",             # all | image | video | meme
    search_type="keyword_unordered",  # or keyword_exact, page
    page_ids=[],                  # explicit Facebook page ids
    view_all_page_id=None,        # advertiser search (page id)
    start_date=None,              # YYYY-MM-DD
    sort_mode="total_impressions",# total_impressions | time_active | relevancy_monthly_grouped
    sort_direction="desc",        # desc | asc
    page_size=10,
)
```

## Examples

### Keyword search

```python
with AdsLibraryClient(request_delay=1.5) as client:
    ads = client.search(
        "running shoes",
        country="DE",
        media_type="video",
        start_date="2025-01-01",
        limit=200,
    )
```

### Stream a large result set

```python
client = AdsLibraryClient()
for ad in client.iter_ads("nike", country="US", limit=2000):
    print(ad["ad_archive_id"], ad["page_name"], ad["start_date"])
```

### One advertiser

```python
ads = client.advertiser("113728961341467", country="ALL")
```

or stream:

```python
for ad in client.iter_advertiser_ads("113728961341467", country="ALL", limit=2000):
    ...
```

### Page-by-page access

```python
for page in client.iter_pages(
    SearchFilters(query="nike", country="US"), limit=200, page_size=10
):
    # `page` is a list of flattened ads
    ...
```

### Proxies

```python
client = AdsLibraryClient(
    proxies=[
        "socks5h://user:pass@10.0.0.5:1080",
        "http://user:pass@proxy.example:8080",
    ],
    proxy_strategy="random",
    verify="/path/to/intercepting-proxy-ca.pem",
)
```

See [Proxies](proxies.md) for details.

### Cookies

```python
from ads_library import load_cookies

client = AdsLibraryClient(cookies=load_cookies("cookies.txt"))
```

### Error handling

```python
from ads_library import AdsLibraryError, RateLimitedError

try:
    ads = client.search("nike", limit=50)
except RateLimitedError:
    # Facebook returned 1675004/429 and retries were exhausted
    ...
except AdsLibraryError:
    # challenge/login wall/unknown response/proxy pool exhausted
    ...
```

### Lower-level helpers

```python
from ads_library import flatten_ad
from ads_library.parsing import connection_ads

raw = ...  # a `search_results_connection` dict
rows = connection_ads(raw)
row = flatten_ad(raw["edges"][0]["node"]["collated_results"][0])
```
