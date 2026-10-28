"""Plumbing tests with fake backends — no torch, no weights, no network.

These prove the box->prompt handoff, focus selection/fallback, aim math and
refusals. They do NOT prove model quality; that needs the real run in
README.md. Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw  # noqa: E402

from tank_vision.pipeline import Box, Detection, VisionPipeline  # noqa: E402

W, H = 200, 100


def blank():
    return Image.new("RGB", (W, H), (10, 10, 10))


class FakeDetector:
    def __init__(self, dets):
        self.dets = dets
        self.calls = []

    def detect(self, img, confidence):
        self.calls.append(confidence)
        return list(self.dets)


class FakeSegmenter:
    """Mask = interior of the prompt box (or a disc at the point)."""

    def __init__(self):
        self.prompts = []

    def segment(self, img, point=None, box=None):
        self.prompts.append((point, box))
        m = Image.new("L", img.size, 0)
        d = ImageDraw.Draw(m)
        if box is not None:
            d.rectangle(list(box), fill=255)
        else:
            x, y = point
            d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=255)
        return m


def pipe_with(dets):
    det, seg = FakeDetector(dets), FakeSegmenter()
    return VisionPipeline(detector=det, segmenter=seg), det, seg


class TestHandoff(unittest.TestCase):
    def test_yolo_box_reaches_sam_unchanged(self):
        det_box = Box(0.1, 0.2, 0.5, 0.6)
        pipe, _, seg = pipe_with([Detection("cat", 0.9, det_box)])
        objs = pipe.detect_and_segment(blank())
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].label, "cat")
        self.assertEqual(seg.prompts[0][1], det_box.to_pixels(W, H))

    def test_no_detections_stays_empty(self):
        pipe, _, seg = pipe_with([])
        self.assertEqual(pipe.detect_and_segment(blank()), [])
        self.assertEqual(seg.prompts, [])  # SAM never called on a guess

    def test_summary_geometry(self):
        pipe, _, _ = pipe_with([Detection("cat", 0.9, Box(0.0, 0.0, 0.5, 1.0))])
        s = pipe.detect_and_segment(blank())[0].summary()
        self.assertAlmostEqual(s["area_frac"], 0.5, delta=0.01)
        self.assertAlmostEqual(s["centroid"]["x"], 0.25, delta=0.01)
        self.assertAlmostEqual(s["centroid"]["y"], 0.5, delta=0.01)


class TestFocus(unittest.TestCase):
    def test_focus_picks_detection_inside_box(self):
        inside = Detection("dog", 0.7, Box(0.55, 0.55, 0.75, 0.75))
        outside = Detection("cat", 0.99, Box(0.0, 0.0, 0.2, 0.2))
        pipe, _, seg = pipe_with([inside, outside])
        got = pipe.focus(blank(), Box(0.5, 0.5, 1.0, 1.0))
        self.assertEqual(got.source, "focus-detect")
        self.assertEqual(got.label, "dog")  # higher-conf outsider ignored
        self.assertEqual(seg.prompts[0][1], inside.box.to_pixels(W, H))

    def test_focus_falls_back_to_box_prompt(self):
        pipe, _, seg = pipe_with([Detection("cat", 0.9, Box(0.0, 0.0, 0.2, 0.2))])
        user_box = Box(0.5, 0.5, 1.0, 1.0)
        got = pipe.focus(blank(), user_box)
        self.assertEqual(got.source, "focus-box")
        self.assertEqual(seg.prompts[0][1], user_box.to_pixels(W, H))

    def test_aim_signs_and_empty(self):
        pipe, _, _ = pipe_with([Detection("x", 0.9, Box(0.5, 0.0, 1.0, 0.5))])
        aim = VisionPipeline.aim(pipe.detect_and_segment(blank())[0])
        self.assertGreater(aim["dx_right"], 0)  # target right of centre
        self.assertGreater(aim["dy_up"], 0)     # and above centre
        empty_pipe, _, _ = pipe_with([])
        seg = empty_pipe.mask_from_box(blank(), Box(0.1, 0.1, 0.2, 0.2))
        seg.mask = Image.new("L", (W, H), 0)
        self.assertIsNone(VisionPipeline.aim(seg))  # no target, never 'straight'


class TestRefusals(unittest.TestCase):
    def test_bad_coordinates_raise(self):
        pipe, _, _ = pipe_with([])
        for bad in [(1.2, 0.5), (-0.1, 0.5), (0.5, 2.0)]:
            with self.assertRaises(ValueError):
                pipe.mask_from_point(blank(), *bad)
            with self.assertRaises(ValueError):
                pipe.focus_point(blank(), *bad)
        with self.assertRaises(ValueError):
            Box(0.5, 0.5, 0.4, 0.9)  # inverted
        with self.assertRaises(ValueError):
            pipe.mask_from_box(blank(), Box(0.0, 0.0, 1.5, 1.0))

    def test_missing_backend_is_a_clear_error(self):
        real = VisionPipeline()  # no fakes, (usually) no ultralytics here
        try:
            import ultralytics  # noqa: F401
            self.skipTest("ultralytics installed; error path not exercisable")
        except ImportError:
            pass
        with self.assertRaises(RuntimeError):
            real.detect(blank())


if __name__ == "__main__":
    unittest.main()
