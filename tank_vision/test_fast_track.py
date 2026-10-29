"""Fast-track tests — fake pipeline, no torch, no network, no hardware.

Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw  # noqa: E402

from tank_vision.fast_track import (  # noqa: E402
    FastTracker, blind_action, expand_box, needs_recheck, track_aim,
)
from tank_vision.pipeline import Box, Segmented  # noqa: E402

W, H = 200, 100


def seg_for(box, size=(W, H)):
    """A Segmented whose mask fills `box` (normalized), like MobileSAM."""
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle(list(box.to_pixels(*size)), fill=255)
    return Segmented(source="box", mask=m, prompt_box=box)


class FakePipe:
    """SAM stand-in: whatever the prompt, the mask is the object box."""

    OBJ = Box(0.4, 0.4, 0.6, 0.6)

    def __init__(self, found=True):
        self.prompts = []
        self.found = found

    def mask_from_box(self, image, box):
        self.prompts.append(box)
        if not self.found:
            return Segmented(source="box",
                             mask=Image.new("L", image.size, 0),
                             prompt_box=box)
        return seg_for(self.OBJ)


class TestExpandBox(unittest.TestCase):
    def test_expands_each_side_by_margin_of_size(self):
        b = expand_box(Box(0.4, 0.4, 0.6, 0.6), margin=0.5)
        self.assertAlmostEqual(b.x0, 0.3)
        self.assertAlmostEqual(b.x1, 0.7)
        self.assertAlmostEqual(b.y0, 0.3)
        self.assertAlmostEqual(b.y1, 0.7)

    def test_clamps_to_frame(self):
        b = expand_box(Box(0.0, 0.0, 0.2, 0.2), margin=1.0)
        self.assertEqual((b.x0, b.y0), (0.0, 0.0))
        self.assertLessEqual(b.x1, 1.0)
        self.assertLessEqual(b.y1, 1.0)


class TestTrackAim(unittest.TestCase):
    def test_aim_uses_mask_box_centre(self):
        s = seg_for(Box(0.5, 0.0, 1.0, 0.5)).summary()
        aim = track_aim(s)
        self.assertGreater(aim["dx_right"], 0)  # right of centre
        self.assertGreater(aim["dy_up"], 0)     # upper half
        self.assertAlmostEqual(aim["area_frac"], 0.25, delta=0.02)

    def test_empty_summary_has_no_aim(self):
        s = Segmented(source="box", mask=Image.new("L", (W, H), 0)).summary()
        self.assertIsNone(track_aim(s))


class TestRecheck(unittest.TestCase):
    PREV = {"dx_right": 0.0, "dy_up": 0.0, "area_frac": 0.04}

    def test_steady_target_needs_no_recheck(self):
        new = {"dx_right": 0.02, "dy_up": -0.01, "area_frac": 0.05}
        self.assertFalse(needs_recheck(self.PREV, new))

    def test_empty_needs_recheck(self):
        self.assertTrue(needs_recheck(self.PREV, None))

    def test_area_jump_needs_recheck(self):
        grown = dict(self.PREV, area_frac=0.12)   # 3x in one step
        shrunk = dict(self.PREV, area_frac=0.01)  # quartered
        self.assertTrue(needs_recheck(self.PREV, grown))
        self.assertTrue(needs_recheck(self.PREV, shrunk))

    def test_centroid_jump_needs_recheck(self):
        jumped = dict(self.PREV, dx_right=0.4)
        self.assertTrue(needs_recheck(self.PREV, jumped))


class TestBlindAction(unittest.TestCase):
    def test_found_target_actions(self):
        self.assertEqual(
            blind_action(None, {"dx_right": 0.0, "dy_up": 0.0,
                                "area_frac": 0.3}), "arrived")
        self.assertEqual(
            blind_action(None, {"dx_right": 0.3, "dy_up": 0.0,
                                "area_frac": 0.05}), "spin")
        self.assertEqual(
            blind_action(None, {"dx_right": 0.0, "dy_up": 0.0,
                                "area_frac": 0.05}), "forward")

    def test_under_camera_loss_creeps(self):
        # Target was big and sliding under the camera (low in frame).
        prev = {"dx_right": 0.0, "dy_up": -0.35, "area_frac": 0.12}
        self.assertEqual(blind_action(prev, None), "creep")

    def test_side_exit_loss_spins_to_reacquire(self):
        prev = {"dx_right": 0.4, "dy_up": 0.0, "area_frac": 0.03}
        self.assertEqual(blind_action(prev, None), "spin")

    def test_true_loss_stops(self):
        prev = {"dx_right": 0.0, "dy_up": 0.0, "area_frac": 0.03}
        self.assertEqual(blind_action(prev, None), "stop")
        self.assertEqual(blind_action(None, None), "stop")


class TestFastTracker(unittest.TestCase):
    def test_track_prompts_with_expanded_previous_box(self):
        pipe = FakePipe()
        tr = FastTracker(pipe, margin=0.5)
        tr.lock(Box(0.4, 0.4, 0.6, 0.6), area_frac=0.04)
        aim, recheck = tr.track(Image.new("RGB", (W, H)))
        self.assertIsNotNone(aim)
        self.assertFalse(recheck)
        prompted = pipe.prompts[0]
        self.assertLess(prompted.x0, 0.4)   # margin around the lock box
        self.assertGreater(prompted.x1, 0.6)

    def test_empty_mask_reports_recheck_and_no_aim(self):
        pipe = FakePipe(found=False)
        tr = FastTracker(pipe)
        tr.lock(Box(0.4, 0.4, 0.6, 0.6), area_frac=0.04)
        aim, recheck = tr.track(Image.new("RGB", (W, H)))
        self.assertIsNone(aim)
        self.assertTrue(recheck)

    def test_track_without_lock_raises(self):
        tr = FastTracker(FakePipe())
        with self.assertRaises(RuntimeError):
            tr.track(Image.new("RGB", (W, H)))


if __name__ == "__main__":
    unittest.main()
