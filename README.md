# multimodal-teleoperation

**Say what you want, and a real tank goes and gets it.**

A XiaoR Geek tracked robot (Raspberry Pi 5, pan/tilt camera, arm) that takes
a spoken or typed instruction such as *"go to the blue ball then go to the
mug"* or *"chase the cat"*, finds each target with **Meta SAM 3.1**, turns
and drives to it, confirms it has arrived, and moves on to the next one.
It runs on physical hardware, not in a simulator.

Built for the Meta AI Developer Hackathon (indie track), Oct 26 – Nov 4 2026.
Every step, including the failures, is logged in [DEVLOG.md](DEVLOG.md).

## What it does

- **Phone remote**: dual-thumbstick driving, a drag-to-pose arm, live
  camera, telemetry, and voice or typed commands (`tank_phone/`).
- **Language → mission**: a fixed-phrase parser turns `go to / go get /
  find / fetch / check out / chase the X` into a vision goto. *"…then
  …"* chains up to three targets. Negated, ambiguous or unknown input
  never moves the hardware, and stop always wins (`tank_tools/`).
- **See → turn → drive → arrive** (`tank_vision/`):
  1. **Look**: camera frame → SAM 3.1 with the target words → the
     instance nearest the last sighting.
  2. **Tandem move** from one picture: the chassis spins toward the
     target's bearing *while* the neck swings back to centre, then drives
     forward. (Yes, the head turns like the Exorcist.)
  3. **Arrive** when the target is big in frame or runs off the bottom
     edge, but only after one confirm look that faces it squarely with
     the camera aimed down.
  4. **Lose it?** A recovery ladder: back up and look (it may be under
     the camera), then an outward alternating sweep of the neck, then
     alternating chassis turns (left 60°, right 120°, left 180°). If
     nothing turns up, it stops.

## Meta in the stack

- **SAM 3.1 via the Meta Model API** is the vision. Text prompt plus
  image in, masks and boxes out (`tank_vision/meta_sam.py`, with the
  official parser). Every look in the drive loop is a SAM call.
- **Muse, Meta's coding agent**, built much of the stack. That includes
  reverse-engineering the stock servo controller: the XiaoR servo MCU
  protocol at I2C `0x17` (`FF ch angle FF`) was recovered from the
  vendor's compiled module and documented in
  [`tank_tools/servo_0x17_protocol.md`](tank_tools/servo_0x17_protocol.md).
  `tank_phone/servo_ctl.py` now drives the servos directly, with no
  vendor code.

**The whole robot runs on this repo's own code. The stock XiaoR stack is
fully replaced:**
- **Motors**: the repo's own GPIO listener and a motor map measured on
  the bench (`tank_bench/`).
- **Servos**: the recovered `0x17` protocol.
- **Camera**: a small C MJPEG grabber (`tank_phone/qstream.c`).

## Live results (from DEVLOG, physical runs)

| When | Run | Result |
|---|---|---|
| Oct 27 | "go get the shoe" | first end-to-end SAM approach, ARRIVED |
| Oct 29 | full mission to a Croc | scan → lock-on → 7 steps, ARRIVED in 91 s |
| Oct 30 | cat run (before fixes) | 10 min 52 s: network stalls and false recoveries |
| Oct 30 | foot, after IPv4 fix | 5 steps in 68 s |
| Oct 30 | blue ball | ARRIVED in 71 s, including a 29 s cold search |
| Oct 31 | **blue ball → mug (chained)** | **both ARRIVED in 67 s** |
| Oct 31 | chase the cat | followed the cat; when she moved, it searched |
| Oct 31 | object → new object chase | 38 s (timed by Adam) |

The Oct 30–31 speedups came from finding the actual causes. Briefly:
- IPv6 connects to the API that never answered (now IPv4, with a short
  connect timeout).
- A pan-servo scale measured at 0.85°/unit, not the assumed 1.2.
- A recovery check that ran even when the target had been found.
- A scan that looked at every spot about 2.5 times.

Each fix has a test and a commit.

## Safety

- Motors run through a token-gated listener on the Pi. Every move is
  bounded in time, and a dropped connection stops the motors.
- Each drive is capped in steps. On any error the runner sends a stop
  in its `finally`.
- Unknown, negated or ambiguous language never moves anything.
- No keys or tokens in this repo. Keys come from the environment only.

## Layout

| Path | What |
|---|---|
| `tank_vision/` | SAM client, approach loop (`drive_run.py`), geometry (`centre.py`), launcher, offline YOLO11n + MobileSAM fallback |
| `tank_tools/` | parser (`xiaor_text_action.py`), keyboard driver, servo protocol notes |
| `tank_phone/` | phone web UI + Pi server, direct `0x17` servo driver, C MJPEG grabber |
| `tank_speech/` | speech hooks (the live path is the phone browser's speech recognition → parser) |
| `tank_bench/` | motor listener, measured motor map, calibration scripts |
| `docs/WORKSPACE.md` | the author's agent/sandbox workspace notes |

Tests: `python3 -m unittest discover -s <dir> -p 'test_*.py'` for each of
`tank_vision`, `tank_tools`, `tank_phone`, `tank_speech`. All four suites
pass (Oct 31).

## Hardware and vendor files

The robot is a **XiaoR Geek** tank kit (Raspberry Pi 5 "V2" control board).
XiaoR's stock software, including the compiled servo module
`_XiaoRGEEK_SERVO_*.so` and its companion files, is **proprietary and is
not included in this repository**. It ships with the kit and its image.
This project does not need it at runtime: the servos are driven through
the documented `0x17` protocol. Only the research tool
`tank_tools/fake_smbus_trace.py`, which reproduces the reverse-engineering
trace, expects you to supply your own copy of the vendor files.
`IMPORT_MANIFEST.json` records their hashes for reference. "XiaoR Geek"
is the vendor's name; this project is not affiliated with them.

## Status and known limits

- Open-loop motion: short spins undershoot (motor spin-up), and timing
  drifts with battery charge.
- Arrival is judged from the image. The ultrasonic sensor is wired but
  silent, and tilt degrees per unit are not yet measured.
- With two cats in the room, it hunts whichever one it sees first.

## Built with

Built by Adam with AI coding agents: Meta's Muse, OpenAI's Codex and
Anthropic's Claude. The hardware tests were run in person on a living-room
floor. [HANDOFF.md](HANDOFF.md) has the current engineering state.
