# Troubleshooting

## `403 Client challenge`

Facebook serves a small HTML page that posts to `/__rd_verify_...` and reloads.
The client solves this automatically by POSTing to that URL with the same cookie
jar, then retrying. You only need to act if the retries also fail.

## `429` on the challenge endpoint

The challenge POST can itself be throttled:

```
Facebook rate limited the challenge endpoint (HTTP 429)
```

The scraper retries it, then treats it as a rate limit. Wait a few minutes and
run again, add `--delay`, or route through another proxy.

## `Rate limit exceeded`, code `1675004`

The Ad Library throttles pagination for sessions it does not trust. Causes, in
order of likelihood:

1. **Stale browser fingerprint.** Bump the advertised Chrome version:
   `--chrome-version 160` (and optionally `--user-agent`). The client already
   sends complete `Sec-CH-UA-*` hints — incomplete hints are the classic cause.
2. **Too many new searches too quickly.** Keep `--delay 1`–`2`, do not
   parallelise searches from one IP.
3. **New session on a flagged IP.** Rotate proxies
   (`--proxy-file ...`) so each session gets a fresh egress.
4. **Logged-out restrictions.** Export browser cookies and pass
   `--cookies cookies.txt`.

The client retries with exponential backoff (≈20s, 30s, 45s, 67s, 101s by
default), then switches proxies if a pool is configured.

## Redirected to `/login` or `/checkpoint`

The Ad Library wants a logged-in session for what you asked for. Export cookies
from a browser where you are signed in:

```bash
uv run main.py search nike --cookies cookies.txt
```

`load_cookies` accepts a Netscape `cookies.txt` or a JSON object/array.

## Zero ads returned

- Advertiser search needs the **page id**, not the page username:
  `page 113728961341467`, not `page breeze`.
- `--active-status active` hides paused ads; try `--active-status all`.
- `--media-type video` plus a narrow country/date can legitimately be empty.
- `country=ALL` is for page searches; keyword searches normally use a country.
- Some page ids are region-restricted; try another `--country`.

## `unsupported proxy scheme` / proxy errors

- Supported: `http`, `https`, `socks4`, `socks4a`, `socks5`, `socks5h`
  (`socks` is an alias for `socks5h`). A bare `host:port` means HTTP.
- A port is required.
- `407` means wrong/missing proxy credentials. Put them in the URL or use
  `--proxy-user user:pass`.
- When every proxy fails you get
  `ProxyConnectionError: all proxies failed`. Check `-v` output for the specific
  proxy that broke.

## TLS errors through an intercepting proxy

Intercepting proxies re-sign certificates. Trust their CA:

```bash
uv run main.py search nike --proxy http://127.0.0.1:8080 --ca ~/mitmproxy-ca-cert.pem
```

`--httptoolkit` does this automatically.

## `GraphQL request failed` / unknown query

Meta rotated the pagination `doc_id`. The client tries to re-discover it from
the page's JS bundles automatically. You can also do it explicitly:

```python
print(client.discover_pagination_doc_id())
```

or pin one with `--doc-id 29554948227445166`.

## Result count looks different from the rows read

Those are different numbers. `client.result_count` is Meta's own approximate
total for the search ("~6,300 results"); the number of ads read is capped by
`--limit` / the top 200 you asked for. The count also drifts during the day and
differs slightly between `keyword_unordered` and `keyword_exact_phrase`. Capture
it once per run/day rather than comparing snapshots taken at different times.

The first-page `count` can also be one higher than the number of unique
`ad_archive_id`s (Meta revisits an entry while paginating). The scraper
de-duplicates by `ad_archive_id`, so the output is unique.

## CSV looks like it has too many lines

Ad copy can contain newlines; the CSV is RFC 4180 quoted and your parser must
handle multi-line fields. Count rows with a CSV reader, not `wc -l`.

## Dates look offset

`start_date`/`end_date` are Unix timestamps converted to **UTC** dates.
