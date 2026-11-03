"""fast_track.py — Speedup 2: Meta lock-on once, MobileSAM box-track.

drive_run's slow loop pays 2 camera grabs + 2 Meta SAM calls per step
(~7.8 s/step live). This module is the cheap inner loop: SAM 3.1 finds
the target once, then each step re-segments ONE local MobileSAM call
prompted with the previous mask box plus a margin (bench: 0.59 s/frame
after a 1.82 s load, aim agreeing with Meta SAM). Meta is re-asked only
when tracking looks lost — empty mask, area jumping, or the box jumping
— never on a steady track.

Losing the target mid-drive is classified by blind_action (the
blind-exit table): under-camera creep, side-exit spin to reacquire, or
a plain stop. No function here moves hardware; the caller owns motors,
servos, and the one-blind-action-per-loss budget.
"""

from tank_vision.pipeline import Box

# Mirrors drive_run.ARRIVE_AREA; kept local so this module stays
# importable without the runner (and its SSH/motor plumbing).
ARRIVE_AREA = 0.25
SPIN_DX = 0.15        # |dx| past this is a spin, not a forward step
RECHECK_AREA_RATIO = 2.0   # one-step area change past this is suspect
RECHECK_JUMP = 0.30        # one-step box-centre move past this is suspect
UNDER_AREA = 0.08     # blind table: target this big and low = under camera
UNDER_DY = -0.25
SIDE_DX = 0.35        # blind table: last seen this far side = side exit


def expand_box(box, margin=0.3):
    """`box` grown by `margin` of its own size on every side, clamped."""
    w, h = box.x1 - box.x0, box.y1 - box.y0
    return Box(max(0.0, box.x0 - margin * w), max(0.0, box.y0 - margin * h),
               min(1.0, box.x1 + margin * w), min(1.0, box.y1 + margin * h))


def track_aim(summary):
    """Aim from a Segmented.summary(): mask-BOX centre, or None if empty.

    Box centre, not mask centroid — the same choice centre_run makes:
    in dim light the pixel mask breathes frame-to-frame while the box
    stays put.
    """
    if not summary or summary.get("empty"):
        return None
    mb = summary["mask_box"]
    cx, cy = (mb["x0"] + mb["x1"]) / 2, (mb["y0"] + mb["y1"]) / 2
    return {"dx_right": round(cx - 0.5, 4), "dy_up": round(0.5 - cy, 4),
            "area_frac": summary["area_frac"]}


def needs_recheck(prev_aim, new_aim):
    """True when the local track is suspect and Meta should re-look."""
    if new_aim is None:
        return True
    if prev_aim is None:
        return False
    prev_area, new_area = prev_aim["area_frac"], new_aim["area_frac"]
    if prev_area > 0 and (new_area > prev_area * RECHECK_AREA_RATIO
                          or new_area < prev_area / RECHECK_AREA_RATIO):
        return True
    jump = ((new_aim["dx_right"] - prev_aim["dx_right"]) ** 2
            + (new_aim["dy_up"] - prev_aim["dy_up"]) ** 2) ** 0.5
    return jump > RECHECK_JUMP


def blind_action(prev_aim, aim):
    """Next action from the last known aim and the fresh aim (or None).

    Found: arrived / spin / forward. Lost after tracking: a target that
    was big and low slid under the camera (creep one short step), one
    last seen at the side edge left sideways (spin toward it to
    reacquire), anything else is a true loss (stop). The caller must
    allow at most ONE creep/spin per loss, then stop.
    """
    if aim is not None:
        if aim["area_frac"] > ARRIVE_AREA:
            return "arrived"
        return "spin" if abs(aim["dx_right"]) > SPIN_DX else "forward"
    if prev_aim is None:
        return "stop"
    if (prev_aim["area_frac"] >= UNDER_AREA
            and prev_aim["dy_up"] <= UNDER_DY):
        return "creep"
    if abs(prev_aim["dx_right"]) >= SIDE_DX:
        return "spin"
    return "stop"


class FastTracker:
    """Box-tracking over an injected VisionPipeline (fakes in tests)."""

    def __init__(self, pipeline, margin=0.3):
        self._pipe = pipeline
        self._margin = margin
        self._box = None
        self._aim = None

    @property
    def locked(self):
        return self._box is not None

    def lock(self, box, area_frac=None):
        """Record the Meta lock-on box; the next track prompts around it."""
        self._box = box
        self._aim = None if area_frac is None else {
            "dx_right": round((box.x0 + box.x1) / 2 - 0.5, 4),
            "dy_up": round(0.5 - (box.y0 + box.y1) / 2, 4),
            "area_frac": area_frac}

    def track(self, image):
        """One local segment. Returns (aim|None, needs_meta_recheck)."""
        if self._box is None:
            raise RuntimeError("track before lock: Meta lock-on first")
        seg = self._pipe.mask_from_box(image, expand_box(self._box,
                                                         self._margin))
        summary = seg.summary()
        aim = track_aim(summary)
        if aim is None:
            return None, True
        recheck = needs_recheck(self._aim, aim)
        mb = summary["mask_box"]
        self._box = Box(mb["x0"], mb["y0"], mb["x1"], mb["y1"])
        self._aim = aim
        return aim, recheck
