# DEVLOG — multimodal teleoperation

Newest first. Record verified results separately from proposals and live tests.

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
