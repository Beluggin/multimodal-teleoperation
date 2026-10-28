"""Centreing math tests. Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tank_vision.centre import centred, plan_step, sign_after_trial  # noqa: E402


class TestCentre(unittest.TestCase):
    def test_step_clamped_and_signed(self):
        pan, tilt = plan_step({"dx_right": 0.5, "dy_up": -0.5})
        self.assertEqual((pan, tilt), (5.0, -5.0))  # clamped, signs follow aim
        pan, _ = plan_step({"dx_right": 0.5, "dy_up": 0.0}, sign_pan=-1)
        self.assertEqual(pan, -5.0)  # learned sign flips the command

    def test_trial_learning(self):
        before = {"dx_right": 0.2, "dy_up": 0.0}
        worse = {"dx_right": 0.3, "dy_up": 0.0}
        better = {"dx_right": 0.1, "dy_up": 0.0}
        self.assertEqual(sign_after_trial(before, worse, "dx_right", 1), -1)
        self.assertEqual(sign_after_trial(before, better, "dx_right", 1), 1)

    def test_centred_tolerance(self):
        self.assertTrue(centred({"dx_right": 0.04, "dy_up": -0.05}))
        self.assertFalse(centred({"dx_right": 0.2, "dy_up": 0.0}))


if __name__ == "__main__":
    unittest.main()
