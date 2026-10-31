#!/usr/bin/env python3
"""drive_run.py — 'go get the shoe': bounded drive steps under vision.

Desktop runner. Each step: stop -> grab -> SAM 3.1 -> aim (box centre,
tracked instance) -> ONE bounded motor step -> repeat. Forward steps
are adaptive at 30% with +17% right trim (measured straight): step
length scales with 1/sqrt(target area) — 1.5 s when far, shrinking to
0.5 s near arrival — unless --step-secs fixes it. Aim drift past
0.15 buys a short spin correction instead of a forward step.

Stops when: target fills >25% of frame (arrived), target lost, step cap
hit, or any motor command errors. A final stop is always sent. Motors go
through the Pi bench listener (:5098, token on the Pi only); every move
is also listener-capped at 3 s / 40%.

    .venv/bin/python -m tank_vision.drive_run --prompt shoe --steps 5
    .venv/bin/python -m tank_vision.drive_run --text "go get the shoe"

Authorisation: Adam present, per-case (AGENTS.md). Never run unattended.
"""

import argparse
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tank_tools"))
from tank_vision.centre_run import (  # noqa: E402
    api, grab, move_camera, recognise_tracked, recalibrate_camera,
    recenter_servo, scan_for_target,
)
from tank_vision.centre import run_chassis_scan, tandem_plan  # noqa: E402
from tank_vision.fast_track import FastTracker, blind_action  # noqa: E402
from tank_vision.pipeline import Box, VisionPipeline  # noqa: E402
import xiaor_text_action as _xta  # noqa: E402


def resolve_prompt(text):
    """'go get the shoe' -> ('shoe', ''). Anything the fixed-phrase parser
    does not route as a clean goto -> (None, why). Never moves anything."""
    a = _xta.classify(text or "")
    if a.kind == "goto" and a.target:
        return a.target, ""
    return None, f"{a.kind}: {a.reason}"

SSH = ["ssh", "-o", "ConnectTimeout=10", "tank-lan"]
SPIN_DEG_PER_SEC = 110.0  # measured ~101-135 at 30%; mid value, loop corrects
ARRIVE_AREA = 0.25
STEP_MIN_SECS = 0.5   # near the target: shortest, safest step
STEP_MAX_SECS = 2.5   # far away: longest blind step (listener caps 3 s);
                      # raised from 1.5 on Adam's call — ~4 in per old
                      # step at cat distance was far too timid


SPIN_MIN_SECS = 0.07
SPIN_MAX_SECS = 0.5


def spin_secs_for_dx(dx_right, last_dx=None, last_secs=None):
    """Body-spin duration for an aim offset, damped on overshoot.

    Base scale is the measured spin rate. When the previous spin
    flipped the offset's sign, it overshot: the next correction is at
    most half the previous duration, so the -0.37 -> +0.26 -> -0.26
    ping-pong (2026-10-29 live loop) decays instead of repeating.
    """
    try:
        dx = abs(float(dx_right))
    except (TypeError, ValueError):
        return SPIN_MIN_SECS
    secs = min(SPIN_MAX_SECS,
               max(SPIN_MIN_SECS, dx * 60.0 / SPIN_DEG_PER_SEC))
    if (last_dx is not None and last_secs is not None
            and dx_right * last_dx < 0):
        secs = min(secs, max(SPIN_MIN_SECS, last_secs * 0.5))
    return round(secs, 3)


def step_secs_for_area(area_frac):
    """Forward step length from target size. Apparent linear size scales
    with sqrt(area), so step ~ 0.40/sqrt(area): 0.6 s at arrival area,
    1.6 s at quarter area, capped both ends (2.5 s far, 0.5 s near).
    Above 0.08 the step shrinks harder (x0.75): near the target even
    the bigger curve must stay cautious blind. Garbage in -> shortest."""
    try:
        area = float(area_frac)
    except (TypeError, ValueError):
        return STEP_MIN_SECS
    if area <= 0:
        return STEP_MIN_SECS
    secs = 0.40 / area ** 0.5
    if area > 0.08:
        secs *= 0.75
    return min(STEP_MAX_SECS, max(STEP_MIN_SECS, secs))


SCAN_TURN_DEG = 60.0   # chassis turn between neck scans (step 1):
                       # ~80 deg neck sweep minus ~20 deg overlap,
                       # so legs cannot gap but each buys real ground
                       # (Adam, 2026-10-30: 40 deg was too narrow)


