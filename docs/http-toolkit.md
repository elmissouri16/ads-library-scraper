# Debugging with HTTP Toolkit

The scraper uses plain HTTP requests, so [HTTP Toolkit](https://httptoolkit.com)
can capture and replay them. This is how the client was originally reverse
engineered.

## Point the scraper at HTTP Toolkit

```bash
uv run main.py search nike --limit 5 --httptoolkit
```

This sets:

- proxy `http://127.0.0.1:8000`
- CA bundle:
  - macOS `~/Library/Preferences/httptoolkit/ca.pem`
  - Linux `~/.config/httptoolkit/ca.pem`
  - Windows `%APPDATA%\httptoolkit\ca.pem`

Manual equivalent:

```bash
uv run main.py search nike --proxy http://127.0.0.1:8000 \
  --ca /Users/you/Library/Preferences/httptoolkit/ca.pem
```

Python:

```python
AdsLibraryClient(proxy="http://127.0.0.1:8000", verify="/path/to/ca.pem")
```

Use `-v` to see proxy and retry messages.

## What you will see

| Request | Purpose |
| --- | --- |
| `GET /ads/library/?...` | HTML shell, cookies, `lsd`, SSR first page |
| `POST /__rd_verify_...` | JavaScript challenge solved with the cookie jar |
| `POST /api/graphql/` (`AdLibraryFoundationRootQuery`) | page state, tokens |
| `POST /api/graphql/` (`AdLibrarySearchPaginationQuery`) | every page after the first |

The first page comes from the HTML, so a small `--limit` may never call the
pagination query at all.

## Capture real browser traffic

Launch Chrome through HTTP Toolkit to compare with the client:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir=/tmp/fbchrome \
  --proxy-server=http://127.0.0.1:8000 \
  --ignore-certificate-errors \
  "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q=nike&search_type=keyword_unordered&media_type=all"
```

Scroll the page to trigger `AdLibrarySearchPaginationQuery`; compare
`x-fb-friendly-name`, the form body and the cookies with the scraper's requests.

## Key request fields

`POST /api/graphql/` is form-encoded and sends:

| Field | Meaning |
| --- | --- |
| `doc_id` | Relay operation id; `29554948227445166` for pagination |
| `variables` | JSON filters + `cursor` + `sessionID` + `v` |
| `lsd` | Token from the landing page |
| `jazoest`, `__hs`, `__hsi`, `__rev`, `__spin_r/b/t` | Comet/client hints |
| `fb_api_req_friendly_name` | Operation name |
| `x-fb-friendly-name`, `x-asb*/x-fb-entry-nonce` | Headers the site sends |

## Rediscovering the `doc_id`

Meta rotates GraphQL operation ids. The client can find the current one in the
page's JS bundles:

```python
from ads_library import AdsLibraryClient

print(AdsLibraryClient().discover_pagination_doc_id())
```

It is also called automatically once when a pagination request fails with a
query error. Override manually with `--doc-id` / `doc_id=`.

## Reducing noise

The Ad Library page loads hundreds of assets. In HTTP Toolkit, filter by
`hostname=www.facebook.com path=/api/graphql/` or by the
`x-fb-friendly-name` header to see only the interesting calls.
