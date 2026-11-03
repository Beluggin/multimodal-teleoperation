"""Meta SAM client tests — offline, against captured wire format.

The box/mask tag grammar here is copied from a REAL sam-3.1 response
(mc.jpg, 'silver capacitor', 2026-10-27). Mask pixel decode needs
meta-sam-parser; without it parse_response must degrade to labelled
box-fill, never crash and never claim pixel masks.

Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))

from tank_vision.meta_sam import parse_response, parse_sam_text  # noqa: E402

TEXT = ("<0f>0<|box;x1=265;y1=353;x2=372;y2=473;w=964;h=1280|>"
        "<|mask;x=0;y=0;data=121,108,~!!!fake|>"
        "1<|box;x1=645;y1=800;x2=785;y2=927;w=964;h=1280|>"
        "<|mask;x=0;y=0;data=128,141,~!!!fake|>")


def response(text=TEXT):
    return {"output": [{"content": [{"type": "output_text", "text": text}]}]}


class TestWireFormat(unittest.TestCase):
    def test_boxes_normalize(self):
        recs = parse_sam_text(TEXT, "silver capacitor")
        self.assertEqual(len(recs), 2)
        b = recs[0]["box"]
        self.assertAlmostEqual(b.x0, 265 / 964, places=4)
        self.assertAlmostEqual(b.y1, 473 / 1280, places=4)
        self.assertIsNotNone(recs[0]["mask_tag"])

    def test_empty_text_no_objects(self):
        self.assertEqual(parse_response(response(""), (964, 1280), "x"), [])
        self.assertEqual(parse_response({"output": []}, (964, 1280), "x"), [])

    def test_objects_carry_aim_geometry(self):
        try:
            import meta_sam_parser  # noqa: F401
            has_parser = True
        except ImportError:
            has_parser = False
        objs = parse_response(response(), (964, 1280), "silver capacitor")
        if has_parser:
            # Strict official validation rejects the fake payload outright:
            # garbage masks become NO objects, never fabricated geometry.
            self.assertEqual(objs, [])
            return
        self.assertEqual(len(objs), 2)
        s = objs[0].summary()
        self.assertFalse(s["empty"])
        self.assertAlmostEqual(s["centroid"]["x"], 0.331, delta=0.01)
        self.assertEqual(objs[0].source, "sam3-box")


if __name__ == "__main__":
    unittest.main()
