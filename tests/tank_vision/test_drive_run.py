#!/usr/bin/env python3
"""Router tests for drive_run --text: sentence -> vision prompt, no motion.

Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
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
            tandem=True, has_prev=True, recovered=False, found=False))
        self.assertFalse(drive_run.should_tandem_recover(
            tandem=True, has_prev=True, recovered=True, found=False))
        self.assertFalse(drive_run.should_tandem_recover(
            tandem=False, has_prev=True, recovered=False, found=False))
        self.assertFalse(drive_run.should_tandem_recover(
            tandem=True, has_prev=False, recovered=False, found=False))

    def test_spin_is_followed_by_a_capped_forward_step(self):
        # Adam 2026-10-30: a turn must launch a drive step after it,
        # capped so a missed open-loop spin can't carry it far.
        args = drive_run.argparse.Namespace(step_secs=None, duty=30,
                                            trim=17)
        spin = {"action": "spin", "bearing_deg": 20.0}
        far = drive_run.tandem_followup_cmd(
            spin, {"area_frac": 0.005}, args)
        self.assertEqual(far, f"go {drive_run.SPIN_FOLLOW_MAX_SECS:g} 30 17")
        near = drive_run.tandem_followup_cmd(
            spin, {"area_frac": 0.2}, args)
        secs = float(near.split()[1])
        self.assertGreaterEqual(secs, drive_run.STEP_MIN_SECS)
        self.assertLessEqual(secs, drive_run.SPIN_FOLLOW_MAX_SECS)

    def test_forward_plan_needs_no_followup(self):
        args = drive_run.argparse.Namespace(step_secs=None, duty=30,
                                            trim=17)
        self.assertIsNone(drive_run.tandem_followup_cmd(
            {"action": "forward", "bearing_deg": 1.0},
            {"area_frac": 0.05}, args))

    def test_found_target_never_triggers_recovery(self):
        # 2026-10-30: without this the scan ran after EVERY tracked
        # step, threw away a good aim and logged a false "lost".
        self.assertFalse(drive_run.should_tandem_recover(
            tandem=True, has_prev=True, recovered=False, found=True))

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
        # First turn favours LEFT (the neck's handicapped side, Adam
        # 2026-10-30); then Adam's sweep (2026-10-31): alternate sides,
        # each turn bigger — left 60, then right 120 (60 past start).
        self.assertEqual(drives, ["spinl 0.55 30", "spinr 1.09 30"])

    def test_turns_alternate_and_grow(self):
        # Chain 4: three LEFT turns hunted 180 deg away from the mug
        # (it was right, past the neck) and found a cat instead.
        drives = []
        chassis_scan("mug", scan_fn=lambda p: None,
                     drive_fn=drives.append, max_turns=3)
        self.assertEqual(drives, ["spinl 0.55 30", "spinr 1.09 30",
                                  "spinl 1.64 30"])

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


class BottomClip(unittest.TestCase):
    """2026-10-31 ball run: box on the bottom edge = close, not far."""
    # Step 3 of chain 3: Adam saw it ~4 in away ("perfect"), area only
    # 0.076; step 4 the ball was a sliver (area 0.0099) at dy -0.48.
    PERFECT = {"dx_right": -0.2, "dy_up": -0.405, "area_frac": 0.0755,
               "y_bottom": 0.995}
    SLIVER = {"dx_right": -0.07, "dy_up": -0.48, "area_frac": 0.0099,
              "y_bottom": 1.0}
    FAR = {"dx_right": 0.1, "dy_up": 0.22, "area_frac": 0.03,
           "y_bottom": 0.80}

    def test_bottom_clipped_target_has_arrived(self):
        self.assertTrue(drive_run.arrived(self.PERFECT))
        self.assertTrue(drive_run.arrived(self.SLIVER))

    def test_far_target_has_not_arrived(self):
        self.assertFalse(drive_run.arrived(self.FAR))
        self.assertFalse(drive_run.arrived(
            {"dx_right": 0, "dy_up": 0, "area_frac": 0.1}))  # no box edge

    def test_big_target_still_arrives_by_area(self):
        self.assertTrue(drive_run.arrived(
            {"dx_right": 0, "dy_up": 0, "area_frac": 0.3}))

    def test_sliver_loss_reverses(self):
        calls = []
        drive_run.recover_after_loss(
            self.SLIVER, look_fn=lambda: None,
            drive_fn=lambda c: calls.append(c), wide_fn=lambda: None,
            duty=30, trim=17)
        self.assertEqual(calls, [f"rev {drive_run.REVERSE_SECS:g} 30 17"])


class ArrivalConfirm(unittest.TestCase):
    """Chain 5 mug: ARRIVED with only the NECK on it (pan 28), the
    chassis unturned, ~1 ft short (Adam). Arrival must face + aim first."""

    def plan(self, aim, pan, tilt):
        from tank_vision.centre import tandem_plan
        return tandem_plan(aim, pan, tilt, (0, 75), (20, 120))

    def test_neck_only_arrival_needs_confirm(self):
        mug = {"dx_right": 0.078, "dy_up": -0.271, "area_frac": 0.183,
               "y_bottom": 1.0}
        plan = self.plan(mug, pan=28, tilt=41)
        self.assertEqual(plan["action"], "spin")     # not facing it
        self.assertTrue(drive_run.needs_arrival_confirm(plan, tilt=41))

    def test_facing_clip_that_can_tilt_lower_needs_confirm(self):
        aim = {"dx_right": 0.0, "dy_up": -0.3, "area_frac": 0.12,
               "y_bottom": 1.0}
        plan = self.plan(aim, pan=53, tilt=41)
        self.assertEqual(plan["action"], "forward")
        self.assertTrue(drive_run.needs_arrival_confirm(plan, tilt=41))

    def test_facing_and_aimed_is_arrived(self):
        aim = {"dx_right": 0.02, "dy_up": -0.02, "area_frac": 0.3,
               "y_bottom": 0.9}
        plan = self.plan(aim, pan=53, tilt=30)
        self.assertFalse(drive_run.needs_arrival_confirm(plan, tilt=30))

    def test_tilt_at_floor_trusts_the_clip(self):
        aim = {"dx_right": 0.0, "dy_up": -0.45, "area_frac": 0.01,
               "y_bottom": 1.0}
        plan = self.plan(aim, pan=53, tilt=20)        # can't look lower
        self.assertFalse(drive_run.needs_arrival_confirm(plan, tilt=20))

    def test_tandem_can_move_neck_without_motor(self):
        calls = []
        drive_run.run_tandem(
            {"pan": 53, "tilt": 30}, None,
            servo_fn=lambda p, t: calls.append(("servo", p, t)) or True,
            drive_fn=lambda c: calls.append(("motor", c)))
        self.assertEqual(calls, [("servo", 53, 30)])


class RecogniseBox(unittest.TestCase):
    def test_aim_carries_box_bottom(self):
        from tank_vision import centre_run

        class Obj:
            def summary(self):
                return {"empty": False, "area_frac": 0.05,
                        "mask_box": {"x0": 0.4, "y0": 0.8,
                                     "x1": 0.6, "y1": 1.0}}
        real = centre_run.segment_text
        centre_run.segment_text = lambda path, prompt: ([Obj()], {})
        try:
            aim, _ = centre_run.recognise("x.jpg", "ball")
        finally:
            centre_run.segment_text = real
        self.assertEqual(aim["y_bottom"], 1.0)


class LostRecovery(unittest.TestCase):
    """Tandem loss ladder: close -> reverse+look, then chassis-assisted scan."""
    CLOSE = {"dx_right": -0.30, "dy_up": -0.23, "area_frac": 0.186}
    FAR = {"dx_right": 0.10, "dy_up": 0.00, "area_frac": 0.03}
    SEEN = {"dx_right": 0.0, "dy_up": -0.2, "area_frac": 0.2}

    def run_ladder(self, prev, look=None, wide=None):
        calls = []

        def drive_fn(cmd):
            calls.append(("motor", cmd))

        def look_fn():
            calls.append(("look",))
            return look

        def wide_fn():
            calls.append(("wide",))
            return wide

        aim, under = drive_run.recover_after_loss(
            prev, look_fn=look_fn, drive_fn=drive_fn, wide_fn=wide_fn,
            duty=30, trim=17)
        return aim, under, calls

    def test_close_loss_reverses_then_looks(self):
        aim, under, calls = self.run_ladder(self.CLOSE, look=self.SEEN)
        self.assertEqual(calls[0], ("motor",
                         f"rev {drive_run.REVERSE_SECS:g} 30 17"))
        self.assertEqual(calls[1], ("look",))
        self.assertTrue(under)          # seen after backing off = arrived
        self.assertEqual(aim, self.SEEN)
        self.assertNotIn(("wide",), calls)

    def test_close_loss_not_seen_after_reverse_goes_wide(self):
        aim, under, calls = self.run_ladder(self.CLOSE, look=None,
                                            wide=self.FAR)
        self.assertEqual([c[0] for c in calls], ["motor", "look", "wide"])
        self.assertFalse(under)
        self.assertEqual(aim, self.FAR)

    def test_far_loss_never_reverses(self):
        aim, under, calls = self.run_ladder(self.FAR, wide=None)
        self.assertEqual(calls, [("wide",)])
        self.assertIsNone(aim)
        self.assertFalse(under)

    def test_far_loss_right_after_forward_step_reverses_first(self):
        # Chain 6 mug (Adam): last seen small (0.029), then a 2 s go put
        # the short mug under the camera; the ladder skipped the reverse
        # and chassis-scanned away from a mug under its chin.
        calls = []
        aim, under = drive_run.recover_after_loss(
            self.FAR, look_fn=lambda: calls.append(("look",)) or self.SEEN,
            drive_fn=lambda c: calls.append(("motor", c)),
            wide_fn=lambda: calls.append(("wide",)),
            duty=30, trim=17, after_forward=True)
        self.assertEqual(calls[0], ("motor",
                         f"rev {drive_run.REVERSE_SECS:g} 30 17"))
        self.assertTrue(under)
        self.assertNotIn(("wide",), calls)

    def test_wide_search_is_chassis_assisted(self):
        # Recovery must use the neck + chassis-turn scan, not neck only.
        self.assertIs(drive_run.LOST_WIDE_SCAN, drive_run.chassis_scan)


if __name__ == "__main__":
    unittest.main(verbosity=1)
