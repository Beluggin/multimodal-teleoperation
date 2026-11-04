# MITT

**Multimodal Interface for Teleoperation and Tracking.** Say what you want, and a real tank goes and gets it.

**Push the Frontier:** Meta's models get a real robot out of the simulator, turning a spoken sentence into a physical search, drive and arrival check.

**Watch the demo:** https://youtu.be/jEXv6ofJLUQ

**Read the story:** [Build notes](docs/MITT_BUILD_NOTES.md), including what broke and what's next.

**See the numbers:** [Run report](https://beluggin.github.io/multimodal-teleoperation/) (recorded runs, not a live tank) and [evaluation](eval/README.md).

## Prior work

These came from before the hackathon's Oct 26 kickoff. Everything else in this repo was built during the event.

- **Motor driver, bench tools and measured motor map** (`src/tank_bench/`, except `drive_step.py`). The motor listener wasn't changed during the hackathon.
- **Base text-command parser and its tests** (`src/tank_tools/xiaor_text_action.py`). Go-to phrases, chaining and the stricter whole-sentence rule were added during the event.
- **Keyboard driver** (`src/tank_tools/tank_control.py`).
- **Llama 3.2 on the Pi.** It was installed and tried before kickoff. The raw-mode code, test lists and both fine-tunes in this repo came during the event.

MITT is a XiaoR Geek tracked robot (Raspberry Pi 5, pan/tilt camera, arm) that takes a spoken or typed instruction such as *"go to the blue ball then go to the bottle"*, finds each target with **Meta SAM 3.1**, turns and drives to it, checks that it has arrived, and moves on to the next one. It runs on physical hardware, not in a simulator.

Built for the Meta AI Developer Hackathon (indie track), Oct 26 – Nov 4 2026. Every step, including the failures, is logged in [DEVLOG.md](DEVLOG.md). Old entries are kept as written, apart from redacted personal details, so they can contradict later ones.

## Quickstart

No robot or API key needed:

```
git clone https://github.com/Beluggin/multimodal-teleoperation.git
cd multimodal-teleoperation
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
make test    # all test suites, using fakes for the hardware and network
make eval    # scores the language parser
python3 src/tank_phone/server.py --port 8123 --demo    # the phone page at localhost:8123, no robot
```

Or with Docker, which runs the same things:

```
docker build -t mitt .
docker run --rm mitt make test
docker run --rm mitt make eval
docker run --rm -p 127.0.0.1:8123:8123 mitt    # the phone page at localhost:8123
```

The container can't reach a robot, so it's for trying the software. Motors, servos and the camera need the Pi, using the steps below.

With `--demo`, which the container uses by default, the language parser is real. The sticks and Launch drive only show "Simulated, hardware not available". There's no fake mission, camera or SAM call, so to see those working, watch [the demo](https://youtu.be/jEXv6ofJLUQ).

With a XiaoR tank, run these only with someone watching it:

1. `cp .env.example .env` and fill it in. `MODEL_API_KEY` is your Meta Model API key.
2. Add a `tank-lan` host to `~/.ssh/config` pointing at your Pi.
3. Pick a token and save it to `/tmp/mitt/bench_token`, on the Pi and on the desktop.
4. Copy `src/tank_bench/motor_listen.py` to the Pi and start it: `BENCH_TOKEN=<token> python3 -u motor_listen.py`. It shuts itself off after an hour, so restart it for each session.
5. Deploy the phone server. The commands are at the top of `src/tank_phone/server.py`.
6. Run a mission from the desktop:

```
set -a; . ./.env; set +a
cd src
python3 -m tank_vision.drive_run --text "go to the blue ball" --tandem
```

Raw mode needs [Ollama](https://ollama.com) and `ollama pull llama3.2:3b`. Then run `python3 src/tank_tools/tank_control.py --raw`, press `t`, and type an instruction. Stop skips the model, but Llama can misread anything else, including negated commands. Every move stays capped at 3 s.

To use the fine-tuned model, get the GGUF and Modelfile from [Hugging Face](https://huggingface.co/Beluggin/Llama-3.2-3B-MITT-Tank), run `ollama create llama-3.2-3b-mitt-tank -f Modelfile`, then set `TANK_LLAMA_MODEL=llama-3.2-3b-mitt-tank` and `TANK_LLAMA_PROMPT=tuned`.

## What it does

- **Phone remote**: dual-thumbstick driving, a drag-to-pose arm, live camera, telemetry, and voice or typed commands (`src/tank_phone/`).
- **Language → mission**: a fixed-phrase parser turns `go to / go get / find / fetch / check out / chase the X` into a vision goto. *"…then…"* chains up to three targets. Stop always wins (`src/tank_tools/`).
- **See → turn → drive → arrive** (`src/tank_vision/`):
  1. **Look**: camera frame → SAM 3.1 with the target words → the instance nearest the last sighting.
  2. **Tandem move** from one picture: the chassis spins toward the target's bearing *while* the neck swings back to centre, then drives forward.
  3. **Arrive** when the target is big in frame or runs off the bottom edge, after one confirm look that faces it with the camera aimed down.
  4. **Lose it?** Back up and look (it may be under the camera), then sweep the neck outward, then turn the chassis left 60°, right 120°, left 180°. If nothing turns up, it stops.

## Meta in the stack

- **SAM 3.1 via the Meta Model API** is the vision. Every look in the drive loop is a SAM call (`src/tank_vision/meta_sam.py`, using Meta's official parser).
- **Muse Wonder** was the main builder from day 2 until Friday night, when the hackathon credits ran low. It ran the servo calibration and made the phone GUI.
- **Muse, Meta's coding agent**, built much of the stack, including recovering the XiaoR servo protocol at I2C `0x17` (`FF ch angle FF`) from the vendor's compiled module. See [`src/tank_tools/servo_0x17_protocol.md`](src/tank_tools/servo_0x17_protocol.md). `src/tank_phone/servo_ctl.py` drives the servos directly, with no vendor code.
- **Muse Spark Open** (`muse-spark-open-1026`), served through Baseten, is wired in as the fallback when the parser doesn't know a phrase. It can only propose a sentence, and that sentence must still pass the parser (`src/tank_speech/`).
- **Llama 3.2** on the Pi was the starting point. It is not in the main drive path, and the build notes explain why. It's still runnable as an optional raw mode, words to moves with no parser, so the baseline can be compared with the full pipeline (`src/tank_tools/llama_raw.py`, [results](eval/README.md)).
- **[Llama-3.2-3B-MITT-Tank](https://huggingface.co/Beluggin/Llama-3.2-3B-MITT-Tank)** is a LoRA fine-tune of Llama 3.2 3B for raw mode, published on Hugging Face. It scored 49/50 on new commands against stock's 45/50 on the same Pi, and mainly learned when not to move ([results](eval/README.md), [training](train/README.md)).
- **[Muse-Glimmer-30B-MITT-Tank](https://huggingface.co/Beluggin/Muse-Glimmer-30B-MITT-Tank)** is a LoRA fine-tune of Muse Glimmer 30B on the same data, trained on a rented GPU. It scored 50/50 and 18/18 there, but stock Glimmer's lower score has a big caveat ([results](eval/README.md)). It has never run on the tank, because it's far too big for the Pi, so the tank keeps the Llama tune.

The stock XiaoR stack is fully replaced: the repo's own motor listener and bench-measured motor map (`src/tank_bench/`), the recovered servo protocol, and a small C MJPEG grabber (`src/tank_phone/qstream.c`).

## Live results

From the timestamped launcher log, except Nov 3, which is from the run's output: launch to the final stop the motors acknowledged. ARRIVED is what the software reported.

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
| Nov 3 | Blue ball, after the parser fix | 209 s | Drove to the ball, then lost it and stopped itself. No ARRIVED. Cause not found yet |

More measurements are in [eval/README.md](eval/README.md). The log holds 14 chained attempts, and 6 ended with both targets ARRIVED while the code was changing underneath them. Of the last 7, 5 finished both targets. These are test runs in one room, not a controlled reliability trial.

## Safety

- Motors run through a token-gated listener on the Pi. Every move is capped at 3 s and 40% power, and the listener exits after an hour.
- A dropped connection, a bad line or an exit drives all pins low.
- Each drive is capped in steps. On any error the runner sends a stop.
- Stop wins. Anything that moves has to be the whole sentence: a command plus harmless words. Unknown, negated or ambiguous language should move nothing, but that comes from a word list, so it isn't a guarantee ([evaluation](eval/README.md)).
- No keys or tokens in this repo. They come from the environment only.

## Layout

| Path | What |
|---|---|
| `src/tank_vision/` | SAM client, approach loop (`drive_run.py`), geometry (`centre.py`), launcher, offline YOLO11n + MobileSAM fallback |
| `src/tank_tools/` | parser (`xiaor_text_action.py`), keyboard driver, servo protocol notes |
| `src/tank_phone/` | phone web UI + Pi server, direct `0x17` servo driver, C MJPEG grabber |
| `src/tank_speech/` | speech hooks; the live path is the phone browser's speech recognition → parser |
| `src/tank_bench/` | motor listener, measured motor map, calibration scripts |
| `tests/` | test suites, one folder per module |
| `eval/` | language comparison and measured results |
| `docs/` | build notes and the run report page |

Tests: `make test`.

The tank's address and login are placeholders (`tank.local`, user `pi`). Set `TANK_HOST` and `TANK_TOKEN` for your own setup.

## Hardware and vendor files

The robot is a **XiaoR Geek** tank kit (Raspberry Pi 5 "V2" control board). XiaoR's stock software, including the compiled servo module `_XiaoRGEEK_SERVO_*.so`, is **proprietary and is not included in this repository**. It ships with the kit and its image. This project doesn't need it at runtime. Only the research tool `src/tank_tools/fake_smbus_trace.py`, which reproduces the reverse-engineering trace, expects you to supply your own copy. "XiaoR Geek" is the vendor's name; this project is not affiliated with them.

## Known limits

- Open-loop motion: short spins undershoot, and timing drifts with battery charge.
- Arrival is judged from the image, and some paths can report ARRIVED too early or count an unfinished run as success. The ultrasonic sensor is wired but silent.
- With two cats in the room, it hunts whichever one it sees first.
- The arm is manual only. The build notes have the full list under "Room to grow."

## Built with

**Built with Llama.** Built by Adam with AI coding agents: Meta's Muse, Anthropic's Claude and OpenAI's Codex. The hardware tests were run in person on a living-room floor.
