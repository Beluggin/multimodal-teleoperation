#!/usr/bin/env python3
"""Raw mode's limits. Stdlib only, no real model and no hardware."""
import http.server
import json
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "src", "tank_tools"))
import llama_raw as raw  # noqa: E402


def reply(*moves):
    return json.dumps({"moves": [{"move": m, "secs": s} for m, s in moves]})


class StopNeverReachesTheModel(unittest.TestCase):
    def test_stop_words_skip_the_model(self):
        def ask(_text):
            raise AssertionError("the model was asked about a stop")
        for text in ("stop", "STOP!", "emergency stop right now", "e-stop",
                     "estop", "halt", "whoa", "freeze", "please stop now",
                     "stop then go forward", "go forward then stop",
                     "don't stop"):
            with self.subTest(text=text):
                plan = raw.interpret(text, ask)
                self.assertTrue(plan.stop)
                self.assertEqual(plan.moves, [])
                self.assertIsNone(plan.latency_s)

    def test_words_containing_stop_letters_are_not_stops(self):
        self.assertFalse(raw.is_stop("go forward"))
        self.assertFalse(raw.is_stop("unstoppable"))


class RepliesAreCheckedStrictly(unittest.TestCase):
    def test_good_plan(self):
        plan = raw.check_reply(reply(("spinl", 0.65), ("go", 1)))
        self.assertEqual(plan.moves, [("spinl", 0.65), ("go", 1.0)])
        self.assertFalse(plan.capped)

    def test_long_move_is_capped(self):
        plan = raw.check_reply(reply(("go", 30)))
        self.assertEqual(plan.moves, [("go", raw.MAX_SECS)])
        self.assertTrue(plan.capped)

    def test_bad_replies_move_nothing(self):
        bad = {
            "not json": "go forward please",
            "none": None,
            "list": "[]",
            "no moves key": '{"move": "go", "secs": 1}',
            "moves not list": '{"moves": "go"}',
            "move not dict": '{"moves": ["go"]}',
            "unknown move": reply(("fly", 1)),
            "missing secs": '{"moves": [{"move": "go"}]}',
            "string secs": '{"moves": [{"move": "go", "secs": "1"}]}',
            "bool secs": '{"moves": [{"move": "go", "secs": true}]}',
            "zero secs": reply(("go", 0)),
            "negative secs": reply(("go", -1)),
            "nan secs": '{"moves": [{"move": "go", "secs": NaN}]}',
            "infinite secs": '{"moves": [{"move": "go", "secs": Infinity}]}',
            "too many": reply(*[("go", 1)] * (raw.MAX_MOVES + 1)),
        }
        for name, text in bad.items():
            with self.subTest(name=name):
                plan = raw.check_reply(text)
                self.assertEqual(plan.moves, [])
                self.assertTrue(plan.reason)

    def test_one_bad_move_rejects_the_whole_plan(self):
        text = json.dumps({"moves": [{"move": "go", "secs": 1},
                                     {"move": "fly", "secs": 1}]})
        self.assertEqual(raw.check_reply(text).moves, [])

    def test_empty_plan_is_a_choice_not_to_move(self):
        plan = raw.check_reply('{"moves": []}')
        self.assertEqual(plan.moves, [])
        self.assertIn("no motion", plan.reason)

    def test_model_cannot_set_speed_or_trim(self):
        text = json.dumps({"moves": [{"move": "go", "secs": 1, "speed": 100,
                                      "trim": 99}]})
        items, _ = raw.plan_to_queue("x", raw.check_reply(text), 30)
        self.assertEqual(items, [("go", 1.0, 30, "llama.go")])


class ModelFailureMovesNothing(unittest.TestCase):
    def test_exception(self):
        def ask(_text):
            raise OSError("no route to host")
        plan = raw.interpret("go forward", ask)
        self.assertEqual(plan.moves, [])
        self.assertIn("unavailable", plan.reason)

    def test_unreachable_server(self):
        plan = raw.interpret(
            "go forward",
            lambda t: raw.ask_ollama(t, url="http://127.0.0.1:9", timeout=1))
        self.assertEqual(plan.moves, [])
        self.assertIn("unavailable", plan.reason)


class RunnerDropsLateAnswers(unittest.TestCase):
    def make(self):
        self.asked = threading.Event()
        self.release = threading.Event()
        self.delivered = []
        self.done = threading.Event()

        def ask(_text):
            self.asked.set()
            self.release.wait(5)
            return reply(("go", 1))

        def deliver(text, plan, speed):
            self.delivered.append((text, plan.moves, speed))
            self.done.set()

        return raw.RawRunner(deliver, ask)

    def test_answer_arrives_when_nothing_cancelled(self):
        runner = self.make()
        runner.submit("go", 30)
        self.assertTrue(self.asked.wait(5))
        self.release.set()
        self.assertTrue(self.done.wait(5))
        self.assertEqual(self.delivered, [("go", [("go", 1.0)], 30)])

    def test_stop_while_thinking_drops_the_answer(self):
        runner = self.make()
        runner.submit("go", 30)
        self.assertTrue(self.asked.wait(5))
        runner.cancel()         # stop or manual key while Llama is thinking
        self.release.set()
        self.assertFalse(self.done.wait(0.3))
        self.assertEqual(self.delivered, [])

    def test_cancel_drops_jobs_still_waiting(self):
        runner = self.make()
        runner.submit("first", 30)
        self.assertTrue(self.asked.wait(5))
        runner.submit("second", 30)
        runner.cancel()
        self.release.set()
        self.assertFalse(self.done.wait(0.3))
        self.assertEqual(self.delivered, [])

    def test_runner_still_works_after_a_cancel(self):
        runner = self.make()
        runner.submit("old", 30)
        self.assertTrue(self.asked.wait(5))
        runner.cancel()
        runner.submit("new", 25)
        self.release.set()
        self.assertTrue(self.done.wait(5))
        self.assertEqual(self.delivered, [("new", [("go", 1.0)], 25)])


class WireFormat(unittest.TestCase):
    def test_request_and_reply_match_ollama(self):
        seen = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen["path"] = self.path
                length = int(self.headers["Content-Length"])
                seen["body"] = json.loads(self.rfile.read(length))
                out = json.dumps({"response": reply(("go", 1))}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *_args):
                pass

        httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_port}"
        text = raw.ask_ollama("go forward", model="llama3.2:3b", url=url)
        self.assertEqual(seen["path"], "/api/generate")
        self.assertEqual(seen["body"]["model"], "llama3.2:3b")
        self.assertEqual(seen["body"]["format"], "json")
        self.assertFalse(seen["body"]["stream"])
        self.assertEqual(seen["body"]["options"]["temperature"], 0)
        self.assertEqual(raw.check_reply(text).moves, [("go", 1.0)])


if __name__ == "__main__":
    unittest.main()
