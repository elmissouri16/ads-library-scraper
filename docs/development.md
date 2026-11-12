# Development

## Layout

```
ads_library/
├── __init__.py     public exports
├── client.py       session, challenge, tokens, GraphQL pagination, proxies glue
├── parsing.py      SSR/GraphQL parsing and ad flattening
├── proxies.py      proxy parsing, lists, pool, rotation
└── cli.py          argparse CLI, JSONL/CSV writers
main.py             `python main.py ...` entry point
tests/              unittest suite (offline)
docs/               this documentation
tmp/                local scrape output (git-ignored)
```

## Setup

```bash
uv sync
```

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

All tests are offline: JSON parsing, ad flattening, proxy URL parsing, proxy
lists/files/env, pool rotation and failover. Add a unit test for any parsing or
proxy change; network tests are intentionally not part of the suite.

## Build

```bash
uv build            # sdist + wheel in dist/
```

The wheel contains only `ads_library/` and installs the `ads-library` console
script.

## Style

- Python 3.13, `from __future__ import annotations`
- Standard library + `curl_cffi` only at runtime
- Type hints on public functions
- Keep `flatten_ad` output keys stable; add fields at the end and update
  [Data schema](data.md)
- Never log proxy passwords (use `Proxy.masked`)

## Adding a filter

1. Add the field to `SearchFilters` with a default.
2. Map it in `SearchFilters.url_params()` (the landing page URL) **and**
   `SearchFilters.graphql_variables()` (pagination) — the two must agree or the
   SSR cursor and the GraphQL pages will describe different result sets.
3. Expose it in `ads_library/cli.py` and document it in [CLI](cli.md).

## Rate limits and fingerprints

Pagination is sensitive to the advertised browser fingerprint. When bumping the
default Chrome version, update `DEFAULT_CHROME_VERSION`, `DEFAULT_CHROME_FULL_VERSION`
and `DEFAULT_USER_AGENT` together, then smoke-test a 200+ ad scrape.

## Release checklist

1. `uv run python -m unittest discover -s tests`
2. `uv build`
3. Bump `version` in `pyproject.toml`
4. Commit, tag, push
