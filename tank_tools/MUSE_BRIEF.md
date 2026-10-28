# Fresh-session handoff — 2026-10-26

This is the tank-only hackathon workspace. Start here; do not resume sessions
from another workspace. Only Meta models belong in the demo inference path.

## Current task

Recover and document the stock servo protocol from
`xiaor/_XiaoRGEEK_SERVO_.cpython-311-aarch64-linux-gnu.so`.
Read `tank_tools/CODEX_REVIEW_2026-10-26.md` first, then the protocol notes.
The review supersedes the claim that static analysis is exhausted:

- SetServoAngle uses statically resolvable names through base `0x21568`.
- The four cited Call2Args sites are alternate sleep paths, not bus writes.
- Static argument tracing supports `FF ServoNum angle FF` for set-angle.
  This is not an executed trace or physical validation.
- Save/reset still need decoding. An isolated fake-smbus execution trace
  remains useful to confirm the reconstruction before physical testing.

`python3` has Capstone and pyelftools copied from the existing environment.
The vendor binary requires ARM64 CPython 3.11; the desktop interpreter cannot
import it directly. Keep the binary, about.py and JPEG companions together.

## Access and hardware

`ssh tank` connects to the Pi using the isolated profile's dedicated key.
`ssh tank-lan` is the local-network fallback. SCP uses the same configuration.
Read-only diagnostics are available; no motor or servo writes without Adam's
explicit authorization and presence. Do not fetch unrelated private files
from the Pi into this workspace or into model context.

Read `tank_bench/README.md` for measured wiring and motor behavior. Motors
use the bench listener, port 5098. The stock servo MCU is at I2C 0x17.
Camera channels on this tank are 5/6; 7/8 are unused. The public API takes
degrees but wire behavior must still be confirmed. Timing-based turns vary
with battery charge; do not present them as precise closed-loop navigation.

## Other open demo work

- Build the visible language/vision → bounded approach → stop loop.
- Fix decimal-duration parsing and stop-priority bugs before relying on
  natural-language emergency stops. Existing 32 parser tests pass but miss
  these cases.
- This workspace's keyboard driver talks to the timed bench listener. The
  older full server was not imported; do not silently switch control paths.

Log substantive work in DEVLOG.md. Do not push or add dependencies without
Adam's instruction. The isolation launcher is managed outside this repo.
