#!/usr/bin/env python3
"""src/tank_phone/server.py — Pi-hosted phone GUI for the tank.

Stdlib only. Serves index.html plus a JSON API. Tap/text endpoints are
dry-run previews. Servo writes are LIVE only with --enable-servo and
motor writes only with --enable-motors; neither is ever the default —
those flags are the authorization gates, set only with Adam present at
the tank. Servo writes speak the proven 0x17 frame via servo_ctl.py
(channels 1-6); motors speak the bench-listener protocol (:5098, token
read from a Pi-local file, never sent to the phone).

Try it with no robot (--demo labels every control as simulated, and never
talks to motors, servos or the desktop launcher):
    python3 src/tank_phone/server.py --port 8123 --demo

Desktop smoke (no hardware touched):
    python3 src/tank_phone/server.py --port 8123
    curl localhost:8123/api/status

Pi deploy:
    scp src/tank_phone/server.py src/tank_phone/index.html src/tank_phone/servo_ctl.py \\
        src/tank_tools/xiaor_text_action.py tank-lan:~/tank_phone/
    ssh tank-lan 'cd ~/tank_phone && TANK_PHONE_MJPEG_CMD=/tmp/qstream \\
        python3 server.py --bind 0.0.0.0 --enable-servo'
Phone on the same WiFi: http://tank.local:8123/
(Tailscale address works too when it is up.)
"""

