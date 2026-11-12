"""Proxy parsing, lists and rotation.

Supported schemes (whatever libcurl speaks): ``http``, ``https``, ``socks4``,
``socks4a``, ``socks5`` and ``socks5h``. Bare ``host:port`` entries default to
HTTP, and ``host:port:user:pass`` lists are accepted too.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import quote, unquote, urlparse

PROXY_SCHEMES = {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}
ENV_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
)


@dataclass(frozen=True)
class Proxy:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def url(self) -> str:
        auth = ""
        if self.username is not None:
            auth = quote(self.username, safe="")
            if self.password is not None:
                auth += ":" + quote(self.password, safe="")
            auth += "@"
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        return f"{self.scheme}://{auth}{host}:{self.port}"

    @property
    def masked(self) -> str:
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        auth = "***@" if self.username is not None else ""
        return f"{self.scheme}://{auth}{host}:{self.port}"

    def __str__(self) -> str:
        return self.masked


def parse_proxy(value: str | Proxy) -> Proxy:
    """Parse one proxy definition into a :class:`Proxy`."""
    if isinstance(value, Proxy):
        return value
    raw = str(value).strip()
    if not raw:
        raise ValueError("empty proxy definition")

    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        scheme = scheme.lower()
        if scheme == "socks":
            scheme = "socks5h"
    else:
        scheme, rest = "http", raw
        # host:port:user:pass is a common proxy-list format
        if "@" not in rest and not rest.startswith("[") and rest.count(":") >= 3:
            parts = rest.split(":")
            host, port, user = parts[0], parts[1], parts[2]
            password = ":".join(parts[3:])
            rest = f"{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"

    if scheme not in PROXY_SCHEMES:
        raise ValueError(
            f"unsupported proxy scheme {scheme!r}; use one of {', '.join(sorted(PROXY_SCHEMES))}"
        )

    parsed = urlparse(f"{scheme}://{rest}")
    if not parsed.hostname:
        raise ValueError(f"proxy {raw!r} has no host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"proxy {raw!r} has an invalid port") from exc
    if port is None:
        raise ValueError(f"proxy {raw!r} is missing a port (expected host:port)")
    if not 1 <= port <= 65535:
        raise ValueError(f"proxy {raw!r} has an out-of-range port")

    username = parsed.username
    password = parsed.password
    if username is not None:
        username = unquote(username)
    if password is not None:
        password = unquote(password)

    return Proxy(
        scheme=scheme,
        host=parsed.hostname,
        port=port,
        username=username,
        password=password,
    )


def _file_entries(path: Path) -> Iterator[str]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "host:port user:pass" / "name: http://host:8080" style lists
        if " " in line and "://" in line:
            line = line.split()[-1]
        if "=" in line:
            _, _, tail = line.partition("=")
            tail = tail.strip()
            if "://" in tail or (":" in tail and tail.rsplit(":", 1)[-1].isdigit()):
                line = tail
            else:
                line = line.split(":", 1)[-1].strip()
        yield line


def _split_entries(value: str) -> Iterator[str]:
    for line in value.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            yield line


def env_proxies() -> list[str]:
    """Proxy URLs from the usual environment variables."""
    found: list[str] = []
    for key in ENV_KEYS:
        value = os.environ.get(key)
        if value and value not in found:
            found.append(value)
    return found


def load_proxies(
    values: str | Proxy | Iterable[str | Proxy] | None = None,
    *,
    include_env: bool = False,
) -> list[Proxy]:
    """Build a de-duplicated proxy list.

    ``values`` may contain proxy URLs, bare ``host:port`` entries, file paths,
    or the literal ``env`` (which reads ``HTTPS_PROXY``/``ALL_PROXY``/...).
    """
    if values is None:
        items: list[str | Proxy] = []
    elif isinstance(values, (str, Proxy)):
        items = [values]
    else:
        items = list(values)

    raw: list[str | Proxy] = []
    for item in items:
        if isinstance(item, Proxy):
            raw.append(item)
            continue
        text = str(item).strip()
        if not text:
            continue
        if text.lower() == "env":
            raw.extend(env_proxies())
            continue
        if "\n" in text:
            raw.extend(_split_entries(text))
            continue
        if "://" not in text:
            path = Path(text).expanduser()
            try:
                is_file = path.is_file()
            except OSError:
                is_file = False
            if is_file:
                raw.extend(_file_entries(path))
                continue
        raw.append(text)

    if include_env:
        raw.extend(env_proxies())

    proxies: list[Proxy] = []
    seen: set[str] = set()
    for item in raw:
        proxy = parse_proxy(item)
        if proxy.url not in seen:
            seen.add(proxy.url)
            proxies.append(proxy)
    return proxies


class ProxyPool:
    """Sticky proxy rotation with failover.

    One proxy is leased per search session, because Ad Library cursors and
    cookies are session-bound. ``rotate()`` moves to the next untried proxy and
    returns ``None`` once every proxy has failed.
    """

    def __init__(
        self,
        proxies: Iterable[Proxy],
        *,
        strategy: str = "round_robin",
        seed: int | None = None,
    ) -> None:
        if strategy not in ("round_robin", "random"):
            raise ValueError("proxy strategy must be 'round_robin' or 'random'")
        self.proxies = list(proxies)
        self.strategy = strategy
        order = list(range(len(self.proxies)))
        if strategy == "random":
            random.Random(seed).shuffle(order)
        self._order = order
        self._position = 0
        self._failed: set[str] = set()

    def __len__(self) -> int:
        return len(self.proxies)

    def __bool__(self) -> bool:
        return bool(self.proxies)

    def _at(self, position: int) -> Proxy:
        return self.proxies[self._order[position % len(self._order)]]

    def lease(self) -> Proxy | None:
        if not self.proxies:
            return None
        return self._at(self._position)

    def rotate(self, *, mark_failed: bool = True) -> Proxy | None:
        if not self.proxies:
            return None
        if mark_failed:
            current = self.lease()
            if current is not None:
                self._failed.add(current.url)
        for _ in range(len(self.proxies)):
            self._position += 1
            candidate = self._at(self._position)
            if candidate.url not in self._failed:
                return candidate
        return None

    def reset_failures(self) -> None:
        self._failed.clear()

    def __iter__(self) -> Iterator[Proxy]:
        return iter(self.proxies)
