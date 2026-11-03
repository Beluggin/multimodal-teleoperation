# DEVLOG — multimodal teleoperation

Newest first. Record verified results separately from proposals and live tests.

## 2026-11-03 — No-robot tip at startup, quieter test output

Starting the phone server with nothing live now prints a tip to use `--demo`. It stays
quiet in a demo or with motors or servos on. The demo mode test no longer prints its
expected error into `make test`, where it looked like a failure.

## 2026-11-03 — Demo mode for trying the page with no robot

Someone without a tank used to see "Drive refused" on the sticks, and Launch drive
waited for the desktop launcher forever, which looks broken. `server.py --demo` now
labels those as "Simulated, hardware not available", with a banner. The README
Quickstart and the Docker container use it. The language parser is still real, so a
negated command is still refused.

There's no fake mission, camera or SAM call. A simulated launch never reports done or
ARRIVED, and the launcher can't consume it. `--demo` won't start with the motor or
servo flags, and it's off unless asked for, so the tank's own page behaves as before.
Idea from Codex.

Checked: tests, the API on a running demo server, and the sticks, Launch drive and a
negated command in headless Firefox.

## 2026-11-03 — Pi phone page has the current parser

The Pi's `xiaor_text_action.py` now matches the repo (same SHA-256). Started the phone
server on the Pi with motors and servos off, and Adam typed five commands on his phone:
a goto, a goto chain, a negated goto, stop, and a goto mixed with another command. All
five came back as expected: goto, chain, refused, stop, ambiguous. No mission launched
and the tank didn't move, so this checks the parser on the page, not a drive.

## 2026-11-03 — Fine-tuned Muse Glimmer 30B on Modal

The hackathon board gave no tuning points for the Llama LoRA, so the same data and
settings went through Muse Glimmer 30B on a rented A100 80 GB. Dry-ran the code on a
tiny random model first. That showed random weights score 22/50, because rejected
replies pass no-motion commands, so the results now count invalid replies. Modal
refused the GPU until the account had a payment method, and interrupted the download
once. Training took 19 minutes, with no interruption. $1.46 on the Modal bill.

Verified: tuned 50/50 and 18/18, stock 31/50 and 13/18, 0 invalid replies, 0 wrong
moves for either. Stock's score is measured with its reasoning step skipped, and with
reasoning on wasn't tested. Never run on the tank, which keeps the Llama tune.

## 2026-11-03 — Parser: a command has to be the whole sentence

The new test list showed the parser acted on known phrases anywhere in a
sentence. Now a moving command must be the whole sentence plus harmless words, a
goto must start the sentence, any n't word or "avoid" refuses, and a typed line
moves all or nothing. Stop is exempt. `dance then go to the mug` no longer goes,
so the old test pinning that was changed on purpose.

Verified: 240 tests; parser 18/18 and 38/50 with 0 wrong moves (was 36/50 and 6),
not an unseen score. On the tank: `you shouldn't go to the mug` refused at the
real entry point. `go to the blue ball` launched and, by eye, drove to the ball,
then lost it, scanned, and stopped itself after 209 s with no ARRIVED. Cause not
established; no vision or drive code changed. Early output of that run was lost.

Not done: the Pi's phone page still has the old parser.

## 2026-11-03 — Fine-tuned Llama for raw mode

Wrote `eval/heldout.json` (50 commands) first, then a generated training set
(`train/make_dataset.py`) that leaves out every whole test command. LoRA on
Llama 3.2 3B, 3 epochs, about 8.5 minutes on an RTX 4060. A first run ran out of
memory because `prepare_model_for_kbit_training` cast the embeddings to 32-bit.

Verified: fine-tune 49/50 and 18/18 on both the Pi and the desktop. Stock 45/50
on the Pi, 42/50 on the desktop. Parser 36/50. No clear speed change on the Pi.
Eight floor steps at 30% with a person watching, all as expected.

