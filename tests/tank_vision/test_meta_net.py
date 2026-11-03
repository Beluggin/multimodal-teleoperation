"""Meta API connection tests — offline, fake sockets only.

Measured 2026-10-30 from the desktop: 7/30 IPv6 connects to api.meta.ai
never answered SYN (0/30 over IPv4). urllib tried IPv6 first and sat out
the whole 120 s timeout before falling back, so a SAM look stalled ~2 min.
call_api must therefore connect over IPv4 with a short connect timeout,
retrying on a FRESH socket (new source port) instead of waiting.

Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'
"""

import os
import socket
import sys
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))

from tank_vision import meta_sam  # noqa: E402


class FakeSock:
    def __init__(self, fail):
        self.fail = fail
        self.timeouts = []
        self.closed = False

    def settimeout(self, t):
        self.timeouts.append(t)

    def connect(self, addr):
        if self.fail:
            raise socket.timeout("SYN never answered")

    def close(self):
        self.closed = True


def factory(fails):
    """Socket factory: the n-th socket fails when fails[n] is True."""
    made = []

    def make(family, kind):
        assert family == socket.AF_INET, "must never open an IPv6 socket"
        s = FakeSock(fails[len(made)])
        made.append(s)
        return s
    return make, made


def gai(families):
    def getaddrinfo(host, port, family=0, kind=0):
        families.append(family)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("31.13.80.8", port))]
    return getaddrinfo


class TestConnectIPv4(unittest.TestCase):
    def test_resolves_ipv4_only(self):
        families = []
        make, _ = factory([False])
        meta_sam.connect_ipv4("api.meta.ai", 443, 120,
                              getaddrinfo=gai(families), sock_factory=make)
        self.assertEqual(families, [socket.AF_INET])

    def test_short_connect_then_long_read_timeout(self):
        make, made = factory([False])
        s = meta_sam.connect_ipv4("api.meta.ai", 443, 120,
                                  getaddrinfo=gai([]), sock_factory=make)
        self.assertIs(s, made[0])
        self.assertEqual(made[0].timeouts,
                         [meta_sam.CONNECT_TIMEOUT, 120])

    def test_hung_connect_retries_on_fresh_socket(self):
        make, made = factory([True, False])
        s = meta_sam.connect_ipv4("api.meta.ai", 443, 120,
                                  getaddrinfo=gai([]), sock_factory=make)
        self.assertEqual(len(made), 2)
        self.assertTrue(made[0].closed)
        self.assertIs(s, made[1])

    def test_gives_up_after_tries(self):
        make, made = factory([True] * meta_sam.CONNECT_TRIES)
        with self.assertRaises(OSError):
            meta_sam.connect_ipv4("api.meta.ai", 443, 120,
                                  getaddrinfo=gai([]), sock_factory=make)
        self.assertEqual(len(made), meta_sam.CONNECT_TRIES)
        self.assertTrue(all(s.closed for s in made))


class TestOpener(unittest.TestCase):
    def https_handlers(self, opener):
        return [h for h in opener.handlers
                if isinstance(h, urllib.request.HTTPSHandler)]

    def test_direct_uses_ipv4_handler(self):
        hs = self.https_handlers(meta_sam.api_opener(proxies={}))
        self.assertEqual(len(hs), 1)
        self.assertIsInstance(hs[0], meta_sam.IPv4HTTPSHandler)

    def test_proxy_keeps_default_path(self):
        # Muse sandbox broker: the proxy makes the connection, not us.
        hs = self.https_handlers(
            meta_sam.api_opener(proxies={"https": "http://broker:3128"}))
        self.assertFalse(any(isinstance(h, meta_sam.IPv4HTTPSHandler)
                             for h in hs))


if __name__ == "__main__":
    unittest.main()
