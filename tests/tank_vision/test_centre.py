"""Centreing math tests. Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from tank_vision.centre import (  # noqa: E402
    camera_recenter_angles, centred, plan_step, run_chassis_scan,
    run_scan, scan_pan_positions, scan_tilts, sign_after_trial,
)


class TestTandemPlan(unittest.TestCase):
    def test_straight_camera_offcentre_target_spins_chassis(self):
        from tank_vision.centre import tandem_plan
        plan = tandem_plan({"dx_right": 0.30, "dy_up": 0.0},
                           pan_angle=53, tilt_angle=40)
        self.assertEqual(plan["action"], "spin")
        self.assertAlmostEqual(plan["bearing_deg"], 0.30 * 33.0, places=1)
        self.assertEqual(plan["pan"], 53)  # neck returns to forward

    def test_saturated_camera_bearing_includes_neck_offset(self):
        from tank_vision.centre import tandem_plan
        # Camera at pan 75 is 22 units view-left of the nose, ~19 deg
        # at the measured 0.85 deg/unit; a centred target is that far
        # left of the chassis.
        plan = tandem_plan({"dx_right": 0.0, "dy_up": 0.0},
                           pan_angle=75, tilt_angle=40)
        self.assertEqual(plan["action"], "spin")
        self.assertAlmostEqual(plan["bearing_deg"], -22 * 0.85, delta=0.5)

    def test_forward_recentre_points_neck_at_the_bearing(self):
        from tank_vision.centre import PAN_FORWARD, tandem_plan, SERVO_DEG_PER_UNIT
        # The neck pan chosen to centre the target must agree with the
        # bearing the same plan computed (one deg/unit, not two).
        plan = tandem_plan({"dx_right": 0.12, "dy_up": 0.0},
                           pan_angle=55, tilt_angle=40)
        self.assertEqual(plan["action"], "forward")
        neck_bearing = (PAN_FORWARD - plan["pan"]) * SERVO_DEG_PER_UNIT
        self.assertAlmostEqual(neck_bearing, plan["bearing_deg"],
                               delta=SERVO_DEG_PER_UNIT / 2 + 0.01)

    def test_small_bearing_forwards_and_centres_camera(self):
        from tank_vision.centre import tandem_plan
        plan = tandem_plan({"dx_right": 0.10, "dy_up": 0.0},
                           pan_angle=53, tilt_angle=40)
        self.assertEqual(plan["action"], "forward")
        self.assertLess(plan["pan"], 53)  # view-right = ch6 down


class TestCalibration(unittest.TestCase):
    def test_pan_forward_inside_limits_with_asymmetric_travel(self):
        from tank_vision.centre import PAN_FORWARD
        self.assertTrue(0 < PAN_FORWARD < 75)
        self.assertEqual(75 - PAN_FORWARD, 22)  # view-left travel
        self.assertEqual(PAN_FORWARD - 0, 53)   # view-right travel

    def test_servo_deg_per_unit_measured(self):
        # Measured 2026-10-30 (Claude, SAM on a fixed object, pan
        # 45..61): dx 0.0258/unit x 33 deg = 0.85 deg/unit, linear,
        # backlash < 1 unit. The old eyeball fit said 1.2.
        from tank_vision.centre import SERVO_DEG_PER_UNIT
        self.assertAlmostEqual(SERVO_DEG_PER_UNIT, 0.85, delta=0.05)


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


class TestScan(unittest.TestCase):
    def covered(self, pos, current, lo=0, hi=75):
        # Every pan in range must be inside some frame (current included).
        from tank_vision.centre import FOV_H_DEG, SERVO_DEG_PER_UNIT
        half = FOV_H_DEG / SERVO_DEG_PER_UNIT / 2
        return all(any(abs(p - c) <= half for c in [current] + pos)
                   for p in range(lo, hi + 1))

    def test_sweep_alternates_outward_from_current(self):
        # Adam 2026-10-31: one shot, then the other side slightly
        # bigger, and so on — near the front is searched first.
        pos = scan_pan_positions((0, 75), current=37)
        offs = [p - 37 for p in pos]
        self.assertGreater(offs[0], 0)            # view-left first
        self.assertLess(offs[1], 0)               # then the other side
        mags = [abs(o) for o in offs]
        self.assertEqual(mags, sorted(mags))      # swings never shrink
        self.assertNotIn(37, pos)                 # first look already done

    def test_sweep_covers_full_range_in_few_stops(self):
        for cur in (0, 10, 37, 53, 60, 75):
            with self.subTest(current=cur):
                pos = scan_pan_positions((0, 75), current=cur)
                self.assertTrue(self.covered(pos, cur))
                self.assertLessEqual(len(pos), 4)  # was 6 stops/row
                self.assertTrue(all(0 <= p <= 75 for p in pos))

    def test_measured_fov_not_assumed(self):
        from tank_vision.centre import FOV_H_DEG, FOV_V_DEG
        # a helper's feet, 50 cm apart at 185 cm, 2026-10-30: 32.7 x 24.8.
        self.assertAlmostEqual(FOV_H_DEG, 33.0, delta=2.0)
        self.assertAlmostEqual(FOV_V_DEG, 25.0, delta=2.0)

    def test_later_rows_also_look_at_the_starting_pan(self):
        # The first look happened at (start pan, first tilt) only; the
        # floor row must still look straight ahead at its own tilt.
        moves = []

        def move(pan, tilt):
            moves.append((pan, tilt))
            return True
        run_scan([62, 12], [72, 42], move, lambda: None, origin=(37, 72))
        self.assertIn((37, 42), moves)
        self.assertNotIn((37, 72), moves[:-1])   # only the final restore

    def test_tilts_add_a_floor_row_below_current(self):
        self.assertEqual(scan_tilts((30, 120), current=72), [72, 42])
        self.assertEqual(scan_tilts((30, 120), current=35), [35, 30])

    def test_run_scan_finds_and_stops_moving(self):
        moves, looks = [], []

        def move(pan, tilt):
            moves.append((pan, tilt))
            return True

        def recognise():
            looks.append(1)
            return {"dx_right": 0.1} if len(looks) == 3 else None

        aim = run_scan([75, 45, 15], [72], move, recognise,
                       origin=(74, 72))
        self.assertEqual(aim, {"dx_right": 0.1})
        self.assertEqual(moves, [(75, 72), (45, 72), (15, 72)])

    def test_run_scan_failure_restores_origin_and_returns_none(self):
        moves = []

        def move(pan, tilt):
            moves.append((pan, tilt))
            return True

        aim = run_scan([75, 45, 15, 0], [72, 42], move, lambda: None,
                       origin=(74, 72))
        self.assertIsNone(aim)
        self.assertEqual(moves[-1], (74, 72))  # put the head back
        # every stop (+ the start pan on the floor row), then restore
        self.assertEqual(len(moves), 4 + 5 + 1)

    def test_chassis_scan_finds_on_second_leg_after_one_turn(self):
        scans, spins = [], []

        def scan():
            scans.append(1)
            return {"dx_right": 0.2} if len(scans) == 2 else None

        def spin():
            spins.append(1)
            return True

        aim = run_chassis_scan(scan, spin, max_turns=3)
        self.assertEqual(aim, {"dx_right": 0.2})
        self.assertEqual(len(scans), 2)
        self.assertEqual(len(spins), 1)

    def test_chassis_scan_first_leg_find_never_spins(self):
        spins = []
        aim = run_chassis_scan(lambda: {"dx_right": 0.0},
                               lambda: spins.append(1) or True,
                               max_turns=3)
        self.assertEqual(aim, {"dx_right": 0.0})
        self.assertEqual(spins, [])

    def test_chassis_scan_never_found_stops_after_turn_cap(self):
        scans, spins = [], []

        def scan():
            scans.append(1)
            return None

        def spin():
            spins.append(1)
            return True

        self.assertIsNone(run_chassis_scan(scan, spin, max_turns=3))
        self.assertEqual(len(scans), 4)   # initial leg + 3 re-scans
        self.assertEqual(len(spins), 3)

    def test_chassis_scan_refused_spin_aborts_without_rescan(self):
        scans = []

        def scan():
            scans.append(1)
            return None

        self.assertIsNone(run_chassis_scan(scan, lambda: False,
                                           max_turns=3))
        self.assertEqual(len(scans), 1)

    def test_run_scan_move_refusal_aborts_and_restores(self):
        moves = []

        def move(pan, tilt):
            moves.append((pan, tilt))
            return len(moves) < 2  # second move refused

        aim = run_scan([75, 45], [72], move, lambda: None, origin=(74, 72))
        self.assertIsNone(aim)
        self.assertEqual(moves[-1], (74, 72))


class TestRecenter(unittest.TestCase):
    def test_target_right_moves_view_right_ch6_down(self):
        # Physical mapping proven live 2026-10-29: view right = ch6 down,
        # view up = ch5 up.
        pan, tilt = camera_recenter_angles(
            {"dx_right": 0.3, "dy_up": 0.2}, 57, 43, (0, 75), (30, 120))
        self.assertLess(pan, 57)
        self.assertGreater(tilt, 43)

    def test_target_left_moves_view_left_ch6_up(self):
        pan, _ = camera_recenter_angles(
            {"dx_right": -0.37, "dy_up": 0.0}, 57, 43, (0, 75), (30, 120))
        self.assertGreater(pan, 57)

    def test_recentre_converts_degrees_to_servo_units(self):
        # dx 0.2 = 6.6 deg = 7.8 units at 0.85 deg/unit (not 6.6 units).
        pan, _ = camera_recenter_angles(
            {"dx_right": 0.2, "dy_up": 0.0}, 53, 43, (0, 75), (30, 120))
        self.assertEqual(pan, 45)

    def test_centred_target_needs_no_move(self):
        self.assertIsNone(camera_recenter_angles(
            {"dx_right": 0.02, "dy_up": -0.03}, 57, 43, (0, 75), (30, 120)))

    def test_saturated_pan_needs_no_servo_move(self):
        # At the limit the neck cannot help: None tells the caller the
        # body must spin, with the current aim unchanged.
        self.assertIsNone(camera_recenter_angles(
            {"dx_right": -0.37, "dy_up": 0.0}, 75, 43, (0, 75), (30, 120)))


if __name__ == "__main__":
    unittest.main()
