import os
import tempfile
import unittest
from pathlib import Path

from ads_library.proxies import Proxy, ProxyPool, load_proxies, parse_proxy


class TestParseProxy(unittest.TestCase):
    def test_http_with_scheme(self):
        proxy = parse_proxy("http://127.0.0.1:8000")
        self.assertEqual((proxy.scheme, proxy.host, proxy.port), ("http", "127.0.0.1", 8000))
        self.assertEqual(proxy.url, "http://127.0.0.1:8000")

    def test_bare_host_port_defaults_to_http(self):
        proxy = parse_proxy("proxy.example.com:3128")
        self.assertEqual(proxy.scheme, "http")
        self.assertEqual(proxy.port, 3128)

    def test_socks_alias(self):
        self.assertEqual(parse_proxy("socks://h:1080").scheme, "socks5h")
        for scheme in ("socks4", "socks4a", "socks5", "socks5h", "https"):
            self.assertEqual(parse_proxy(f"{scheme}://h:1080").scheme, scheme)

    def test_auth_is_decoded_and_reencoded(self):
        proxy = parse_proxy("socks5://user:p%40ss@host:1080")
        self.assertEqual(proxy.username, "user")
        self.assertEqual(proxy.password, "p@ss")
        self.assertIn("user:p%40ss@host:1080", proxy.url)
        self.assertNotIn("p@ss", proxy.masked)

    def test_host_port_user_pass_list_format(self):
        proxy = parse_proxy("10.0.0.1:8000:alice:secret")
        self.assertEqual(proxy.host, "10.0.0.1")
        self.assertEqual(proxy.username, "alice")
        self.assertEqual(proxy.password, "secret")

    def test_ipv6(self):
        proxy = parse_proxy("socks5://[::1]:1080")
        self.assertEqual(proxy.host, "::1")
        self.assertEqual(proxy.url, "socks5://[::1]:1080")

    def test_rejects_bad_definitions(self):
        for value in ("ftp://host:21", "host-without-port", "http://:8080", "host:99999"):
            with self.assertRaises(ValueError):
                parse_proxy(value)


class TestLoadProxies(unittest.TestCase):
    def test_dedupes_and_accepts_lists(self):
        proxies = load_proxies(["http://a:1", "http://a:1", "socks5://b:2"])
        self.assertEqual([p.url for p in proxies], ["http://a:1", "socks5://b:2"])

    def test_reads_file_with_comments_and_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proxies.txt"
            path.write_text(
                "# comment\n"
                "proxy1: http://user:pass@a:8080\n"
                "b:3128\n"
                "named=https://c:8443\n"
            )
            proxies = load_proxies(str(path))
        self.assertEqual(
            [p.url for p in proxies],
            ["http://user:pass@a:8080", "http://b:3128", "https://c:8443"],
        )

    def test_env_literal(self):
        old = {key: os.environ.get(key) for key in ("HTTPS_PROXY", "ALL_PROXY", "HTTP_PROXY")}
        try:
            os.environ["HTTPS_PROXY"] = "http://env:8080"
            os.environ.pop("ALL_PROXY", None)
            os.environ.pop("HTTP_PROXY", None)
            proxies = load_proxies("env")
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.assertEqual([p.url for p in proxies], ["http://env:8080"])


class TestProxyPool(unittest.TestCase):
    def setUp(self):
        self.proxies = [parse_proxy("http://a:1"), parse_proxy("http://b:2"), parse_proxy("http://c:3")]

    def test_lease_is_sticky(self):
        pool = ProxyPool(self.proxies)
        self.assertEqual(pool.lease().url, "http://a:1")
        self.assertEqual(pool.lease().url, "http://a:1")

    def test_rotation_skips_failed_and_stops(self):
        pool = ProxyPool(self.proxies)
        self.assertEqual(pool.rotate().url, "http://b:2")
        self.assertEqual(pool.rotate().url, "http://c:3")
        self.assertIsNone(pool.rotate())
        self.assertIsNone(pool.rotate())

    def test_empty_pool(self):
        pool = ProxyPool([])
        self.assertIsNone(pool.lease())
        self.assertIsNone(pool.rotate())
        self.assertFalse(pool)

    def test_random_strategy_uses_all(self):
        pool = ProxyPool(self.proxies, strategy="random", seed=7)
        seen = {pool.lease().url}
        for _ in range(2):
            seen.add(pool.rotate(mark_failed=False).url)
        self.assertEqual(len(seen), 3)


if __name__ == "__main__":
    unittest.main()