def chassis_scan(prompt, scan_fn=None, drive_fn=None, max_turns=3,
                 spin="spinr", duty=30):
    """Step 1: neck scan; on failure spin the chassis and rescan.

    Defaults favour `spinr`: Adam's pan is asymmetric (~50 deg one
    side of chassis-forward, ~30 the other), and the long side is
    the productive search direction. Each turn is one bounded spin
    (~60 deg at the measured spin rate); a failed spin aborts the
    search. Returns an aim or None (fail closed, no drive).
    """
    scan_fn = scan_fn or scan_for_target
    drive_fn = drive_fn or drive
    secs = round(SCAN_TURN_DEG / SPIN_DEG_PER_SEC, 2)

    def spin_once():
        try:
            print(f"chassis scan: {spin} {secs:.2f}s turn, rescan")
            drive_fn(f"{spin} {secs:.2f} {duty}")
            return True
        except Exception as e:
            print(f"chassis scan: spin failed ({e}) — aborting")
            return False

    return run_chassis_scan(lambda: scan_fn(prompt), spin_once,
                            max_turns=max_turns)


def run_tandem(plan, motor_cmd, servo_fn=None, drive_fn=None):
    """Step 2: neck + chassis from ONE picture, concurrently.

    The servo move and the motor command run in parallel threads —
    the chassis turn eats the servo travel time instead of waiting
    for a recalibrate + confirm-look cycle. A motor failure raises
    (the caller's finally stops the tank); a servo failure is only
    noted, because the next fresh look recalibrates anyway.
    """
    servo_fn = servo_fn or move_camera
    drive_fn = drive_fn or drive
    errors = []

    def do_servo():
        try:
            if not servo_fn(plan["pan"], plan["tilt"]):
                print("tandem: servo move refused — continuing")
        except Exception as e:
            print(f"tandem: servo error ({e}) — continuing")

    def do_motor():
        try:
            drive_fn(motor_cmd)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do_servo),
               threading.Thread(target=do_motor)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]


def tandem_motor_cmd(plan, aim, args):
    """Motor half of a tandem plan (spin the full bearing, or go)."""
    if plan["action"] == "spin":
        spin = "spinr" if plan["bearing_deg"] > 0 else "spinl"
        secs = round(min(0.8, max(SPIN_MIN_SECS,
                                  abs(plan["bearing_deg"])
                                  / SPIN_DEG_PER_SEC)), 2)
        return f"{spin} {secs:.2f} {args.duty}", secs
    secs = (args.step_secs if args.step_secs is not None
            else step_secs_for_area(aim["area_frac"]))
    return f"go {secs:g} {args.duty} {args.trim}", secs


def fast_look(tracker, prompt, prev_centroid=None):
    """One fast-loop look: MobileSAM track; Meta SAM only on suspicion.

    A steady track recentres the neck on the fresh aim (recenter_servo)
    and re-tracks locally. An empty or suspect track falls back to a
    Meta recognition, which also re-locks the tracker. Returns an aim
    dict or None. Servos may move (the recentre); motors never do here.
    """
    from PIL import Image
    aim, recheck = tracker.track(Image.open(grab()).convert("RGB"))
    if aim is not None and not recheck and recenter_servo(aim):
        aim, recheck = tracker.track(Image.open(grab()).convert("RGB"))
    if aim is None or recheck:
        meta_aim, s = recognise_tracked(prompt, prev_centroid)
        if meta_aim is not None and s and not s.get("empty"):
            mb = s["mask_box"]
            tracker.lock(Box(mb["x0"], mb["y0"], mb["x1"], mb["y1"]),
                         meta_aim["area_frac"])
        return meta_aim
    return aim


