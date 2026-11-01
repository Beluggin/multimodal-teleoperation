"""Manual-mode API tests — FakeMotor/FakeBus only, no hardware, no sockets.

Run: python3 -m unittest discover -s tank_phone -p 'test_*.py'
"""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import servo_ctl  # noqa: E402
import server as srv  # noqa: E402

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(port, method, path, payload=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class StickMath(unittest.TestCase):
    def test_deadzone_is_stop(self):
        self.assertEqual(srv.stick_to_move(0.05, -0.05, 30)["move"], "stop")
        self.assertEqual(srv.stick_to_move(0, 0, 30)["move"], "stop")

    def test_forward_and_reverse(self):
        m = srv.stick_to_move(0, -1, 30)   # stick up = forward
        self.assertEqual(m["move"], "go")
        self.assertAlmostEqual(m["duty"], 30)
        m = srv.stick_to_move(0, 1, 30)
        self.assertEqual(m["move"], "rev")

    def test_spin_dominates_on_pure_side_push(self):
        self.assertEqual(srv.stick_to_move(1, 0, 25)["move"], "spinr")
        self.assertEqual(srv.stick_to_move(-1, 0, 25)["move"], "spinl")

    def test_duty_never_exceeds_cap_or_hard_limit(self):
        self.assertLessEqual(srv.stick_to_move(0, -1, 999)["duty"], 40)
        self.assertLessEqual(srv.stick_to_move(0, -1, 15)["duty"], 15)

    def test_garbage_is_stop(self):
        for x, y in (("a", 0), (None, 1), (float("nan"), 0)):
            with self.subTest(x=x, y=y):
                self.assertEqual(srv.stick_to_move(x, y, 30)["move"], "stop")


class FakeMotor:
    def __init__(self):
        self.calls = []

    def send(self, move, secs, duty, trim):
        self.calls.append((move, secs, duty, trim))
        return "ok " + move


class ManualApi(unittest.TestCase):
    motors = True

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.mkdtemp()
        cls.motor = FakeMotor()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        cls.httpd.servo_enabled = True
        cls.httpd.servo_bus = servo_ctl.FakeBus()
        cls.httpd.servo_state = dict(servo_ctl.DEFAULTS)
        cls.httpd.servo_lock = threading.Lock()
        cls.httpd.flags_file = os.path.join(cls.tmp, "flags.json")
        cls.httpd.servo_flags = []
        cls.httpd.servo_limits = dict(servo_ctl.LIMITS)
        cls.httpd.limits_file = os.path.join(cls.tmp, "limits.json")
        cls.httpd.motor_enabled = cls.motors
        cls.httpd.motor_client = cls.motor
        cls.httpd.motor_cap = 40.0
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_drive_forward_reaches_motor(self):
        code, body = call(self.port, "POST", "/api/drive",
                          {"x": 0, "y": -1, "cap": 20})
        if not self.motors:
            self.assertEqual(code, 403)
            return
        self.assertEqual(code, 200)
        self.assertEqual(body["move"], "go")
        self.assertEqual(self.motor.calls[-1][0], "go")
        self.assertLessEqual(self.motor.calls[-1][2], 20)

    def test_stop_always_allowed(self):
        code, body = call(self.port, "POST", "/api/drive", {"x": 0, "y": 0})
        self.assertEqual(code, 200)
        self.assertEqual(body["move"], "stop")

    def test_camera_stick_moves_pan_within_limits(self):
        before = self.httpd.servo_state[6]
        code, body = call(self.port, "POST", "/api/camera", {"x": 1, "y": 0})
        self.assertEqual(code, 200)
        self.assertNotEqual(body["state"]["6"], before)
        lo, hi = servo_ctl.LIMITS[6]
        self.assertTrue(lo <= body["state"]["6"] <= hi)

    def test_camera_axes_match_stick_direction(self):
        # Physical head (Adam live test): stick right = ch6 DOWN,
        # stick up = ch5 UP. Both axes were reversed before this fix.
        pan0, tilt0 = self.httpd.servo_state[6], self.httpd.servo_state[5]
        code, body = call(self.port, "POST", "/api/camera", {"x": 1, "y": -1})
        self.assertEqual(code, 200)
        self.assertLess(body["state"]["6"], pan0)
        self.assertGreater(body["state"]["5"], tilt0)

    def test_telemetry_shape(self):
        code, body = call(self.port, "GET", "/api/telemetry")
        self.assertEqual(code, 200)
        for key in ("servo_enabled", "motor_enabled", "motor_cap",
                    "speech", "ultrasonic"):
            self.assertIn(key, body)


class ManualApiMotorsOff(ManualApi):
    motors = False


JPEG = b"\xff\xd8" + b"pixels" + b"\xff\xd9"


class DriveFrame(unittest.TestCase):
    # While a drive runs the camera belongs to the drive loop, so the
    # phone shows the frames the loop saves (Adam's demo screen recording).
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.frame = os.path.join(self.tmp, "centre_frame.jpg")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
        self.httpd.drive_frame_path = self.frame
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def get(self):
        try:
            with _OPENER.open(f"http://127.0.0.1:{self.port}/api/driveframe",
                              timeout=5) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, None, b""

    def queue(self, queued_at):
        self.httpd.launch_status = {"state": "running", "text": "",
                                    "target": "mug", "detail": "",
                                    "stop_requested": False,
                                    "queued_at": queued_at}

    def write(self, data, mtime):
        with open(self.frame, "wb") as f:
            f.write(data)
        os.utime(self.frame, (mtime, mtime))

    def test_serves_frame_taken_during_this_launch(self):
        self.queue(1000.0)
        self.write(JPEG, 1005.0)
        code, ctype, body = self.get()
        self.assertEqual((code, ctype, body), (200, "image/jpeg", JPEG))

    def test_frame_from_an_earlier_mission_is_not_shown(self):
        self.queue(1000.0)
        self.write(JPEG, 990.0)
        self.assertEqual(self.get()[0], 204)

    def test_half_written_frame_falls_back_to_last_complete(self):
        self.queue(1000.0)
        self.write(JPEG, 1005.0)
        self.get()
        self.write(b"\xff\xd8half", 1009.0)   # qstream mid-write
        code, _, body = self.get()
        self.assertEqual((code, body), (200, JPEG))

    def test_no_launch_or_no_file_is_no_content(self):
        self.assertEqual(self.get()[0], 204)
        self.queue(1000.0)
        self.assertEqual(self.get()[0], 204)


if __name__ == "__main__":
    unittest.main()
