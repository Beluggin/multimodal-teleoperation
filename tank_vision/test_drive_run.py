#!/usr/bin/env python3
"""Router tests for drive_run --text: sentence -> vision prompt, no motion.

Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tank_vision.drive_run import (  # noqa: E402
    chassis_scan, resolve_prompt, spin_secs_for_dx, step_secs_for_area,
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
        # Bigger-steps curve (Adam 2026-10-30: ~4in per old step was
        # too timid): 0.40/sqrt(area), cap raised 1.5 -> 2.5 s.
        self.assertAlmostEqual(step_secs_for_area(0.25), 0.6)
        self.assertAlmostEqual(step_secs_for_area(0.0625), 1.6)
        self.assertAlmostEqual(step_secs_for_area(0.01),
                               drive_run.STEP_MAX_SECS)

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
        # plain 0.40/sqrt(area) curve, but never below the floor.
        plain = 0.40 / 0.10 ** 0.5
        self.assertLess(step_secs_for_area(0.10), plain)
        self.assertGreaterEqual(step_secs_for_area(0.10),
                                drive_run.STEP_MIN_SECS)
        # Below the threshold the plain curve applies.
        self.assertAlmostEqual(step_secs_for_area(0.0625), 1.6)

    def test_garbage_area_falls_back_to_shortest_step(self):
        for area in (0, -1, None):
            with self.subTest(area=area):
                self.assertEqual(step_secs_for_area(area),
                                 drive_run.STEP_MIN_SECS)


class TandemMove(unittest.TestCase):
    def test_loss_after_tracking_gets_one_recovery(self):
        self.assertTrue(drive_run.should_tandem_recover(
            tandem=True, has_prev=True, recovered=False))
        self.assertFalse(drive_run.should_tandem_recover(
            tandem=True, has_prev=True, recovered=True))
        self.assertFalse(drive_run.should_tandem_recover(
            tandem=False, has_prev=True, recovered=False))
        self.assertFalse(drive_run.should_tandem_recover(
            tandem=True, has_prev=False, recovered=False))

    def test_servo_and_motor_both_run_for_one_picture(self):
        calls = []
        plan = {"pan": 53, "tilt": 40, "action": "spin",
                "bearing_deg": 12.0}
        drive_run.run_tandem(
            plan, "spinr 0.11 30",
            servo_fn=lambda pan, tilt: calls.append(("servo", pan, tilt)) or True,
            drive_fn=lambda cmd: calls.append(("motor", cmd)))
        self.assertIn(("servo", 53, 40), calls)
        self.assertIn(("motor", "spinr 0.11 30"), calls)

    def test_motor_failure_propagates(self):
        plan = {"pan": 53, "tilt": 40, "action": "forward",
                "bearing_deg": 1.0}

        def bad(cmd):
            raise RuntimeError("listener down")

        with self.assertRaises(RuntimeError):
            drive_run.run_tandem(plan, "go 1 30 17",
                                 servo_fn=lambda p, t: True,
                                 drive_fn=bad)


class ChassisScan(unittest.TestCase):
    def test_turns_toward_handicapped_left_and_rescans_until_found(self):
        scans, drives = [], []

        def scan(prompt):
            scans.append(prompt)
            return {"dx_right": 0.1} if len(scans) == 3 else None

        aim = chassis_scan("mug", scan_fn=scan,
                           drive_fn=drives.append, max_turns=3)
        self.assertEqual(aim, {"dx_right": 0.1})
        self.assertEqual(scans, ["mug"] * 3)
        # Default favours LEFT: the neck has only 22 units of travel
        # that side of PAN_FORWARD (Adam, 2026-10-30), so the chassis
        # turns left to cover the handicapped side. ~60 deg at 110/s.
        self.assertEqual(drives, ["spinl 0.55 30", "spinl 0.55 30"])

    def test_failed_spin_aborts_search(self):
        scans = []

        def scan(prompt):
            scans.append(prompt)
            return None

        def bad_drive(cmd):
            raise RuntimeError("listener down")

        self.assertIsNone(chassis_scan("mug", scan_fn=scan,
                                       drive_fn=bad_drive, max_turns=3))
        self.assertEqual(scans, ["mug"])

    def test_spin_direction_is_configurable(self):
        drives = []
        chassis_scan("mug", scan_fn=lambda p: None,
                     drive_fn=drives.append, max_turns=1, spin="spinr")
        self.assertEqual(drives, ["spinr 0.55 30"])


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
