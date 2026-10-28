# tank_phone — phone GUI for the tank

Pi-hosted web page: camera frame, tap/text previews, and manual servo
sliders (live only behind `--enable-servo`). No motor path exists here.

## Layout

- `server.py` — stdlib-only HTTP server + JSON API (port 8123).
- `index.html` — phone page: tap frame, text box, tap/text preview output,
  servo sliders ch1–6 with wonky-flagging.
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
- `GET /api/frame` — MJPEG relay from `TANK_PHONE_MJPEG_CMD`
  (on the Pi: `/tmp/qstream`); dead producer → 503 within 4 s.
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
`TANK_PHONE_MJPEG_CMD=/tmp/qstream python3 server.py --bind 0.0.0.0 --enable-servo`
Phone opens `http://tank.local:8123/` (LAN) or the Tailscale address.

## Safety

- `--enable-servo` is the authorization gate; default off, sliders inert.
- Page load sends nothing; only deliberate slider movement writes.
- No code path here reaches the bench listener / motors.
- LAN/Tailscale only; add API auth before any wider exposure.

## Tests

`python3 -m unittest discover -s tank_phone -p 'test_*.py'` (FakeBus; no
hardware). Parser suite in `tank_tools` is unchanged.

## Roadmap

1. Calibrate pan/tilt visual centre against the live frame (sliders +
   flags are the tool for exactly this).
2. Wire tap→focus (tank_vision `focus()`) into the page.
3. Drive-to-centre via bench listener (port 5098, token), per-case auth.