def drive(cmd):
    out = subprocess.run(SSH + [f"python3 ~/drive_step.py {cmd}"],
                         capture_output=True, text=True, timeout=30)
    print(f"  motor '{cmd}' -> {out.stdout.strip()}")
    if "ok" not in out.stdout:
        raise RuntimeError(f"motor command failed: {cmd} {out.stdout} {out.stderr}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompt", default="shoe")
    ap.add_argument("--text", default="",
                    help='instruction sentence, e.g. "go get the shoe"; '
                         'parsed by the fixed-phrase parser, goto only')
    ap.add_argument("--steps", type=int, default=5)
    ap.add_argument("--step-secs", type=float, default=None,
                    help="fixed forward step seconds "
                         "(default: adaptive by target area)")
    ap.add_argument("--duty", type=float, default=30)
    ap.add_argument("--trim", type=float, default=17)
    ap.add_argument("--fast", action="store_true",
                    help="Speedup 2: Meta lock-on once, MobileSAM "
                         "box-track per step, Meta recheck on loss; "
                         "blind-exit table on mid-drive loss")
    ap.add_argument("--scan-turns", type=int, default=3,
                    help="step 1: chassis turns between neck scans "
                         "when the target starts out of frame")
    ap.add_argument("--scan-spin", choices=("spinr", "spinl"),
                    default="spinr",
                    help="chassis-scan turn direction (default spinr: "
                         "the camera's long side)")
    ap.add_argument("--tandem", action="store_true",
                    help="step 2: neck + chassis concurrently from one "
                         "picture (no recalibrate confirm-look); "
                         "ignored with --fast")
    args = ap.parse_args(argv)
    if args.text:
        target, why = resolve_prompt(args.text)
        if target is None:
            print(f"not a goto instruction — no motion ({why})")
            return 2
        print(f"text {args.text!r} -> goto target {target!r}")
        args.prompt = target

    prev = None
    scanned = False
    last_dx, last_spin_secs = None, None
    tracker = FastTracker(VisionPipeline()) if args.fast else None
    prev_aim, blind_used = None, False
    try:
        for step in range(1, args.steps + 1):
            if tracker is not None and tracker.locked:
                aim = fast_look(tracker, args.prompt, prev)
            else:
                aim, s = recognise_tracked(args.prompt, prev)
                if aim is not None and tracker is not None:
                    # Meta lock-on: hand the box to the local tracker.
                    if s and not s.get("empty"):
                        mb = s["mask_box"]
                        tracker.lock(Box(mb["x0"], mb["y0"],
                                         mb["x1"], mb["y1"]),
                                     aim["area_frac"])
                elif aim is not None and not args.tandem:
                    # Recalibrate the camera on the target BEFORE any
                    # motor decision — and, on later steps, after the
                    # last move. Fresh aim only; no remembered sign.
                    # Tandem mode skips this: the same picture plans
                    # both the neck and chassis move below.
                    aim = recalibrate_camera(args.prompt, aim)
            if aim is None and prev is None and not scanned:
                # Never seen it this run: wide head scan before giving
                # up. (A loss AFTER tracking is the under-camera case —
                # that stays a plain stop, handled by the blind table.)
                scanned = True
                print(f"step {step}: not in frame — wide scan "
                      f"(+ up to {args.scan_turns} chassis turns)")
                aim = chassis_scan(args.prompt,
                                   max_turns=args.scan_turns,
                                   spin=args.scan_spin, duty=args.duty)
            if (aim is None and tracker is not None
                    and prev_aim is not None and not blind_used):
                # Blind-exit table (fast loop): ONE creep or reacquire
                # spin per loss, then the next loss stops the run.
                action = blind_action(prev_aim, None)
                if action == "creep":
                    print(f"step {step}: lost under camera — "
                          f"one {STEP_MIN_SECS:g}s creep")
                    drive(f"go {STEP_MIN_SECS:g} {args.duty} {args.trim}")
                    blind_used = True
                    time.sleep(1.2)
                    continue
                if action == "spin":
                    spin = ("spinr" if prev_aim["dx_right"] > 0
                            else "spinl")
                    secs = spin_secs_for_dx(prev_aim["dx_right"],
                                            last_dx, last_spin_secs)
                    print(f"step {step}: side exit — {spin} {secs:.2f}s "
                          f"to reacquire")
                    drive(f"{spin} {secs:.2f} {args.duty}")
                    last_dx = prev_aim["dx_right"]
                    last_spin_secs = secs
                    blind_used = True
                    time.sleep(1.2)
                    continue
            if aim is None:
                print(f"step {step}: target lost — stopping")
                return 1
            prev = (aim["dx_right"] + 0.5, 0.5 - aim["dy_up"])
            prev_aim, blind_used = aim, False
            print(f"step {step}: aim={aim}")
            if aim["area_frac"] > ARRIVE_AREA:
                print(f"ARRIVED (area {aim['area_frac']:.2f} > {ARRIVE_AREA})")
                return 0
            if args.tandem and tracker is None:
                # Step 2: plan neck + chassis from THIS picture and
                # move both at once. No confirm-look in between.
                st = api("/api/servo")
                plan = tandem_plan(
                    aim, st["state"]["6"], st["state"]["5"],
                    (st["limits"]["6"][0], st["limits"]["6"][1]),
                    (st["limits"]["5"][0], st["limits"]["5"][1])) \
                    if st.get("enabled") else None
                if plan is None:
                    print("  tandem: servo unavailable — stopping")
                    return 1
                cmd, secs = tandem_motor_cmd(plan, aim, args)
                print(f"  tandem: bearing {plan['bearing_deg']:+.1f} deg "
                      f"-> neck pan {plan['pan']} + motor '{cmd}'")
                run_tandem(plan, cmd)
                if plan["action"] == "spin":
                    last_dx, last_spin_secs = aim["dx_right"], secs
            elif abs(aim["dx_right"]) > 0.15:
                spin = "spinr" if aim["dx_right"] > 0 else "spinl"
                secs = spin_secs_for_dx(aim["dx_right"], last_dx,
                                        last_spin_secs)
                print(f"  correcting: {spin} {secs:.2f}s")
                drive(f"{spin} {secs:.2f} {args.duty}")
                last_dx, last_spin_secs = aim["dx_right"], secs
            else:
                secs = (args.step_secs if args.step_secs is not None
                        else step_secs_for_area(aim["area_frac"]))
                print(f"  forward step {secs:.2f}s "
                      f"(area {aim['area_frac']:.3f})")
                drive(f"go {secs:g} {args.duty} {args.trim}")
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
