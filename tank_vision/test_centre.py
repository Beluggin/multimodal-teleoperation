"""Centreing math tests. Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tank_vision.centre import (  # noqa: E402
    camera_recenter_angles, centred, plan_step, run_scan,
    scan_pan_positions, scan_tilts, sign_after_trial,
)


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
    def test_pan_positions_cover_full_range_with_broad_steps(self):
        pos = scan_pan_positions((0, 75), current=74)
        self.assertEqual(pos[0], 75)
        self.assertEqual(pos[-1], 0)
        self.assertEqual(set(pos), {0, 30, 60, 75})
        steps = [abs(b - a) for a, b in zip(pos, pos[1:])]
        self.assertTrue(all(s <= 30 for s in steps))
        self.assertTrue(all(s >= 15 for s in steps))  # broad, not mini moves

    def test_pan_positions_start_toward_nearest_end_then_sweep_back(self):
        pos = scan_pan_positions((0, 75), current=10)
        self.assertEqual(pos[0], 0)
        self.assertEqual(pos[-1], 75)

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
        self.assertEqual(len(moves), 8 + 1)    # every stop, then restore

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
