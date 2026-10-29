# tank_phone — phone GUI for the tank

Pi-hosted web page: camera frame, tap/text previews, and manual servo
sliders (live only behind `--enable-servo`). No motor path exists here.

## Layout

- `server.py` — stdlib-only HTTP server + JSON API (port 8123).
- `index.html` — phone-first full-screen GUI. Manual mode: drive +
  camera thumbsticks, big STOP, max-speed cap, draggable arm picture
  (our own SVG; the stock XiaoR files contain no GUI), servo engineering
  drawer (sliders ch1–6, limits, wonky flags). Showcase mode: typed
  instructions with plain-English status, speech toggle (Baseten hooks),
  telemetry panel.
- `servo_ctl.py` — stdlib I2C servo writer (`/dev/i2c-1`, addr 0x17, frame
  `FF ch angle FF`). Channels 1–6 only; 7/8 unprobed by scope rule.
- `qstream.c` — V4L2 MJPEG camera grabber (the Python packer hits a QBUF
  ghost bug; this C twin works). Build: `gcc -O2 -o /tmp/qstream qstream.c`.
- `servo_flags.json` / `servo_limits.json` — wonky flags and per-channel
  allowed ranges, written by the server at runtime on the Pi
  (`~/tank_phone/`); not source. Default limits are the physically swept
  ranges in `servo_ctl.LIMITS`. There is no position telemetry (write-only
  MCU); page state is last-commanded, never measured.

## API contract

- `GET /` — the page.
- `GET /api/status` — `{"ok", "servo_enabled"}`.
- `POST /api/tap {"x","y"}` — floats in 0..1. Preview only (±10° nudge).
- `POST /api/text {"text"}` — runs `classify()` ONLY. Preview only.
- `GET /api/speech/status` — Baseten speech status; `wired` is true only
  when a live STT session is running (key + deployed STT model in env).
- `POST /api/speech/transcript {"text"}` — speech-final landing hook;
  runs the speech router (`classify()` only). Preview only.
- `POST /api/speech/audio` (raw `audio/wav`, ≤2 MB) — one mic utterance
  → Baseten STT on the background worker → routed parser preview.
  503 unconfigured, 415 non-audio, 413 too long, 504 nothing heard.
  Preview only: no path from here to motors or servos.
- Showcase Hold-to-talk: primary STT is the phone browser's own
  `SpeechRecognition` (finals → `/api/speech/transcript`); the WAV
  upload above is only the fallback when the browser lacks it. Baseten
  credits are Muse-Spark-only, so no Baseten STT is required.
- `GET /api/frame` — MJPEG relay from `TANK_PHONE_MJPEG_CMD`
  (on the Pi: `/tmp/qstream`); dead producer → 503 within 4 s.
- `POST /api/drive {"x","y","cap"}` — manual thumbstick (−1..1). Stop is
  always accepted; other moves need `--enable-motors`. Duty clamped by
  page cap, `--motor-cap`, and the 40% hard cap; moves are 0.5 s and
  re-sent by the page while held, so a dead client stops the tank.
- `POST /api/camera {"x","y"}` — camera thumbstick; incremental pan/tilt
  through the servo path (needs `--enable-servo`), clamped to limits.
- `GET /api/telemetry` — read-only aggregate: gates, motor cap, speech
  status, servo pose, ultrasonic note (honestly "unavailable").
- `GET /api/servo` — `{enabled, labels, state, flags}`.
- `POST /api/servo {"channel","angle"}` — channel 1–6, integer angle
  0–180. 400 on bad input; 403 when live control is disabled; on success
  writes the frame and returns the new state. Slider page-load never sends.
- `POST /api/servo/flag {"channel","angle","note?"}` — record a wonky
  point; persisted to `servo_flags.json`. Works with servos disabled.
- `POST /api/servo/flag/clear {"channel"?}` — clear one channel's flags
  (omit channel to clear all).

## Run

Desktop smoke (touches no hardware):
`python3 tank_phone/server.py --port 8123` → `curl localhost:8123/api/status`
(sliders render, disabled; servo writes return 403.)

Pi live (Adam present, explicit authorization only):
`TANK_PHONE_MJPEG_CMD=/tmp/qstream python3 server.py --bind 0.0.0.0 --enable-servo --enable-motors`
Phone opens `http://tank.local:8123/` (LAN) or the Tailscale address.
Motors also need the bench listener on :5098 with its token file at
`/tmp/claude-1000/bench_token` (Pi-local; the server reads it, the phone
never sees it). Start the server without the `--enable-*` flags for a
safe review: every control renders, nothing can move.

## Safety

- `--enable-servo` / `--enable-motors` are the authorization gates;
  default off, controls inert (drive returns 403, stop still accepted).
- Page load sends nothing; only deliberate stick/slider/arm movement writes.
- Manual drive re-sends 0.5 s moves while held; release, mode switch,
  tab hide, or window blur all send stop.
- LAN/Tailscale only; add API auth before any wider exposure.

## Tests

`python3 -m unittest discover -s tank_phone -p 'test_*.py'` (FakeBus; no
hardware). Parser suite in `tank_tools` is unchanged.

## Roadmap

1. Calibrate pan/tilt visual centre against the live frame (sliders +
   flags are the tool for exactly this).
2. Wire tap→focus (tank_vision `focus()`) into the page.
3. Drive-to-centre via bench listener (port 5098, token), per-case auth.
