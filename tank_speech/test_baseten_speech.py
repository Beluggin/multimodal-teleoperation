"""Baseten speech hooks — offline tests. No network, no hardware, no key.

Run: python3 -m unittest discover -s tank_speech -p 'test_*.py'
"""

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tank_speech.baseten_client import (  # noqa: E402
    SpeechConfig, build_chain_ws_url, build_model_ws_url,
    parse_transcript_event,
)
from tank_speech.session import (  # noqa: E402
    SpeechInbox, SpeechSession, llm_fallback_route, route_transcript,
)


class Config(unittest.TestCase):
    def test_disabled_without_key(self):
        cfg = SpeechConfig.from_env({})
        self.assertFalse(cfg.enabled)
        self.assertFalse(cfg.status()["enabled"])
        self.assertEqual(cfg.status()["stt"], "unconfigured")

    def test_status_never_leaks_key(self):
        cfg = SpeechConfig.from_env({
            "BASETEN_API_KEY": "sekret-value",
            "BASETEN_STT_MODEL_ID": "abc123",
        })
        st = cfg.status()
        self.assertTrue(st["enabled"])
        self.assertTrue(st["has_key"])
        self.assertNotIn("sekret-value", str(st))

    def test_ws_url_builders(self):
        self.assertEqual(
            build_model_ws_url("abc123"),
            "wss://model-abc123.api.baseten.co/environments/production/websocket")
        self.assertEqual(
            build_chain_ws_url("xyz"),
            "wss://chain-xyz.api.baseten.co/environments/production/websocket")
        cfg = SpeechConfig.from_env({
            "BASETEN_API_KEY": "k", "BASETEN_STT_MODEL_ID": "abc123"})
        self.assertIn("model-abc123", cfg.stt_ws_url())

    def test_explicit_ws_url_wins(self):
        cfg = SpeechConfig.from_env({
            "BASETEN_API_KEY": "k",
            "BASETEN_STT_WS_URL": "wss://example.test/websocket",
            "BASETEN_STT_MODEL_ID": "abc123",
        })
        self.assertEqual(cfg.stt_ws_url(), "wss://example.test/websocket")


class TranscriptParsing(unittest.TestCase):
    def test_common_shapes(self):
        for raw, text, final in (
            ({"text": "go forward", "is_final": True}, "go forward", True),
            ({"transcript": "stop", "final": True}, "stop", True),
            ({"type": "transcript", "text": "wave"}, "wave", False),
            ({"segments": [{"text": "look "}, {"text": "left"}]}, "look left", False),
        ):
            with self.subTest(raw=raw):
                ev = parse_transcript_event(raw)
                self.assertIsNotNone(ev)
                self.assertEqual(ev.text, text)
                self.assertEqual(ev.is_final, final)

    def test_garbage_is_none_not_exception(self):
        for raw in (None, "", "not json", 42, [], {"nope": 1}, {"text": "  "}):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_transcript_event(raw))


class Routing(unittest.TestCase):
    """Speech routing reuses the fixed-phrase parser ONLY. No motion."""

    def test_goto_has_no_commands(self):
        r = route_transcript("go get the shoe")
        self.assertEqual(r["kind"], "goto")
        self.assertEqual(r["target"], "shoe")
        self.assertEqual(r["commands"], [])

    def test_unknown_and_refused_have_no_commands(self):
        for text in ("blorpt", "don't wave", "forward and wave"):
            with self.subTest(text=text):
                r = route_transcript(text)
                self.assertEqual(r["commands"], [])
                self.assertIn(r["kind"], ("unknown", "refused", "ambiguous"))

    def test_stop_is_priority(self):
        r = route_transcript("forward stop")
        self.assertEqual(r["kind"], "stop")
        self.assertTrue(r["priority"])


class LlmFallback(unittest.TestCase):
    def test_no_llm_is_noop_for_unknown(self):
        self.assertIsNone(llm_fallback_route("bring me the shoe"))

    def test_llm_proposal_must_reclassify_as_goto(self):
        r = llm_fallback_route("bring me the shoe",
                               llm_fn=lambda t: "go get the shoe")
        self.assertEqual(r["kind"], "goto")
        self.assertEqual(r["commands"], [])

    def test_llm_cannot_create_drive_commands(self):
        r = llm_fallback_route("blorpt", llm_fn=lambda t: "drive forward")
        self.assertIsNone(r)

    def test_llm_error_is_none_not_exception(self):
        def boom(t):
            raise RuntimeError("llm down")
        self.assertIsNone(llm_fallback_route("blorpt", llm_fn=boom))


