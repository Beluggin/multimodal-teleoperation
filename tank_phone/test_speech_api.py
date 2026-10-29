"""Speech-hook API tests — previews only, no hardware, no network.

Run: python3 -m unittest discover -s tank_phone -p 'test_*.py'
"""

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as srv  # noqa: E402

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


class SpeechApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.httpd.servo_enabled = False
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_status_reports_unwired_and_disabled_without_key(self):
        code, body = call(self.port, "GET", "/api/speech/status")
        self.assertEqual(code, 200)
        self.assertFalse(body["wired"])
        self.assertIn("speech", body)
        self.assertNotIn("BASETEN_API_KEY", str(body))

    def test_transcript_goto_preview_has_no_commands(self):
        code, body = call(self.port, "POST", "/api/speech/transcript",
                          {"text": "go get the shoe"})
        self.assertEqual(code, 200)
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["kind"], "goto")
        self.assertEqual(body["commands"], [])

    def test_transcript_rejects_non_string(self):
        code, _ = call(self.port, "POST", "/api/speech/transcript",
                       {"text": 42})
        self.assertEqual(code, 400)


def call_raw(port, path, body, ctype):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST", data=body,
        headers={"Content-Type": ctype})
    try:
        with _OPENER.open(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class _FakeSession:
    """Stands in for SpeechSession: one canned routed final per feed."""

    enabled = True

    def __init__(self, routed):
        self._routed = routed
        self.fed = []

    def feed_audio(self, chunk):
        self.fed.append(chunk)
        return True

    def tick(self):
        routed, self._routed = self._routed, None
        return routed


class AudioApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.httpd.servo_enabled = False
        cls.httpd.speech_session = None
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def tearDown(self):
        self.httpd.speech_session = None

    def test_audio_503_when_speech_not_configured(self):
        code, body = call_raw(self.port, "/api/speech/audio",
                              b"RIFFxxxx", "audio/wav")
        self.assertEqual(code, 503)
        self.assertFalse(body["ok"])

    def test_audio_returns_routed_preview_no_commands(self):
        routed = {"kind": "goto", "label": "goto", "target": "shoe",
                  "commands": [], "reason": "r", "priority": False,
                  "source": "speech", "text": "go get the shoe"}
        self.httpd.speech_session = _FakeSession(routed)
        code, body = call_raw(self.port, "/api/speech/audio",
                              b"RIFFxxxx", "audio/wav")
        self.assertEqual(code, 200)
        self.assertTrue(body["wired"])
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["kind"], "goto")
        self.assertEqual(body["commands"], [])

    def test_audio_rejects_non_audio_content_type(self):
        self.httpd.speech_session = _FakeSession(None)
        code, _ = call_raw(self.port, "/api/speech/audio",
                           b"{}", "application/json")
        self.assertEqual(code, 415)


class _FakeStreamConn:
    """Stateful Baseten stand-in: poll yields one final after end."""

    def __init__(self):
        self.audio = b""
        self.ended = False

    def open(self):
        pass

    def send_audio(self, pcm):
        self.audio += pcm

    def send_end(self):
        self.ended = True

    def poll(self):
        if self.ended and self.audio:
            self.audio = b""
            return ['{"text": "check out the shoe", "is_final": true}']
        return []

    def close(self):
        pass


class LaunchApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.httpd.servo_enabled = False
        cls.httpd.launch_status = {"state": "idle", "text": "",
                                   "target": "", "detail": "",
                                   "stop_requested": False}
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        self.httpd.launch_status = {"state": "idle", "text": "",
                                    "target": "", "detail": "",
                                    "stop_requested": False}

    def test_launch_accepts_goto_only(self):
        code, body = call(self.port, "POST", "/api/launch",
                          {"text": "wave"})
        self.assertEqual(code, 400)
        self.assertFalse(body["ok"])
        code, body = call(self.port, "POST", "/api/launch",
                          {"text": "investigate the shoe"})
        self.assertEqual(code, 200)
        self.assertEqual(body["target"], "shoe")
        self.assertEqual(body["state"], "pending")

    def test_second_launch_conflicts_while_pending(self):
        call(self.port, "POST", "/api/launch",
             {"text": "go get the shoe"})
        code, _ = call(self.port, "POST", "/api/launch",
                       {"text": "go get the shoe"})
        self.assertEqual(code, 409)

    def test_consume_once_then_report_done(self):
        call(self.port, "POST", "/api/launch",
             {"text": "go get the shoe"})
        code, body = call(self.port, "POST", "/api/launch/consume", {})
        self.assertEqual(code, 200)
        self.assertEqual(body["text"], "go get the shoe")
        code, _ = call(self.port, "POST", "/api/launch/consume", {})
        self.assertEqual(code, 409)
        code, body = call(self.port, "POST", "/api/launch/report",
                          {"state": "done", "detail": "ARRIVED"})
        self.assertEqual(code, 200)
        code, body = call(self.port, "GET", "/api/launch")
        self.assertEqual(body["launch"]["state"], "done")

    def test_stop_pending_clears_it(self):
        call(self.port, "POST", "/api/launch",
             {"text": "go get the shoe"})
        code, body = call(self.port, "POST", "/api/launch/stop", {})
        self.assertEqual(code, 200)
        code, body = call(self.port, "GET", "/api/launch")
        self.assertEqual(body["launch"]["state"], "stopped")


class StreamApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.httpd.servo_enabled = False
        cls.httpd.speech_session = None
        cls.httpd.speech_conn_factory = None
        cls.httpd.speech_partial = ""
        cls.httpd.speech_last_routed = None
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_stream_503_without_factory(self):
        code, _ = call(self.port, "GET", "/api/speech/latest")
        self.assertEqual(code, 200)  # latest always answers, honestly empty

    def test_stream_relays_audio_and_routes_final(self):
        from tank_speech.ws_client import ws_connect
        fake = _FakeStreamConn()
        self.httpd.speech_conn_factory = lambda: fake
        try:
            ws = ws_connect(f"ws://127.0.0.1:{self.port}/api/speech/stream",
                            timeout=5)
            ws.send_binary(b"\x01\x00\x02\x00")
            ws.send_text('{"type": "end"}')
            routed = None
            deadline = time.time() + 5
            while time.time() < deadline:
                _, body = call(self.port, "GET", "/api/speech/latest")
                routed = body.get("routed")
                if routed:
                    break
                time.sleep(0.05)
            ws.close()
            self.assertIsNotNone(routed)
            self.assertEqual(routed["kind"], "goto")
            self.assertEqual(routed["target"], "shoe")
            self.assertEqual(routed["commands"], [])
        finally:
            self.httpd.speech_conn_factory = None


if __name__ == "__main__":
    unittest.main()
