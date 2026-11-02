# MITT: Build Notes

**Multimodal Interface for Teleoperation and Tracking**
Meta AI Developer Hackathon, indie track. Built Oct 26 – Nov 4, 2026, by Adam.

**Watch the video first:** https://youtu.be/jEXv6ofJLUQ

MITT is a XiaoR Geek tracked robot with a camera and an arm. You tell it what you want, by voice or by typing, something like "go to the blue ball then go to the bottle." It finds each target with Meta's SAM 3.1, turns, drives over, checks that it got there, and moves on to the next one. You can also take over and drive it by hand from your phone.

It runs on real hardware on my living-room floor, with two cats who did not agree to any of this.

## Where I started

Going into the hackathon I had text-only teleoperation: Llama 3.2 3B (Q4_K_M) running on a 4 GB Raspberry Pi 5, a Python CLI over SSH from my desktop, on both Wi-Fi and Tailscale. It had no vision. Only the motors were worked out, and the servos were left for Muse to decompile once the event opened. The left motor is stronger than the right, so the tank lists to the right unless it's trimmed.

The opening demo was the tank driving an octagon and reversing back to about where it started, with no sensors and no mapping. Manual control fired 0.6 s per key press, and typing "t" got you multi-step instructions.

**Baseline benchmarks: Llama 3.2 3B Q4_K_M, Raspberry Pi 5 (4 GB)**

| Metric | Result | Notes |
|---|---|---|
| Command accuracy | 11/18 (61.1%) | Mostly extra actions; 1B scored 6/18 |
| Llama parse time | ~2.1 s | 5.1 tok/s; 11.7 s cold load |
| Network → motor pins | 55–65 ms | 127–168 ms with Wi-Fi power saving |
| Command round trip | 4–18 ms | Max 34 ms; 95 commands, 5 runs |
| Motor spin-up | ~0.5 s | At 40% duty; mechanical lag |
| Motor power cap | 30–40% | 30% for floor tests |
| Straight-line trim | +17% right | Compensates for stronger left motor |
| Spin rate (30%) | 101–135°/s | ~35% faster when charged |
| Octagon: low battery | 2.5 cm; 15° CCW | Spin times: 1.11 / 0.40 / 0.61 s |
| Octagon: charged, original | Failed | First turn ~150°; same code |
| Octagon: charged, retuned | 5 cm; 10° CCW | All 8 sides; 0.80 / 0.35 / 0.46 s |
| Heading variation | ±10° | Open-loop driving, no sensors |

Octagon results were measured by hand on the floor, not from telemetry. They're also the whole argument for vision: the same code on a charged battery fell apart on the first turn.

## What I set out to do, and how it went

| Goal | Where it landed |
|---|---|
| 1. Servo map for object manipulation with the arm | **Half.** The servo protocol is decompiled and proven on hardware, and every arm joint moves from the phone. The arm is manual only. It doesn't pick anything up on its own yet. |
| 2. Object detection with YOLO and SAM | **Done, with a change of plan.** SAM 3.1 does the seeing on every look in the drive loop. YOLO and MobileSAM ended up as an offline fallback. |
| 3. Phone GUI for full manual control | **Done.** Two thumbsticks, drag-to-pose arm, live camera, telemetry, voice and typed commands. |
| 4. Duplex speech | **One way.** You can talk to it through the phone. It can't talk back yet. |

## Llama, honestly

Llama was the starting point, and it isn't in the final drive path. Getting 11/18 at about 2 seconds a command was a fair baseline for a Pi, and the misses taught me something: "emergency stop right now" came back as stop *and* turn right. Stop can't be left to a model's judgement.

So a fixed-phrase parser took over the front end, with stop always winning and anything unknown, negated or ambiguous moving nothing. Once the job became "go to that thing," the hard part was seeing, and that's SAM's.

There are still plenty of Meta fingerprints on this:

- **SAM 3.1** through the Meta Model API is the vision. Every look in the drive loop is a SAM call.
- **Muse** built most of the stack through the first days, including the phone GUI, the vision loop and the speech hooks.
- **Muse decompiled the vendor's compiled servo module.** The servo controller at I2C `0x17` was a black box, and Muse recovered the protocol (`FF channel angle FF`) from the `.so`, first statically with capstone and pyelftools, then with a fake-smbus trace on the Pi. The servos now run on our own driver with no vendor code.
- **Muse Spark** is wired in as the fallback when the parser doesn't know a phrase. It can only suggest a sentence, and that sentence still has to pass the parser.

## The build

**Day 1 (Oct 26).** Tailscale running through my phone hotspot, so the robot can leave the house network. Muse started on the servo decompile.

