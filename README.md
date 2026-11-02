# MITT

**Multimodal Interface for Teleoperation and Tracking.** Say what you want, and a real tank goes and gets it.

**Watch the demo:** https://youtu.be/jEXv6ofJLUQ

**Read the story:** [Build notes](docs/MITT_BUILD_NOTES.md), including what broke and what's next.

MITT is a XiaoR Geek tracked robot (Raspberry Pi 5, pan/tilt camera, arm) that takes a spoken or typed instruction such as *"go to the blue ball then go to the bottle"*, finds each target with **Meta SAM 3.1**, turns and drives to it, checks that it has arrived, and moves on to the next one. It runs on physical hardware, not in a simulator.

Built for the Meta AI Developer Hackathon (indie track), Oct 26 – Nov 4 2026. Every step, including the failures, is logged in [DEVLOG.md](DEVLOG.md). Old entries are kept as written, apart from redacted personal details, so they can contradict later ones.

## What it does

- **Phone remote**: dual-thumbstick driving, a drag-to-pose arm, live camera, telemetry, and voice or typed commands (`tank_phone/`).
- **Language → mission**: a fixed-phrase parser turns `go to / go get / find / fetch / check out / chase the X` into a vision goto. *"…then…"* chains up to three targets. Stop always wins (`tank_tools/`).
- **See → turn → drive → arrive** (`tank_vision/`):
  1. **Look**: camera frame → SAM 3.1 with the target words → the instance nearest the last sighting.
  2. **Tandem move** from one picture: the chassis spins toward the target's bearing *while* the neck swings back to centre, then drives forward.
  3. **Arrive** when the target is big in frame or runs off the bottom edge, after one confirm look that faces it with the camera aimed down.
  4. **Lose it?** Back up and look (it may be under the camera), then sweep the neck outward, then turn the chassis left 60°, right 120°, left 180°. If nothing turns up, it stops.

## Meta in the stack

- **SAM 3.1 via the Meta Model API** is the vision. Every look in the drive loop is a SAM call (`tank_vision/meta_sam.py`, using Meta's official parser).
- **Muse, Meta's coding agent**, built much of the stack, including recovering the XiaoR servo protocol at I2C `0x17` (`FF ch angle FF`) from the vendor's compiled module. See [`tank_tools/servo_0x17_protocol.md`](tank_tools/servo_0x17_protocol.md). `tank_phone/servo_ctl.py` drives the servos directly, with no vendor code.
- **Muse Spark**, served through Baseten, is wired in as the fallback when the parser doesn't know a phrase. It can only propose a sentence, and that sentence must still pass the parser (`tank_speech/`).
- **Llama 3.2** on the Pi was the starting point. It is not in the current drive path; the build notes explain why.

The stock XiaoR stack is fully replaced: the repo's own motor listener and bench-measured motor map (`tank_bench/`), the recovered servo protocol, and a small C MJPEG grabber (`tank_phone/qstream.c`).

## Live results

From the timestamped launcher log: launch to the final stop the motors acknowledged. ARRIVED is what the software reported.

| Date | Run | Time | Result |
|---|---|---|---|
| Oct 30 | "go to the cat", before the IPv4 fix | 10 m 52 s | ARRIVED, through two-minute stalls |
| Oct 30 | "go to the foot", after the fix | 67 s | Ran out of steps, no stalls |
| Oct 30 | "go to the blue ball" | 71 s | ARRIVED, stopped short of the ball |
| Oct 31 | Blue ball → mug | 67 s | Both ARRIVED, but the mug was short (led to the arrival check) |
| Oct 31 | Blue ball → mug | 140 s | Both ARRIVED, mug reached |
| Oct 31 | Blue ball → mug | 179 s | Both ARRIVED |
| Oct 31 | Bottle → cat | 171 s | Both ARRIVED |
| Oct 31 | Blue ball → bottle | 163 s | Both ARRIVED |
| Nov 1 | Blue ball → bottle (the run in the video) | 157 s | Both ARRIVED |

The log holds 14 chained attempts, and 6 ended with both targets ARRIVED while the code was changing underneath them. Of the last 7, 5 finished both targets. These are test runs in one room, not a controlled reliability trial.

## Safety

- Motors run through a token-gated listener on the Pi. Every move is capped at 3 s and 40% power, and the listener exits after an hour.
- A dropped connection, a bad line or an exit drives all pins low.
- Each drive is capped in steps. On any error the runner sends a stop.
- Stop wins. Unknown, negated or ambiguous language moves nothing, with one known exception: *"dance then go to the mug"* still goes to the mug.
- No keys or tokens in this repo. They come from the environment only.

## Layout

| Path | What |
|---|---|
| `tank_vision/` | SAM client, approach loop (`drive_run.py`), geometry (`centre.py`), launcher, offline YOLO11n + MobileSAM fallback |
| `tank_tools/` | parser (`xiaor_text_action.py`), keyboard driver, servo protocol notes |
| `tank_phone/` | phone web UI + Pi server, direct `0x17` servo driver, C MJPEG grabber |
| `tank_speech/` | speech hooks; the live path is the phone browser's speech recognition → parser |
| `tank_bench/` | motor listener, measured motor map, calibration scripts |
| `docs/` | build notes |

Tests: `python3 -m unittest discover -s <dir> -p 'test_*.py'` for each of `tank_vision`, `tank_tools`, `tank_phone`, `tank_speech`.

The tank's address and login are placeholders (`tank.local`, user `pi`). Set `TANK_HOST` and `TANK_TOKEN` for your own setup.

## Hardware and vendor files

The robot is a **XiaoR Geek** tank kit (Raspberry Pi 5 "V2" control board). XiaoR's stock software, including the compiled servo module `_XiaoRGEEK_SERVO_*.so`, is **proprietary and is not included in this repository**. It ships with the kit and its image. This project doesn't need it at runtime. Only the research tool `tank_tools/fake_smbus_trace.py`, which reproduces the reverse-engineering trace, expects you to supply your own copy. "XiaoR Geek" is the vendor's name; this project is not affiliated with them.

## Known limits

- Open-loop motion: short spins undershoot, and timing drifts with battery charge.
- Arrival is judged from the image, and some paths can report ARRIVED too early or count an unfinished run as success. The ultrasonic sensor is wired but silent.
- With two cats in the room, it hunts whichever one it sees first.
- The arm is manual only. The build notes have the full list under "Room to grow."

## Built with

Built by Adam with AI coding agents: Meta's Muse, Anthropic's Claude and OpenAI's Codex. The hardware tests were run in person on a living-room floor.
