#!/usr/bin/env python3
"""
test_xiaor_text_action.py — committed tests for the fixed-phrase text→action
classifier. Stdlib unittest, no network, no waiting (fake sender + fake sleep).

Run from tank_tools/:
    python3 test_xiaor_text_action.py
"""

import unittest

import xiaor_text_action as x


def classify(text):
    return x.classify(text)


class ClassifyDrive(unittest.TestCase):
    def test_synonyms(self):
        for text in ("drive forward", "move forward", "go forward",
                     "straight ahead", "forward", "ahead", "advance"):
            with self.subTest(text=text):
                self.assertEqual(classify(text).label, "drive.forward")

    def test_backward(self):
        for text in ("back up", "go back", "reverse", "backwards", "back"):
            with self.subTest(text=text):
                self.assertEqual(classify(text).label, "drive.backward")

    def test_turns(self):
        self.assertEqual(classify("turn left").label, "drive.left")
        self.assertEqual(classify("veer right").label, "drive.right")

    def test_bare_go_has_no_direction(self):
        # Like omni_gate: directionless motion words never drive.
        for text in ("go", "move", "drive", "just move around", "move!"):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.kind, "unknown")
                self.assertEqual(a.commands, [])

    def test_stop_and_estop(self):
        self.assertEqual(classify("stop").label, "drive.stop")
        self.assertEqual(classify("halt").label, "drive.stop")
        self.assertEqual(classify("stop now").label, "drive.estop")
        self.assertEqual(classify("emergency stop").label, "drive.estop")

    def test_turn_around_is_timed(self):
        a = classify("turn around")
        self.assertEqual(a.label, "drive.around")
        self.assertAlmostEqual(a.duration, x.TURN_AROUND_SECONDS)

    def test_duration_and_cap(self):
        a = classify("drive forward for 3 seconds")
        self.assertAlmostEqual(a.duration, 3.0)
        a = classify("go back for 999 seconds")
        self.assertAlmostEqual(a.duration, x.MAX_DURATION)

    def test_zero_duration_refused(self):
        a = classify("drive forward for 0 seconds")
        self.assertEqual(a.kind, "refused")
        self.assertEqual(a.commands, [])

    def test_decimal_durations(self):
        for text in ("forward 0.5 seconds",
                     "drive forward for 0.5 seconds",
                     "drive forward for 2.5 seconds"):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.label, "drive.forward")
        self.assertAlmostEqual(classify("forward 0.5 seconds").duration, 0.5)
        self.assertAlmostEqual(
            classify("drive forward for 2.5 seconds").duration, 2.5)

    def test_stop_priority(self):
        for text in ("forward stop", "hey stop", "stop right now"):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.label, "drive.stop")
                self.assertTrue(a.commands)
        self.assertEqual(classify("stop now please forward").label,
                         "drive.estop")

    def test_speed_modifiers(self):
        a = classify("go forward slowly")
        self.assertEqual(a.commands[0],
                         {"action": "speed", "left": 25, "right": 25})
        a = classify("drive forward fast")
        self.assertEqual(a.commands[0]["left"], x.FAST_SPEED)

    def test_speed_standalone(self):
        self.assertEqual(classify("slow down").label, "drive.slow")
        self.assertEqual(classify("speed up").label, "drive.fast")


class ClassifyArm(unittest.TestCase):
    def test_claw_values_match_config(self):
        self.assertEqual(classify("grab").commands,
                         [{"action": "servo", "num": 4, "angle": 10}])
        self.assertEqual(classify("open the claw").commands,
                         [{"action": "servo", "num": 4, "angle": 130}])
        self.assertEqual(classify("drop it").commands,
                         [{"action": "servo", "num": 4, "angle": 130}])

    def test_arm_moves(self):
        self.assertEqual(classify("arm up").label, "arm.up")
        self.assertEqual(classify("lower the arm").label, "arm.down")
        self.assertEqual(classify("reach out").label, "arm.reach")
        self.assertEqual(classify("arm left").label, "arm.left")
        self.assertEqual(classify("twist the wrist").label, "arm.wrist_spin")

    def test_gestures(self):
        self.assertEqual(classify("wave").label, "arm.wave")
        self.assertGreater(len(classify("wave").commands), 5)
        self.assertEqual(classify("hello").label, "arm.wave")
        self.assertEqual(classify("pet").label, "arm.pet")
        self.assertEqual(classify("stow the arm").label, "arm.home")