**Day 2 (Oct 27).** The big one. Camera live on the phone, on a pretty rough first page with touch grid mapping. Servos mapped, after a long silent stretch that turned out to need a power cycle \*facepalm\*. Servos calibrated, wonky spots flagged, home position set. SAM 3.1 recognizing objects through the Meta API. By the end of the day: "go get the shoe," start to finish, for the first time.

**Day 3 (Oct 28).** Parser glue for meaning, so "check out the shoe" instead of "go forward x seconds." A proper phone GUI with thumbsticks and an arm you drag around. Tried the ultrasonic as a distance stop, and it went silent.

**Day 4 (Oct 29).** Speech with simple instructions through the phone mic. Launching a drive from the phone. The wide scan, so a target doesn't have to start in frame. First full mission: scan, lock on, drive, arrive at a Croc. A Whisper relay also got built for paid duplex speech, but it was never deployed.

**Days 5–7 (Oct 30 – Nov 1).** This is where the plan stopped and vibe testing took over, including a Friday night into Saturday morning sprint to get to MVP. Put something on the floor, say go, watch what it does, say what I saw. My eyes outranked the logs, and the logs got corrected more than once. Claude took over the main debugging at the IPv6 fix on Oct 30, which was the turning point, and Codex did the reviews and red-teaming. Chained missions, the recovery ladder and arrival checks all came out of this stretch. Then I made the video.

## What broke

Most of the project was this part. Each one of these looked like something else first.

- **The silent servos.** Frames were being acknowledged and nothing moved. We suspected the frame, the shim and the power rail. A cold power cycle fixed it.
- **The exorcist.** The camera head shook violently. It wasn't the loop or the battery, it was the weight of the cable bundle dragging on the tilt servo. I relieved the strain and it stopped.
- **Swapped axes.** Pan and tilt were labelled backwards, quietly poisoning every centering attempt until I caught it.
- **The twitch.** Drive commands died within milliseconds, because the safety listener stops the motors on disconnect and the client was hanging up right after sending. Good safety, bad client.
- **The ping-pong.** The tank spun left, right, left, right and never drove. The camera has to recalibrate after every move or it just loops forever.
- **"Shoe."** SAM wouldn't call my Croc a shoe. "Sandal" worked. Wording, framing and light all matter.
- **The fast loop.** A local tracker looked great on the desk, then chased a shoe pile as soon as the motors were involved. I parked it.
- **The narrow lens.** The tank kept declaring arrival from across the room. The camera was assumed to be 60° wide. We measured it using a helper's feet, and it's 33°.
- **The box.** "Arrived" meant the target filled a quarter of the frame. A big box does that from across the room, and a small mug barely does it at all.
- **IPv6.** The one that changed everything. Looks would hang for two minutes for no visible reason. 7 of 30 IPv6 connections to the API never answered, against 0 of 30 on IPv4, and each one waited out a two-minute timeout. Forcing IPv4 made it a different robot.
- **The false "lost."** Every step logged a lost target and ran a pointless search. Saving the "lost" frames showed SAM had found the target every time. The recovery check never asked whether the look succeeded.
- **The neck.** The pan servo was assumed to be 1.2° per unit and measured 0.85°, so every turn overshot.
- **Wrong way.** The search only ever turned left, so with a mug on the right it went the other way and found a cat. It now searches outward on both sides. My framing for the video was "tank eats cats."
- **The pushed ball.** It read a sliver of ball at the bottom of the frame as far away, and drove into it. A box running off the bottom edge now counts as arrived.
- **The mug.** It claimed arrival short of the mug, looking with its neck turned instead of facing it. It now squares up and looks down before it believes itself.

## How it works

1. **Listen.** Voice or typed text goes to the parser. "Go to," "go get," "find," "fetch," "check out" and "chase" all become missions, and "then" chains up to three.
2. **Look.** A camera frame and the target words go to SAM 3.1, which returns masks and boxes. It keeps the instance nearest the last sighting.
3. **Turn and drive.** From one picture, the chassis spins toward the target while the neck swings back to center, then it drives forward. Yes, the head turns like the Exorcist.
4. **Arrive.** The target is big in frame or running off the bottom edge, confirmed by one more look, facing it, camera aimed down.
5. **Lost it?** Back up and look, because it may be under the camera. Then sweep the neck outward, then turn the chassis left 60°, right 120°, left 180°. If nothing turns up, it stops.

The stock XiaoR stack is fully replaced: our own motor listener, our own servo driver, and a small C camera grabber.

### The Tailscale pipeline

