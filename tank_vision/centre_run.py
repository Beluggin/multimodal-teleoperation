#!/usr/bin/env python3
"""centre_run.py — closed-loop camera centreing on a named target.

Desktop runner (SAM key lives here; servo writes go through the Pi's
already-gated phone API). Loop: grab frame -> SAM 3.1 prompt -> aim ->
bounded pan/tilt step (<=5 deg, inside the Pi's enforced limits) ->
repeat. First step is a 3 deg pan trial to LEARN the servo sign from
observed centroid motion; nothing assumes angle->direction mapping.

    MODEL_API_KEY in .env; tank reachable as tank-lan; phone server live.
    .venv/bin/python -m tank_vision.centre_run --prompt "white box"

Stops when centred (tol), target lost (empty SAM result), or step cap
hit. Servos only — no motor path exists in this runner. Authorisation:
run only with Adam present (see AGENTS.md).
"""

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tank_vision.centre import (  # noqa: E402
    camera_recenter_angles, centred, plan_step, run_scan,
    scan_pan_positions, scan_tilts, sign_after_trial,
)
from tank_vision.meta_sam import segment_text  # noqa: E402

SSH = ["ssh", "-o", "ConnectTimeout=10", "tank-lan"]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kw)


def grab(path="/tmp/centre_frame.jpg"):
    for _ in range(2):
        sh(SSH + ["timeout 20 /tmp/qstream 1 > /tmp/centre_frame.jpg"])
        sh(["scp", "-q", "tank-lan:/tmp/centre_frame.jpg", path])
        try:
            with open(path, "rb") as f:
                if f.read(2) == b"\xff\xd8":
                    return path
        except OSError:
            pass
    raise RuntimeError("camera grab failed (device busy or no frames)")


def api(method_path, payload=None):
    if payload is None:
        cmd = f"curl -s http://127.0.0.1:8123{method_path}"
    else:
        data = json.dumps(payload).replace("'", "'\\''")
        cmd = (f"curl -s -X POST http://127.0.0.1:8123{method_path} "
               f"-H 'Content-Type: application/json' -d '{data}'")
    out = sh(SSH + [f"export no_proxy=127.0.0.1; {cmd}"])
    return json.loads(out.stdout)


def recognise(path, prompt, prev_centroid=None):
    """Track one instance: nearest to the previous centroid (else largest).

    Multiple same-label objects are normal ('white box' x2 here); blindly
    picking the largest swaps targets between frames and the aim jumps.
    """
    objects, _ = segment_text(path, prompt)
    cands = []
    for o in objects:
        s = o.summary()
        if s.get("empty"):
            continue
        # Aim from the BOX centre, not the mask centroid: in dim light
        # the pixel mask breathes between frames while SAM's box head
        # stays put. (Mask centroid swung +/-0.15 frame-to-frame live.)
        mb = s["mask_box"]
        cx, cy = (mb["x0"] + mb["x1"]) / 2, (mb["y0"] + mb["y1"]) / 2
        aim = {"dx_right": round(cx - 0.5, 4),
               "dy_up": round(0.5 - cy, 4),
               "area_frac": s["area_frac"]}
        cands.append((aim, s))
    if not cands:
        return None, None
    if prev_centroid is None:
        return max(cands, key=lambda c: c[0]["area_frac"])
    px, py = prev_centroid
    return min(cands, key=lambda c: (c[0]["dx_right"] + 0.5 - px) ** 2
               + (0.5 - c[0]["dy_up"] - py) ** 2)


