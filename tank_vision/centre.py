"""centre.py — aim math for drive-to-target (no hardware in here).

Maps an aim() offset to a bounded pan/tilt step. Servo direction signs
are NOT assumed: the runner learns them from a trial nudge (centroid
moved the wrong way -> flip sign), because the angle->direction mapping
was never recorded for this mount.

FOV figures are starting gains only (typical UVC cam); the loop is
closed on the centroid, so a wrong gain costs steps, not correctness.
"""

# Measured 2026-10-30, not the typical-UVC guess (was 60x45):
# a helper's feet 50 cm apart (centres) at 185 cm spanned frame
# x 0.459 -> 0.919, giving H 32.7 deg; V 24.8 from square pixels.
# This lens is narrow ("zoomed in"): at 1.3 m a cat legitimately
# filled 0.27 of frame. Frame width at 185 cm is only ~109 cm.
FOV_H_DEG = 33.0
FOV_V_DEG = 25.0

# Calibrated 2026-10-30 (eyeball against the chassis nose, Adam):
# the ch6 angle where the camera looks along the chassis centreline.
# Pan travel from straight is asymmetric — 22 servo units to the
# 75 limit on the view-left side, 53 units to the 0 limit on the
# view-right side (~30/50 physical degrees). Searches and spins
# should favour view-right; a saturated pan near 75 means the neck
# has almost no left travel left and the body must spin.
PAN_FORWARD = 53


def plan_step(aim, sign_pan=1, sign_tilt=1, max_step=5.0):
    """aim -> (pan_deg, tilt_deg) step, each clamped to +/-max_step.

    aim: {"dx_right", "dy_up"} from VisionPipeline.aim / SAM summaries.
    Positive pan_deg = increase ch6 angle; positive tilt_deg = ch5.
    (Adam confirmed 2026-10-27 the HTML had pan/tilt names swapped.)
    Signs convert 'servo angle up' into 'view moves right/up' once the
    runner has learned them from observation.
    """
    pan = sign_pan * aim["dx_right"] * FOV_H_DEG
    tilt = sign_tilt * aim["dy_up"] * FOV_V_DEG
    clamp = lambda v: max(-max_step, min(max_step, v))  # noqa: E731
    return round(clamp(pan), 2), round(clamp(tilt), 2)


def sign_after_trial(before, after, axis, current_sign, min_delta=0.02):
    """Learn a servo sign from one trial nudge on `axis` ("dx_right").

    If the absolute offset grew, the sign was backwards. Deltas below
    min_delta are centroid noise (dim frames!) — sign stays unchanged
    and the caller's per-step re-check remains the real teacher.
    """
    grew = abs(after[axis]) - abs(before[axis])
    if grew > min_delta:
        return -current_sign
    return current_sign


def centred(aim, tol=0.05):
    return abs(aim["dx_right"]) <= tol and abs(aim["dy_up"]) <= tol


def camera_recenter_angles(aim, pan_angle, tilt_angle,
                           pan_limits, tilt_limits, tol=0.05):
    """One camera recalibration: angles that centre the target, or None.

    Uses the physical mapping proven on the live head (2026-10-29 GUI
    test): view right = ch6 DOWN, view up = ch5 UP. Unlike plan_step's
    trial-learned signs, this is a fixed recalibration after a body
    move: it re-derives where the target sits from a FRESH aim, so a
    stale sign can never ping-pong the loop. Results clamp to the
    servo limits — a clamped pan means the neck is saturated and the
    body must spin; the caller re-recognises to see the new dx.
    """
    if centred(aim, tol):
        return None
    pan = round(pan_angle - aim["dx_right"] * FOV_H_DEG)
    tilt = round(tilt_angle + aim["dy_up"] * FOV_V_DEG)
    pan = max(int(pan_limits[0]), min(int(pan_limits[1]), pan))
    tilt = max(int(tilt_limits[0]), min(int(tilt_limits[1]), tilt))
    if pan == int(pan_angle) and tilt == int(tilt_angle):
        return None
    return pan, tilt


# ---------------------------------------------------------------------------
# Out-of-frame scan: BROAD head moves, fail-closed.
#
# When the target is not in frame at all, mini centreing steps are the
# wrong tool. The scan sweeps the pan servo across its FULL left/right
# range in two legs (current -> nearest end, then back across to the far
# end), stopping every half-FOV so no gap is skipped, at the current
# tilt and then at a lower floor-looking tilt. If it is not found by the
# end of the second leg, the scan FAILS: the head returns to its origin
# pose and the caller must not drive. Servo travel here is the physical
# pan range (ch6 limits, 75 deg on this tank), not an assumed 180.
# ---------------------------------------------------------------------------
SCAN_STEP_DEG = 15.0   # ~half the measured 33 deg FOV (servo units):
                       # overlap, no gaps. Was 30 under the 60 deg
                       # assumption — a full FOV per step, gap-prone.
SCAN_TILT_DROP = 30    # second row looks this far toward the floor


def scan_pan_positions(pan_limits, current, step=SCAN_STEP_DEG):
    """Ordered pan stops covering [lo, hi], broad steps, two legs.

    Starts toward the nearest end first, then sweeps back across the
    full range. Both limits are always included; no stop is more than
    `step` from the previous one.
    """
    lo, hi = int(pan_limits[0]), int(pan_limits[1])
    stops = set()
    a = lo
    while a < hi:
        stops.add(a)
        a += int(step)
    stops.add(hi)
    stops = sorted(stops)
    # Nearest grid stop to current is where leg 1 heads first.
    start = min(range(len(stops)), key=lambda i: abs(stops[i] - current))
    if start <= len(stops) / 2:
        return stops[start::-1] + stops[start + 1:]
    return stops[start:] + list(reversed(stops[:start]))


def scan_tilts(tilt_limits, current, drop=SCAN_TILT_DROP):
    """Tilt rows for the scan: current tilt, then one floor row."""
    lo = int(tilt_limits[0])
    rows = [int(current)]
    floor_row = max(lo, int(current) - drop)
    if floor_row != rows[0]:
        rows.append(floor_row)
    return rows


def run_scan(pan_positions, tilt_rows, move_fn, recognise_fn, origin):
    """Execute a scan. move_fn(pan, tilt)->bool, recognise_fn()->aim|None.

    Recognises once per stop. On success returns the aim immediately
    (head stays where it found the target). On any failure — target not
    found, or a move refused — restores the origin pose and returns
    None. The caller drives only on a non-None aim.
    """
    last = None

    def restore():
        if origin is not None and last != origin:
            move_fn(origin[0], origin[1])

    for tilt in tilt_rows:
        for pan in pan_positions:
            if (pan, tilt) == last:
                continue
            if not move_fn(pan, tilt):
                restore()
                return None
            last = (pan, tilt)
            aim = recognise_fn()
            if aim is not None:
                return aim   # head stays where it found the target
    restore()
    return None


def run_chassis_scan(scan_fn, spin_fn, max_turns=3):
    """Neck scan, then chassis-turn-and-rescan, capped. Aim or None.

    The neck covers only its pan range (~80 deg, asymmetric about
    chassis-forward on this tank); a target beyond it is invisible to
    run_scan no matter how often it sweeps. Here a failed neck scan
    earns ONE bounded chassis turn (spin_fn -> bool) and a fresh
    scan, up to `max_turns` turns. A refused/failed spin aborts the
    whole search (fail closed, no further scans); never-found after
    the cap also returns None. The caller drives only on an aim.
    """
    aim = scan_fn()
    turns = 0
    while aim is None and turns < max_turns:
        if not spin_fn():
            return None
        turns += 1
        aim = scan_fn()
    return aim
