# tank_bench

Bench and floor tools for the XiaoR tank (Pi 5, L298N on lgpio). Motors only, no servos.
Built and run live on 2026-10-24.

## Files

| File | Runs on | What it does |
|---|---|---|
| `motor_bench.py` | tank | One move per process over SSH. Stage timestamps; 3 s / 40% caps. |
| `motor_listen.py` | tank | TCP listener on :5098 that holds the pins open. Token from `BENCH_TOKEN`; caps 3 s / 40%; every move is timed; stops on disconnect; exits after 1 h. |
| `tankrun.sh` | desktop | Runs `motor_bench.py` over a reused SSH connection and logs latency. |
| `benchclient.py` | desktop | Sends N commands to the listener and reports latency. Disconnects at the end, which stops the last move. |
| `route.py` | desktop | Runs a move sequence over **one** connection: `"move secs duty pause [right_trim]"`. |
| `octagon.sh` | desktop | The octagon demo route: `octagon.sh [first_turn] [corner] [final_spinl]`. Defaults are v2 (run-down battery); charged battery uses `0.80 0.35 0.46`. |
| ~~`tankdrive.py`~~ | | Moved to `../tank_tools/tank_control.py` (keyboard + typed queue). |

The desktop tools read the token from `/tmp/claude-1000/bench_token` and append to
`/tmp/claude-1000/tank_live.log`. Start the listener on the tank with the same token:
`BENCH_TOKEN=<token> nohup python3 -u /home/pi/motor_listen.py > ~/motor_listen.log 2>&1 &`

## Measured

- **Motor map:** channel A (IN1/IN2, ENA 13) = right track, + is forward. Channel B (IN3/IN4, ENB 20) = left track, **wired reversed**.
  Forward = IN1 1, IN2 0, IN3 0, IN4 1. The built `tank_server.py` "fwd" and "back" are actually spins.
- **Latency:** send to pins switching is ~8 ms round trip through the listener, on both Wi-Fi and Tailscale. Over SSH plus a fresh Python process it's ~55 ms.
  Wi-Fi `power_save` on adds 100+ ms spikes after idle, so turn it off.
- **Spin-up:** pins switch in ~45 ms at any duty, but motors need ~0.5 s to get moving at 40%. Higher duty starts visibly faster.
- **Floor at 30%:** forward ~7"/s untrimmed, veers right. A right-track trim of +17% drives straight at ~11"/s.
  Same trim works in reverse (~3° drift).
- **Spins at 30%, untrimmed (chained runs):** right ~101°/s (360° ≈ 3.55 s), left ~110°/s (360° ≈ 3.3 s).
  Time each direction separately. Run-to-run noise is about ±10°.
- **Octagon runs (dead reckoning, no sensors):**
  - v1, 0.45 s corners: ended within 2" of center, 30° clockwise.
  - v2, 0.40 s corners: ~1" off center, 15° counter-clockwise.
  - v3, 0.42 s corners: overshot. Tuning is now below the noise floor.
  - The first leg pulls right from a standstill because the right motor spins up slower; a kick-start burst would help.
  - Next step is closed-loop heading (IMU or camera fiducial). Also check the right motor for debris, track tension, the connector, and battery sag.
- **Battery charge changes spin rate (2026-10-25).** After an overnight charge, the same 30% spun ~135°/s instead of ~101°/s, so v2 timings
  turned the first corner ~150° and the path fell apart. Scaling every spin by 0.75 left the short corners short: spin-up eats a bigger share
  of a short pulse, so spin angle isn't linear in time. Retuned to `0.80 / 0.35 / 0.46`: all 8 sides closed, ended ~5 cm right of the mark, ~10° CCW.
- **Real sensor wiring (read-only probe, 2026-10-25):** ultrasonic is TRIG = BCM 4, ECHO = BCM 17 (stock 17/5 and built 17/4 are both wrong); read ~88 cm.
  IR pins 18, 27, 22, 23, 24 are driven; pin 11 floats (nothing attached). What each IR sensor detects is untested.