import argparse
import json
import math
import os
import select
import shlex
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
SIMULATED = "Simulated, hardware not available."
# The desktop drive loop (src/tank_vision/centre_run.grab) writes each look
# here with qstream while it owns the camera.
DRIVE_FRAME = "/tmp/centre_frame.jpg"
for _p in (HERE, os.path.dirname(HERE),
           os.path.join(os.path.dirname(HERE), "tank_tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import xiaor_text_action as tx
except ImportError:  # desktop without tank_tools on path: text endpoint degrades
    tx = None

try:
    from tank_speech.baseten_client import (
        BasetenStreamConnection as _BasetenStreamConnection,
        SpeechConfig as _SpeechConfig,
        make_llm_fn as _make_llm_fn,
        make_transcribe_fn as _make_transcribe_fn,
        parse_transcript_event as _parse_transcript_event,
    )
    from tank_speech.session import (
        SpeechSession as _SpeechSession,
        route_transcript as _route_transcript,
    )
    from tank_speech.ws_client import (
        WebSocketError as _WebSocketError,
        accept_websocket as _accept_websocket,
    )
except ImportError:  # speech hooks degrade to 503, page still serves
    _SpeechConfig = None
    _route_transcript = None
    _SpeechSession = None
    _make_llm_fn = None
    _make_transcribe_fn = None
    _BasetenStreamConnection = None
    _parse_transcript_event = None
    _accept_websocket = None
    _WebSocketError = Exception

try:
    import servo_ctl
except ImportError:  # servo endpoints degrade to 503, page still serves
    servo_ctl = None

# Tap-point brain (skeleton values): full-frame tap maps to a bounded
# pan/tilt nudge preview. Degrees chosen small; nothing is sent anywhere.
MAX_NUDGE_DEG = 10.0

# Camera: rpicam-vid emits concatenated JPEGs on stdout; the server wraps
# each in a multipart boundary for <img>/phone playback. Override for tests:
#   TANK_PHONE_MJPEG_CMD="python3 /tmp/fake_mjpeg.py"
_MJPEG_CMD = os.environ.get(
    "TANK_PHONE_MJPEG_CMD",
    "rpicam-vid --codec mjpeg --timeout 0 --width 640 --height 480 -o -")
_FIRST_BYTES_TIMEOUT = 4.0  # then 503 instead of hanging the phone


def _split_jpegs(buf):
    """Pull complete SOI..EOI JPEGs off the front of buf. Returns (frames, rest)."""
    frames = []
    while True:
        soi = buf.find(b"\xff\xd8")
        if soi < 0:
            return frames, b"" if len(buf) < 2 else buf[-2:]
        eoi = buf.find(b"\xff\xd9", soi + 2)
        if eoi < 0:
            return frames, buf[soi:]
        frames.append(buf[soi:eoi + 2])
        buf = buf[eoi + 2:]


def _load_flags(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_flags(path, flags):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(flags, f)
    os.replace(tmp, path)


def _load_limits(path):
    limits = dict(servo_ctl.LIMITS) if servo_ctl else {}
    try:
        with open(path) as f:
            saved = json.load(f)
        for key, val in saved.items():
            ch, (lo, hi) = int(key), (int(val[0]), int(val[1]))
            if ch in limits and 0 <= lo < hi <= 180:
                limits[ch] = (lo, hi)
    except (OSError, ValueError, TypeError, IndexError):
        pass
    return limits


def tap_preview(x, y):
    """Normalized tap (0..1, origin top-left) -> pan/tilt nudge preview."""
    dx = x - 0.5          # + = right
    dy = 0.5 - y          # + = up
    return {"pan_deg": round(dx * 2 * MAX_NUDGE_DEG, 1),
            "tilt_deg": round(dy * 2 * MAX_NUDGE_DEG, 1)}


# ---------------------------------------------------------------------------
# Manual drive: thumbstick -> bench-listener move. The listener's own caps
# (3 s / 40%) are the hard floor; the page cap and --motor-cap can only
# lower duty. Continuous drive works by re-sending short (0.5 s) moves at
# ~10 Hz while the stick is held — if the client dies, the last move
# self-stops within 0.5 s and the listener stops on disconnect.
# ---------------------------------------------------------------------------
HARD_DUTY_CAP = 40.0
STICK_DEADZONE = 0.18
DRIVE_SECS = 0.5

# Speech audio: one short utterance per POST (16 kHz mono WAV from the
# page is ~32 KB/s; 2 MB is over a minute — plenty, and bounded so a bad
# client cannot park a handler thread or the speech queue).
SPEECH_AUDIO_MAX = 2_000_000
SPEECH_WAIT_SECS = 20.0


def stick_to_move(x, y, cap):
    """Stick (x right+, y down+, each -1..1) -> {move, duty, trim}.

    Pure function. Garbage in -> stop. Pure side push spins; otherwise
    forward/reverse with steering trim (right track faster = turn left,
    so turning right needs negative trim — see src/tank_bench/README.md).
    """
    try:
        x, y, cap = float(x), float(y), float(cap)
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(cap)):
            raise ValueError
    except (TypeError, ValueError):
        return {"move": "stop", "duty": 0.0, "trim": 0.0}
    x = max(-1.0, min(1.0, x))
    y = max(-1.0, min(1.0, y))
    cap = max(0.0, min(HARD_DUTY_CAP, cap))
    if math.hypot(x, y) < STICK_DEADZONE:
        return {"move": "stop", "duty": 0.0, "trim": 0.0}
    if abs(x) > abs(y):
        return {"move": "spinr" if x > 0 else "spinl",
                "duty": round(abs(x) * cap, 1), "trim": 0.0}
    return {"move": "go" if y < 0 else "rev",
            "duty": round(abs(y) * cap, 1),
            "trim": round(-x * 30.0, 1)}


class BenchMotorClient:
    """One persistent connection to the bench listener (:5098).

    Token is read from a Pi-local file at construction and never leaves
    the Pi: it is only ever written into listener lines, never returned
    to the phone. Disconnect stops the tank (listener behaviour), so a
    dead server can never leave it driving.
    """

    def __init__(self, token_file, host="127.0.0.1", port=5098):
        with open(token_file) as f:
            self._token = f.read().strip()
        self._host, self._port = host, port
        self._sock = None
        self._file = None

    def _connect(self):
        self._sock = socket.create_connection((self._host, self._port),
                                              timeout=5)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._file = self._sock.makefile("r")

    def send(self, move, secs, duty, trim):
        line = f"{self._token} {move} {secs:g} {duty:g} {trim:g}\n"
        try:
            if self._sock is None:
                self._connect()
            self._sock.sendall(line.encode())
            reply = self._file.readline().strip()
        except (OSError, ValueError):
            self.close()
            self._connect()           # one retry on a fresh connection
            self._sock.sendall(line.encode())
            reply = self._file.readline().strip()
        if not reply.startswith("ok"):
            raise OSError(f"bench listener replied {reply!r}")
        return reply

    def close(self):
        try:
            if self._sock is not None:
                self._sock.close()
        except OSError:
            pass
        self._sock = self._file = None


class Handler(BaseHTTPRequestHandler):
    server_version = "TankPhone/0.1"

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 4096:
            return None
        try:
            return json.loads(self.rfile.read(n).decode())
        except (ValueError, UnicodeDecodeError):
            return None

    def _serve_drive_frame(self):
        """Latest complete frame the drive loop took during this launch.

        204 when there is none yet: no launch, no file, or only a frame
        left over from an earlier mission. A frame qstream is still
        writing (no JPEG end marker) falls back to the last complete one.
        """
        s = self.server
        queued_at = self._launch_status().get("queued_at")
        path = getattr(s, "drive_frame_path", DRIVE_FRAME)
        body = None
        try:
            if queued_at is not None and os.path.getmtime(path) >= queued_at:
                with open(path, "rb") as f:
                    data = f.read()
                if data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9":
                    s.drive_frame_last = (queued_at, data)
                    body = data
        except OSError:
            pass
        last = getattr(s, "drive_frame_last", None)
        if body is None and last and last[0] == queued_at:
            body = last[1]
        if body is None:
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_mjpeg(self):
        """Relay concatenated-JPEG stdout as multipart/x-mixed-replace.

        One producer process per viewer (single-viewer assumption for now).
        No camera / dead producer -> 503 JSON, never a hung phone.
        Spawning the camera touches no motors or servos.
        """
        try:
            proc = subprocess.Popen(shlex.split(_MJPEG_CMD),
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        except (FileNotFoundError, PermissionError):
            return self._json({"ok": False,
                                "error": "camera not configured"}, code=503)
        try:
            buf, frames = b"", []
            deadline = time.monotonic() + _FIRST_BYTES_TIMEOUT
            while not frames and time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                ready, _, _ = select.select(
                    [proc.stdout], [], [],
                    max(0.0, deadline - time.monotonic()))
                if not ready:
                    continue
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                frames, buf = _split_jpegs(buf)
            if not frames:
                proc.terminate()
                return self._json({"ok": False,
                                    "error": "camera unavailable"}, code=503)
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=FRAME")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.flush()
            while True:
                for fr in frames:
                    head = (b"--FRAME\r\nContent-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(fr)).encode() +
                            b"\r\n\r\n")
                    self.wfile.write(head + fr + b"\r\n")
                frames, buf = [], buf
                chunk = proc.stdout.read(65536)
                if not chunk:
                    return
                buf += chunk
                frames, buf = _split_jpegs(buf)
        except (BrokenPipeError, ConnectionResetError):
            pass  # phone navigated away; normal
        finally:
            proc.terminate()

    def _handle_speech_stream(self):
        """Browser <-> Baseten STT relay over one websocket.

        Binary PCM frames flow up, transcript events flow into
        server.speech_partial / speech_last_routed, and the page polls
        /api/speech/latest. Routed finals are parser previews ONLY —
        this relay has no path to run(), motors, or servos.
        """
        factory = getattr(self.server, "speech_conn_factory", None)
        if factory is None or _accept_websocket is None:
            return self._json({"ok": False,
                               "error": "speech streaming not configured"},
                              code=503)
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            ws = _accept_websocket(self.connection, self.rfile, headers)
        except Exception:
            return  # 400 already written by accept_websocket
        self.close_connection = True
        upstream = factory()
        try:
            upstream.open()
        except Exception as e:  # Baseten unreachable: honest close
            self.server.speech_partial = ""
            self.server.speech_last_error = str(e)
            ws.close()
            return
        ws.settimeout(0.05)
        try:
            while True:
                try:
                    kind, payload = ws.recv_message()
                except TimeoutError:
                    kind, payload = None, None
                except Exception:
                    break
                if kind == "close":
                    break
                if kind == "binary":
                    upstream.send_audio(payload)
                elif kind == "text" and '"end"' in str(payload):
                    upstream.send_end()
                for raw in upstream.poll():
                    ev = _parse_transcript_event(raw)
                    if ev is None:
                        continue
                    if ev.is_final:
                        routed = _route_transcript(ev.text)
                        seq = getattr(self.server, "speech_seq", 0) + 1
                        self.server.speech_seq = seq
                        self.server.speech_last_routed = {**routed,
                                                          "seq": seq}
                        self.server.speech_partial = ""
                    else:
                        self.server.speech_partial = ev.text
        finally:
            try:
                upstream.close()
            except Exception:
                pass
            ws.close()

    def _launch_status(self):
        st = getattr(self.server, "launch_status", None)
        if st is None:
            st = self.server.launch_status = {
                "state": "idle", "text": "", "target": "", "detail": "",
                "stop_requested": False}
        return st

    # -- servo sliders ---------------------------------------------------
    def _lock(self):
        lock = getattr(self.server, "servo_lock", None)
        if lock is None:
            lock = self.server.servo_lock = threading.Lock()
        return lock

    def _servo_payload(self):
        s = self.server
        return {"ok": True,
                "enabled": bool(getattr(s, "servo_enabled", False)),
                "labels": {str(k): v for k, v in servo_ctl.LABELS.items()}
                if servo_ctl else {},
                "state": {str(k): v for k, v in
                          getattr(s, "servo_state", {}).items()},
                "limits": {str(k): list(v) for k, v in
                           getattr(s, "servo_limits", {}).items()},
                "flags": getattr(s, "servo_flags", [])}

    def _parse_servo(self, data, need_angle=True):
        try:
            raw_ch = data["channel"]
            if isinstance(raw_ch, bool) or int(raw_ch) != raw_ch:
                raise ValueError
            channel = int(raw_ch)
            angle = data["angle"] if need_angle else None
            if need_angle:
                if isinstance(angle, bool) or int(angle) != angle:
                    raise ValueError
                angle = int(angle)
        except (KeyError, TypeError, ValueError):
            return None, None
        try:
            servo_ctl.check(channel, angle if need_angle else 0)
        except (ValueError, AttributeError):
            return None, None
        return channel, angle

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # The page changes often during the demo build; a stale
            # cached copy looks exactly like "the fix didn't work".
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status":
            self._json({"ok": True,
                        "servo_enabled": bool(getattr(self.server,
                                                      "servo_enabled", False)),
                        "demo": bool(getattr(self.server, "demo", False)),
                        "note": "tap/text are previews; servo sliders live "
                                "only when servo_enabled"})
        elif path == "/api/speech/status":
            if _SpeechConfig is None:
                return self._json({"ok": False,
                                   "error": "speech hooks unavailable"},
                                  code=503)
            session = getattr(self.server, "speech_session", None)
            wired = bool(session is not None
                         and getattr(session, "enabled", False))
            wired = wired or getattr(
                self.server, "speech_conn_factory", None) is not None
            self._json({"ok": True, "wired": wired,
                        "speech": _SpeechConfig.from_env().status(),
                        "session": session.status() if session else None,
                        "note": "speech is preview-only: transcripts are "
                                "classified, nothing sent to hardware"})
        elif path == "/api/launch":
            self._json({"ok": True, "launch": self._launch_status()})
        elif path == "/api/speech/stream":
            self._handle_speech_stream()
        elif path == "/api/speech/latest":
            self._json({"ok": True,
                        "partial": getattr(self.server,
                                           "speech_partial", ""),
                        "routed": getattr(self.server,
                                          "speech_last_routed", None),
                        "error": getattr(self.server,
                                         "speech_last_error", "")})
        elif path == "/api/telemetry":
            s = self.server
            self._json({
                "ok": True,
                "servo_enabled": bool(getattr(s, "servo_enabled", False)),
                "motor_enabled": bool(getattr(s, "motor_enabled", False)),
                "demo": bool(getattr(s, "demo", False)),
                "motor_cap": getattr(s, "motor_cap", HARD_DUTY_CAP),
                "servo": self._servo_payload() if servo_ctl else None,
                "speech": (_SpeechConfig.from_env().status()
                           if _SpeechConfig else None),
                "ultrasonic": "unavailable — physical check pending",
                "camera": "mjpeg /api/frame",
            })
        elif path == "/api/servo":
            if servo_ctl is None:
                return self._json({"ok": False, "error": "servo unavailable"},
                                  code=503)
            self._json(self._servo_payload())
        elif path == "/api/frame":
            self._serve_mjpeg()
        elif path == "/api/driveframe":
            self._serve_drive_frame()
        else:
            self._json({"ok": False, "error": "not found"}, code=404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/tap":
            data = self._read_json() or {}
            try:
                x, y = float(data["x"]), float(data["y"])
            except (KeyError, TypeError, ValueError):
                return self._json({"ok": False,
                                    "error": "need numeric x and y in 0..1"},
                                   code=400)
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                return self._json({"ok": False,
                                    "error": "x and y must be in 0..1"},
                                   code=400)
            self._json({"ok": True, "dry_run": True,
                        "tap": {"x": x, "y": y},
                        "nudge": tap_preview(x, y),
                        "note": "preview only: not sent (dry run)"})
        elif path == "/api/text":
            data = self._read_json() or {}
            text = data.get("text", "")
            if not isinstance(text, str):
                return self._json({"ok": False,
                                    "error": "text must be a string"},
                                   code=400)
            if tx is None:
                return self._json({"ok": False,
                                    "error": "text parser unavailable"},
                                   code=503)
            a = tx.classify(text)  # classify ONLY: never run(), never drive
            self._json({"ok": True, "dry_run": True,
                        "kind": a.kind, "label": a.label, "target": a.target,
                        "duration": a.duration, "reason": a.reason,
                        "commands": a.commands,
                        "note": "preview only: not sent (dry run)"})
        elif path == "/api/speech/transcript":
            # Speech hook (opened, not wired): a future Baseten STT final
            # lands here / in SpeechSession.tick(). Classify ONLY.
            data = self._read_json() or {}
            text = data.get("text", "")
            if not isinstance(text, str):
                return self._json({"ok": False,
                                   "error": "text must be a string"},
                                  code=400)
            if _route_transcript is None:
                return self._json({"ok": False,
                                   "error": "speech hooks unavailable"},
                                  code=503)
            session = getattr(self.server, "speech_session", None)
            self._json({"ok": True, "dry_run": True,
                        "wired": bool(session is not None and
                                      getattr(session, "enabled", False)),
                        **_route_transcript(text),
                        "note": "preview only: not sent (dry run)"})
        elif path == "/api/speech/audio":
            # Phone mic utterance -> Baseten STT (background worker) ->
            # parser preview. Classify ONLY: this endpoint has no path
            # to run(), the bench listener, or any servo write.
            ctype = (self.headers.get("Content-Type") or ""
                     ).split(";")[0].strip().lower()
            if not (ctype.startswith("audio/")
                    or ctype == "application/octet-stream"):
                return self._json(
                    {"ok": False,
                     "error": "need an audio Content-Type (e.g. audio/wav)"},
                    code=415)
            session = getattr(self.server, "speech_session", None)
            if session is None or not getattr(session, "enabled", False):
                return self._json({"ok": False,
                                   "error": "speech not configured on "
                                            "server (Baseten STT env)"},
                                  code=503)
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n <= 0:
                return self._json({"ok": False, "error": "empty audio body"},
                                  code=400)
            if n > SPEECH_AUDIO_MAX:
                return self._json({"ok": False,
                                   "error": "audio too long (one short "
                                            "utterance please)"},
                                  code=413)
            audio = self.rfile.read(n)
            if not session.feed_audio(audio):
                return self._json({"ok": False,
                                   "error": "speech busy — try again"},
                                  code=503)
            deadline = time.monotonic() + SPEECH_WAIT_SECS
            routed = None
            while time.monotonic() < deadline:
                routed = session.tick()
                if routed is not None:
                    break
                time.sleep(0.05)
            if routed is None:
                err = getattr(session, "last_error", "")
                return self._json(
                    {"ok": False, "wired": True,
                     "error": "no transcript heard"
                              + (f" ({err})" if err else " — try again")},
                    code=504)
            self._json({"ok": True, "dry_run": True, "wired": True,
                        **routed,
                        "note": "speech preview only: not sent (dry run)"})
        elif path == "/api/launch":
            # Page -> desktop launcher queue. Goto only: the desktop
            # launcher (src/tank_vision/launcher.py) consumes one pending
            # launch and drives under its own authorisation; this Pi
            # endpoint itself moves nothing.
            data = self._read_json() or {}
            text = data.get("text", "")
            if not isinstance(text, str) or tx is None:
                return self._json({"ok": False,
                                   "error": "need instruction text"},
                                  code=400)
            a = tx.classify(text)
            if a.kind != "goto" or not a.target:
                return self._json(
                    {"ok": False, "kind": a.kind,
                     "error": f"only a goto can launch ({a.kind})"},
                    code=400)
            st = self._launch_status()
            if getattr(self.server, "demo", False):
                # Never "pending", so a launcher can't consume it, and never
                # "done", so it can't read as a mission that happened.
                self.server.launch_status = {
                    "state": "simulated", "text": text, "target": a.target,
                    "detail": SIMULATED + " Nothing moved and SAM wasn't called.",
                    "stop_requested": False}
                return self._json({"ok": True, "simulated": True,
                                   "state": "simulated", "target": a.target,
                                   "detail": self.server.launch_status["detail"]})
            if st["state"] in ("pending", "running"):
                return self._json({"ok": False,
                                   "error": "a drive is already active"},
                                  code=409)
            self.server.launch_status = {
                "state": "pending", "text": text, "target": a.target,
                "detail": "queued — waiting for the desktop launcher",
                "stop_requested": False, "queued_at": time.time()}
            self._json({"ok": True, "state": "pending",
                        "target": a.target})
        elif path == "/api/launch/consume":
            st = self._launch_status()
            if st["state"] != "pending":
                return self._json({"ok": False,
                                   "error": "no pending launch"}, code=409)
            st["state"] = "running"
            st["detail"] = "launcher starting"
            self._json({"ok": True, "text": st["text"],
                        "target": st["target"]})
        elif path == "/api/launch/report":
            data = self._read_json() or {}
            state = data.get("state")
            if state not in ("running", "done", "failed", "stopped"):
                return self._json({"ok": False,
                                   "error": "bad report state"}, code=400)
            st = self._launch_status()
            st["state"] = state
            st["detail"] = str(data.get("detail", ""))[:200]
            if state in ("done", "failed", "stopped"):
                st["stop_requested"] = False
            self._json({"ok": True, "launch": st})
        elif path == "/api/launch/stop":
            st = self._launch_status()
            if st["state"] == "pending":
                st["state"] = "stopped"
                st["detail"] = "stopped before it started"
            elif st["state"] == "running":
                st["stop_requested"] = True
                st["detail"] = "stop requested"
            self._json({"ok": True, "launch": st})
        elif path == "/api/drive":
            # Manual thumbstick. Stop is ALWAYS accepted; any real move
            # needs --enable-motors (Adam present). Duty is clamped by
            # the page cap, the server cap, and the 40% hard cap.
            data = self._read_json() or {}
            mv = stick_to_move(data.get("x", 0), data.get("y", 0),
                               data.get("cap", HARD_DUTY_CAP))
            mv["duty"] = min(mv["duty"],
                             float(getattr(self.server, "motor_cap",
                                           HARD_DUTY_CAP)))
            if mv["move"] != "stop" and getattr(self.server, "demo", False):
                return self._json({"ok": True, "simulated": True, **mv,
                                   "note": SIMULATED})
            if mv["move"] != "stop" and not getattr(
                    self.server, "motor_enabled", False):
                return self._json({"ok": False,
                                   "error": "motor live control disabled"},
                                  code=403)
            client = getattr(self.server, "motor_client", None)
            if client is None:
                if mv["move"] == "stop":
                    return self._json({"ok": True, **mv,
                                       "note": "motors disabled: already stopped"})
                return self._json({"ok": False,
                                   "error": "bench listener not connected"},
                                  code=503)
            try:
                with self._lock():
                    reply = client.send(mv["move"], DRIVE_SECS,
                                        mv["duty"], mv["trim"])
            except OSError as e:
                return self._json(
                    {"ok": False,
                     "error": f"bench listener unreachable ({e}) — "
                              f"is motor_listen running on :5098?"},
                    code=503)
            self._json({"ok": True, **mv, "reply": reply})
        elif path == "/api/camera":
            # Camera thumbstick: incremental pan/tilt through the proven
            # servo path. Same --enable-servo gate as the sliders.
            if servo_ctl is None:
                return self._json({"ok": False, "error": "servo unavailable"},
                                  code=503)
            data = self._read_json() or {}
            try:
                x, y = float(data.get("x", 0)), float(data.get("y", 0))
                if not (math.isfinite(x) and math.isfinite(y)):
                    raise ValueError
            except (TypeError, ValueError):
                return self._json({"ok": False, "error": "need numeric x, y"},
                                  code=400)
            # Stick axes are inverted vs servo angle on the physical
            # head (Adam, live test 2026-10-29): stick right must pan
            # right, which is ch6 DOWN; stick up must tilt up, ch5 UP.
            step_pan = int(round(max(-1.0, min(1.0, x)) * -3))
            step_tilt = int(round(max(-1.0, min(1.0, y)) * -3))
            if getattr(self.server, "demo", False):
                return self._json({"ok": True, "simulated": True,
                                   "note": SIMULATED})
            if not getattr(self.server, "servo_enabled", False):
                return self._json({"ok": False,
                                   "error": "servo live control disabled"},
                                  code=403)
            limits = getattr(self.server, "servo_limits", servo_ctl.LIMITS)
            with self._lock():
                state = dict(self.server.servo_state)
                new = dict(state)
                new[6] = min(max(state[6] + step_pan, limits[6][0]),
                             limits[6][1])
                new[5] = min(max(state[5] + step_tilt, limits[5][0]),
                             limits[5][1])
                try:
                    for ch in (6, 5):
                        if new[ch] != state[ch]:
                            self.server.servo_bus.set_angle(ch, new[ch])
                            self.server.servo_state[ch] = new[ch]
                except OSError as e:
                    return self._json({"ok": False,
                                       "error": f"i2c write failed: {e}"},
                                      code=503)
            self._json(self._servo_payload())
        elif path == "/api/servo":
            if servo_ctl is None:
                return self._json({"ok": False, "error": "servo unavailable"},
                                  code=503)
            channel, angle = self._parse_servo(self._read_json() or {})
            if channel is None:
                return self._json({"ok": False,
                                   "error": "need channel 1..6, angle 0..180"},
                                  code=400)
            lo, hi = getattr(self.server, "servo_limits",
                             servo_ctl.LIMITS)[channel]
            if not lo <= angle <= hi:
                return self._json({"ok": False,
                                   "error": f"ch{channel} limited to {lo}..{hi}"},
                                  code=400)
            if not getattr(self.server, "servo_enabled", False):
                return self._json({"ok": False,
                                   "error": "servo live control disabled"},
                                  code=403)
            try:
                with self._lock():
                    self.server.servo_bus.set_angle(channel, angle)
                    self.server.servo_state[channel] = angle
            except OSError as e:
                return self._json({"ok": False, "error": f"i2c write failed: {e}"},
                                  code=503)
            self._json(self._servo_payload())
        elif path == "/api/servo/flag":
            if servo_ctl is None:
                return self._json({"ok": False, "error": "servo unavailable"},
                                  code=503)
            data = self._read_json() or {}
            channel, angle = self._parse_servo(data)
            if channel is None:
                return self._json({"ok": False,
                                   "error": "need channel 1..6, angle 0..180"},
                                  code=400)
            note = data.get("note", "")
            if not isinstance(note, str):
                return self._json({"ok": False, "error": "note must be text"},
                                  code=400)
            flag = {"channel": channel, "angle": angle,
                    "note": note[:120], "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
            with self._lock():
                self.server.servo_flags.append(flag)
                _save_flags(self.server.flags_file, self.server.servo_flags)
            self._json(self._servo_payload())
        elif path == "/api/servo/flag/clear":
            if servo_ctl is None:
                return self._json({"ok": False, "error": "servo unavailable"},
                                  code=503)
            data = self._read_json() or {}
            channel = data.get("channel")  # absent = clear all
            with self._lock():
                if channel is None:
                    self.server.servo_flags = []
                else:
                    self.server.servo_flags = [
                        f for f in self.server.servo_flags
                        if f["channel"] != channel]
                _save_flags(self.server.flags_file, self.server.servo_flags)
            self._json(self._servo_payload())
        elif path == "/api/servo/limits":
            if servo_ctl is None:
                return self._json({"ok": False, "error": "servo unavailable"},
                                  code=503)
            data = self._read_json() or {}
            try:
                channel = int(data["channel"])
                lo, hi = int(data["min"]), int(data["max"])
                if isinstance(data["min"], bool) or isinstance(data["max"], bool):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                return self._json({"ok": False,
                                   "error": "need channel, min, max"}, code=400)
            if channel not in servo_ctl.CHANNELS or not 0 <= lo < hi <= 180:
                return self._json({"ok": False,
                                   "error": "need channel 1..6, 0<=min<max<=180"},
                                  code=400)
            with self._lock():
                self.server.servo_limits[channel] = (lo, hi)
                _save_flags(self.server.limits_file,
                            {str(k): list(v) for k, v in
                             self.server.servo_limits.items()})
                self.server.servo_state = servo_ctl.clamp_state(
                    self.server.servo_state, self.server.servo_limits)
            self._json(self._servo_payload())
        else:
            self._json({"ok": False, "error": "not found"}, code=404)

    def log_message(self, *args):  # quieter logs
        pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--demo", action="store_true",
                    help="no robot: label controls as simulated, send nothing")
    ap.add_argument("--enable-servo", action="store_true",
                    help="LIVE servo writes via sliders (Adam present only)")
    ap.add_argument("--servo-device", default="/dev/i2c-1")
    ap.add_argument("--enable-motors", action="store_true",
                    help="LIVE motor writes via thumbstick (Adam present only)")
    ap.add_argument("--motor-cap", type=float, default=HARD_DUTY_CAP,
                    help="server-side duty cap %% (hard ceiling 40)")
    ap.add_argument("--bench-host", default="127.0.0.1")
    ap.add_argument("--bench-port", type=int, default=5098)
    ap.add_argument("--bench-token-file",
                    default="/tmp/mitt/bench_token",
                    help="Pi-local bench token file (never sent to phone)")
    ap.add_argument("--tls-cert", default="",
                    help="PEM cert for HTTPS (phone mic needs a secure "
                         "origin; e.g. a Tailscale cert for the Pi)")
    ap.add_argument("--tls-key", default="",
                    help="PEM key matching --tls-cert")
    args = ap.parse_args(argv)
    if args.demo and (args.enable_motors or args.enable_servo):
        ap.error("--demo can't be combined with --enable-motors or --enable-servo")
    srv = ThreadingHTTPServer((args.bind, args.port), Handler)
    srv.demo = bool(args.demo)
    srv.motor_enabled = bool(args.enable_motors)
    srv.motor_cap = max(0.0, min(HARD_DUTY_CAP, args.motor_cap))
    srv.motor_client = None
    if args.enable_motors:
        # Loud failure is correct here: enabling motors without the
        # listener/token must not silently look like a working GUI.
        srv.motor_client = BenchMotorClient(args.bench_token_file,
                                            host=args.bench_host,
                                            port=args.bench_port)
    srv.servo_enabled = bool(args.enable_servo and servo_ctl is not None)
    srv.servo_bus = None
    srv.servo_state = dict(servo_ctl.DEFAULTS) if servo_ctl else {}
    srv.servo_lock = threading.Lock()
    srv.flags_file = os.path.join(HERE, "servo_flags.json")
    srv.servo_flags = _load_flags(srv.flags_file)
    srv.limits_file = os.path.join(HERE, "servo_limits.json")
    srv.servo_limits = _load_limits(srv.limits_file)
    if servo_ctl is not None:
        srv.servo_state = servo_ctl.clamp_state(srv.servo_state, srv.servo_limits)
    if args.enable_servo:
        if servo_ctl is None:
            raise SystemExit("--enable-servo: servo_ctl unavailable")
        srv.servo_bus = servo_ctl.ServoBus(args.servo_device)  # may raise: loud
    # Speech: background Baseten STT session (worker thread; warmup and
    # transcription never block a handler or any drive path). Needs
    # BASETEN_API_KEY + a deployed streaming-STT model id in the env —
    # without them the session is simply absent and speech endpoints
    # report 503. The session can only produce parser previews.
    srv.speech_session = None
    srv.speech_conn_factory = None
    srv.speech_partial = ""
    srv.speech_last_routed = None
    srv.speech_last_error = ""
    srv.speech_seq = 0
    srv.launch_status = {"state": "idle", "text": "", "target": "",
                         "detail": "", "stop_requested": False}
    if _SpeechSession is not None:
        _cfg = _SpeechConfig.from_env()
        _fn = _make_transcribe_fn(_cfg)
        if _fn is not None:
            srv.speech_session = _SpeechSession(
                _cfg, transcribe_fn=_fn,
                llm_fn=_make_llm_fn(_cfg)).start()
        if _cfg.enabled and _BasetenStreamConnection is not None:
            srv.speech_conn_factory = (
                lambda: _BasetenStreamConnection(_cfg))
    mode = "LIVE SERVO" if srv.servo_enabled else "servo disabled"
    mmode = "LIVE MOTORS" if srv.motor_enabled else "motors disabled"
    smode = ("SPEECH LIVE" if (srv.speech_session
                               or srv.speech_conn_factory)
             else "speech off")
    scheme = "https" if (args.tls_cert and args.tls_key) else "http"
    if scheme == "https":
        import ssl as _ssl
        _ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        _ctx.load_cert_chain(args.tls_cert, args.tls_key)
        srv.socket = _ctx.wrap_socket(srv.socket, server_side=True)
    print(f"serving on {scheme}://{args.bind}:{args.port}/ ({mode}; "
          f"{mmode}; {smode}; tap/text previews)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