class Inbox(unittest.TestCase):
    def test_stop_jumps_ahead_of_queued_finals(self):
        box = SpeechInbox(maxsize=8)
        box.put_final(route_transcript("wave"))
        box.put_final(route_transcript("look left"))
        box.put_final(route_transcript("stop"))
        self.assertEqual(box.poll()["kind"], "stop")
        self.assertEqual(box.poll()["kind"], "arm")

    def test_poll_is_nonblocking_when_empty(self):
        box = SpeechInbox()
        t0 = time.monotonic()
        self.assertIsNone(box.poll())
        self.assertLess(time.monotonic() - t0, 0.05)

    def test_partials_never_queue_a_command(self):
        box = SpeechInbox()
        box.put_partial("go forw")
        self.assertIsNone(box.poll())


class Session(unittest.TestCase):
    def test_slow_transcriber_never_blocks_the_caller_loop(self):
        # The robot loop keeps ticking while transcription is in flight:
        # that is the minimal-downtime property, measured not asserted.
        release = threading.Event()

        def slow_transcribe(chunk):
            release.wait(timeout=5)
            return {"text": "wave", "is_final": True}

        sess = SpeechSession(SpeechConfig.from_env({}),
                             transcribe_fn=slow_transcribe)
        sess.start()
        try:
            sess.feed_audio(b"\x00\x01")
            ticks = 0
            t0 = time.monotonic()
            while time.monotonic() - t0 < 0.3:
                sess.tick()
                ticks += 1
            self.assertGreater(ticks, 10)  # caller was never parked
            release.set()
            deadline = time.monotonic() + 5
            got = None
            while time.monotonic() < deadline and got is None:
                got = sess.tick()
                time.sleep(0.01)
            self.assertIsNotNone(got)
            self.assertEqual(got["kind"], "arm")
        finally:
            sess.stop()

    def test_transcriber_error_surfaces_but_session_survives(self):
        calls = {"n": 0}

        def flaky(chunk):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return {"text": "status", "is_final": True}

        sess = SpeechSession(SpeechConfig.from_env({}), transcribe_fn=flaky)
        sess.start()
        try:
            sess.feed_audio(b"a")
            sess.feed_audio(b"b")
            deadline = time.monotonic() + 5
            got = None
            while time.monotonic() < deadline and got is None:
                got = sess.tick()
                time.sleep(0.01)
            self.assertIsNotNone(got)
            self.assertEqual(got["kind"], "query")
            self.assertIn("boom", sess.status()["last_error"])
        finally:
            sess.stop()

    def test_warmup_runs_in_background_and_failure_is_survived(self):
        warmed = threading.Event()

        def warmup():
            warmed.set()
            raise RuntimeError("cold replica")

        sess = SpeechSession(SpeechConfig.from_env({}),
                             transcribe_fn=lambda c: {"text": "wave",
                                                      "is_final": True},
                             warmup_fn=warmup)
        sess.start()
        try:
            self.assertTrue(warmed.wait(timeout=5))
            self.assertTrue(sess.ready.wait(timeout=5))
            sess.feed_audio(b"x")
            deadline = time.monotonic() + 5
            got = None
            while time.monotonic() < deadline and got is None:
                got = sess.tick()
                time.sleep(0.01)
            self.assertEqual(got["kind"], "arm")
            self.assertIn("cold replica", sess.status()["last_error"])
        finally:
            sess.stop()

    def test_disabled_session_feed_is_a_noop(self):
        sess = SpeechSession(SpeechConfig.from_env({}))  # no transcribe_fn
        sess.start()
        try:
            self.assertFalse(sess.feed_audio(b"x"))
            self.assertIsNone(sess.tick())
            self.assertFalse(sess.status()["enabled"])
        finally:
            sess.stop()


import base64  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json as _json  # noqa: E402
import socket  # noqa: E402
import struct  # noqa: E402
import wave  # noqa: E402

from tank_speech.baseten_client import (  # noqa: E402
    BasetenStreamTranscriber, make_llm_fn, make_transcribe_fn, wav_to_pcm,
)
from tank_speech.ws_client import WebSocketError, ws_connect  # noqa: E402


def _wav_bytes(pcm=b"\x01\x00\x02\x00"):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return buf.getvalue()


class Wav(unittest.TestCase):
    def test_wav_header_stripped_to_pcm(self):
        self.assertEqual(wav_to_pcm(_wav_bytes(b"\x05\x00\x06\x00")),
                         b"\x05\x00\x06\x00")

    def test_non_wav_passes_through(self):
        self.assertEqual(wav_to_pcm(b"\x01\x02"), b"\x01\x02")


