"""Servo slider API tests — FakeBus only, no hardware, no I2C device.

Run: python3 -m unittest discover -s tank_phone -p 'test_*.py'
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import servo_ctl  # noqa: E402
import server as srv  # noqa: E402


class TestFrame(unittest.TestCase):
    def test_frame_bytes(self):
        self.assertEqual(servo_ctl.frame(5, 95), (0xFF, 5, 95, 0xFF))
        self.assertEqual(servo_ctl.frame(4, 40), (0xFF, 4, 40, 0xFF))

    def test_refusals(self):
        for ch, ang in [(0, 90), (7, 90), (8, 90), (1, -1), (1, 181), (1, 90.5)]:
            with self.assertRaises(ValueError):
                servo_ctl.frame(ch, ang)


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(port, method, path, payload=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class ApiCase(unittest.TestCase):
    enabled = True

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.bus = servo_ctl.FakeBus()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.httpd.servo_enabled = cls.enabled
        cls.httpd.servo_bus = cls.bus
        cls.httpd.servo_state = dict(servo_ctl.DEFAULTS)
        cls.httpd.flags_file = os.path.join(cls.tmp, "flags.json")
        cls.httpd.servo_flags = []
        cls.httpd.servo_limits = dict(servo_ctl.LIMITS)
        cls.httpd.limits_file = os.path.join(cls.tmp, "limits.json")
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_valid_write_reaches_bus(self):
        code, body = call(self.port, "POST", "/api/servo", {"channel": 5, "angle": 100})
        if not self.enabled:
            self.assertEqual(code, 403)
            return
        self.assertEqual(code, 200)
        self.assertEqual(self.bus.frames[-1], (0xFF, 5, 100, 0xFF))
        self.assertEqual(body["state"]["5"], 100)

    def test_invalid_writes_refused(self):
        for payload in [{"channel": 7, "angle": 90}, {"channel": 1, "angle": 181},
                        {"channel": 1, "angle": -5}, {"channel": 1, "angle": 90.5},
                        {"channel": "x", "angle": 90}, {"angle": 90}]:
            code, _ = call(self.port, "POST", "/api/servo", payload)
            self.assertEqual(code, 400, payload)

    def test_limits_enforced_and_adjustable(self):
        code, _ = call(self.port, "POST", "/api/servo", {"channel": 4, "angle": 170})
        self.assertEqual(code, 400)  # claw default limit is 40..100
        code, body = call(self.port, "POST", "/api/servo/limits",
                          {"channel": 4, "min": 40, "max": 175})
        self.assertEqual(code, 200)
        self.assertEqual(body["limits"]["4"], [40, 175])
        with open(self.httpd.limits_file) as f:  # persisted
            self.assertEqual(json.load(f)["4"], [40, 175])
        code, _ = call(self.port, "POST", "/api/servo/limits",
                       {"channel": 4, "min": 175, "max": 40})
        self.assertEqual(code, 400)  # inverted range refused

    def test_flag_roundtrip(self):
        code, body = call(self.port, "POST", "/api/servo/flag",
                          {"channel": 6, "angle": 140, "note": "grinds"})
        self.assertEqual(code, 200)
        self.assertEqual(body["flags"][-1]["note"], "grinds")
        code, body = call(self.port, "GET", "/api/servo")
        self.assertEqual(body["flags"][-1]["angle"], 140)
        with open(self.httpd.flags_file) as f:  # persisted to disk
            self.assertEqual(json.load(f)[-1]["angle"], 140)


class TestDisabled(ApiCase):
    enabled = False

    def test_disabled_gate(self):
        code, _ = call(self.port, "POST", "/api/servo", {"channel": 5, "angle": 100})
        self.assertEqual(code, 403)
        self.assertEqual(self.bus.frames, [])  # nothing reached the bus


if __name__ == "__main__":
    unittest.main()