class ClassifyCameraLightsQuery(unittest.TestCase):
    def test_camera(self):
        self.assertEqual(classify("look left").label, "cam.left")
        self.assertEqual(classify("look up").label, "cam.up")
        self.assertEqual(classify("look forward").label, "cam.center")

    def test_lights(self):
        self.assertEqual(classify("lights on").label, "lights.on")
        self.assertEqual(classify("turn off the lights").label, "lights.off")

    def test_queries_never_move(self):
        for text in ("how far", "what do you see", "status", "how are you"):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.kind, "query")
                self.assertTrue(all(c["action"] in ("sensor_read", "status")
                                    for c in a.commands))


class ClassifyGoto(unittest.TestCase):
    def test_goto_extraction(self):
        for text, target in (("go to the shoe", "shoe"),
                             ("go get the shoe", "shoe"),
                             ("go get the shoe!", "shoe"),
                             ("get the shoe", "shoe"),
                             ("fetch the red bag", "red bag"),
                             ("go find the white box", "white box"),
                             ("go to the kitchen", "kitchen"),
                             ("go to shoe", "shoe")):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.kind, "goto")
                self.assertEqual(a.target, target)
                self.assertEqual(a.commands, [])

    def test_goto_safety(self):
        # Negated goto never routes anywhere.
        a = classify("don't go to the shoe")
        self.assertEqual(a.kind, "refused")
        self.assertEqual(a.commands, [])
        # Goto plus another action is ambiguous, never executed.
        a = classify("go to the shoe and wave")
        self.assertEqual(a.kind, "ambiguous")
        self.assertEqual(a.commands, [])
        # "go to the left" hits the drive phrase — ambiguous, not a target.
        a = classify("go to the left")
        self.assertEqual(a.kind, "ambiguous")
        self.assertEqual(a.commands, [])
        # Stop still wins over a goto clause.
        self.assertEqual(classify("go to the shoe stop").label,
                         "drive.stop")
        # Empty target has nothing to route to.
        a = classify("go to the")
        self.assertEqual(a.kind, "unknown")
        self.assertEqual(a.commands, [])

    def test_goto_synonyms(self):
        # Speech-friendly ways to say "go look at the thing": all must
        # route to the same no-motion goto with the target extracted.
        for text, target in (
                ("investigate the shoe", "shoe"),
                ("check out the shoe", "shoe"),
                ("check out that red bag", "red bag"),
                ("examine the white box", "white box"),
                ("inspect the shoe", "shoe"),
                ("look at the shoe", "shoe"),
                ("take a look at the shoe", "shoe"),
                ("have a look at the shoe", "shoe"),
                ("go look at the shoe", "shoe"),
                ("go investigate the shoe", "shoe")):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.kind, "goto")
                self.assertEqual(a.target, target)
                self.assertEqual(a.commands, [])

    def test_goto_synonym_safety(self):
        # "check" alone is NOT a goto verb: the sensors query survives.
        self.assertEqual(classify("check the sensors").kind, "query")
        # Negated synonym goto is refused, pronoun target is unknown.
        a = classify("don't investigate the shoe")
        self.assertEqual(a.kind, "refused")
        self.assertEqual(a.commands, [])
        a = classify("investigate it")
        self.assertEqual(a.kind, "unknown")
        self.assertEqual(a.commands, [])
        # "look at the left" still collides with the drive phrase.
        a = classify("look at the left")
        self.assertEqual(a.kind, "ambiguous")
        self.assertEqual(a.commands, [])

    def test_goto_run_sends_nothing(self):
        sent = []
        sender = lambda cmd: sent.append(cmd) or {"ok": True}
        t = x.run("go get the shoe", sender=sender, sleep=lambda s: None)
        self.assertEqual(sent, [])
        self.assertEqual(t["target"], "shoe")


class LongestMatch(unittest.TestCase):
    def test_overlaps_resolve_to_longer_phrase(self):
        # "kill" alone would e-stop; the longer phrase wins.
        self.assertEqual(classify("kill the lights").label, "lights.off")
        # "ahead"/"forward"/"straight" alone would drive.
        self.assertEqual(classify("look ahead").label, "cam.center")
        self.assertEqual(classify("arm forward").label, "arm.reach")
        self.assertEqual(classify("look straight").label, "cam.center")
        # "drop" alone opens the claw; "drop the arm" lowers the arm.
        self.assertEqual(classify("drop the arm").label, "arm.down")


