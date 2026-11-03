"""Desktop launch poller — offline tests with fake Pi + fake drive.

Run: python3 -m unittest discover -s tank_vision -p 'test_*.py'
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))

from tank_vision.launcher import Launcher, parse_pi_output  # noqa: E402


class ParsePiOutput(unittest.TestCase):
    def test_marker_with_real_newline(self):
        code, body = parse_pi_output('{"ok": true}\n200')
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_marker_with_mangled_newline(self):
        # The ssh/bash path can eat the backslash, leaving "}n200".
        code, body = parse_pi_output('{"ok": true}n200')
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_garbage_is_zero_empty(self):
        self.assertEqual(parse_pi_output(""), (0, {}))
        self.assertEqual(parse_pi_output("not json"), (0, {}))


class FakePi:
    def __init__(self, state="pending"):
        self.launch = {"state": state, "text": "go get the shoe",
                       "target": "shoe", "detail": "",
                       "stop_requested": False}
        self.reports = []

    def __call__(self, method, path, payload=None):
        if path == "/api/launch" and method == "GET":
            return 200, {"ok": True, "launch": dict(self.launch)}
        if path == "/api/launch/consume":
            if self.launch["state"] != "pending":
                return 409, {"ok": False}
            self.launch["state"] = "running"
            return 200, {"ok": True, "text": self.launch["text"],
                         "target": self.launch["target"]}
        if path == "/api/launch/report":
            self.reports.append(dict(payload))
            self.launch["state"] = payload["state"]
            self.launch["detail"] = payload.get("detail", "")
            return 200, {"ok": True}
        raise AssertionError(path)


class PollOnce(unittest.TestCase):
    def test_pending_launch_drives_and_reports_done(self):
        pi = FakePi()
        seen = {}

        def run_drive(text, steps, fast, should_stop):
            seen["text"] = text
            return "done", "ARRIVED (area 0.30)"

        launcher = Launcher(pi, run_drive, steps=5)
        self.assertTrue(launcher.poll_once())
        self.assertEqual(seen["text"], "go get the shoe")
        self.assertEqual(pi.launch["state"], "done")
        self.assertEqual(pi.reports[-1]["state"], "done")

    def test_idle_does_nothing(self):
        pi = FakePi(state="idle")
        launcher = Launcher(pi, lambda *a: ("done", ""))
        self.assertFalse(launcher.poll_once())
        self.assertEqual(pi.reports, [])

    def test_stop_request_reaches_drive_and_reports_stopped(self):
        pi = FakePi()

        def run_drive(text, steps, fast, should_stop):
            pi.launch["stop_requested"] = True
            return ("stopped", "stop requested") if should_stop() \
                else ("done", "")

        launcher = Launcher(pi, run_drive)
        self.assertTrue(launcher.poll_once())
        self.assertEqual(pi.launch["state"], "stopped")


class Chain(unittest.TestCase):
    def chain_pi(self, text):
        pi = FakePi()
        pi.launch["text"] = text
        return pi

    def test_chain_runs_each_mission_in_order(self):
        pi = self.chain_pi("go to the blue ball then go to the mug")
        texts = []

        def run_drive(text, steps, fast, should_stop):
            texts.append(text)
            return "done", "ARRIVED"

        self.assertTrue(Launcher(pi, run_drive).poll_once())
        self.assertEqual(texts, ["go to the blue ball", "go to the mug"])
        self.assertEqual(pi.launch["state"], "done")
        self.assertIn("2/2", pi.reports[-1]["detail"])

    def test_failed_mission_ends_the_chain(self):
        pi = self.chain_pi("go to the cat then go to the mug")
        texts = []

        def run_drive(text, steps, fast, should_stop):
            texts.append(text)
            return "failed", "target lost"

        Launcher(pi, run_drive).poll_once()
        self.assertEqual(texts, ["go to the cat"])
        self.assertEqual(pi.launch["state"], "failed")

    def test_stop_ends_the_chain(self):
        pi = self.chain_pi("go to the cat then go to the mug")
        texts = []

        def run_drive(text, steps, fast, should_stop):
            texts.append(text)
            return "stopped", "stop requested from the page"

        Launcher(pi, run_drive).poll_once()
        self.assertEqual(texts, ["go to the cat"])
        self.assertEqual(pi.launch["state"], "stopped")


if __name__ == "__main__":
    unittest.main()