class _FakeWsServer(threading.Thread):
    """One-shot WS server: collects binary audio, replies one final."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.audio = b""
        self.auth = ""

    def run(self):
        conn, _ = self.sock.accept()
        f = conn.makefile("rb")
        headers = {}
        while True:
            line = f.readline().decode("latin1").strip()
            if not line:
                break
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        self.auth = headers.get("authorization", "")
        accept = base64.b64encode(hashlib.sha1(
            (headers["sec-websocket-key"] +
             "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\n"
                     b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                     b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        while True:
            head = f.read(2)
            if len(head) < 2:
                break
            fin_op, b2 = head[0], head[1]
            op = fin_op & 0x0F
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", f.read(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", f.read(8))[0]
            mask = f.read(4) if b2 & 0x80 else b""
            payload = bytearray(f.read(ln))
            for i in range(len(payload)):
                payload[i] ^= mask[i % 4]
            if op == 2:
                self.audio += bytes(payload)
            elif op == 1 and b'"end"' in bytes(payload):
                msg = _json.dumps(
                    {"text": "go get the shoe", "is_final": True}).encode()
                conn.sendall(bytes([0x81, len(msg)]) + msg)
            elif op == 8:
                conn.sendall(b"\x88\x00")
                break
        conn.close()
        self.sock.close()


class WsTransport(unittest.TestCase):
    def test_transcriber_streams_pcm_and_collects_final(self):
        server = _FakeWsServer()
        server.start()
        cfg = SpeechConfig.from_env({
            "BASETEN_API_KEY": "k",
            "BASETEN_STT_WS_URL": f"ws://127.0.0.1:{server.port}/websocket"})
        fn = make_transcribe_fn(cfg)
        self.assertIsNotNone(fn)
        events = fn(_wav_bytes(b"\x07\x00\x08\x00"))
        server.join(timeout=5)
        self.assertEqual(server.audio, b"\x07\x00\x08\x00")
        self.assertEqual(server.auth, "Bearer k")
        ev = parse_transcript_event(events[-1])
        self.assertEqual(ev.text, "go get the shoe")
        self.assertTrue(ev.is_final)

    def test_make_transcribe_fn_none_when_unconfigured(self):
        self.assertIsNone(make_transcribe_fn(SpeechConfig.from_env({})))
        self.assertIsNone(make_transcribe_fn(
            SpeechConfig.from_env({"BASETEN_API_KEY": "k"})))

    def test_ws_connect_rejects_non_ws_url(self):
        with self.assertRaises(WebSocketError):
            ws_connect("https://example.test/socket")


class StreamConnection(unittest.TestCase):
    def test_open_send_poll_final_close(self):
        from tank_speech.baseten_client import BasetenStreamConnection
        server = _FakeWsServer()
        server.start()
        cfg = SpeechConfig.from_env({
            "BASETEN_API_KEY": "k",
            "BASETEN_STT_WS_URL": f"ws://127.0.0.1:{server.port}/websocket"})
        conn = BasetenStreamConnection(cfg)
        conn.open()
        conn.send_audio(b"\x09\x00\x0a\x00")
        conn.send_end()
        events = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = conn.poll()
            if events:
                break
            time.sleep(0.02)
        conn.close()
        server.join(timeout=5)
        self.assertEqual(server.audio, b"\x09\x00\x0a\x00")
        ev = parse_transcript_event(events[-1])
        self.assertEqual(ev.text, "go get the shoe")
        self.assertTrue(ev.is_final)


class LlmTransport(unittest.TestCase):
    def test_llm_fn_reads_chat_completion(self):
        seen = {}

        class Resp:
            def read(self):
                return _json.dumps({"choices": [{"message": {
                    "content": "go get the shoe"}}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=0):
            seen["url"] = req.full_url
            seen["body"] = _json.loads(req.data.decode())
            return Resp()

        cfg = SpeechConfig.from_env({"BASETEN_API_KEY": "k"})
        fn = make_llm_fn(cfg, opener=opener)
        self.assertIsNotNone(fn)
        r = llm_fallback_route("bring me the shoe", llm_fn=fn)
        self.assertEqual(r["kind"], "goto")
        self.assertEqual(r["target"], "shoe")
        self.assertEqual(r["commands"], [])
        self.assertIn("muse-spark", seen["body"]["model"])

    def test_session_uses_llm_only_for_unknown_finals(self):
        sess = SpeechSession(
            SpeechConfig.from_env({}),
            transcribe_fn=lambda c: {"text": "bring me the shoe",
                                     "is_final": True},
            llm_fn=lambda t: "go get the shoe")
        sess.start()
        try:
            sess.feed_audio(b"x")
            deadline = time.monotonic() + 5
            got = None
            while time.monotonic() < deadline and got is None:
                got = sess.tick()
                time.sleep(0.01)
            self.assertEqual(got["kind"], "goto")
            self.assertEqual(got["commands"], [])
        finally:
            sess.stop()


if __name__ == "__main__":
    unittest.main()