class TankWire(unittest.TestCase):
    def test_generic_tank_auth_names(self):
        # Tank controls use generic auth, not the old chat-project names.
        self.assertEqual(x.DEFAULT_TOKEN, "change-me")
        with open(x.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('"X-Tank-Token"', src)
        self.assertNotIn("X-SignalBot-Token", src)
        self.assertNotIn("SIGNALBOT_TOKEN", src)

    def test_fast_speed_within_tank_cap(self):
        # Tank config caps autonomous speed at 40.
        self.assertLessEqual(x.FAST_SPEED, 40)
        a = classify("drive forward fast")
        self.assertLessEqual(a.commands[0]["left"], 40)


class Safety(unittest.TestCase):
    def test_negated_commands_refused(self):
        for text in ("don't move forward", "do not turn left",
                     "never wave", "don't stop",
                     "won't go forward", "not forward", "no forward"):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.kind, "refused")
                self.assertEqual(a.commands, [])

    def test_unknown_inputs(self):
        for text in ("make me a sandwich", "",
                     "   ", "blorpt"):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.kind, "unknown")
                self.assertEqual(a.commands, [])

    def test_ambiguous_inputs(self):
        for text in ("drive forward and wave", "left and right",
                     "turn left then grab"):
            with self.subTest(text=text):
                a = classify(text)
                self.assertEqual(a.kind, "ambiguous")
                self.assertEqual(a.commands, [])

    def test_never_raises_on_garbage(self):
        for text in (None, "", "!!!", "12345", "x" * 5000,
                     "don't", "for 3 seconds"):
            with self.subTest(text=text):
                a = classify(text)
                self.assertIn(a.kind, ("unknown", "refused", "ambiguous",
                                       "drive", "arm", "camera", "lights",
                                       "query", "speed", "stop", "estop"))


class TableIntegrity(unittest.TestCase):
    def test_every_phrase_hits_its_own_action(self):
        for phrase, aid in x.PHRASES:
            with self.subTest(phrase=phrase):
                self.assertEqual(classify(phrase).label,
                                 x.ACTIONS[aid].label)

    def test_every_action_is_shippable(self):
        for aid, spec in x.ACTIONS.items():
            with self.subTest(action=aid):
                a = x.Action(kind=spec.kind, label=spec.label,
                             commands=[dict(c) for c in spec.commands],
                             delays=list(spec.delays), duration=spec.duration)
                self.assertEqual(x.validate_commands(a), [])

    def test_every_phrase_output_is_shippable(self):
        for phrase, _ in x.PHRASES:
            with self.subTest(phrase=phrase):
                self.assertEqual(x.validate_commands(classify(phrase)), [])

    def test_servo_angles_within_config_limits(self):
        for phrase, _ in x.PHRASES:
            for cmd in classify(phrase).commands:
                if cmd.get("action") == "servo":
                    lo, hi = x.SERVO_LIMITS[cmd["num"]]
                    self.assertTrue(lo <= cmd["angle"] <= hi,
                                    f"{phrase}: servo {cmd}")


class RunTranscript(unittest.TestCase):
    def _fake(self):
        sent = []
        sleeps = []
        sender = lambda cmd: sent.append(cmd) or {"ok": True, "fake": True}
        return sent, sleeps, sender, sleeps.append

    def test_claim_release_ordering(self):
        sent, _, sender, sleep = self._fake()
        t = x.run("wave", sender=sender, sleep=sleep)
        self.assertEqual(sent[0], {"action": "claim"})
        self.assertEqual(sent[-1], {"action": "release"})
        self.assertEqual(len(t["responses"]), len(sent))

    def test_timed_drive_auto_stops(self):
        sent, sleeps, sender, sleep = self._fake()
        x.run("drive forward for 3 seconds", sender=sender, sleep=sleep)
        self.assertIn(3.0, sleeps)
        # release is last; auto-stop is the command before it.
        self.assertEqual(sent[-2], {"action": "move", "direction": "stop"})
        self.assertEqual(sent[-1], {"action": "release"})

    def test_estop_skips_claim(self):
        sent, _, sender, sleep = self._fake()
        x.run("stop now", sender=sender, sleep=sleep)
        self.assertEqual(sent, [{"action": "emergency_stop"}])

    def test_queries_skip_claim(self):
        sent, _, sender, sleep = self._fake()
        x.run("how far", sender=sender, sleep=sleep)
        self.assertEqual(sent, [{"action": "sensor_read"}])

    def test_no_motion_sends_nothing(self):
        for text in ("don't move", "blorpt", "forward and wave"):
            with self.subTest(text=text):
                sent, _, sender, sleep = self._fake()
                t = x.run(text, sender=sender, sleep=sleep)
                self.assertEqual(sent, [])
                self.assertEqual(t["sent"], [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
