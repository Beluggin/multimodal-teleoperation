"""launcher.py — desktop side of page-launched drives.

The phone page can only queue a goto (Pi: POST /api/launch). This
poller is the actuator: it watches the Pi queue over ssh, consumes one
pending launch, runs tank_vision.drive_run for exactly that spoken
sentence (bounded steps, proven loop by default), reports progress
back to the Pi so the page can show it, and honours the page's stop
(SIGINT — drive_run's finally sends its stop either way).

Run it only with Adam present and a per-case authorisation:

    set -a; . ./.env; set +a
    .venv/bin/python -m tank_vision.launcher --steps 5

Ctrl+C leaves the queue alone; an in-flight drive gets SIGINT first.
"""

import argparse
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

SSH = ["ssh", "-o", "ConnectTimeout=10", "tank-lan"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tank_tools"))
import xiaor_text_action as _xta  # noqa: E402


def mission_texts(text):
    """'go to the ball then go to the mug' -> one goto text per mission.

    A single goto (or anything the parser does not chain) comes back
    unchanged as one mission; drive_run still gates it with its own
    goto check, so nothing here widens what can move.
    """
    targets = _xta.classify(text or "").targets
    if len(targets) < 2:
        return [text]
    return [f"go to the {t}" for t in targets]


def parse_pi_output(raw):
    """curl '-w \\n%{http_code}' output -> (code, dict).

    Split on the LAST '}' rather than the newline marker: the ssh/shell
    path can eat the backslash and deliver "}n200" instead of "}\\n200".
    Garbage in -> (0, {}), never an exception.
    """
    s = (raw or "").strip()
    idx = s.rfind("}")
    if idx < 0:
        return 0, {}
    tail = s[idx + 1:].strip().lstrip("n")
    try:
        code = int(tail)
        return code, json.loads(s[:idx + 1])
    except ValueError:
        return 0, {}


def pi_json(method, path, payload=None):
    """One Pi phone-server call via ssh+curl. Returns (code, dict).

    The payload travels as base64 into curl --data-binary @-: raw JSON
    through the joined ssh shell string would be word-split on spaces.
    """
    import base64
    cmd = (f"curl -s -m 10 -w '\\n%{{http_code}}' -X {method} "
           f"http://127.0.0.1:8123{path}")
    if payload is not None:
        b64 = base64.b64encode(json.dumps(payload).encode()).decode()
        cmd = (f"echo {b64} | base64 -d | {cmd} "
               f"-H 'Content-Type: application/json' --data-binary @-")
    out = subprocess.run(SSH + [cmd], capture_output=True,
                         text=True, timeout=30)
    return parse_pi_output(out.stdout)


class Launcher:
    """One pending launch -> one bounded drive. Transports injected."""

    def __init__(self, pi, run_drive, steps=5, fast=False,
                 sleep=time.sleep):
        self._pi = pi
        self._run_drive = run_drive
        self._steps = steps
        self._fast = fast
        self._sleep = sleep

    def _stop_requested(self):
        try:
            _, body = self._pi("GET", "/api/launch")
            return bool((body.get("launch") or {}).get("stop_requested"))
        except Exception:
            return False

    def poll_once(self):
        """Handle one pending launch if present. True when one ran."""
        try:
            _, body = self._pi("GET", "/api/launch")
        except Exception:
            return False
        if (body.get("launch") or {}).get("state") != "pending":
            return False
        code, job = self._pi("POST", "/api/launch/consume", {})
        if code != 200:
            return False
        self._pi("POST", "/api/launch/report",
                 {"state": "running", "detail": "drive starting"})
        missions = mission_texts(job["text"])
        for i, text in enumerate(missions, 1):
            if len(missions) > 1:
                print(f"launcher: mission {i}/{len(missions)}: {text!r}",
                      flush=True)
                self._pi("POST", "/api/launch/report",
                         {"state": "running",
                          "detail": f"mission {i}/{len(missions)}: {text}"})
            state, detail = self._run_drive(
                text, self._steps, self._fast, self._stop_requested)
            if state != "done":
                break
        if len(missions) > 1:
            detail = f"mission {i}/{len(missions)} {state}: {detail}"
        self._pi("POST", "/api/launch/report",
                 {"state": state, "detail": detail})
        return True

    def run(self):
        print("launcher: watching the Pi launch queue (Ctrl+C to stop)",
              flush=True)
        try:
            while True:
                if not self.poll_once():
                    self._sleep(1.5)
        except KeyboardInterrupt:
            print("launcher: bye", flush=True)


def run_drive_subprocess(text, steps, fast, should_stop, tandem=False):
    """drive_run as a subprocess; SIGINT on stop (its finally stops)."""
    cmd = [sys.executable, "-m", "tank_vision.drive_run",
           "--text", text, "--steps", str(steps)]
    if fast:
        cmd.append("--fast")
    if tandem:
        cmd.append("--tandem")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    lines = queue.Queue()

    def reader():
        for line in proc.stdout:
            lines.put(line.rstrip())

    threading.Thread(target=reader, daemon=True).start()
    detail = "driving"
    stopped = False
    while True:
        try:
            line = lines.get(timeout=0.5)
            print(f"drive: {line}", flush=True)
            if line.strip():
                detail = line.strip()[:200]
        except queue.Empty:
            pass
        if should_stop() and proc.poll() is None:
            stopped = True
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            break
        if proc.poll() is not None and lines.empty():
            break
    rc = proc.wait()
    if stopped:
        return "stopped", "stop requested from the page"
    return ("done", detail) if rc == 0 else ("failed", detail)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--fast", action="store_true",
                    help="use the fast MobileSAM loop (default: proven)")
    ap.add_argument("--tandem", action="store_true",
                    help="step 2: concurrent neck+chassis moves")
    args = ap.parse_args(argv)
    from functools import partial
    Launcher(pi_json, partial(run_drive_subprocess, tandem=args.tandem),
             steps=args.steps, fast=args.fast).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