def recognise_tracked(prompt, prev_centroid=None, samples=2):
    """Median aim over `samples` frames; one target, tracked by proximity."""
    aims = []
    prev = prev_centroid
    for _ in range(samples):
        aim, s = recognise(grab(), prompt, prev)
        if aim is None:
            continue
        aims.append(aim)
        prev = (aim["dx_right"] + 0.5, 0.5 - aim["dy_up"])
    if not aims:
        return None, None
    aims.sort(key=lambda a: a["dx_right"])
    mid = aims[len(aims) // 2]
    aims.sort(key=lambda a: a["dy_up"])
    mid = dict(mid, dy_up=aims[len(aims) // 2]["dy_up"])
    return mid, s


def scan_for_target(prompt):
    """Wide out-of-frame scan (servos only, no motors).

    Sweeps the full pan range in two broad legs at the current tilt,
    then at a floor tilt, recognising at every stop. Found: returns the
    aim with the head left on the target. Not found: head restored to
    its origin pose, returns None — the caller must not drive.
    """
    state = api("/api/servo")
    if not state.get("enabled"):
        print("scan: servo not enabled — aborting")
        return None
    origin = (state["state"]["5"], state["state"]["6"])
    pans = scan_pan_positions(
        (state["limits"]["6"][0], state["limits"]["6"][1]), origin[1])
    tilts = scan_tilts(
        (state["limits"]["5"][0], state["limits"]["5"][1]), origin[0])
    print(f"scan: pans {pans} tilts {tilts} from origin tilt={origin[0]} "
          f"pan={origin[1]}")

    def move(pan, tilt):
        r = api("/api/servo", {"channel": 6, "angle": int(pan)})
        if not r.get("ok"):
            print(f"scan: pan refused {r}")
            return False
        r = api("/api/servo", {"channel": 5, "angle": int(tilt)})
        if not r.get("ok"):
            print(f"scan: tilt refused {r}")
            return False
        time.sleep(0.8)
        return True

    def look():
        aim, _ = recognise_tracked(prompt)
        print(f"scan: look -> {'aim=' + str(aim) if aim else 'nothing'}")
        return aim

    # run_scan works in (pan, tilt) pairs; origin above is (tilt, pan).
    aim = run_scan(pans, tilts, move, look, origin=(origin[1], origin[0]))
    if aim is None:
        print("scan: not found in range — head restored, FAIL (no drive)")
    else:
        print(f"scan: FOUND aim={aim}")
    return aim


def recenter_servo(aim):
    """Move pan/tilt once to centre `aim`; True when the head is settled.

    Servo half of recalibrate_camera, split out so the fast loop can
    pair the same physical recentre with a local MobileSAM re-look
    instead of a Meta one. False = no move needed or a move refused;
    the caller keeps its current aim either way.
    """
    if aim is None:
        return False
    state = api("/api/servo")
    if not state.get("enabled"):
        return False
    angles = camera_recenter_angles(
        aim, state["state"]["6"], state["state"]["5"],
        (state["limits"]["6"][0], state["limits"]["6"][1]),
        (state["limits"]["5"][0], state["limits"]["5"][1]))
    if angles is None:
        return False
    pan, tilt = angles
    print(f"recalibrate: pan->{pan} tilt->{tilt} (aim was {aim})")
    for ch, ang in ((6, pan), (5, tilt)):
        if ang != state["state"][str(ch)]:
            r = api("/api/servo", {"channel": ch, "angle": int(ang)})
            if not r.get("ok"):
                print(f"recalibrate: ch{ch} refused {r} — keeping old aim")
                return False
    time.sleep(0.8)
    return True


def move_camera(pan, tilt):
    """Move pan/tilt to absolute angles; True when both accepted.

    Used by the tandem move (Step 2), which drives the neck to a
    planned pose concurrently with a chassis move instead of
    recentring-then-relooking. No recognition happens here.
    """
    state = api("/api/servo")
    if not state.get("enabled"):
        return False
    for ch, ang in ((6, int(pan)), (5, int(tilt))):
        if ang != state["state"][str(ch)]:
            r = api("/api/servo", {"channel": ch, "angle": ang})
            if not r.get("ok"):
                print(f"move_camera: ch{ch} refused {r}")
                return False
    return True


def recalibrate_camera(prompt, aim):
    """Recentre the camera on the target after a body move, then re-look.

    One bounded pan/tilt recalibration from the FRESH aim (never a
    remembered sign), followed by a new recognition. Returns the new
    aim, the old aim when no recalibration was needed/possible, or
    None when the re-look lost the target.
    """
    if aim is None:
        return None
    if not recenter_servo(aim):
        return aim
    centroid = (aim["dx_right"] + 0.5, 0.5 - aim["dy_up"])
    new_aim, _ = recognise_tracked(prompt, centroid)
    print(f"recalibrate: re-look aim={new_aim}")
    return new_aim


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prompt", default="white box")
    ap.add_argument("--tol", type=float, default=0.05)
    ap.add_argument("--max-steps", type=int, default=6)
    ap.add_argument("--search", action="store_true", help="tilt-sweep to find target first")
    ap.add_argument("--scan", action="store_true",
                    help="wide pan scan over the full L/R range (two tilts) "
                         "to find an out-of-frame target; fails closed")
    args = ap.parse_args(argv)

    state = api("/api/servo")
    if not state.get("enabled"):
        print("servo not enabled on Pi — aborting")
        return 1
    print(f"start pose ch5={state['state']['5']} ch6={state['state']['6']}")

    aim, s = recognise_tracked(args.prompt)
    if aim is None and args.scan:
        aim = scan_for_target(args.prompt)
    if aim is None and args.search:
        # Bounded tilt search: step ch5 (tilt) down through its range,
        # recognising after each step, until the target enters frame.
        limits = api("/api/servo")["limits"]["5"]
        angle = api("/api/servo")["state"]["5"]
        print(f"searching: tilt sweep from {angle} down to {limits[0]}")
        while aim is None and angle > limits[0]:
            angle = max(limits[0], angle - 6)
            r = api("/api/servo", {"channel": 5, "angle": angle})
            if not r.get("ok"):
                print(f"search tilt refused: {r}")
                return 1
            time.sleep(1.0)
            aim, s = recognise_tracked(args.prompt)
            print(f"  tilt {angle}: {'found aim=' + str(aim) if aim else 'no'}")
    if aim is None:
        print(f"target '{args.prompt}' not found — no motion")
        return 1
    print(f"step 0: aim={aim}")
    if centred(aim, args.tol):
        print("already centred")
        return 0

    # Trial: pan only, 5 deg, learn the sign from what the camera sees.
    # Skipped at the travel limit (per-step supervision still learns).
    before = dict(aim)
    _st = api("/api/servo")
    cur, _lim = _st["state"], _st["limits"]["6"]
    trial_delta = 5 if cur["6"] + 5 <= _lim[1] else 0
    if trial_delta:
        api("/api/servo", {"channel": 6, "angle": cur["6"] + trial_delta})
        time.sleep(1.0)
    centroid = (before['dx_right'] + 0.5, 0.5 - before['dy_up'])
    aim, s = recognise_tracked(args.prompt, centroid)
    if aim is None:
        # Trial ejected the target (it sat near the frame edge): undo
        # the trial move — that IS the sign lesson — and re-acquire.
        cur = api("/api/servo")["state"]
        api("/api/servo", {"channel": 6, "angle": cur["6"] - trial_delta})
        time.sleep(1.0)
        aim, s = recognise_tracked(args.prompt, centroid)
        if aim is None:
            print("target lost during trial, undo did not recover — stopping")
            return 1
        print(f"trial ejected target; undone, sign_pan=-1, aim={aim}")
        sign_pan = -1
        pan_deg_trial = True
    else:
        sign_pan = sign_after_trial(before, aim, "dx_right", 1)
        pan_deg_trial = False
    print(f"trial: aim={aim} -> sign_pan={sign_pan}")
    sign_tilt = 1  # re-evaluated after every step, like pan

    for step in range(1, args.max_steps + 1):
        if centred(aim, args.tol):
            print(f"CENTRED at step {step}: aim={aim}")
            return 0
        pan_deg, tilt_deg = plan_step(aim, sign_pan, sign_tilt, max_step=3.0)
        cur = api("/api/servo")["state"]
        if pan_deg:
            r = api("/api/servo", {"channel": 6,
                                   "angle": round(cur["6"] + pan_deg)})
            if not r.get("ok") and "limited" in str(r.get("error", "")):
                # Limit refusal with sign unproven: the other direction
                # is both the retry and the sign lesson.
                sign_pan = -sign_pan
                pan_deg = -pan_deg
                print(f"pan limit hit; flipping sign -> {sign_pan}, retry {pan_deg:+}")
                cur = api("/api/servo")["state"]
                r = api("/api/servo", {"channel": 6,
                                       "angle": round(cur["6"] + pan_deg)})
            if not r.get("ok"):
                print(f"pan refused: {r} — stopping")
                return 1
        if tilt_deg:
            r = api("/api/servo", {"channel": 5,
                                   "angle": round(cur["5"] + tilt_deg)})
            if not r.get("ok") and "limited" in str(r.get("error", "")):
                sign_tilt = -sign_tilt
                tilt_deg = -tilt_deg
                print(f"tilt limit hit; flipping sign -> {sign_tilt}, retry {tilt_deg:+}")
                cur = api("/api/servo")["state"]
                r = api("/api/servo", {"channel": 5,
                                       "angle": round(cur["5"] + tilt_deg)})
            if not r.get("ok"):
                print(f"tilt refused: {r} — stopping")
                return 1
        time.sleep(1.0)
        prev, aim = aim, None
        centroid = (prev['dx_right'] + 0.5, 0.5 - prev['dy_up'])
        aim, s = recognise_tracked(args.prompt, centroid)
        if aim is None:
            print(f"target lost at step {step} — stopping")
            return 1
        # Continuous sign supervision: a step that made an axis worse
        # by more than noise flips that axis for the next step.
        if pan_deg:
            new_sign = sign_after_trial(prev, aim, "dx_right", sign_pan)
            if new_sign != sign_pan:
                print(f"pan sign flip -> {new_sign}")
            sign_pan = new_sign
        if tilt_deg:
            new_sign = sign_after_trial(prev, aim, "dy_up", sign_tilt)
            if new_sign != sign_tilt:
                print(f"tilt sign flip -> {new_sign}")
            sign_tilt = new_sign
        print(f"step {step}: moved pan{pan_deg:+} tilt{tilt_deg:+} -> aim={aim}")
    print(f"step cap reached, final aim={aim}")
    return 0 if centred(aim, args.tol) else 2


if __name__ == "__main__":
    raise SystemExit(main())
