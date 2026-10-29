#!/usr/bin/env python3
"""Router tests for drive_run --text: sentence -> vision prompt, no motion.

Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tank_vision.drive_run import (  # noqa: E402
    resolve_prompt, spin_secs_for_dx, step_secs_for_area,
)
import tank_vision.drive_run as drive_run  # noqa: E402


class ResolvePrompt(unittest.TestCase):
    def test_goto_sentences_route_to_target(self):
        self.assertEqual(resolve_prompt("go get the shoe"), ("shoe", ""))
        self.assertEqual(resolve_prompt("go to the white box"),
                         ("white box", ""))

    def test_non_goto_sentences_route_nowhere(self):
        for text in ("wave", "drive forward", "don't go to the shoe",
                     "go to the shoe and wave", "blorpt", ""):
            with self.subTest(text=text):
                target, why = resolve_prompt(text)
                self.assertIsNone(target)
                self.assertTrue(why)


class AdaptiveStep(unittest.TestCase):
    def test_far_target_takes_long_step_near_takes_short(self):
        # Distance scales with 1/sqrt(area): quarter area = twice as far.
        self.assertAlmostEqual(step_secs_for_area(0.25), 0.5)
        self.assertAlmostEqual(step_secs_for_area(0.0625), 1.0)

    def test_step_always_within_bounds(self):
        for area in (0.001, 0.01, 0.05, 0.1, 0.2, 0.24, 0.5, 1.0):
            with self.subTest(area=area):
                secs = step_secs_for_area(area)
                self.assertGreaterEqual(secs, drive_run.STEP_MIN_SECS)
                self.assertLessEqual(secs, drive_run.STEP_MAX_SECS)

    def test_step_shrinks_monotonically_as_target_grows(self):
        areas = (0.01, 0.03, 0.06, 0.1, 0.15, 0.2)
        secs = [step_secs_for_area(a) for a in areas]
        self.assertEqual(secs, sorted(secs, reverse=True))

    def test_step_shrinks_harder_above_008(self):
        # Near the target the blind step must drop faster than the
        # plain 0.25/sqrt(area) curve, but never below the floor.
        plain = 0.25 / 0.10 ** 0.5
        self.assertLess(step_secs_for_area(0.10), plain)
        self.assertGreaterEqual(step_secs_for_area(0.10),
                                drive_run.STEP_MIN_SECS)
        # Below the threshold the proven curve is unchanged.
        self.assertAlmostEqual(step_secs_for_area(0.0625), 1.0)

    def test_garbage_area_falls_back_to_shortest_step(self):
        for area in (0, -1, None):
            with self.subTest(area=area):
                self.assertEqual(step_secs_for_area(area),
                                 drive_run.STEP_MIN_SECS)


class DampedSpin(unittest.TestCase):
    def test_spin_scales_with_offset(self):
        self.assertAlmostEqual(spin_secs_for_dx(-0.37), 0.37 * 60 / 110,
                               places=2)

    def test_overshoot_halves_next_spin(self):
        # Tonight's loop: -0.37 -> +0.26 -> -0.26 forever at the 0.15 floor.
        first = spin_secs_for_dx(-0.37)
        second = spin_secs_for_dx(0.26, last_dx=-0.37, last_secs=first)
        third = spin_secs_for_dx(-0.25, last_dx=0.26, last_secs=second)
        self.assertLess(second, first)
        self.assertLess(third, second)

    def test_same_sign_keeps_full_correction(self):
        first = spin_secs_for_dx(-0.37)
        nxt = spin_secs_for_dx(-0.26, last_dx=-0.37, last_secs=first)
        self.assertAlmostEqual(nxt, 0.26 * 60 / 110, places=2)

    def test_spin_bounds(self):
        for dx in (0.01, 0.2, 0.5, 1.0):
            secs = spin_secs_for_dx(dx)
            self.assertGreaterEqual(secs, 0.07)
            self.assertLessEqual(secs, 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=1)
