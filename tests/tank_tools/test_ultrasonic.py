"""Ultrasonic math tests — no GPIO. Run: python3 -m unittest discover -s tank_tools -p 'test_*.py'"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src", "tank_tools"))
from ultrasonic import median_distance, pulse_to_cm  # noqa: E402


class TestUltrasonic(unittest.TestCase):
    def test_conversion(self):
        self.assertAlmostEqual(pulse_to_cm(0.0058), 100.0, places=1)  # 1 m
        self.assertAlmostEqual(pulse_to_cm(0.00058), 10.0, places=1)

    def test_median_ignores_timeouts_and_outliers(self):
        self.assertEqual(median_distance([88.0, None, 89.0, 400.0, 88.5]), 88.8)
        self.assertIsNone(median_distance([None, None]))
        self.assertIsNone(median_distance([]))


if __name__ == "__main__":
    unittest.main()
