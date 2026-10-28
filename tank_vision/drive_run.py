#!/usr/bin/env python3
"""drive_run.py — 'go get the shoe': bounded drive steps under vision.

Desktop runner. Each step: stop -> grab -> SAM 3.1 -> aim (box centre,
tracked instance) -> ONE bounded motor step -> repeat. Forward steps are
0.5 s at 30% with +17% right trim (measured straight). Aim drift past
0.15 buys a short spin correction instead of a forward step.

Stops when: target fills >25% of frame (arrived), target lost, step cap
hit, or any motor command errors. A final stop is always sent. Motors go
through the Pi bench listener (:5098, token on the Pi only); every move
is also listener-capped at 3 s / 40%.

    .venv/bin/python -m tank_vision.drive_run --prompt shoe --steps 5

Authorisation: Adam present, per-case (AGENTS.md). Never run unattended.
"""

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tank_vision.centre_run import recognise_tracked  # noqa: E402

SSH = ["ssh", "-o", "ConnectTimeout=10", "tank-lan"]
SPIN_DEG_PER_SEC = 110.0  # measured ~101-135 at 30%; mid value, loop corrects
ARRIVE_AREA = 0.25


def drive(cmd):
    out = subprocess.run(SSH + [f"python3 ~/drive_step.py {cmd}"],
                         capture_output=True, text=True, timeout=30)
    print(f"  motor '{cmd}' -> {out.stdout.strip()}")
    if "ok" not in out.stdout:
        raise RuntimeError(f"motor command failed: {cmd} {out.stdout} {out.stderr}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompt", default="shoe")
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--step-secs", type=float, default=0.5)
    ap.add_argument("--duty", type=float, default=30)
    ap.add_argument("--trim", type=float, default=17)
    args = ap.parse_args(argv)

    prev = None
    try:
        for step in range(1, args.steps + 1):
            aim, s = recognise_tracked(args.prompt, prev)
            if aim is None:
                print(f"step {step}: target lost — stopping")
                return 1
            prev = (aim["dx_right"] + 0.5, 0.5 - aim["dy_up"])
            print(f"step {step}: aim={aim}")
            if aim["area_frac"] > ARRIVE_AREA:
                print(f"ARRIVED (area {aim['area_frac']:.2f} > {ARRIVE_AREA})")
                return 0
            if abs(aim["dx_right"]) > 0.15:
                spin = "spinr" if aim["dx_right"] > 0 else "spinl"
                secs = min(0.5, max(0.15, abs(aim["dx_right"]) * 60 / SPIN_DEG_PER_SEC))
                print(f"  correcting: {spin} {secs:.2f}s")
                drive(f"{spin} {secs:.2f} {args.duty}")
            else:
                drive(f"go {args.step_secs} {args.duty} {args.trim}")
            time.sleep(1.2)
        aim, s = recognise_tracked(args.prompt, prev)
        print(f"final aim={aim}")
        return 0
    finally:
        try:
            drive("stop")
        except Exception as e:  # listener may already be down; tank stops anyway
            print(f"final stop note: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
