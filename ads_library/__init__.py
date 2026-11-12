"""Facebook Ad Library scraper built on curl_cffi."""

from .client import (
    AdsLibraryClient,
    AdsLibraryError,
    BlockedError,
    ProxyConnectionError,
    RateLimitedError,
    SearchFilters,
    load_cookies,
)
from .parsing import flatten_ad
from .proxies import Proxy, ProxyPool, load_proxies, parse_proxy

__all__ = [
    "AdsLibraryClient",
    "AdsLibraryError",
    "BlockedError",
    "Proxy",
    "ProxyConnectionError",
    "ProxyPool",
    "RateLimitedError",
    "SearchFilters",
    "flatten_ad",
    "load_cookies",
    "load_proxies",
    "parse_proxy",
]
