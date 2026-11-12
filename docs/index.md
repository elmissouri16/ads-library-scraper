# Meta Ad Library scraper

A Python library and CLI for the public [Meta Ad Library](https://www.facebook.com/ads/library/).
It replays the same HTTP requests the website makes using
[`curl_cffi`](https://github.com/lexiforest/curl_cffi), so it keeps a real Chrome
TLS/HTTP fingerprint without a browser or an API key.

## Features

- Keyword search, advertiser (page) search, filters, sorting and pagination
- First page read from the server-rendered HTML, the rest via
  `AdLibrarySearchPaginationQuery`
- Automatic `__rd_verify` challenge solving
- HTTP / HTTPS / SOCKS4 / SOCKS4a / SOCKS5 / SOCKS5h proxies, lists, auth,
  rotation and failover
- JSONL, CSV and streaming APIs
- Rate-limit retries with exponential backoff
- First-class [HTTP Toolkit](https://httptoolkit.com) support for debugging

## Install

```bash
uv sync                 # within this repo
pip install .           # or install the package
```

Wheel: `uv build` → `dist/ads_library_scraper-0.1.0-py3-none-any.whl`

## Quick start

```bash
# keyword
uv run main.py search nike --limit 100

# advertiser (Breeze)
uv run main.py page 113728961341467 --country ALL --limit 500

# save both formats
uv run main.py search nike --limit 500 --jsonl ads.jsonl --csv ads.csv

# after `pip install .`
ads-library search nike --limit 100
```

```python
from ads_library import AdsLibraryClient

with AdsLibraryClient() as client:
    for ad in client.iter_ads("nike", country="US", limit=100):
        print(ad["ad_archive_id"], ad["page_name"], ad["start_date"])
```

## Documentation

| Page | Contents |
| --- | --- |
| [Library usage](library.md) | Client API, filters, streaming, errors |
| [CLI](cli.md) | Commands, options, output |
| [Proxies](proxies.md) | Every scheme, lists, auth, rotation, failover |
| [Data schema](data.md) | All output fields and their meaning |
| [HTTP Toolkit](http-toolkit.md) | Capture and debug requests |
| [Troubleshooting](troubleshooting.md) | 403s, 429s, rate limits, stale tokens |
| [Development](development.md) | Tests, build, project layout |

## Notes

- Public, logged-out Ad Library data only. Respect Meta's terms and applicable law.
- Meta versions the GraphQL `doc_id` and browser fingerprints. If pagination
  breaks, see [Troubleshooting](troubleshooting.md).