Tailscale is what lets the tank leave the house. The Pi, my desktop and my phone sit on one private tailnet, so they can find each other from any network with nothing opened to the public internet. It was working over my phone's hotspot on Day 1, and the first time the camera feed showed up on my phone, it came through the tailnet.

That fits how the build is split. The Pi runs the motors, servos, camera and phone page. The desktop runs the drive loop and calls SAM. The phone is the remote. In the bench test, the network round trip was about 8 ms over both Tailscale and plain Wi-Fi, so the tunnel costs basically nothing. At home the drive loop goes over the LAN, because it's sitting right there. The network isn't what you wait on anyway. The look cycle and the motors are.

## Live results

Every number here comes from the timestamped launcher log, measured from launch to the final stop the motors acknowledged. "ARRIVED" is what the software reported. Where what I saw on the floor was different, it says so.

| Date | Run | Time | Result |
|---|---|---|---|
| Oct 30 | "go to the cat," before the IPv4 fix | 10 m 52 s | ARRIVED, through two-minute stalls |
| Oct 30 | "go to the foot," after the fix | 67 s | Ran out of steps, no stalls |
| Oct 30 | "go to The Mug" | 93 s | Ran out of steps, right at the mug |
| Oct 30 | "go to the blue ball" | 71 s | ARRIVED, stopped short of the ball |
| Oct 31 | Blue ball → mug | 67 s | Both ARRIVED, but the mug was short. This led to the arrival check. |
| Oct 31 | Blue ball → mug | 140 s | Both ARRIVED, and I confirmed it reached the mug |
| Oct 31 | Blue ball → mug | 179 s | Both ARRIVED |
| Oct 31 | Bottle → cat | 171 s | Both ARRIVED |
| Oct 31 | Blue ball → bottle | 163 s | Both ARRIVED |
| Nov 1 | Blue ball → bottle, **the run in the video** | 157 s | Both ARRIVED |

**The honest denominator:** the log holds 14 chained attempts. Six ended with both targets ARRIVED, and the code changed underneath them the whole time. One attempt never moved because the motor listener's hour had expired. Of the last seven, once the search and arrival fixes were in, five finished both targets, one couldn't find the ball, and one has no result in the log. These are test runs in one room, not a controlled reliability trial.

The chain in the video spends most of its time searching. Tracked steps are the quick part, and finding a target that isn't in frame is the slow part.

## Safety

- Motors run through a token-gated listener on the Pi. Every move is capped at 3 seconds and 40% power, and the listener shuts itself off after an hour.
- A dropped connection, a bad line or an exit drives all the pins low.
- Stop always wins. Unknown, negated or ambiguous language moves nothing, with one known exception: "dance then go to the mug" still goes to the mug.
- If the target can't be found, it stops. On any error, the runner sends a stop.
- The token never goes to the phone, and no keys live in the repo.

The offline test suites total 219 tests (1 skipped), all passing on Nov 2. They cover the logic, and they don't prove it works on a floor. That's what the runs are for.

## Room to grow

Things I didn't get to yet, roughly in the order I'd want them:

- **Using the arm.** The protocol's solved and the arm moves. Autonomous pick-up was the original goal number one, and it's still the next big step.
- **Talking back.** Real duplex speech. The Whisper relay is built and tested against fakes, but it isn't deployed, and there's no spoken reply yet.
- **Knowing it really arrived.** Arrival is judged from the image, and the size of the object still affects it. Reviews also found paths that can report ARRIVED too early, or count an unfinished run as success. It needs a signal that doesn't care about size, and a working ultrasonic sensor would help.
- **Closed-loop heading.** It's still open-loop timing, and it drifts with battery charge. An IMU or a camera fiducial first, then SLAM, which I deliberately parked until after the hackathon.
- **Short spins.** Spin-up eats short turns, so a kick-start would save a lot of search time.
- **Speed between looks.** A local tracker between SAM calls, one that survives the motors this time.
- **Which cat.** With two matches in the room it hunts whichever it sees first. I started on tap-to-select from the phone for this, but it isn't finished and it isn't in this repo yet.
- **Language.** "Shoe" should work as well as "sandal." A small Llama expanding the prompt is a natural way back in for it.
- **Proper repeatability trials.** Fixed layout, every attempt recorded, missing and duplicate targets included.
- **Housekeeping.** Auto-switching between home Wi-Fi and the hotspot, and a token for `tank_drive.py`.

## Built with

Built by me with AI coding agents: Meta's Muse, Anthropic's Claude and OpenAI's Codex. The hardware tests were in person, on the floor. Every step, including the failures, is in [DEVLOG.md](../DEVLOG.md).