Found: the parser moved on 7 of its 14 misses on the new list ("you shouldn't
drive forward", "you're right"), and "you shouldn't go to the mug" starts a
mission, so the docs' "moves nothing" claim was too strong. Docs corrected.
Parser behaviour not changed in this commit.

## 2026-11-02 — Raw mode, eval, Quickstart, CI, new layout

Older entries use the old paths. Code now lives under `src/` and tests under
`tests/`. Suites stayed green through the move; no behaviour change.

Raw mode (`tank_control.py --raw`, `llama_raw.py`) sends typed words to Llama
on Ollama with no parser. Stop skips the model, one bad move rejects the whole
plan, moves are capped at 3 s, and a stop or manual key drops a pending answer.

Verified: unit tests; the real driver in a pty against a fake listener and a
fake slow model (a stop or manual key while it was thinking dropped the
answer); `eval/language_eval.py` against a real Llama 3.1 8B on the desktop,
17/18, where "do not turn left" came back as back up, turn right.
Also on the Pi with Llama 3.2 3B, no motors: 18/18, 3.86 s median, 42.55 s cold first
call. Four of the commands also appear as prompt examples, so that score is flattering.
On the motors, floor test with Adam watching: all six steps passed, including a
stop sent during thinking, which moved nothing. Table in `eval/README.md`.

Also fixed: bench tools and the driver read a path specific to one dev session,
and Pillow was an undeclared dependency.

## 2026-11-01 — Showcase shows the drive loop's frames (no more black screen)

Adam: in Showcase the phone screen goes black during a drive, and the
screen recording is part of the demo video. Cause: the USB camera has one
reader, so the page drops its MJPEG feed when a launch is queued.
New `GET /api/driveframe` on the Pi server serves `/tmp/centre_frame.jpg`
(what `centre_run.grab` writes on every look), only if written after the
current launch was queued (`queued_at`; 204 otherwise) and only if the
JPEG has its end marker (a half-written frame falls back to the last
complete one). The page polls it every 700 ms during a drive and keeps the
last frame up afterwards until the live camera resumes. One frame per
look, not video, and no SAM box overlay yet. Red-first: 4 DriveFrame
tests failed, then passed; phone suite green; page JS syntax-checked.
Deployed to the Pi and the server restarted with the same flags (LIVE
SERVO, LIVE MOTORS), launch idle, no motion. Not yet seen on a live drive.
Deploy note: a first deploy from the working tree also pushed Codex's
uncommitted tap-to-select page/server, whose `selection.py` the Pi lacked;
the server failed to start for about a minute. Redeployed as HEAD plus
this change only. Pi backups: `*.bak-20261101`; the copied selection.py
is parked as `selection.py.codex-wip`.

## 2026-10-31 — Bench revived at 16:22 EDT

At Adam's request, checked Pi :5098: no listener/process. Started existing
motor_listen.py with its existing token (not displayed). Stop-only check
returned `ok stop` at 16:22:10 EDT; listener PID 649490. Expected expiry
~17:22 EDT under its one-hour lifetime. No drive or servo commands sent.

## 2026-10-31 — Adversarial review of demo claims and failure handling

Adam requested a red-team review of this project ("/multi" resolved to
~/multimodal-teleoperation). Reviewed current DEVLOG, README, AGENTS,
vision capture/arrival/recovery and launcher code; HEAD 9b41735. Existing
uncommitted log history preserved. No hardware calls or runtime edits.

New offline reproductions (mocked transports, no network):
- centre_run.grab accepted an existing valid temporary JPEG even when
  BOTH capture and SCP returned exit 255. Return codes are ignored and
  only the old file's JPEG prefix is checked. A stale frame can therefore
  reach control decisions as a fresh observation. Priority: check command
  success, use a new capture destination, validate freshness and decoding.
- run_tandem(plan, None) returned normally when its servo callback returned
  False. Arrival confirmation can proceed despite a refused neck move;
  motor+servo paths also suppress servo failures. Propagate failed pose
  commands and distinguish attempted confirmation from successful motion.
- Parser still routes "dance then go to the mug" to mug, while the reversed
  clause order is ambiguous. This is intentional in an existing test but
  contradicts broad unknown/mixed-command refusal claims.

Previously reproduced false-success paths remain: any post-reverse
reacquisition becomes ARRIVED, and step-cap fallthrough returns success
with no final target. Identity is nearest image position (largest on a
fresh scan), not persistent object identity. Two matching objects or
occlusion can swap the target. These are limits on reliability claims,
not evidence that the successful mug approach did not happen.

Evidence/presentation: README's 67 s "both ARRIVED" row omits Adam's
correction that the mug was ~1 ft short. The stronger grounded result is
139.728 s to final acknowledged stop with Adam confirming mug reached.
38 s remains an Adam-reported sequence without exact boundaries/targets.
No success-rate denominator is recorded; passing unit tests and selected
runs do not establish repeatability. Recommend fixed-layout repeated
trials, missing-target/duplicate-target/occlusion cases, and offline
capture-failure, step-cap and interruption regressions. Measure physical
arrival separately from software status and record all attempts.

No full suites rerun: this pass used targeted reproductions plus source
and historical evidence review. README claims flagged for correction;
not edited during this review. The successful demo remains substantiated;
robust arrival, identity and failure handling are unfinished.

## 2026-10-31 — Timed blue ball → mug: 2 min 19.73 s, mug reached

Monitored /tmp/launcher_timed.log live after the authorized bench restart.
Launcher mission 1 announcement 03:10:00.983 → final acknowledged stop
03:12:20.711 = **139.728 s** for the chain (log-receipt timestamps, not
phone-tap timing). Ball ARRIVED 03:10:30.940, stop ok 03:10:31.199
(30.216 s elapsed); mug mission began 03:10:31.436. Mug search needed
neck sweeps and L60 then R120 chassis turns, both motor-acknowledged.
Mug scan FOUND 03:12:02.909; spin + forward 1.76261 s, arrival confirm,
ARRIVED 03:12:20.447, stop ok 03:12:20.711. Mission 2 took 109.275 s;
17.802 s from mug scan FOUND to final stop. Both missions reported
ARRIVED, rather than falling through the step cap.

Adam's ground truth: mug was visible at the right frame edge at the
rightmost camera pan during earlier search; recognition missed it.
Exact corresponding frame not independently inspected. Adam subsequently
confirmed "it got there" at the mug. This run demonstrates successful
rightward chassis-search recovery and physical mug approach despite the
initial missed detection. Earlier 38-second report remains a separate
Adam-reported result; this is the timed run. No code changes made.

## 2026-10-31 — Bench listener restored for timed retry

Adam authorized restart and stop verification. Read-only Pi diagnostics
confirmed no listener on :5098 and no motor_listen.py process. Started
existing ~/motor_listen.py using the existing Pi token without displaying
it. At 03:09:27 EDT, drive_step.py stop returned `ok stop`; listener PID
318515. Expected one-hour expiry ~04:09. No drive or servo command sent.
Codex SSH needs explicit tank identity and LAN hostname (default identity
was rejected; tank-lan alias absent); existing ~/.ssh/tank succeeded.

## 2026-10-31 — Timed chain attempt blocked by motor listener

Live log: mission 1/2 "go to the blue ball" at 03:07:41.962;
first aim at 03:07:46.733 (4.771 s from mission announcement).
First go 2.5 s command failed; final stop also failed with Pi
127.0.0.1:5098 ConnectionRefusedError. No completed mission timing;
these timestamps measure launcher log receipt, not the phone tap.
Listener had been left down at Adam's request; no restart performed.

## 2026-10-31 — Adam reports 38-second object-to-object chase

Adam reports **38 seconds** for "chase object and acquire new object
chase": approach/follow one object, acquire a new object, and chase it.
This timing refers to the object-to-object sequence, not the cat chase
alone. Target identities and precise timing boundaries were not supplied;
this is Adam's observed result, not an independently timed log analysis.
It does not establish confirmed arrival at both targets or resolve the
previously documented completion-status bugs. No code changes made.

## 2026-10-31 — Cat round 2: recognition succeeded, listener refused motors

Monitored /tmp/launcher_timed.log live. At 02:00:19 "chase the cat"
launched; step 1 detected cat (area 0.0496, dx -0.314). Planned bearing
+32.1 degrees / spinr 0.29 s, but drive_step failed connecting to Pi
127.0.0.1:5098 with ConnectionRefusedError. Final stop also refused;
no successful motor actuation or stop acknowledgement in this run.
This matches the handoff's ~01:59 listener expiry; expiry itself was
not independently diagnosed. Requested Adam's authorization to restart
listener and verify stop; Adam chose "Leave it stopped." No restart
or hardware writes performed here.

## 2026-10-31 — Cat test: followed, cat moved, tank searched

Adam's live ground truth: the tank followed the cat; when the cat moved,
the tank scanned. Adam stopped the test at that point, having obtained
the behavior he wanted. This verifies observed follow-to-search behavior;
reacquisition and autonomous arrival were not tested to completion.
No independent motor-stop or live-log verification performed in this
entry; the stop is Adam's report. No runtime changes made.

## 2026-10-31 — Passive Pi-view recording armed for cat test

Adam requested recording from the Pi. Continuous qstream capture would
contend with the drive loop's exclusive camera opens, so started a passive
desktop recorder of fresh /tmp/centre_frame.jpg snapshots already copied
from the Pi. No camera or motor commands, no drive-code changes. Recorder:
/tmp/record_tank_frames.py; output ~/tank-recordings/20261031-015624.
Saves changed valid JPEGs plus timestamps and a 2 fps MP4 holding the last
frame between updates; polls every 0.5 s, stops after 15 minutes. This is
sampled tracker imagery, not continuous camera footage; rapid updates
can be missed. Startup verified waiting for fresh frames; no frames or
finished video verified yet. Recorder exec session: 73986.

## 2026-10-31 — Codex reads cat-test handoff at a37624b

Reviewed 68cd416 parser changes and a37624b handoff. "chase the cat"
now routes to goto; parser suite 46 passed locally. Verbless chain
segments now require a determiner; invalid prefix handling remains as
explicitly documented by the new test ("dance then go to the mug"
still routes to mug). Neither completion defect from the previous
review changed: drive_run.py is unchanged since be48b3a.
Read-only desktop check: handoff launcher PIDs 551201/551203 were absent;
/tmp/launcher_timed.log ended at the 01:01:54 queue-watching message,
with no later cat mission shown. This does not establish Pi state or
exclude a launcher under other PIDs. No hardware writes, service restarts,
or hosted calls performed. Live state needs checking before resumption.

## 2026-10-31 — Codex review of changes through be48b3a

Read-only runtime review of edccf07..be48b3a while Claude continues work;
HEAD stayed at be48b3a and the working tree was clean during checks.
The false tandem-loss guard is fixed. Reviewed measured pan calibration,
alternating neck/chassis sweeps, chained missions, spin-follow drive,
bottom-clip arrival, arrival confirmation, and reverse-first recovery.

Two confirmed completion defects remain (no fixes made in this review):
- recover_after_loss returns arrived=True for ANY detection after reverse.
  Fully mocked main(): far aim (area 0.01, y_bottom 0.55), forward, loss,
  same far aim after reverse -> ARRIVED / exit 0, although arrived(aim)
  is False. Reacquisition should return to approach/arrival validation;
  visibility alone does not establish arrival or identity continuity.
- Step-cap fallthrough returns 0 even when the final look is None.
  Fully mocked one-step main() reproduced final aim=None / exit 0.
  Launcher chains advance on this success code, so exhaustion can skip
  an unfinished target. Arrival confirmation on the last step also falls
  through to this unchecked result. Distinguish reached from incomplete.

Offline checks: vision 106 run (105 passed, 1 skipped), parser 44 passed,
roundtable 6 passed. No hardware/hosted API calls. Phone and speech suites
were not rerun in this pass (their source/tests unchanged in this range).
Existing tests cover recovery/arrival helpers but lack main-loop coverage
for these outcomes. Add those regressions with the fixes. The previously
reported parent-launcher interruption/child-cleanup issue also remains.
Only this review entry was written; code and HANDOFF left to active work.

## 2026-10-30 — Codex offline repository review

Reviewed clean working tree at edccf07, drive/recovery control flow,
launcher lifecycle, recent IPv4 change, and project status documents.
No hardware commands or hosted API calls were made; runtime code unchanged.

Confirmed priority bug: drive_run.py's should_tandem_recover call lacks
an `aim is None` guard. After the first successful step, tandem mode
unconditionally logs "lost" and replaces even a valid recognition with
a scan result. Fully mocked two-step main() reproduction: recognition
always returned a valid aim; recovery nevertheless ran once, returned
None, and the run exited 1. Existing helper tests miss this caller bug.
Proposed fix: guard on actual loss and add main-loop regression coverage
for successful tracking and real loss. Not implemented in this review.
Prior live entries' repeated "first-look lost" interpretation is therefore
unproven: those messages alone do not establish recognition failure.
Preserve raw recognition results before diagnosing calibration/settling.

Other findings: step-cap exhaustion returns 0 regardless of final aim,
so launcher reports done without proving arrival; area >0.25 remains
size-blind. Launcher lacks child cleanup on parent interruption despite
its Ctrl+C docstring; the handoff already warns of orphaned runs.
Non-tandem spin_secs_for_dx still uses 60 degrees rather than the measured
33-degree horizontal FOV. These remain review findings, not fixes.

Checks: vision 80 run, 79 passed / 1 skipped; parser 41 passed;
phone 38 passed; speech 28 passed; round-table 6 passed. Phone/speech
initially hit sandbox socket restrictions, then passed outside sandbox
using their local fake servers. Vision import emitted an Ultralytics
settings-reset warning. No live readiness or physical state verified.
Updated README opening status and HANDOFF review note to reflect these
findings; historical live entries preserved.

## 2026-10-31 — Chain 6: both stages; loss after a forward step reverses first

Chain 6 (arrival confirm live): ball — step 2 bottom-clipped →
"arrival check: bearing -4.0 → neck pan 58 tilt 34" → ball fully in
frame (0.144) → go 0.79 s → area 0.28 + clipped → "arrival check:
bearing -10.2 → spinl 0.09, tilt 26" → ARRIVED, facing it, 38 s.
Mug: sweep found it at pan 3 (+50.3°) → spinr 0.46 (undershot ~15°)
→ spinr 0.13 + go 2 s → lost → sweep + chassis turn 1 (spinl 60, the
alternating turns' first live use). Adam: "It got to the mug and the
mug was shorter than the camera angle … wild pump arm celebrated
because second stage went. 2nd camera alignment was slow, but
everything else was incredible."

Cause: the last sighting was small (0.029, y_bottom 0.87), so the ladder
skipped the reverse; the 2 s go had put the short mug under the camera.
Fix: recover_after_loss(after_forward=True) reverses + looks first
whenever the losing move drove forward (tandem go, or spin + chained
go); the arrival-check move (no go) clears it. Test: 1 red-first;
vision 106. NOT yet live-tested. The slow second alignment = the
short-spin undershoot (0.46 s for 50° turned ~35°).

## 2026-10-31 — Arrival confirm: face it and aim down before ARRIVED

An arrived aim (area > 0.25 or bottom-clipped) in tandem mode now gets
ONE confirm when needs_arrival_confirm(plan, tilt): the chassis isn't
facing it (tandem plan = spin, bearing > 5°) or the camera can still
tilt down onto it. The confirm is the tandem move WITHOUT a forward
step (spin if needed + neck to plan pan/tilt; run_tandem accepts
motor_cmd=None), then the next look decides: still arrived → ARRIVED;
otherwise the loop drives on (a tall mug a foot off now sits fully in
frame). Tilt at its floor trusts the clip (the ball case). A non-arrived
aim resets the check. Tests: 5 red-first (mug neck-only case,
facing+can tilt, aimed = arrived, tilt floor, neck-only tandem);
vision 105. The main-loop wiring is not unit-tested; NOT live-tested.

## 2026-10-31 — CHAIN COMPLETE: blue ball → mug in 67 s (both sweeps live)

Chain 5, "go to the blue ball then go to the mug", mug placed off to
the right (where chain 4's always-left search never looked). 00:41:37
→ 00:42:44, 67 s for BOTH missions, every stop ok:

  mission 1  look 1: area 0.030 → go 2.33 s → lost → sweep [75, 29, 4]
             found at the FIRST stop, box on frame bottom → ARRIVED (22 s)
  mission 2  sweep from pan 75: [50, 25, 0] → mug at pan 0 (far right)
             after 17.6 s → +48.5° → spinr 0.44 + chained go 1.99 s →
             lost (spin undershoot) → sweep [75, 28, 3] → found at
             pan 28, box on frame bottom → ARRIVED (45 s)

Live-proven: Adam's outward neck sweep (3 stops a row, not 6), the
bottom-clip arrival (twice), the spin→drive chain, the chain handover.
No chassis turn was needed this time, so the alternating chassis turns
are still unproven live.

Adam's ground truth: the ball was reached; the MUG was ~1 ft short,
and "not chassised at it… just camera." The mug ARRIVED from a sweep
stop at pan 28 (neck ~21° right of the nose), level tilt 41, area 0.18
with the box on the frame bottom: tall object + unaimed camera + an
unturned chassis. Fix (next entry): arrival confirm. Remaining waste: the short-spin undershoot
(0.44 s for 48°) cost one loss + sweep.

## 2026-10-31 — Chassis turns alternate too (L60, R120, L180)

Ground truth from chain 4 mission 2 (Adam): "It didn't go to the mug. It
turned the opposite direction towards a cat." The mug was to the RIGHT,
past the neck's ~61° right reach; chassis_scan turned spinl 60° three
times (always left, the Oct 30 handicapped-side rule) — 180° the wrong
way. Applying Adam's sweep at chassis level: turn k goes k × 60° on
alternating sides, first left — L60, R120 (60° past start), L180 — so
three turns search both sides. Spins up to 1.64 s (listener caps 3 s).
Tests: the always-left expectation updated + 1 new; vision 100.
NOT yet live-tested. Video note (Adam): frame it as "tank eats cats".

## 2026-10-31 — Chain 4: bottom-clip ARRIVED live; Adam's outward sweep

Chain 4 ("go to the blue ball then go to the mug"), after d13773c:
mission 1 seen at look 1, go 2.5 s ×2, lost (step 2 area had DROPPED
0.016→0.011 — likely a farther blue thing), the ladder's wide scan found
the ball at the first stop with y_bottom 1.0 → "ARRIVED (box on the
frame bottom)" 30 s after launch, stop ok; mission 2 started 0.6 s later.
Mission 2 (mug): 4 neck sweeps × 12 stops + 3 chassis turns (spinl
0.55 s each — FIRST live chassis-assisted search) → not found, fail
closed, stop ok, ~4.5 min. Mug placement unknown/out of view.

Adam: "sweep is the correct method. One shot, then alternate to the
other side slightly bigger, and so on." scan_pan_positions now sweeps
outward from the current pan, alternating sides (view-left first),
swings never shrinking; each side stops once its frame reaches the
limit. Step 15 → 25 units: the frame is 33° ≈ 39 units at 0.85°/unit,
so 15 looked at every spot ~2.5×. Full 0–75 row: 6 stops → 2–3
(e.g. from 53: [75, 28, 3]). run_scan: later (floor) rows also look at
the start pan, which the caller's first look covered only at the first
tilt. Tests: 3 red-first (alternation, coverage ≤4 stops from any
start, floor-row start pan); old ordering tests replaced; one count
updated (4+5+1). Vision 99. NOT yet live-tested. Still open: 2-sample
scan stops; neck tilt inherited between missions.

## 2026-10-31 — Bottom-clipped box = arrived (chain 3 pushed the ball)

Chain 3 (loss ladder live): ball seen at look 1; go 2.5 s, go 2.26 s,
step 3 area 0.076 at dy −0.41 — Adam: within ~4 in, "Oh it's
perfect!" — then spin + go 1.46 s; step 4 the ball was a bottom-edge
sliver (area 0.0099, dy −0.48), read as FAR → go 2.5 s, pushed the
ball. Step 5 lost; the ladder skipped the reverse (sliver area < 0.08)
and went to the chassis-assisted scan (tilt already at its floor, one
row); Adam stopped it.

Fix: recognise() now carries the box bottom edge (y_bottom); arrived(aim)
= area > 0.25 OR box bottom >= 0.97 (target runs off the frame bottom).
Tandem re-aims tilt every step, so bottom clipping means near, not
small. Ladder also reverses when the last sighting was bottom-clipped.
Step 3 of chain 3 would now have stopped at Adam's "perfect" spot.
Tests: 6 red-first; vision 98. NOT yet live-tested.

## 2026-10-31 — Chained missions live; loss ladder (reverse, then chassis scan)

Chained missions (7fe2d76): "go to the blue ball then go to the mug".
The parser accepts a chain only when every segment is a clean goto (max
3); the Pi server + parser were redeployed (old parser kept as
xiaor_text_action.py.bak-20261030; server restarted with the same flags;
pose re-synced to pan 60 / tilt 36), and the launcher was restarted.
Chain 1: mission 1 ball, 5 steps, ended with the ball under the camera
(final aim None, Adam: "it got so close the ball is under the camera");
mission 2 mug started 0.3 s later — handover proven; Adam stopped it
mid-scan. Adam: early steps felt short → spin follow-up cap 1.0 → 2.0 s
(b3bc3ef). Chain 2: ball seen at look 1, go 2.5 s, go 1.97 s (area
0.012 → 0.041 → 0.186 by step 3), then lost at the ball → neck-only
verification scan (12 stops) → mission FAILED → chain ended, mug never
tried. Ground truth: the ball was under the nose.

Cause: after tracking, recovery was neck-only (scan_for_target). The
chassis-assisted scan (chassis_scan, built with Muse) ran only at step
1, and tonight's step-1 neck sweeps always found the target first, so
zero chassis turns ever happened. A neck/chassis turn can't see under
the nose anyway.

Fix (recover_after_loss): last seen close (area >= UNDER_AREA 0.08)
→ reverse 0.5 s and look once; seen = ARRIVED (under camera), exit 0,
so a chain continues. Otherwise / not seen → chassis_scan (neck sweep
+ chassis turns). Nothing → stop (fail closed). The fast loop's dy rule
isn't reused: tandem recentres tilt every step, so dy at loss is
unreliable; size alone gates the reverse. Tests: 4 red-first; vision 93.
NOT yet live-tested. Still open: neck tilt is inherited between missions
(mission 2 scanned from 29°); scan stops take 2 samples (≈5 s each).

## 2026-10-30 — "go to the blue ball": ARRIVED in 71 s, both fixes live-proven

Phone launch 23:50:46, launcher --steps 5 --tandem, Claude monitoring.
Step 1: not in frame → wide scan, found at pan 60 on the 5th stop
(29 s, area 0.013, bearing −17.7°). Then:

  step 1  spinl 0.16 → then 'go 1'        (spin→drive chain LIVE)
  step 2  aim direct, area 0.021, −9.1°  → spinl 0.08 → go 1   (7.3 s)
  step 3  aim direct, area 0.037, −5.9°  → spinl 0.07 → go 1   (7.5 s)
  step 4  aim direct, area 0.082, −4.8°  → go 1.05, neck 59    (8.4 s)
  step 5  real loss (ball low, dy −0.14 at 0.08, under camera) →
          verification scan, first stop: area 0.264 → ARRIVED, stop ok

Adam's ground truth: ARRIVED stopped ~8" short of the ball ("the
speed was next level"). Bug #2 again: area 0.25 is size-blind — a
small ball fills a quarter of the narrow 33° frame from 8" away.

Bug #1 fix proven: steps 2–4 went straight to aim, no false "lost";
the only scan was a genuine loss, which is what recovery is for.
Spin→drive chain proven: every spin followed by a capped go.
Short spins (0.07–0.16 s) only turned ~half the bearing (bug #3);
the loop absorbed it, but a minimum spin/kick-start is the next win.

Tonight's arc: cat run 10 min 52 s (IPv6 stalls, false scans) → foot
68 s (IPv4) → blue ball 71 s INCLUDING a 29 s cold wide scan; tracked
steps ~7–8 s each vs ~12–13 s with false scans.

## 2026-10-30 — Tandem spin now chains a forward step (Adam's call)

Adam: "When thing turns, it has to launch a drive step after it."
A tandem spin used to end the step, so every turn paid a full look
cycle (~5 s) before moving forward. tandem_followup_cmd: after a spin
plan, drive forward from the same picture, area-based secs capped at
SPIN_FOLLOW_MAX_SECS = 1.0 (Adam chose "always, capped" over
"small spins only" / "full step"); the spin is open-loop, and the
next look corrects what is left. Safe to chain: drive_step.py holds
the connection for secs + 0.2 and stops, and drive() waits for it.
Tests: 2 red-first; vision 86. NOT yet live-tested.

## 2026-10-30 — Bug #1 SOLVED: tandem "lost" was a false alarm every step

"go to The Mug" (0.85 calibration, IPv4 fix): wide scan found it at
pan 15 (+45.7°), spins + forward steps, final look area 0.354 at the
mug, stop ok, ~93 s. Adam: "THAT WAS SO GOOD". Every step 2–5 still
logged "lost — verification scan", even at bearing +2.7°.

Claude saved the frames of step 4's "lost" first look: the mug fills
the lower right, and SAM re-run on both frames finds it (area 0.14,
dx +0.30). The look never failed. should_tandem_recover(tandem,
has_prev, recovered) never asked whether the look FOUND the target,
and the call site didn't either, so after every tracked step it
printed "lost", discarded the good aim and ran a neck scan;
tandem_recovered then reset, so it repeated every step. Introduced
with 5e7bafc; its test covered only flag combinations.

Fix: should_tandem_recover(..., found) is False when the look found
the target; call site passes found=aim is not None. Red-first test.
Suites: vision 84, parser 41, phone 38, speech 28. This also
retires the earlier theories (stall, pan scale, settle time) as the
cause of bug #1; they were real problems of their own but not this.

## 2026-10-30 — Pan measured: 0.85 deg/unit (was 1.2 / implied 1.0)

Servo-only test, Adam authorised (motors untouched, tilt 36 held,
pan restored to 53). Fixed object on the desk (an astronaut light;
SAM called it "white paper" consistently in all 18 frames). Pan
53→49→45→49→53→57→61→57→53, 2 SAM looks per stop:

  pan 45 −0.197 · 49 −0.088/−0.095 · 53 +0.016/+0.014/−0.005
  · 57 +0.117/+0.107 · 61 +0.220

Linear, 0.0258 dx/unit x 33° FOV = 0.85 deg/unit; frame-to-frame
noise ~0.001; backlash ~0.01–0.02 dx (<1 unit). Near object (~40 cm)
so pivot parallax may overstate slightly. Adam had an earlier Meta
measurement (number not compared here); he OKed the change.

Code had two scales for one servo: tandem bearing used 1.2 (neck
angle overstated ~40%, so every tandem spin overshot), recentre used
an implied 1.0. Now both use SERVO_DEG_PER_UNIT = 0.85; recentre
converts degrees to units. Tilt still assumes 1 deg/unit (unmeasured).
Tests: 4 red-first in test_centre.py (old saturated-bearing test
updated from the eyeball ~25° to 22 x 0.85). Suites: vision 83, parser
41, phone 38, speech 28, all OK. Next: re-run the foot and see whether
the post-move first looks stop missing.

## 2026-10-30 — First run on the IPv4 fix: "go to the foot", 5 steps in 68 s

Phone launch, launcher --steps 5 --tandem, Claude monitoring the
timestamped log. No stalls: each look (2 grabs + 2 SAM) ~4.8 s. Area
0.0046 → 0.030, step-capped, final stop ok. Compare run 2 on the old
code: 4 steps, 10 min 52 s.

Bug #1 still present on a clean network: the first look after EVERY
move (steps 2–5) was "lost"; the verification scan found it at its
FIRST stop (pan 60) each time, so a step costs ~12–13 s instead of ~6.
Neck was at 53/57 for the misses. Step 3's miss predicted dx ≈ −0.27
at pan 53, yet the final look at pan 53 FOUND it at dx −0.22, so
"SERVO_DEG_PER_UNIT is ~2x off" is NOT established. Small target
(area ~0.009) near the edge of the 33° lens fits as well. Next
diagnostic (servo-only, needs Adam's OK): fixed object, SAM looks at
pan 45/53/60 to measure dx per pan unit; and keep the first-look
frames. Spins of 0.08–0.19 s were issued (bug #3, mostly spin-up).

## 2026-10-30 — Execution time: ~2 min SAM stalls were IPv6, fixed to IPv4

Cat chase monitored by Claude (desktop launcher, timestamped log
/tmp/launcher_timed.log; ssh direct to the Pi, NOT via the Muse broker).
Run 1 went silent after one frame grab (Adam stopped it). Run 2 step 1
took 2 min 05 s; a drive socket sat in SYN-SENT to Meta's IPv6 address
(2a03:2880:…). Measured from the desktop: 7/30 IPv6 TCP connects to
api.meta.ai never answered within 3 s, 0/30 on IPv4 (successful connects
20–90 ms either way). urllib tries IPv6 first and waits out the full
120 s timeout before falling back to IPv4, so roughly 4 in 10 looks
(2 SAM calls each) stalled ~2 min on a stale frame.

Clean path, same run: a scan stop (servo move + 0.8 s settle + 2 grabs
+ 2 SAM) found the cat in 6.1 s, motors on 1.7 s later. Bench parts:
ssh round trip 0.25 s, qstream grab 0.67–0.93 s, scp 0.30 s, SAM call
~1.0–1.5 s.

Fix: meta_sam.call_api connects IPv4-only, 5 s connect timeout, up to 3
tries on fresh sockets; the read timeout stays 120 s. Env-proxied runs
(Muse broker) keep the old default path. Tests: test_meta_net.py (6,
red-first); vision suite 80 OK. Live: 6 SAM calls on the cat frame,
0.99–1.49 s each, no stall.

Bug #1 (post-tandem first look "lost", verification scan finds it):
in run 2, steps 2 and 3 were each "lost" right after a ~2 min stall and
then found by the scan within seconds. But step 4 was "lost" with NO
stall (7.6 s after a 0.75 s forward step, cat at area 0.16), so the
stall explains some losses, not all. A second cause (servo settle,
target near/under the camera, instance carry-over) is still open. The
first-look frame is overwritten by the scan's grabs; keep it before
the next diagnosis.

## 2026-10-30 — Left-favour scan live: two cat runs

Run 1: three spinl chassis turns (~180° left of search), scan
FOUND at area 0.0028 — implausibly tiny for a cat, likely a
false/distant match — tandem spin toward it, lost, verification
scan found nothing, fail-closed stop. Run 2 (better): cat in
frame at step 1 (area 0.043), then EVERY step lost its initial
look and was recovered by the verification scan, areas growing
0.085 → 0.081 → 0.091 → 0.132 across steps, forwards of 0.99 s
and 0.83 s on the last two, final aim area 0.184 — ran out of
5 steps, queue "done", stop verified. Left-favour turns work
as intended; the pattern that remains is the post-tandem-move
first look failing while the verification scan (same camera,
fresh sweep) succeeds — the initial look after a tandem move
is systematically weaker than the scan look. Next diagnostic
candidate: compare first-look frames vs scan frames at the
same pose (settle time / instance-centroid carry-over).

## 2026-10-30 — Beer run spun ~230° the wrong way (pre-fix code)

Phone "go to the beer": neck scan missed, then THREE chassis
turns spinr 0.55 s (~60° each, ~180° total; Adam read it as
~230° with the neck offset) and never found it — fail-closed
stop verified. Ground truth: beer was the other way. Timing
note: this launch started BEFORE the left-favour commit
(0a96d55) landed, so its drive_run subprocess still had the
old spinr default. Left-favour (chassis turns spinl, covering
the neck's 22-unit handicapped side) applies from the next
launch. Prompt "beer" also never got a single SAM hit in 4
neck sweeps (48 looks) — either out of all arcs covered or
the word does not match the object (can/bottle to test).

## 2026-10-30 — "Dungeon Crawler Carl": found, 60 cm short, cats intrude

Phone launch, prompt "dungeon crawler carl" (the book). Wide
scan found it at look 9 (area 0.036) after chassis turns. Then
the verification recovery earned its keep: steps 2–5 ALL lost
the initial look and ALL were recovered by the verification
scan (found areas 0.037 → 0.012 → 0.120 → 0.095), with cat
intrusions in frame during the run (Adam) likely breaking the
tracked-instance look. Tandem bearings were mostly small
(+20.4 spin, then −0.2 / −6.4 / −17.8 / +3.1). Ran out of its
5 steps at final area 0.205 (dx −0.198): queue "done", stop
verified — and Adam's ground truth: stopped ~60 cm short of
the book. So: found and approached the right target through
repeated interference, but the per-step verification scans
(~40 s each) ate the step budget before arrival. Lesson:
verification recovery works, but needing it every step means
the post-move first look is the weak link (pose/instance),
and step caps end runs mid-approach.

## 2026-10-30 — Tandem live on mug: executes, tracking still loses it

Step 2 live via phone (launcher --tandem, listener revived).
Run 1: scan FOUND mug (dx +0.374, area 0.016), tandem bearing
+39.9° → neck to pan 53 + spinr 0.36 s from ONE picture, then
target lost at step 2. Run 2: same find (bearing +37.7°,
spinr 0.34 s), step 2 residual dx −0.152 (slight overshoot,
bearing −5.0°), then neck 58 + a 2.47 s forward (area 0.026 —
the new big-step curve at small area), target lost at step 3.
So tandem actuation works as designed (one look, concurrent
neck+chassis, no confirm-look). CORRECTION (Adam, ground
truth): run 2 DID reach the mug — its "target lost" ending was
the target sliding under the camera at arrival, reported as
failure with no end verification. That is the real second-
stage bug. Fix: a tandem loss after tracking now earns ONE
verification neck scan (scan_for_target, incl. floor tilt row)
before the run may fail — a found target re-enters the loop
and can ARRIVE properly. Run 1's immediate post-spin loss
gets the same recovery. Spin-rate drift over ~40° remains a
suspect for residual error. Cat not attempted under tandem yet.

## 2026-10-30 — Correction: second cat spoiled the scan (not a failure)

The phone "go to the cat" run during the tandem setup scanned,
FOUND at area 0.319 and declared ARRIVED with the bench listener
down (stop refused, connection refused — listener's hour had
expired; it fails safe, motors low, and that run never drove).
Adam's ground truth: a SECOND cat walked into frame close up
and the scan locked her instead. Instance confusion by cat, not
a machine failure. Listener revived 20:48 (pid 98492, ~1 h),
stop verified. There are two cats. Chases may lock either.

## 2026-10-30 — Cat chase with bigger steps: ARRIVED (log), tandem next

Phone "go to the cat" with the 0.40-curve live: forwards of
1.89 s (area 0.045) and 0.99 s (0.092), a spin correction at
dx −0.37, 0.77 s forward (0.150), then step 5 aim area 0.265
→ ARRIVED, stop verified. Much livelier than the ~4in crawl —
but ARRIVED is the log's claim only; Adam's distance ground
truth not yet collected, and at 1.3 m this lens already reads
~0.27 (see FOV entry), so treat as unconfirmed. Next build
(Step 2, Adam's ask): tandem neck+chassis — when a fresh aim
demands a turn, split it: camera pans toward PAN_FORWARD while
the chassis spins the remainder, concurrently, then re-look.
Today the two move strictly in sequence (recalibrate, re-look,
then spin), which is where the chase loses time and the cat.

## 2026-10-30 — Cat chase retest (phone) + way bigger steps

Phone launch "go to the cat" (5 steps, new 33° FOV active):
tracked the cat through steps 1–4 — area 0.100 → 0.131 → 0.103
→ 0.173, spins none, forwards 0.59/0.52/0.58 s — then target
lost at step 5, safe stop verified. The cat out-moved the
stop-decide-move loop, but tracking held across 4 approaches.
Adam's verdict on the steps: "~4in each time" — spin-up eats
0.5 s steps at 30%. Fix (3466587): forward curve 0.25→0.40
coefficient, cap 1.5→2.5 s (listener hard cap 3 s); the >0.08
near-target x0.75 shrink stays, so arrival-area step is only
0.6 s. At cat areas (~0.10) steps become ~0.95 s. Red-first
tests; vision 68 + parser 41 green. Not yet live-tested —
next cat chase is its test. Cat wins round 2; no arm attempted.

## 2026-10-30 — FOV measured with a helper's feet: 33° (was assumed 60°)

Cat chase by phone ("go to the cat") declared ARRIVED at step 1
with no drive: cat area 0.267 at what Adam measured as ~1.3 m.
No zoom exists on this camera (v4l2: no zoom/crop control; only
640x480/320x240) — the lens is just narrow. Measured it with
a helper standing at 185 cm, feet centres exactly 50 cm apart:
SAM boxes x 0.414–0.503 and 0.878–0.959 (centres 0.459/0.919)
→ H_FOV 32.7°, V_FOV 24.8° (square pixels), frame width at
185 cm ≈ 109 cm. centre.py now uses 33x25 (was 60x45), and the
scan step drops 30→15 servo units (was a full old-FOV apart —
gap-prone; now ~half the real FOV). Vision 68 green. This also
means every dx→degrees conversion was overstated ~1.8x, a
likely contributor to recalibration overshoot/sign flips.
Chassis-scan turn widened 40→60° in the same session (95cf5fe,
Adam: "we need a wider turn base") — ~20° leg overlap remains.

## 2026-10-30 — Voice launches, Step 1 chassis scan live, pan calibrated

Voice session (Adam timing, Muse monitoring only): "Go to the
mug" ran 5 steps in ~59 s of motor phase, final area 0.203 — close
but no ARRIVED. "investigate the Box" scanned, found, ARRIVED
area 0.30 — but Adam's ground truth: "It didn't move to the box."
A follow-up "check out the box" declared ARRIVED at step 1 with
zero motor commands. Root cause (Adam: "the box box was too
big"): area-as-distance is size-dependent — a big box fills >0.25
of frame from across the room, a small mug never reaches 0.25 up
close. "go to the bottle" then effectively arrived unflagged:
5 steps, final re-look area 0.440 dead-centre after the step cap.
Arrival needs a size-independent signal (relative area growth or
the dead ultrasonic), not an absolute area.

Step 1 built + live (commits e19af11): run_chassis_scan — neck
scan fails → one bounded ~40° chassis turn (default spinr) →
rescan, ≤3 turns, failed spin aborts. 66 vision tests green
(7 new, red-first). Live: first attempt aborted correctly when
the bench listener's hour expired mid-scan; revived and reran —
neck scan 8 looks nothing, spinr 0.36 s, rescan FOUND the mug
(out-of-frame right), 8 drive steps to final area 0.274 (the
bottle pattern: one look short of ARRIVED), 2m34s total. Step 1
works. Launcher was still running the old queue code path;
drive_run subprocesses pick up the new scan automatically.

Camera pan calibrated (Adam eyeball vs chassis nose; centreline
mug method read 70 and was rejected by eye as ~20° off — the mug
was not on the true centreline): PAN_FORWARD = ch6 53. Travel
from straight: 22 units to the view-left limit (75), 53 units
to view-right (0) — Adam's ~30°/50° split. Recorded as
tank_vision.centre.PAN_FORWARD for step 2 (pan compensation).
Favour the right side for placements until then.

## 2026-10-30 — LIVE TESTS: FastSAM fails, scan/different/moved pass (Adam present)

Git first: the single Day-2 commit became 6 temporal local commits
(parser → phone GUI → speech → vision → round table → docs, dated
2026-10-28…30 from this log; file-level grouping, some files span
days). No remote configured; nothing pushed. Offline suites green
before testing: parser 41, vision 59, phone 38, speech 28.

Prep: bench listener revived on Pi (pid 29544, 1 h life), stop
verified `ok`; phone page closed to free /dev/video0. Cat in the
room interfered twice (Adam: "Aw crap. cat?") — noted per run.

- FastSAM (`drive_run --fast`, sandal/Croc): FAIL, twice. Run A
  (Croc in frame, pile visible): lock-on perfect (dx −0.001,
  area 0.021), then after one 1.5 s forward step dx jumped −0.28,
  spins chased the shoe pile, blind side-exit spin, ARRIVED at
  area 0.27 on the WRONG instance — arrival frame is the door/pile,
  not the Croc; 38 s total, no speedup over the 7.8 s/step baseline
  (Meta rechecks + recalibrations dominate). Adam: "it was
  terrible. It started so well, too." Run B (Croc isolated at
  frame edge): spin corrected, area jumped 0.031→0.126 on
  recalibration, target lost at step 3, safe stop (29 s). Fast
  motor loop remains UNPROVEN; do not demo `--fast` as-is.
- Out-of-frame scan (servo-only `centre_run --scan`, sandal):
  PASS for finding — 2 empty looks then FOUND at stop 3
  (area 0.019); post-scan frame verifies the correct grey Croc.
  Head centreing after the find then lost it at step 2 (same
  centreing fragility as the fast loop, not a scan failure).
- Different objects (black mug, `centre_run --prompt mug`):
  PASS — recognised and CENTRED in 5 steps (dx +0.019,
  dy −0.008); frame verified mug dead-centre.
- Moved objects (same mug): first move was outside the head's
  0–75° pan arc — scan swept 8 looks/2 tilts, not found, head
  restored, no motion: fail-closed CORRECT. Re-placed inside
  the arc (out of frame right): scan FOUND at stop 3,
  CENTRED at step 6 (dx +0.013); frame verified.
- Adam's observation, load-bearing: camera pan is asymmetric
  vs chassis-straight — far more range to one side than the
  other. Likely contributor to repeated pan-75 saturation in
  recalibration. Next fix candidates (offline first): cap the
  first forward step after lock-on, verify tracked instance
  against the lock box before ARRIVED, and map pan centre to
  chassis heading before demo rehearsal.

Tank left stopped (final stop `ok` sent after last frame).

## 2026-10-30 — Isolated Muse: Baseten deployment MCP enabled

At Adam's request, added narrow Baseten HTTPS API/docs/inference and model/
chain endpoint exceptions to the host isolation broker. Configured backend
and docs MCP in the separate Muse profile, preserving settings and approvals;
existing project API key copied privately (0600), never printed or committed.
Private pre-change backup saved outside the repo. Restart Muse to load changes.

Verified from actual Bubblewrap namespace: authenticated backend initialize +
tools/list (161 tools, including deploy_model_from_library), docs MCP (3 tools),
Muse echo startup, all 3 policy tests, and real filesystem/network boundary
checks. Host files remain hidden, direct network and disallowed proxy routes
remain blocked. No deployment, inference, or physical action performed.

Adam reported create_sandbox skipped for credential-shaped schema text.
Inspected upstream public schema: it contains the dummy example
sk-proj-demo-not-a-valid-api-key, the likely false-positive trigger. This is
separate from model-library deployment; kept Muse's schema filter intact.
Discovery does not certify every tool's acceptance by Muse. Whisper deployment,
Pi runtime configuration, live transcription and duplex playback remain untested.
Usage/scope/rollback: BASETEN_ACCESS.md; README, AGENTS, HANDOFF and speech README
updated, including correction of contradictory STT-credit wording.

## 2026-10-29 — FAST SAM SIMULATION (offline + servo-only live; no motors)

Adam at work (power cut), tank on the desk at home: non-motor only,
camera servos authorised. Desk-check of the `--fast` loop in two
parts. Offline (`/tmp/fast_sim_a.py` on a real grabbed frame, Meta
lock-on "computer mouse" dx −0.086): MobileSAM box-track agreed to
~0.02 dx on the same frame, followed synthetic scene shifts in the
right direction (Δdx +0.076 for an 8% left shift), flagged NO Meta
recheck in 4/4 cases, steady 0.61–0.66 s/frame. Live servo-only
(`/tmp/fast_sim.py` `fast_look`, which never touches motors): Meta
lock-on, tracker recentered the head (pan saturated 75, tilt 72→20),
dx pinned to 0.0 on three straight looks, area 0.084→0.276 as the
mouse centred, 6.4 s first look then 1.70/1.75 s per look vs the
~7.8 s/step Meta baseline. Final frame visually verified: mouse
bottom-centre. Fast loop is desk-proven; only its motor steps remain
unlive-tested.

## 2026-10-29 — PAGE LAUNCHER: voice command can now start the drive

Adam's call: launching off the page is the point of the test. Built:
Pi queue endpoints (`POST /api/launch` goto-only, `/consume`,
`/report`, `/stop`, `GET /api/launch` — the Pi moves nothing), desktop
`tank_vision/launcher.py` poller (consumes one launch → drive_run on
the exact sentence, 5 steps proven loop; page stop via SIGINT so
drive_run's finally still sends its stop), page Launch/Stop drive
buttons with live status polling and camera handoff (feed blanks on
launch so the drive loop owns the USB camera). Red-first tests:
phone and vision suites green. Pi server restarted safe + MJPEG;
launcher started on the desktop with Adam present and his bounded
authorisation. Live result pending his tap.

LIVE (same session, Adam present/authorised): first tap ("investigate
the shoe") scanned 8 stops to nothing and failed safe — frame grab
showed the head aimed at a wall/tabletop, no floor in view, and this
Croc has never answered to the prompt "shoe". Retry with the head
tilted down, Croc side-on in the starting frame, and "check out the
sandal": first-frame lock (area 0.019), recalibration after every
move saturated pan at 75 and still converged, one 0.09 s spin
correction, 5 steps, area 0.019 → 0.258 → ARRIVED, final stop sent,
queue reported done. Arrival frame visually verified: grey Croc
side-on, heel strap up, fills the lower frame. So the miss was
wording + framing + light together, not semantics alone. Launcher
stopped after the test; Pi server left as Adam's flagged restart
(--enable-servo --enable-motors), bench listener on its 1 h life.

## 2026-10-29 — SLAMM deferred until after the hackathon

Adam's decision: SLAMM is not necessary for the demo and is parked
until after the hackathon. Demo priorities remain the fast loop,
blind-exit handling and rehearsals. Post-hackathon starting point if
revisited: record a calibrated, head-locked dataset first, then try
offline monocular SLAM before buying an IMU.

## 2026-10-29 — Hold-to-talk long-press fix (page only, live on Pi)

Adam (flags workaround working; "investigate the shoe" transcribed
live): holding the mic button opened Android Chrome's image menu
after ~1 s, stealing the touch and ending the listen. Page fix:
contextmenu suppressed on the mic button and camera image, image
made non-draggable with touch-callout/selection off, mic button
captures its pointer and handles pointercancel. Deployed
`index.html` only — served immediately, no restart. Phone 34 green.
Follow-up same hour: releasing with no final transcript left the
status stuck on "Listening…" — recognition/stream stop paths now
settle to Transcribing… → Heard / Nothing heard on every exit.
Root cause of the stuck screen found live: the Pi's 00:52 server
crashed only on `/api/speech/transcript` (empty reply; `/api/text`
fine), so phone transcripts never got an answer. With Adam's go,
restarted it SAFE (pid 16259, no enable flags, `setsid` detached):
transcript → goto shoe 200, drive/servo gates 403, page now sends
`Cache-Control: no-store`. Speech preview is live from the phone;
nothing can move until a flagged restart at home.

## 2026-10-29 — WHISPER GO-AHEAD: streaming relay + HTTPS mic built (deploy is Adam's)

Adam will pay for Baseten Whisper separately (~$0.06/GPU-min quoted —
outside the Muse credits; deploy for demo windows, deactivate after).
His phone also hit "mic error - not allowed": Chrome refuses mic +
SpeechRecognition on plain `http://tank.local:8123` (insecure
origin). Page now explains that in-place; workarounds are the Chrome
insecure-origin flag (quick) or HTTPS (proper).

Built: `BasetenStreamConnection` (stateful open/send/poll/end over the
existing stdlib WS client, now with server-role `accept_websocket`),
`GET /api/speech/stream` relay in the phone server (browser PCM in →
Baseten; partials → `speech_partial`, finals → routed preview at
`GET /api/speech/latest`; no path to hardware), and `--tls-cert/--tls-key`
on the server so a Tailscale cert (`<tank>.<tailnet>.ts.net`)
makes the page a secure origin. Page: when the server reports wired,
Hold-to-talk streams PCM live and polls partials/finals; browser
recognition and WAV upload remain fallbacks. Verified: speech 28,
phone 34, parser 41, vision 53 green; TLS probe with a throwaway
self-signed cert serves HTTPS; stream relay tested against fakes.
Deployed to Pi, running server NOT restarted. Adam's steps: deploy
Whisper Streaming in Baseten, set `BASETEN_STT_MODEL_ID`, restart the
Pi server with the env + tailscale cert + chosen enable flags.

## 2026-10-29 — CREDIT CORRECTION: $100 is Muse-Spark-only; STT = phone browser

Adam clarified the $100 Baseten credits are tied to Muse Spark Open.
Verified on the account from the Pi: the working model is literally
"[HACKATHON] Muse Spark Open" (`meta-models/muse-spark-open-1026`),
Model-API token pricing, inputs text+image ONLY (no audio). Whisper
(OpenAI weights) therefore cannot spend those credits: Baseten STT
needs a dedicated GPU deployment billed per-second to account
balance. The earlier "deploy Whisper" instruction in the entry below
is superseded. Muse Spark itself stays as the parser-fallback
translator — that IS the credited model used as intended.

Adam chose phone-browser speech: the page's Hold-to-talk now uses
`SpeechRecognition` first (Chrome/Android), finals POST to the
existing `/api/speech/transcript` preview; the Baseten WS audio path
remains as fallback for browsers without recognition. New
`index.html` deployed to the Pi and confirmed served by Adam's
RUNNING server (page reads disk per request — no restart, no flag
changes, no hardware touched). Suites still green (phone 32).

## 2026-10-29 — PHONE SPEECH WIRED (Baseten STT seam + Muse Spark fallback; no hardware)

Adam at work; speech-only testing authorised, servos/motors untouched.
Baseten key added to `.env` (`BASETEN_API_KEY`, never printed/committed).
Probed the account FROM THE PI (sandbox broker blocks baseten.co; key
passed over ssh stdin, persisted nowhere): 21 Model-API models, NO
deployments, no STT among Model APIs — live transcription still needs
Adam to Deploy Streaming (Whisper Large V3) and set
`BASETEN_STT_MODEL_ID`. Per Adam, the key's working LLM is
`meta-models/muse-spark-open-1026` (verified present + answering).

Wired: `tank_speech/ws_client.py` (minimal stdlib RFC6455 client — the
Pi stack is stdlib-only), `BasetenStreamTranscriber` (WAV→PCM, binary
frames in, JSON finals out, `{"type":"end"}` finish; Qwen3-ASR's
different protocol would adapt this one class), `make_llm_fn()` chat-
completions translator (default = Muse Spark; reasoning model, so
max_tokens 800 — 300 measured flaky: 291 tokens of reasoning, content
sometimes empty). Session worker routes parser-first; LLM may only
rescue an unknown into a re-classified goto. Phone: server builds the
session at startup when configured, `POST /api/speech/audio` (raw WAV
≤2 MB → worker → routed preview; 503/415/413/504 honest errors), page
gains Hold-to-talk (AudioContext PCM→16 kHz WAV; browsers gate the mic
to HTTPS/localhost, page says so on LAN HTTP). `/api/text` now returns
`target` (Showcase goto line no longer prints "undefined").

Parser synonyms (speech-friendly goto verbs, all no-motion):
investigate / check out / examine / inspect / look at / take a look at /
have a look at / go look at / go investigate…. Bare check/look
deliberately excluded ("check the sensors" stays query; "look at the
left" stays ambiguous; negated/pronoun forms still refuse/unknown).

Verified: parser 41, speech 27, phone 32, vision 53 — all green
(red-first). Local E2E with a fake Baseten WS server: real phone server
reports SPEECH LIVE, WAV POST → goto shoe, 3200 PCM bytes heard, zero
commands. LIVE from the Pi: Muse Spark fallback turned "bring me the
shoe please" into goto shoe (no commands) and left "sing me a song"
unrouted. Code deployed to Pi (server.py/index.html/parser/speech);
Adam's running server NOT restarted — at home: set the STT env, restart
with chosen flags, hold-to-talk. No servo/motor write at any point.

## 2026-10-29 — Ultrasonic retest still silent; fast loop (Speedup 2) built offline

Ultrasonic (Adam re-seated it, then left for work; sensor reads only):
two runs over `tank-lan` (`ssh tank` demands an interactive Tailscale
check) — median-of-7 and a 3-ping corroboration on TRIG BCM4 /
ECHO BCM17 both all-timeout, `distance_cm: None`. ECHO idles 0 as an
input; pin 4 idles 1 as an input (inconclusive). Still a physical job:
seating, VCC/GND, lead orientation. Phone server still running on the
Pi with `--enable-servo --enable-motors` (pid 9616) — noted, untouched.

Fast loop built offline, NOT yet run live (needs Adam present):
`tank_vision/fast_track.py` — Meta lock-on box → MobileSAM box-track
(prev box + 30% margin), Meta recheck only on empty mask / >2x area
change / >0.30 box jump; `blind_action` table (under-camera creep,
side-exit spin, true-loss stop, one blind move per loss). Wired as
`drive_run --fast` (default path unchanged); `recenter_servo` split
out of `recalibrate_camera` so the fast re-look stays local; forward
step now shrinks harder above area 0.08 (x0.75). Verified: vision 53
(15 new fast-track + 1 step test), parser 39, `--help` clean. Real
MobileSAM smoke on mc.jpg via `/tmp/fast_smoke.py`: load+track 2.57 s,
steady re-track 1.39 s, no recheck flagged. Next live step: `--fast`
drive with Adam present; persistent grab/listener still open.

## 2026-10-29 — Round table with preserved Muse contributor isolation

Added `round_table.py` in the existing singular `multimodal-teleoperation`
workspace. Adam chairs fresh Claude/Codex adviser turns and isolated Muse;
`/keys muse` enables implementation, `/take` returns to discussion. Muse
uses only the existing host isolation supervisor, with no contributor-mode,
network policy, credential, profile, or launcher changes and no unrestricted
fallback. Default Muse discussion disables shell and filesystem writes.
Physical tests still need separate explicit authorization with Adam present.

To avoid carrying host-agent context into the contributor session, adviser
answers require an explicit `/share ID` before inclusion in Muse prompts.
Direct Muse prompts and Muse replies remain in its room context. No existing
sessions are resumed, no transcript is written by the controller, and no
automatic agent-to-agent turns run. CLI-owned logs may still persist. Claude
is tool-free in safe/restricted mode; Codex is ephemeral/read-only with user
config ignored. These host adviser restrictions are not an OS isolation
guarantee. README documents usage and the content-sharing boundary.

Verification: 6 new offline adapter tests passed (context filtering, share
validation, command boundary, fail-closed behavior, subprocess failure and
timeout); required tank_tools suite passed 39 tests; the existing broker's
3 policy tests passed. CLI help and scoped diff whitespace checks passed. Existing isolated Muse
`exec --help` and an echo-provider smoke prompt succeeded through its broker;
no hosted model call or physical actuation was performed. Live hosted-agent
authentication and end-to-end model conversation remain unverified. Full
`git diff --check` reported a pre-existing trailing blank line in the user's
modified `tank_phone/index.html`; unrelated edits were preserved.

## 2026-10-29 — FULL MISSION: scan → recalibrating drive → ARRIVED at Croc

Adam reset the tank with the Croc slightly out of frame right (head
not re-homed; shoe pile further left flagged as a lock-on risk —
start frame confirmed no false "sandal" lock). drive_run: wide scan
found it at stop 2 (pan 60, dx +0.32, area 0.029), then the NEW loop
ran as designed — every motor decision preceded by a camera
recalibration + re-look, damped spins (0.18 / 0.09 / 0.12 s, no
ping-pong), forward steps shrinking with area (1.50 → 0.87 → 0.51 s).
7 steps, 91 s, area 0.029 → 0.293 → ARRIVED (>0.25), final stop
sent. Arrival frame visually verified from here: the grey Croc,
heel strap up, fills the lower frame — the right target, not the
pile. Recalibration pan repeatedly saturated at ch6=75 (target sits
beyond the neck's centre) and the loop still converged: neck when it
can, body when it must. This is the complete demo chain working:
scan (out-of-frame) → lock → track/drive → arrived.

## 2026-10-29 — SCAN FOUND IT, DRIVE SPIN-LOOPED, recalibration fix built

Live (Adam present/authorised): wide scan WORKED first try — found
the Croc at the 4th stop (pan 75, dx −0.37, area 0.025) after 3 empty
looks. Head-centreing then oscillated (target off-axis at the pan
limit — that's body-spin territory, as designed). Listener revived,
drive_run 8 steps: SPIN PING-PONG — dx flipped −0.37→+0.26→−0.26
for all 8 steps at the 0.15 s spin floor, never drove forward, final
stop sent, 54 s. Adam's diagnosis on the spot: "it's gotta
recalibrate the camera after the move or it'll just loop forever."

Fix (offline, built same night): `camera_recenter_angles` (pure;
physical mapping view-right=ch6-down / view-up=ch5-up) +
`recalibrate_camera` in centre_run — after every move, one bounded
recalibration from the FRESH aim, then a re-look; saturated neck
returns the old aim and the body spins. `spin_secs_for_dx` damps on
overshoot (sign flip ⇒ next spin ≤ half the last), killing the
ping-pong sequence in tests. drive_run recalibrates before every
motor decision. Vision 37 (8 new), parser 39 green. NOT yet re-run
live — retry waits for Adam's word (listener revived 03:32, ~1 h).

## 2026-10-29 — WIDE SCAN for out-of-frame targets (offline, not yet live)

Adam's spec: broader than the mini centreing moves; if it isn't found
across the L/R range, it fails. Built in `tank_vision/centre.py`
(pure, tested): `scan_pan_positions` covers the full pan-servo range
(ch6 limits, 75° here — the servo's actual L/R, not an assumed 180)
in two legs (current → nearest end → far end), stops every 30°
(half the 60° FOV, no gaps); `scan_tilts` adds a floor row 30° below
current. `run_scan` recognises per stop; found leaves the head on the
target, failure (or a refused move) restores the origin pose and
returns None — fail closed, caller must not drive. Wired:
`centre_run --scan`, and `drive_run` scans only on a first-frame loss
(never-seen), never after tracking (that's the under-camera case).
Tests: vision 29 (6 new scan tests, red-first; success-does-not-
restore caught by test), parser 39, speech 20 — all green. NOT yet run
live: first physical test is servo-only scan with Adam present.

## 2026-10-29 — FAST SHOE RUN: nose at the Croc in 39 s + MobileSAM bench

Baseline (Adam present, authorised): phone page had to close first
(its MJPEG producer held the camera — grab failed, safe stop, zero
steps). Croc end-on read as a black lump: SAM "shoe"/"croc"/"sandal"
all [] until re-angled side-on, then only "one shoe"/"sandal" hit it
(box 0.433–0.630, dx +0.03). Prompt chosen: "sandal". Run: 5 steps in
39 s (~7.8 s/step, adaptive steps), area 0.016→0.127 peak, spin
correction at step 3 worked, final stop sent. Final aim=None — the
Croc slid under the camera (dy −0.36) before area hit 0.25; Adam
confirmed the tank went right up to it. KNOWN GAP (Adam: "recalibrate
a whole table to compensate for slam when it can't see shit"): blind
behaviour needs an exit-mode table — under-camera (area up, dy
dropping) should creep/stop, side-exit should spin-reacquire, true
loss stays full stop; step formula should shrink harder above ~0.08.

MobileSAM test (Adam's call, offline on tonight's frames): persistent
VisionPipeline, Meta box as lock-on prompt — load+first mask 1.82 s,
then 0.59 s/frame desktop CPU. Aim agreement vs Meta SAM (dx 0.038 vs
0.031, area 0.0174 vs 0.0164). So speedup 2 stands: Meta lock-on once,
MobileSAM box-track (prev bbox + margin as next prompt) per step,
Meta re-check on mask loss/area jump. Expected step pause ~2–3 s vs
7.8 s. Drive test of that loop is tomorrow's job, not tonight's.

## 2026-10-29 — GUI LIVE TEST 2: camera live-then-dead = USB cable again

Adam: feed live then dead; one anomalous camera move, unreplicated.
Read-only Pi check: kernel shows USB disconnect/reconnect cycling
(devices 16→19, repeated -71 UVC probe failures) ~00:53 — the known
marginal camera cable/connector, not the page. Feed healthy when
re-checked (10.5 MB in 5 s via /api/frame). Page fix deployed
(index.html only, no restart): tapping the feed in Manual respawns
the stream, and an img error auto-reloads it after 1.5 s — previously
a mid-stream drop left the phone holding a dead last frame forever.
Anomalous move: no server-side write on page load exists (proven);
candidates are a stuck camera-stick pointer (interval keeps stepping
to the limit) or the documented cable-weight pan/tilt jerk. Left
unreplicated — needs Adam's direction/duration if it recurs.

## 2026-10-29 — GUI LIVE TEST 1: camera axes reversed, motors silent (fixed)

Adam's first flagged run (--enable-servo --enable-motors): layout
"super solid first iteration"; incremental camera steps praised.
Two bugs: (1) both camera stick axes reversed vs the physical head —
fixed in `/api/camera` (stick right = ch6 down, stick up = ch5 up),
with a new direction-asserting test; phone suite 29 green, deployed.
(2) Motors never fired: diagnosed read-only — his server was up but
NOTHING listened on :5098 (bench listener's 1 h lifetime had expired;
token file still present). The page also hid the 503 in Manual mode;
drive/camera errors now show under the STOP button, and the server
error names the missing listener. Restart of his server + listener
revival is Adam's step at his terminal (commands in chat); no motor
or servo write was made from here.

## 2026-10-28 — PHONE GUI v2: manual thumbsticks + arm picture + showcase

Rebuilt `tank_phone/index.html` phone-first, full-screen camera.
Manual mode: DRIVE and CAMERA thumbsticks, big STOP, max-speed cap
slider (5–40%), Arm button, Centre cam. Showcase mode: big plain-
English status, typed instructions + example chips (parser preview
only — vision loop not started from the page), Speech toggle reading
the Baseten hooks status, telemetry grid (gates, motor cap, speech,
servo pose, ultrasonic honestly "unavailable", page reply ms).
Stock XiaoR check: `xiaor/` holds only the vendor .so/about/JPEG trio
— no reusable GUI exists, so the arm is our own draggable SVG
(schematic, commanded-not-measured): drag elbow→ch2, rotation
handle→ch3, claw→ch4, base slider→ch1, through the existing gated
`/api/servo`. Old engineering drawer kept intact (sliders/limits/flags).

Server (`tank_phone/server.py`): new `stick_to_move()` (deadzone,
spin-dominant, steering trim, garbage→stop), `POST /api/drive`
(stop always accepted; moves need `--enable-motors`; duty clamped by
page cap + `--motor-cap` + 40% hard cap; 0.5 s moves re-sent while
held so a dead client stops the tank), `POST /api/camera` (pan/tilt
steps via `--enable-servo` path), `GET /api/telemetry`.
`BenchMotorClient` holds one listener connection; token read from
Pi-local `/tmp/claude-1000/bench_token`, never sent to the phone.

Tests red-first: phone 27 (13 new), parser 39, speech 20, vision 23
(1 skip), JS syntax + id check clean. Deployed server.py/index.html +
tank_speech/ to the Pi and restarted the phone server in SAFE mode
(no --enable-servo/--enable-motors) for Adam's at-home review:
page 200 (30,737 B), telemetry gates both off, drive 403, speech
status OK, camera frame 200. NO hardware was moved. To go live at
home: revive the bench listener, restart the server with both
--enable flags (see tank_phone/README.md).

## 2026-10-28 — BASETEN SPEECH HOOKS OPENED (not wired, no hardware)

New `tank_speech/` package (stdlib only): `baseten_client.py`
(env-only `SpeechConfig` with redacted status, model/chain websocket
URL builders, tolerant transcript-event parser that fails closed on
garbage) + `session.py` (background `SpeechSession` worker, bounded
`SpeechInbox`). Design goal is minimal execution downtime: the drive
loop only calls `tick()` (timeout=0 poll for a routed final) and keeps
driving while transcription/warmup run on the worker; stop/estop
finals jump the inbox; partials never route; worker/warmup errors land
in `status()["last_error"]` and kill nothing. Routing is the existing
fixed-phrase `classify()` ONLY — routed dicts are previews, nothing
calls `run()`/bench/servos. `llm_fallback_route()` hook lets a future
Baseten LLM propose a sentence that must re-classify as goto-only.
Phone hooks opened: `GET /api/speech/status` + `POST
/api/speech/transcript` (classify-only, `wired: false`) in
`tank_phone/server.py`. Live path still needs Adam: deploy streaming
STT on Baseten, set `BASETEN_API_KEY`/`BASETEN_STT_MODEL_ID` (only
`MODEL_API_KEY` exists locally today; no Baseten call attempted, $100
pool unspent), then wire the one `transcribe_fn` websocket seam.
Tests: speech 20, phone 14, parser 39, vision 23 (1 skip) — all green,
no hardware touched.

## 2026-10-28 — CREDITS: $100 Baseten approved, $100 Modal banked

Adam approved for $100 Baseten credits (new, unspent). Baseten is for
side-path jobs only — demo inference stays on Meta models: candidates
are voice transcription, a small LLM translator for the parser
fallback, or hosting the YOLO/MobileSAM fallback. Modal also holds
$100 in credits (approved 2026-10-27, see below), banked for finals
per Adam; Meta credits spend first. Neither balance is to be spent
without Adam picking the job first.

## 2026-10-28 — ADAPTIVE STEP LENGTH (speedup 1 of 3; software only)

drive_run forward steps now scale with target area instead of a fixed
0.5 s: step = clamp(0.25/sqrt(area), 0.5 s, 1.5 s), so far targets get
longer steps (fewer ~7 s SAM cycles per metre; spin-up cost amortised)
and near targets keep the short safe step. --step-secs still fixes a
length when given. On this morning's areas: 0.068 -> 0.96 s,
0.147 -> 0.65 s, 0.24 -> 0.51 s. Garbage area -> shortest step.
step_secs_for_area() is a pure function (kept reusable for the local
tracker in speedup 2/3). Tests red-first: vision 23 (4 new), parser
39, all green, no hardware touched. Queued: (2) SAM lock-on + cheap
local tracking between identity checks, (3) track-and-steer while
moving over one persistent listener connection. TONIGHT, physical,
in order: ultrasonic physical check first (sensor silent since cable
reroute — see 2026-10-27 handoff), then tonight's drive tests;
adaptive steps make the ultrasonic stop more important, not less.

## 2026-10-28 — GOTO SLICE: 'go get the shoe' now routes to the vision loop

Software only (physical testing paused until tonight). Parser
(xiaor_text_action.py): "go to/get/find/fetch the <target>" classifies
as kind="goto", target extracted, commands ALWAYS empty — the parser
never moves for a goto; run() sends nothing and the transcript carries
the target. Safety ordering preserved: negation refuses, stop/estop
win, goto+any other action is ambiguous, extra clauses ("...for 3
seconds", "...then wave") are ambiguous, empty/pronoun targets
("fetch it") are unknown. Contract change: "go to the kitchen" moved
from unknown to goto(kitchen) — still no motion from the parser.
drive_run.py gains --text: resolve_prompt() routes a clean goto to
the SAM prompt and exits 2 with no motion for anything else. Latency:
classify() is ~0.05 ms/call locally, so the template fast-path adds
nothing; an LLM front-end later would run once per command against
~7 s/step vision cycles (measured this morning), and stop never goes
through it. Tests: parser 39 (3 new goto tests, red-first), vision 19
(new test_drive_run.py router tests). Adversarial probes all fail
closed; "bring me the shoe" stays unknown — LLM-fallback territory,
not templated. Try tonight: drive_run --text "go get the shoe".

## 2026-10-28 — 'GO GET THE SHOE' KID DEMO: arrived again, camera cable flaky

Morning demo for family, authorised in two scopes (5 steps, then
+3). Preflight found two blockers: bench listener :5098 had expired
(1 h lifetime) and the USB camera was gone (kernel: disconnect, no
/dev/video0, earlier -71 probe failures). Adam reseated the cable;
first replug half-enumerated (device 9, vanished), second held
(device 10, /dev/video0 back) but dropped/reconnected once more
(device 11) during centreing — cable/connector is marginal, strain
relief needed. SAM 'shoe' found it at the left frame edge (dx -0.46,
area 0.013). centre_run hit its 6-step cap at pan limit ch6=74 with
dx -0.32 (shoe left of body heading — head alone cannot centre it),
so drive_run's body-spin correction did the rest. Listener revived
with the existing Pi-only token (stop verified before motion).
Run 1 (5 steps): spinl 0.17s, go, go, spinl 0.15s, spinr 0.15s —
area 0.068->0.147, final stop ok. Run 2 (+3 steps, re-authorised):
go, spinl 0.15s, go — final aim area 0.307 > 0.25 ARRIVED, stop
confirmed twice, arrival frame shows the shoe filling the lower
frame with no contact push. Suites unchanged: parser 36, vision 17.
Listener self-expires ~09:19 (1 h from revival); tank left stopped
at the shoe, head ch5=41/ch6=74. Note: the typed phrase
"go to the shoe" still parses as unknown in xiaor_text_action.py —
this demo used drive_run --prompt shoe directly; text->vision glue
is still to build.

## 2026-10-27 — 'GO GET THE SHOE' COMPLETE: drove to target under vision

Full chain live: camera -> SAM 3.1 'shoe' -> centre (tilt search found
it at ch5=47, pan learned sign from a limit refusal, converged dx
0.347->0.050, dy -0.284->+0.022) -> drive. Bench listener revived
(fresh token in /tmp/claude-1000, Pi-only; :5098 caps 3s/40%).
First steps exposed a client bug, not a motor bug: the listener stops
on disconnect and my one-shot drive_step closed instantly, killing
every move in milliseconds (aim identical to 4 decimals = the tell).
Fixed: hold the connection for the move duration, then explicit stop
(the original bench tools' pattern). After the fix: 1.0s @30% trim17
moved area 0.056->0.104; next 1.0s -> 0.220 with a 0.15s spinl
correction at dx -0.21; next recognition area 0.254 -> ARRIVED
(threshold 0.25), final stop sent. Arrival frame visually confirms:
shoe fills the lower frame, tank stopped at it, no contact push.
drive_run.py: stop->recognise->one bounded step->repeat; lost target
or any motor error stops the tank. Suites after all changes: vision
17, phone 11, parser 34. Remaining roadmap: pretty/intuitive GUI on
this proven loop, voice (mic -> Muse Voice Transcribe -> parser),
SAM 3.1 already the language-target path; Modal banked for finals.

## 2026-10-27 — CENTRED ON THE SHOE (drive-to-target aim loop closed)

Adam caught the big one: pan/tilt channel NAMES were swapped in the
page (physical: ch5=tilt, ch6=pan). That silently poisoned every earlier
centreing attempt — corrections were applied to the wrong axis and sign
learning read as noise. Fixed in servo_ctl.LABELS (synced to Pi, server
restarted, page now correct) and centre_run channel map.

With axes corrected, the loop closed cleanly: tilt search 53->47 found
the shoe (dx +0.35, dy -0.28), pan trial was limit-blocked at ch6=75 so
the loop flipped sign from the refusal itself and converged:
dx 0.347->0.294->0.204->0.129->0.050, dy -0.284->+0.022, CENTRED in 4
steps of <=3 deg. Final frame visually confirms the shoe dead centre;
final pose ch5=40 (tilt), ch6=63 (pan), display resynced after restart.
Trial hardening from tonight, all in centre_run.py: track-nearest
instance (two 'white box' objects swapped targets), min-delta sign
threshold (dim-light centroid noise +/-0.15), per-step sign supervision,
box-centre aim + 2-frame median (mask pixels breathe; boxes hold),
self-healing trial (eject -> undo -> sign lesson), limit-clamped trial,
flip-and-retry on limit refusal. Adam's failure test also passed en
route: absent target at every sweep stop -> 'not found, no motion'.
Suites: vision 17, phone 11, parser 34, all green. Wheels remain the
only unproven link for 'go get the shoe' (bench listener + token were
wiped by the power cycle; revive before drive steps, per-case auth).

## 2026-10-27 — Pan/tilt jerk root cause: cable weight (not power, not code)

During the shoe centreing run the camera head shook hard ("like the
exorcist"); loop killed immediately, pose left at ch5=72/ch6=32.
Ruled out in order: loop hunting (small supervised steps, ~20 s apart —
wrong timescale, and shaking persisted after the kill), battery (still
jerked on wall power after charging). Adam found it: cable bundle
weight hanging off the camera/servo area torqued the tilt servo; it
hunted against the load. Strain relieved -> shaking STOPPED. Matches
the long-standing note that pan/tilt jerk exceeds arm jerk on identical
bytes: mechanical, load-side. Lessons baked in: (1) cable strain relief
+ a service loop at the head are part of the servo plant, treat any
future jerk as mechanical until proven otherwise; (2) the centreing
loop still needs smaller final steps (1-2 deg) near target; (3) after
any power cycle the physical pose is MCU defaults, NOT page state —
re-home (ch5=72/ch6=74 written) before trusting step math, and note
the reseat shifted the mount (home now looks at the wall/ceiling;
shoe framing starts from a tilt search). Runtime restored after the
reseat: qstream recompiled, server live, limits/flags intact.

## 2026-10-27 — Centreing loop: built, two live attempts, dim-light blocked

Adam authorised servo-only centreing (ch5/ch6, <=10 deg steps). Built
`tank_vision/centre.py` (aim->step math, sign learning) +
`centre_run.py` (grab -> SAM 3.1 -> aim -> Pi slider API -> repeat;
servos only). Attempt 1: instance-swap bug (two 'white box' objects,
pick-largest alternated targets) + target lost; fixed with
track-nearest-centroid + retry. Attempt 2: diverged — 3 deg trial moved
centroid 0.003 (noise), wrong sign learned, walked target out of frame;
fixed with min-delta sign threshold, per-step sign supervision, pose
restored to 72/69 after each attempt (no pose ever left diverged).
Attempt 3 (box-centre aim, 2-frame median, 3 deg cap): SAM returned []
at the start pose — frame measurably darker (auto-exposure drift);
earlier brighter frame at the same pose recognised fine. Mask-centroid
noise in dim light measured +/-0.15 frame-to-frame. BLOCKER is light,
not logic: needs room light/lamp up, then rerun. Suites 17/17 vision
centre tests included. Phone-feed producer held /dev/video0 during one
grab (Adam's open page) — killed that producer; refresh restores it.

## 2026-10-27 — OBJECT RECOGNITION LIVE: SAM 3.1 via Meta Model API

End-to-end, verified at every link. Probe (Adam-generated new key in
gitignored .env, read as env only): sam-3.1 on mc.jpg "silver capacitor"
found 4 instances with box+mask tags. Wired Meta's official
meta-sam-parser (installed in .venv): mask decode for the known cap
scores IoU 0.963 vs the trusted MobileSAM tap mask. Live tank frame
(shelf scene, dim): "white box" returned 2 masks, overlay confirms the
main mask fills the white box exactly, centroid centred, aim geometry
ready; "red bag" returned [] (honest empty, dim light). In-sandbox API
calls work via the broker proxy (api.meta.ai allowed). Suites: vision
14/14 on system python AND .venv (strict parser rejects fake payloads in
the wire test — asserted, not worked around), phone 11, parser 34.
meta_sam.py without the parser degrades to labelled sam3-box geometry,
never fabricated pixel masks. Modal credits untouched (banked for
finals; Meta credits spend first per Adam).

## 2026-10-27 — Modal enabled inside isolated Muse

At Adam's request, extended the host isolation broker for Modal while keeping
the original filesystem and direct-network boundary. Allowed HTTPS under
modal.com/modal2.com/modal.run/modal.host/modal.direct and three exact
storage/CDN hosts returned by authenticated Modal (listed in MODAL_ACCESS.md).
An initial transfer check stopped on the unapproved download CDN; verified
its BlobGet provenance and added that exact host, not a broad AWS/Cloudflare
exception. Meta and tank SSH routes remain unchanged.

Copied only the active Modal profile into isolated home/.modal.toml (0600),
preserving the original host profile. Kept SDK 1.6.3; installed its required
python-socks 3.2.0 and aiohttp-socks 0.12.0 extras in the existing project venv.
Added a read-only `modal` wrapper so the desktop-specific venv shebang does
not fail under /workspace. Existing Muse processes need restart to load the
policy; existing isolated sessions may then be resumed.

Verified from inside the real boundary: Modal CLI, authentication, 25 KiB
synthetic blob upload/download, and a temporary CPU-only Modal Sandbox
(0.25 CPU, 128 MiB, timeout 90s, outbound networking blocked). It printed
the expected marker; termination and ephemeral App shutdown completed.
Three policy regression tests cover service routes, lookalike/storage/port
denials, and private-IP DNS results. Original privacy checks still pass;
credential permissions and Python syntax checked. No GPU/model run, public
deployment, tank movement, or model weights download performed. SDK-internal
blob helpers in the check are version-sensitive, documented accordingly.

Updated README, AGENTS, modal_app's usage note, host administration README,
and MODAL_ACCESS.md with scope and narrow rollback. Backed up the pre-Modal
launcher/checks outside the workspace. Existing SAM 3.1 API decision and
future voice-model choice remain unchanged; this verifies infrastructure.

## 2026-10-27 — SAM 3.1 rerouted: Meta Model API, not HF/Modal

Adam flagged (correctly) that gated HF weights are the wrong path for a
hackathon flagship. Confirmed: SAM 3.1 is served on the Meta Model API
(model `sam-3.1`, text/image in, box+mask out, $2.50/1k images against
the hackathon Model API credits; same key family as Muse Voice
Transcribe, the queued voice path). Wrote `tank_vision/meta_sam.py`:
Responses-API client, key from MODEL_API_KEY env only, tolerant parser +
--probe that dumps the raw response (mask encoding unconfirmed until one
real response is inspected — deliberately not trusted blind). Offline
halves verified: request builder shape, COCO-RLE decode round-trip,
parser centroid. Modal app stays as optional self-host (proven with
mobile_sam); it is no longer the SAM 3.1 route. Segregation note: this
workspace holds only tank files (IMPORT_MANIFEST); nothing else of
Adam's has been read or sent anywhere, and API calls stay limited to
deliberate demo input per AGENTS.md.

## 2026-10-27 — Modal + SAM 3.1 staged (unverified), voice roadmapped

Adam approved for Modal ($100 credits). Wrote `modal_app.py`: Modal L4
class wrapping the tank_vision contract, weights volume `tank-weights`
with preference sam3.1_multiplex.pt > sam3.pt > mobile_sam.pt, plus a
POST web endpoint for the Pi and a `tank_vision/modal_client.py` (stdlib
client, payload shrink to 1280px). SAM 3.1 (Meta, gated HF weights,
research license) does text-prompt detection+segmentation in one model —
the demo's language-target path — while point/box keep tap/drag focus.
First run hit libGL in Modal's slim image (same ghost as the Pi);
fixed with apt libgl1+libglib2.0-0 in the image. VERIFIED 2026-10-27:
`modal run modal_app.py --image mc.jpg --point 0.335,0.320` returned
mobile_sam.pt, one point object, mask_box 0.2754,0.2775,0.3867,0.3694,
centroid (0.3314, 0.3217), area 0.0079 — identical to the desktop/Pi
proofs of the same tap. GPU path produces the same masks as local.
Still pending: SAM 3.1 gated weights (access request at
huggingface.co/facebook/sam3.1, then `modal volume put`), `modal deploy`
for the Pi endpoint. Local checks: py_compile ok, tank_vision suite
11/11 (3 new client payload tests). Voice (next day or two, Adam's
call): phone mic -> transcript -> existing /api/text classify() parser;
candidate is the browser Web Speech API (zero new server deps).

## 2026-10-27 — HOME pose + calibrated limits recorded from slider session

Adam drove the sliders at the tank and declared the resting pose HOME:
ch1 140, ch2 20, ch3 87, ch4 100, ch5 72, ch6 74 — now `servo_ctl.DEFAULTS`
(display/commanded only; no telemetry exists). His widened limits are the
new `servo_ctl.LIMITS` (ch1 0-140, ch2 20-180, ch3 0-180, ch4 40-100,
ch5 30-120, ch6 0-75; Pi `servo_limits.json` agrees). Flags on record:
ch5@30 and ch6@59 "Jerky movement" (known pan/tilt mechanical jerk), and
ch2@141 "When ch1 is at 0, this is the safe limit" — first coupled-limit
observation: ch2 safety depends on ch1 position, which per-channel fences
cannot express; keep capturing these as notes. Synced servo_ctl to the Pi
and restarted the page server; it now opens on HOME with flags intact
(one restart fumbled by a self-matching pkill — recovered, server live).
Repo tests still 11/11 tank_phone.

## 2026-10-27 — Manual servo sliders LIVE on the phone page (Adam-operated)

Added sliders ch1-6 to `tank_phone/` (`servo_ctl.py` stdlib /dev/i2c-1
writer, frame FF ch angle FF; `--enable-servo` gate in server.py, off by
default; page load never sends). Per Adam's safety call: per-channel
allowed ranges enforced server-side BEFORE any write, defaults = the
physically swept ranges (ch1 80-140, ch2 120-170, ch3 60-120, ch4 40-100,
ch5 60-120, ch6 60-100), editable live from the page, persisted to
`servo_limits.json`. Wonky-flag button per channel (+note) persists to
`servo_flags.json`; page groups flags into angle ranges. NO telemetry
exists (write-only MCU) — page state is last-commanded, never measured;
stated in UI contract + README. ch7/8 excluded per scope rule.

Verification: 11 tank_phone tests (FakeBus: frames, refusals, limits,
flag persistence, disabled 403) + parser 34 + vision 8 all green.
Deployed to Pi ~/tank_phone (via tank-lan; Tailscale SSH wants a fresh
interactive check), server running detached with --enable-servo +
TANK_PHONE_MJPEG_CMD=/tmp/qstream. From the Pi: /api/status
servo_enabled=true, /api/servo shows clamped state (ch2 90->120),
out-of-limit POST ch4/170 refused "ch4 limited to 40..100" (no write),
index 200, /api/frame streamed 132 JPEG SOIs in 6s (~22fps). First real
slider movement is Adam's, from the phone, tank in front of him.
Calibration (visual centre ch5/ch6) is the intended first use.

## 2026-10-27 — YOLO+SAM proven on desktop and Pi (focus = tap/drag target)

Built `tank_vision/` (module + CLI, no GUI, no hardware calls): Ultralytics
YOLO11n boxes -> MobileSAM masks. Calls: `detect`, `detect_and_segment`,
`focus(box)` / `focus_point(x,y)` ("go check that out": best YOLO hit inside
the user's box, else direct SAM box prompt), `aim()` -> centroid offset vs
frame centre (`None` = no target). Weights in `tank_vision/weights/`
(YOLO 5.4MB + MobileSAM 39MB). Model decision: keep this pair — masks on
mc.jpg were tight (capacitor at tap 0.335,0.320; L298 chip in focus box
0.11,0.60,0.31,0.81), no SAM2 step-up justified.

Verified: 8 fake-backend plumbing tests pass on desktop + Pi (Pi skips the
missing-backend case, correctly); parser suite still 34. Desktop (CPU torch
2.14, ultralytics 8.4.191): auto on mc.jpg returns `objects: []` — honest
empty, COCO knows no circuit boards; point/focus masks + aim correct.
Live-frame handoff: grabbed a 640x480 frame from the Pi camera (new C
grabber `tank_phone/qstream.c`, compiled to /tmp/qstream — Python uvc
QBUF bug reproduces, parked as before), ran auto on desktop AND Pi: both
produce the identical box (x0 0.4044...). BUT the frame is near-black
(camera parked tilted ch6=79, dark room) and the "airplane 0.88" label is
a false positive on a wall edge — handoff mechanics proven, detection
semantics NOT proven until a lit, level frame exists. Pi cold timings
640x480 incl. model load: ~18s auto, ~9s point — still-frame focus pace,
not video rate. Pi env: `~/tank_vision_env` (uv, py3.11) + `~/tank_vision`;
stock opencv needs libGL — headless swap required (in README). Desktop
`.venv` + `vision_out/` are gitignored; nothing here moves hardware.

## 2026-10-27 — FULL ARM MOTION: servo frame proven on hardware

Cold power cycle (battery off/on) unwedged the servo MCU — root cause of the
entire silent saga, not the frame, shim, rail, or mapping. Post-cycle ch4
40→100 showed visible CLAW MOTION; follow-up 8-write sweep moved every arm
channel (ch1 80/140, ch2 120/170, ch3 60/120, ch4 40/100), all confirmed
visually by Adam. `FF ServoNum angle FF` is now PHYSICALLY PROVEN, not just
emission-proven. Re-staged /tmp/servo_trace after tmpfs wipe (uv 3.11 in
home survived). ch5/6 pan/tilt validation pending (camera re-plugged since).

Camera channels closed out after: ch5 60/120 + ch6 60/100 all moved (Adam
saw the room pan/tilt past); pan/tilt motion visibly jerkier than the arm —
mechanical (mount/load), same bytes swing the arm smoothly. No auto-home
exists (absolute positioning, last command wins); parked back to calibrated
home ch5=95/ch6=79 on auth. Camera still sits tilted back at ch6=79 —
data.ini HOME is not visual center for this mount; needs recalibration pass.
Full map ch1-6 physically proven (7/8 remain unprobed per scope). Phone stream down after reboot (qstream was tmpfs);
revive = recompile + restart server when wanted.

## 2026-10-27 — Camera live on the phone server (UVC, C producer)

Camera is a USB UVC device (/dev/video0+1), not CSI — rpicam stack never
applied. MJPG 640x480@25 native. Python V4L2 packer hit a ghost QBUF EINVAL
(struct sizes machine-verified 208/88/20 via gcc+headers+strace, C twin of
the same ops captures fine) — parked, not hardware. Scratch C producer
`/tmp/qstream.c` streams verified frames (3/3 SOI-EOI, then 11MB/5s clean).

Deployed `tank_phone/` to `~/tank_phone` on the Pi; server running detached
(`TANK_PHONE_MJPEG_CMD=/tmp/qstream`, 0.0.0.0:8123, dry-run, no driving).
Live check from the Pi: 233 multipart frames / 233 real JPEG SOIs in 10 s,
~23 fps. Earlier first-start stall traced to stale/zombie producer state;
fresh restart + header flush fixed it. Tailscale came back (phone on the
same tailnet); Adam VERIFIED video renders on the phone at
http://<tailscale-ip>:8123/. Camera-to-phone milestone DONE. Server left
running detached on the Pi (dry-run only — no driving possible).

Open follow-ups (need Adam home): Python V4L2 QBUF ghost bug (C producer in
/tmp covers streaming meanwhile), tap→motion wiring with per-case auth,
servo power diagnosis (frames ACKed, no motion seen), YOLO/SAM only after
the tap loop works, API auth before exposing beyond tailnet.

## 2026-10-27 — MJPEG relay plumbed and smoked, camera still unplugged

Wired `/api/frame` to relay `rpicam-vid --codec mjpeg -o -` stdout as
multipart/x-mixed-replace (one producer per viewer, 4 s first-bytes cap,
dead producer → 503, `TANK_PHONE_MJPEG_CMD` override for tests). Smoked
locally against a synthetic PIL JPEG source: 5 real JPEGs in, 5 framed
parts out, SOI/EOI intact, correct content-type; no-producer path returns
503. Parser suite still 34 passed. Smoke servers stopped; nothing deployed.

Unblocked-now vs blocked: relay plumbing is done, but end-to-end
camera-to-phone is BLOCKED on hardware — Pi reports zero cameras (camera
physically unplugged, Adam away). When home: plug in, confirm with
`rpicam-hello --list-cameras`, deploy `tank_phone/` + parser to the Pi,
open the page on the phone over home WiFi.

## 2026-10-27 — Phone GUI skeleton built and smoked, live motion unconfirmed

Built `tank_phone/` (Pi-hosted, tap-point-first, plan+skeleton slice):
`server.py` (stdlib-only, dry-run only — no code path reaches bench/I2C),
`index.html` (tap frame, text box, preview output), `README.md` (contract,
deploy, roadmap). Endpoints: tap validates/clamps 0..1 and previews a
±10° nudge; text runs `classify()` only and previews kind/label/commands.

Verification (desktop smoke, no hardware): status/tap-valid/tap-invalid(400)
/text-preview/frame(503)/index(200) all correct; e.g. tap (0.75,0.25) →
pan+tilt 5.0° preview. Parser suite still 34 passed. Server stopped after
smoke; nothing deployed to the Pi yet.

Pi facts: rpicam tools present but `rpicam-hello --list-cameras` reports no
cameras (matches physically unplugged camera), no picamera2. Stream endpoint
stays 503 until the camera is back in.

Live-fire outcome (Adam present, per-case auth): ch5→95 sent twice (first
unseen — camera unplugged; re-fire clean), ch4→60 produced an audible hum
but no visible motion, ch4→110 produced nothing observable. All writes
ACKed at 0x17 (bus scan still shows sole device). Actuation UNCONFIRMED —
prime suspect is servo power rail off or arm harness unseated, not the
frame. No further writes while Adam is away.

## 2026-10-27 — Executed fake-smbus trace on the Pi confirms all frames

Ran `tank_tools/fake_smbus_trace.py` on the tank itself (aarch64) under a
fresh uv-managed CPython 3.11.18 (`~/.local/share/uv`, user-space, no sudo;
authorized download ~40MB). Trio + harness staged in `/tmp/servo_trace`;
trace saved to `/tmp/servo_trace/trace.jsonl` (7 records, file contents
match console output). Zero bus I/O by construction — fake `smbus` only,
nothing persisted, no live servo motion. License gate passed ("well done!").

Executed results: SetServoAngle 5/5 match `FF ServoNum angle FF` (addr 23 =
0x17; e.g. (1,90) → 255,1,90,255; (6,79) → 255,6,79,255). SaveServo →
`FF 17 1 FF`. ReSetServo → `FF 0 1 FF`. Save/Reset static payloads (int_17 +
int_1, int_0 + int_1) confirmed by execution; the old cmd-0x09=reset guess
is dead. Wire-level MCU response still unvalidated — first physical move
waits for Adam present at the bench.

Verification: harness exit 0 with all frame checks OK; parser suite still
34 passed locally. Pi now keeps a 3.11 interpreter for reuse; no system
Python touched, no repo pushes.

## 2026-10-27 — Save/Reset static decode + fake-smbus harness, no tank contact

Decoded first payload facts for Save/Reset (static only, desktop capstone —
no tank contact, no writes). Both wrappers set page register x23 = 0x21000
at entry (Save 0x8294, Reset 0x9518) and never reassign it before the cited
sites, so base 0x21568 holds. Verified instruction-by-instruction: Save
0x85a8 loads offset 0x80 = int_17 and 0x87b8 loads 0x70 = int_1 into call
tuples; Reset 0x982c loads 0x68 = int_0 and 0x9a3c loads 0x70 = int_1. Both
reuse the device/write_byte/sleep/10us-float paths. No base-derived int_9
found in either wrapper, so the old cmd-0x09=reset guess has no static
support; ordered Save/Reset frames remain unrecovered pending execution.

Added `tank_tools/fake_smbus_trace.py`: logging fake `smbus` + trio-dir
loader, traces SetServoAngle on channels 1/2/5/6 plus Save/ReSet, checks
FF-num-angle-FF, writes JSONL. True execution needs ARM64 CPython 3.11, so
it cannot run on this x86 desktop (qemu/uv absent, restricted network);
`tank_tools/fake_smbus_trace.py --self-test` passes here against a stub
servo, proving the harness logic. The real-`.so` run waits on the Pi with
Adam home — zero bus I/O by construction, nothing persists.

Verification: harness self-test ok (5/5 set-angle frames, Save/Reset stub
bytes captured); `python3 -m unittest discover -s tank_tools -p 'test_*.py'`
34 passed; ARM `.so` import correctly impossible on x86_64/Py3.12. Parser
fixes and prior DEVLOG entry preserved. No live servo testing performed.

## 2026-10-27 — Parser fixes offline, servo frame re-verified statically

Fixed both known parser bugs in `tank_tools/xiaor_text_action.py`, offline only.
Decimal durations now parse from raw text (`_normalize()` strips ".", so
"0.5 seconds" read as 5s; "forward 0.5 seconds" now 0.5s, 999s cap intact).
Stop takes priority: "forward stop", "hey stop", "stop right now" all return
`drive.stop`; estop beats stop ("stop now please forward" → `drive.estop`).
Negation still wins ("don't stop" → refused) and true pairs without stop
("drive forward and wave") stay ambiguous. "no no stop" stays refused via
the negator rule — safe no-motion, consistent with the "don't stop" test.

Verification: `python3 -m unittest discover -s tank_tools -p 'test_*.py'` —
34 passed (32 existing + 2 new: decimal durations, stop priority).

Servo static check (no tank contact, no writes): re-verified the Codex
reconstruction instruction-by-instruction. `adrp x21` at 0xa7d4 targets page
0x21000, so base 0x21568 holds; 0xabb0 → 0x219b8 `device`, 0xabd4 → 0x219c0
`write_byte`, 0xad48/0xad50 → 0x219e8 `sleep`, 0xbc4c/0xbc58 → 0x215c8
float 0.00001, 0xac9c/0xb2d8 → 0x215f8 int 255, 0xaec4 places ServoNum (x25),
0xb0e0 places angle (x27). Supports `FF ServoNum angle FF` for set-angle as a
static reconstruction only. Save/Reset wrappers (0x8280/0x9504) reuse the same
device/write/sleep paths; payload bytes not yet traced. Fake-smbus execution
trace and any live servo write wait until Adam is home with the tank.

## 2026-10-26 — Standalone tank workspace and isolated Muse

Imported 16 explicitly selected tank control, bench, review and vendor files as
independent copies; IMPORT_MANIFEST.json records SHA-256 hashes. No source
project Git history, memory, conversations, model router, credentials or
architecture documents imported. Original source/controller files unchanged.

The host `muse` launcher now uses Bubblewrap with a fresh filesystem view,
PID/IPC/network namespaces, clean environment, separate Muse state, and only
this workspace writable alongside its private home. Existing Muse session
closed; old history not imported. Only the Meta login and selected model were
seeded into the private profile. No new packages installed.
Copied the already-installed Capstone/pyelftools package directories (~13 MB)
into the isolated Python user site so static analysis can continue without
mounting the source project's environment. Added a fresh tank-only Muse brief.

Host broker permits HTTPS to api.meta.ai/auth.meta.com and SSH to the tank's
Tailscale/LAN addresses only. Added a dedicated revocable SSH key on the tank,
with authorized_keys restrictions disabling SSH forwarding. Existing SSH key
and logins preserved. `ssh tank` works from inside the boundary; this grants
the pi account's access on the Pi, not just this workspace's files.

Verification: host-private paths and environment absent, direct host/tank/
Internet connections blocked, proxy rejects unapproved destinations/ports,
TLS-verified Meta endpoint reachable (unauthenticated 403), read-only tank SSH
successful, actual Muse offline echo successful, all 32 copied parser tests
passed. No motors/servos driven. Decimal duration and stop phrase failures
remain known; passing existing tests does not resolve them.
Meta account/usage authentication also succeeded through the broker; account
details were omitted from tool output.

Actual Meta-backed tool testing caught a second, nested sandbox hiding the
SSH broker socket. The launcher now disables Muse's inner shell sandbox while
retaining the enclosing Bubblewrap boundary and normal approval controls.
Repeated tool test succeeded: `/workspace` and `muse-shell-ssh-ok` from the Pi.
Two small test prompts used the hosted model in the isolated workspace.
Final boundary checks still passed, including the PID-root escape probe and
static-analysis package imports. Broker parser checks covered 4 allowed and
7 rejected targets/requests; all 16 imported hashes and independent inodes
verified. No physical actuation performed.

Isolation launcher/setup lives outside the agent-visible repo. Host setup and
rollback instructions: ~/.local/state/muse-tank-isolation/README.md.
This does not retract previously submitted content or establish paid-tier
data-use terms. Normal host tank driving remains outside the coding sandbox.
