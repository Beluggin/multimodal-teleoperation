#!/usr/bin/env python3
"""tank_phone/server.py — Pi-hosted phone GUI for the tank.

Stdlib only. Serves index.html plus a JSON API. Tap/text endpoints are
dry-run previews. Servo sliders are LIVE only with --enable-servo, which
is never the default: that flag is the authorization gate, set only with
Adam present at the tank. Servo writes speak the proven 0x17 frame via
servo_ctl.py (channels 1-6, 0-180 deg). No motor path exists here at all.

Desktop smoke (no hardware touched):
    python3 tank_phone/server.py --port 8123
    curl localhost:8123/api/status

Pi deploy:
    scp tank_phone/server.py tank_phone/index.html tank_phone/servo_ctl.py \\
        tank_tools/xiaor_text_action.py tank-lan:~/tank_phone/
    ssh tank-lan 'cd ~/tank_phone && TANK_PHONE_MJPEG_CMD=/tmp/qstream \\
        python3 server.py --bind 0.0.0.0 --enable-servo'
Phone on the same WiFi: http://tank.local:8123/
(Tailscale address works too when it is up.)
"""

import argparse
import json
import os
import select
import shlex
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(os.path.dirname(HERE), "tank_tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import xiaor_text_action as tx
except ImportError:  # desktop without tank_tools on path: text endpoint degrades
    tx = None

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
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status":
            self._json({"ok": True,
                        "servo_enabled": bool(getattr(self.server,
                                                      "servo_enabled", False)),
                        "note": "tap/text are previews; servo sliders live "
                                "only when servo_enabled"})
        elif path == "/api/servo":
            if servo_ctl is None:
                return self._json({"ok": False, "error": "servo unavailable"},
                                  code=503)
            self._json(self._servo_payload())
        elif path == "/api/frame":
            self._serve_mjpeg()
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
                        "kind": a.kind, "label": a.label,
                        "duration": a.duration, "reason": a.reason,
                        "commands": a.commands,
                        "note": "preview only: not sent (dry run)"})
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
    ap.add_argument("--enable-servo", action="store_true",
                    help="LIVE servo writes via sliders (Adam present only)")
    ap.add_argument("--servo-device", default="/dev/i2c-1")
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer((args.bind, args.port), Handler)
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
    mode = "LIVE SERVO" if srv.servo_enabled else "servo disabled"
    print(f"serving on http://{args.bind}:{args.port}/ ({mode}; tap/text previews)",
          flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
