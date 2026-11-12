# Proxies

All libcurl transports are supported.

| Scheme | DNS | Notes |
| --- | --- | --- |
| `http://` | local | HTTP proxy; HTTPS goes through `CONNECT` |
| `https://` | local | TLS connection to the proxy itself |
| `socks4://` | local | SOCKS4 |
| `socks4a://` | remote | SOCKS4a |
| `socks5://` | local | SOCKS5, username/password auth |
| `socks5h://` | remote | SOCKS5 with remote DNS; `socks://` is an alias |

Remote DNS (`socks4a`, `socks5h`) is usually what you want when the proxy
provider does the resolving.

## Definitions

Accepted forms, both in code and in proxy files:

```
http://proxy.example:8080
http://user:pass@proxy.example:8080
https://user:pass@proxy.example:8443
socks5://user:pass@10.0.0.5:1080
socks5h://10.0.0.5:1080
socks4a://10.0.0.5:1080
proxy.example:3128
10.0.0.5:3128:user:pass
proxy5: https://proxy.example:8443
proxy6=http://proxy.example:8080
```

`host:port` defaults to HTTP. Credentials are percent-encoded when the URL is
built, and masked in logs (`socks5h://***@host:1080`).

## CLI

```bash
# one proxy
uv run main.py search nike --proxy http://user:pass@proxy:8080

# separate credentials
uv run main.py search nike --proxy socks5://proxy:1080 --proxy-user user:pass

# several proxies, later ones used as failover
uv run main.py search nike --proxy-file proxies.txt --proxy-strategy round_robin

# randomised order
uv run main.py search nike --proxy env --proxy-strategy random

# intercepting proxy with its CA
uv run main.py search nike --proxy http://127.0.0.1:8080 --ca ~/mitmproxy-ca-cert.pem
```

Environment variables `HTTPS_PROXY`, `ALL_PROXY`, `HTTP_PROXY` (and lowercase
forms) are used automatically when no explicit proxy is passed.
`--ignore-env-proxy` disables that. `--proxy env` loads them explicitly into the
pool, which allows rotation between them.

## Python

```python
from ads_library import AdsLibraryClient, ProxyPool, load_proxies, parse_proxy

client = AdsLibraryClient(
    proxies=[
        "socks5h://user:pass@10.0.0.5:1080",
        "http://user:pass@proxy.example:8080",
    ],
    proxy_strategy="round_robin",
)

pool = ProxyPool(load_proxies("proxies.txt"))
proxy = parse_proxy("socks5h://user:pass@10.0.0.5:1080")
print(proxy.masked)
```

## Rotation semantics

Rotation is **sticky per search session**, not per request.

Why: Ad Library pagination cursors and the `rd_challenge`/`datr` cookies belong
to one server-side session. Rotating the IP mid-pagination creates mismatches
and duplicates or skips results.

The client:

1. leases one proxy for the session;
2. on connection failure, HTTP 407, or exhausted rate-limit retries, marks that
   proxy failed;
3. leases the next untried proxy, clears cookies/tokens, warms a fresh session;
4. restarts pagination and skips ads it already collected (by `ad_archive_id`);
5. raises `ProxyConnectionError` once every proxy has failed.

Manual control:

```python
if not client.use_next_proxy():
    print("pool exhausted")
```

`client.current_proxy` holds the active `Proxy` (or `None` for direct).
`client.proxy_pool.reset_failures()` clears the failed set.

## Proxy files

One entry per line; blank lines and `#` comments are ignored. Name prefixes
(`proxy1:`, `proxy1=`) and inline `host:port:user:pass` are understood.

```
# residential pool
socks5h://user:pass@10.0.0.5:1080
socks5h://user:pass@10.0.0.6:1080
http://user:pass@proxy.example:8080
```
