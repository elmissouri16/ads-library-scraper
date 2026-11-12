# CLI

```bash
uv run main.py --help
uv run main.py search --help
uv run main.py page --help
```

After `pip install .` the same interface is available as `ads-library`.

## Commands

| Command | Description |
| --- | --- |
| `search QUERY` | Keyword search |
| `page PAGE_ID` | All ads from one advertiser |

## Options (shared)

| Option | Default | Description |
| --- | --- | --- |
| `--country CODE` | `US` | Two-letter country, or `ALL` |
| `--active-status` | `active` | `active`, `inactive`, `all` |
| `--ad-type` | `all` | `all`, `political_and_issue_ads` |
| `--media-type` | `all` | `all`, `image`, `video`, `meme` |
| `--search-type` | `keyword_unordered` | `keyword_unordered`, `keyword_exact` (search only) |
| `--start-date` | – | Ads started on/after `YYYY-MM-DD` |
| `--sort-mode` | `total_impressions` | `total_impressions`, `time_active`, `relevancy_monthly_grouped` |
| `--sort-direction` | `desc` | `desc`, `asc` |
| `--limit N` | all | Maximum ads to return |
| `--max-pages N` | all | Maximum result pages |
| `--page-size N` | `10` | Ads per GraphQL page |
| `--delay SECONDS` | `1` | Delay between pages |
| `--retries N` | `5` | Rate-limit retries |
| `--cookies PATH` | – | `cookies.txt` (Netscape) or JSON cookies |
| `--doc-id ID` | built-in | Override the pagination GraphQL `doc_id` |
| `--chrome-version N` | `157` | Chrome major version in UA/client hints |
| `--user-agent STR` | built-in | Full UA override |
| `--impersonate NAME` | `chrome` | curl_cffi impersonation profile |
| `--jsonl PATH` | – | Write JSON Lines |
| `--csv PATH` | – | Write CSV |
| `--pretty` | off | Pretty-print JSON to stdout |
| `-v`, `--verbose` | off | Log proxy/retry activity |
| `--ca PATH` | – | Trust an intercepting proxy CA |
| `--httptoolkit` | off | Shortcut for `--proxy http://127.0.0.1:8000` + CA |

## Proxy options

| Option | Description |
| --- | --- |
| `--proxy URL` | Repeatable; `scheme://[user:pass@]host:port` or `host:port`, or `env` |
| `--proxy-file PATH` | Repeatable; one proxy per line |
| `--proxy-strategy` | `round_robin` (default) or `random` |
| `--proxy-user USER:PASS` | Credentials when not in the URL |
| `--ignore-env-proxy` | Do not use `HTTPS_PROXY`/`ALL_PROXY`/`HTTP_PROXY` |

See [Proxies](proxies.md).

## Examples

```bash
# latest active Nike ads in the US
uv run main.py search nike --limit 100

# worldwide video ads from one advertiser, newest impressions order
uv run main.py page 113728961341467 --country ALL --media-type video --limit 500

# exact phrase, only ads started this year
uv run main.py search "air max" --search-type keyword_exact --start-date 2026-01-01

# everything, into both formats
uv run main.py page 113728961341467 --country ALL --limit 5000 \
  --jsonl tmp/ads.jsonl --csv tmp/ads.csv

# through a SOCKS5 pool
uv run main.py search nike --proxy-file proxies.txt --proxy-strategy random -v
```

## Output

- Default: one JSON object per ad on stdout.
- `--limit 5 --pretty`: an indented JSON array.
- `--jsonl PATH` / `--csv PATH`: files; stdout stays quiet.
- Progress (`N ads captured`) and the final count go to stderr, so piping
  stdout stays clean. The final line also includes Meta's approximate result
  count, e.g. `200 ads from 12 advertisers (Meta reports ~6,777 results)`.
- CSV list fields are joined with `" | "`; CSV is RFC 4180 quoted.
- Meta's result count is not added to the rows, so the JSONL/CSV schema is
  unchanged; read it from the stderr summary or `client.result_count`.

Exit codes: `0` success, `1` scraping error, `2` invalid proxy/cookies options,
`130` interrupted.

Full field list: [Data schema](data.md).
