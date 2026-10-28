"""centre.py — aim math for drive-to-target (no hardware in here).

Maps an aim() offset to a bounded pan/tilt step. Servo direction signs
are NOT assumed: the runner learns them from a trial nudge (centroid
moved the wrong way -> flip sign), because the angle->direction mapping
was never recorded for this mount.

FOV figures are starting gains only (typical UVC cam); the loop is
closed on the centroid, so a wrong gain costs steps, not correctness.
"""

FOV_H_DEG = 60.0
FOV_V_DEG = 45.0


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
