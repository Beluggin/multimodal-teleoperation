# Stock servo 0x17 I2C protocol — static-only notes

**Review update (2026-10-26):** Sections 7–8's static-analysis blocker and
call-count interpretation are superseded by
[Codex's instruction-level review](CODEX_REVIEW_2026-10-26.md).
Name references are statically recoverable; the four cited Call2Args sites
are sleep paths. The set-angle success path supports `FF ServoNum angle FF`
statically, pending an isolated execution trace. Earlier analysis below is
preserved as history; it is not a verified wire-protocol specification.

Target: `xiaor/_XiaoRGEEK_SERVO_.cpython-311-aarch64-linux-gnu.so`
Status: static decode (capstone) + live read-only bus scans + four observed
write probes with Adam watching. No blind writes since the pair-framing
negative result.

## 1. Binary identity (verified via `file`/`readelf`/`strings`, desktop only)

- `ELF 64-bit LSB shared object, ARM aarch64`, `with debug_info, not stripped`
  (BuildID `c2980239e82890b94b798f0f191d392e7fd03961`), 331680 bytes.
- Cython `0.29.32` (`_cython_0_29_32` in rodata), CPython 3.11 headers,
  `GNU C17 12.2.0`, module `pocs._XiaoRGEEK_SERVO_`.
- Build host leak: `/home/pi/work/python_src`, source `build/_XiaoRGEEK_SERVO_.c`.
- Host `objdump` cannot disassemble it (`can't use supplied machine aarch64`).
  Decoded instead with capstone + pyelftools (installed into `.venv`,
  per project python-env rules — no system interpreter touched).
- ELF symtab holds 51 FUNCs, all Cython runtime plus module exec plus four
  `__pyx_pw_` argument wrappers (`__init__`, `SetServoAngle`, `SaveServo`,
  `ReSetServo`). The `__pyx_pf_` bodies are inlined into those wrappers
  (e.g. SetServoAngle wrapper @0xa784 spans 7140 bytes / ~1785 insns).
- Full 78-entry Cython string table recovered in order (index: name):
  0 `_ADDRESS`, 3 `SMBus`, 4 `ServoNum`, 20 `angle`, 23 `_device`,
  41 `md5`, 55 `read`, 60 `sleep`, 61 `smbus`, 67 `time`, 73 `verif`,
  77 `write_byte`, plus the license strings (`_XiaoRGEEK_about_`,
  `/XiaoRGEEK.jpg`, `please add …`, `well done!`,
  `WE have no servo IO as  %d`). Only SMBus primitive referenced anywhere
  is `write_byte` — confirmed no `write_byte_data` / `read_byte_data`.

## 2. Public API (confirmed by callers + symbol names)

Class `XR_Servo`, from `_XiaoRGEEK_SERVO_ import XR_Servo`:

- `XiaoRGEEK_SetServoAngle(ServoNum, angle)` — set one servo.
- `XiaoRGEEK_SaveServo()` — store all angles as power-on defaults.
- `XiaoRGEEK_ReSetServo()` — restore saved defaults.

Callers: `xiaor/Servo_test.py`, `xiaor/xr_socket.py`
(`0x01` servo packet, `0x32` save, `0x33` restore), face/color
follow (`servo 7` = pan X, `servo 8` = tilt Y), maze mode
(`SetServoAngle(7, 90)`, `SetServoAngle(8, 0)`).

## 3. License / integrity gate (must keep for any reuse)

The `.so` embeds all of these strings, so import verifies its directory:

- `please add _XiaoRGEEK_about_.py`
- `_XiaoRGEEK_about_` fields: `__title__`, `__version__`, `__summary__`,
  `__uri__`, `__email__`, plus `Readme`, `Contact us:`
- `/XiaoRGEEK.jpg`, `path_jpg`, opened `rb` via `open` + `read`
- `hashlib`, `md5`, `hexdigest`, `binascii`, `s_md5`, `verif`
- outcomes: `well done!` vs `WE have no servo IO as  %d`

Known-good companions (in repo):

- `xiaor/_XiaoRGEEK_about_.py` (`__version__ = "0.1.1"`,
  `email liuviking@xiaorgeek.com`, `uri http://www.xiao-r.com`)
- `XiaoRGEEK.jpg` IS in the repo: `xiaor/XiaoRGEEK.jpg` (verified JPEG,
  1920x1080, 873155 bytes). `Servo_test.py` says the three files must sit
  in one directory.

Do not strip or rename these. A fresh SD-card deploy needs the same trio.

## 4. I2C transport (static strings + literal table, not yet traced)

- Single write primitive: `write_byte` (not `write_byte_data`). Callers also
  show `read`, `sleep`, `open`, `system`, `md5`/`hexdigest` nearby.
- Instance attrs `_ADDRESS` and `_device` exist as interned names.
- Every numeric literal in the Cython source (from `__pyx_int_*` symbols):
  `0, 1, 9, 17, 23, 255` plus float `0.00001` (likely a 10 us settle sleep).
  `23` = `0x17`. Live-confirmed 2026-10-26: read-only `smbus2` scan of bus 1
  from the tank itself found exactly `['0x17']` — nothing else. No `0x40` /
  `0x50` (64/80) literals exist anywhere in the `.so` either.
- That directly contradicts `xiaor/servo_controller.py`, which drives a
  PCA9685 at `0x40` plus an AT24C02 EEPROM at `0x50`. That file is wrong
  for this board even though its `XR_Servo` method names match.
- Extra color: the binary shells `gsettings set
  org.gnome.desktop.background picture-uri "file:` (sets the desktop picture
  to the verification jpg) and prints `well done!` /
  `WE have no servo IO as  %d` (bus-index error path).

## 5. Servo ID range and angles (from callers, not the wire)

- IDs `1–8`. `xr_config.ANGLE` is an 8-slot list. `7/8` are camera
  pan/tilt on the bigger arm SKU; `tank_tools` notes `7/8` empty on ours.
- Angles are degrees `0–180` in every caller (`Servo_test` uses 30/150,
  `xr_socket` forwards raw byte `buffer[2]` as angle, face follow sweeps
  small deltas with a `>2°` deadband to avoid spamming the bus).
- `tank_tools/xiaor_text_action.py` `SERVO_LIMITS` clamps tighter per
  channel for the arm (e.g. base 10–170, pinch 10–130). Trust those over
  the raw `0–180` until the arm is re-calibrated.
- Scope (Adam, 2026-10-26): servos map only to arm + camera (IDs 1–6).
  Channels 7/8 stay unused on this SKU — no maze-mode writes, no probes
  addressed there. First live write, when approved, goes to a real
  arm/camera channel as a tiny visible move.

## 6. Live read findings (2026-10-26, beer-store floor, reads only)

- Full 0x00–0xFF `read_byte_data` sweep: every register returns `175`
  (`0xAF`), stable across repeats. First sweep showed `17/34/51`
  (`0x11/0x22/0x33`) at regs `0x12–0x14`, but that did NOT reproduce —
  treat it as a first-access transient, not ID registers.
- Working theory: the MCU is effectively write-only; reads clock out an
  idle filler byte (`0xAF`). Register reads carry no state. This fits the
  binary using `write_byte` (single data byte per transaction, likely sent
  as a short command sequence) rather than register reads.
- Blind-write probes, all ACKed, zero motion (cam pan ch5, servos confirmed
  powered by hand-feel, open floor, Adam observing):
  `[5][100]` 10ms gap, `[5][150]` 10ms gap, `[150][5]` reversed,
  `[5][150]` back-to-back. Conclusion: framing is NOT a plain
  servo/angle byte pair in either order. Likely a command-prefix sequence.
  No further blind writes without disassembly.

## 7. Call skeleton of SetServoAngle (new, static)

The inlined body performs 5 one-argument calls (`__Pyx_PyObject_CallOneArg`,
consistent with `int()` coercions of the arguments) and 4 two-argument calls
(`__Pyx_PyObject_Call2Args` at 0xbc5c, 0xbf34, 0xc158, 0xc2b4). Callee
identities are runtime table lookups, not statically resolvable — but a
plain `[servo][angle]` pair would need at most 2 bus calls, so the true
framing is a longer sequence (prefix and/or per-byte calls, possibly with
checksum). Integer literals anywhere in the module are exactly
`0, 1, 9, 17, 23, 255` plus float `0.00001`; `23` is the address, the roles
of `9` and `17` are unassigned (candidates: retry count, command byte —
not proven).
- Review cross-check (Opus table, independently verified three ways:
  symtab, string-table parse, DWARF `DW_OP_addr` locations — all agree,
  e.g. `write_byte`@0x219c0, `int_23`@0x215f0): tracing ADRP+memref loads
  back to these slot addresses was attempted across the whole `.text`
  (single- and double-hop, with and without chunking) and finds ZERO
  references outside module init. The recipe is correct in principle but
  yields nothing: method bodies load through runtime pointers whose values
  only exist at import. DWARF confirms locations, not call flow.
- Unverified hypothesis (Opus, 2026-10-22): 5-byte frame `FF cmd servo
  angle FF` with `cmd` 0x01=set / 0x11=save / 0x09=reset — fits the literal
  set and the `0xFF` framing the stock TCP protocol also uses, but needs 5
  bus calls against 4 observed `Call2Args` (unless the 5th byte rides one
  of the 5 `CallOneArg`s). Do not test blind; settle by execution.

## 8. NOT yet recovered (needs execution, not more static reading)

Static analysis is exhausted: interned names resolve only inside module
init (Cython reaches everything else through runtime pointers), and the
four bus-call callees cannot be named without running the code. Two live
options, both need Adam's sudo password when at a keyboard:
(a) desktop: `qemu-aarch64` + arm64 Python 3.11 sysroot, run the real
`.so` under a logging fake-`smbus` — zero tank contact, full byte trace;
(b) tank: install Python 3.11, copy the license trio (.so + about.py +
jpg), same spy. No qemu, no debootstrap, no passwordless sudo exists on
either machine today.
- Update (review): `uv python install 3.11` fetches a standalone aarch64
  CPython as a normal user — no sudo needed on the tank. Feasibility
  unchecked: tank is currently offline (powered down after the store
  session), and the install would cost hotspot data — waits on Adam's go
  with the tank up.

- Register/command layout on `0x17` (which register = set-angle vs
  save vs restore).
- Byte format per transaction (does `write_byte` send
  addr + reg + value, or a multi-byte command?).
- Angle encoding on the wire (raw degrees vs pulse-width ticks).
- Checksum/ACK behavior (none seen in strings; unknown).
- `SaveServo` / `ReSetServo` persistence location (on-MCU flash vs Pi
  files; no `data.ini` string found in the `.so`).

Why still unknown: capstone disassembly hit the wall described above —
method bodies reach all names through runtime pointers, so callee/argument
identities need execution, not more static passes.

## 9. Safe next steps (only with Adam, tank on the bench)

1. `i2cdetect -y 1` to re-confirm `0x17`.
2. Read-only probe: `i2cget` / `smbus read_byte` single-register reads,
   or preferably a logic-analyzer capture while stock code runs once.
3. Then single-servo move with E-stop handy, watching current/heat.
4. No writes without Adam present and watching, approved case by case —
  the four pair probes above are the only writes ever sent. The servos are
  physical.

## 11. Save/Reset static addendum (2026-10-27, no execution)

Wrappers: SaveServo @0x8280, ReSetServo @0x9504. Both set x23 = page 0x21000
at entry (0x8294 / 0x9518) and keep it through the cited sites, so the
0x21568 base holds. Verified tuple-payload loads: Save 0x85a8 → int_17,
0x87b8 → int_1; Reset 0x982c → int_0, 0x9a3c → int_1. Same
device/write_byte/sleep/10 µs-float paths as set-angle. No base-derived
int_9 in either wrapper (the cmd-0x09=reset guess is unsupported). Ordered
Save/Reset wire frames still need the fake-smbus run:
`tank_tools/fake_smbus_trace.py --dir xiaor --out /tmp/servo_trace.jsonl`
on the Pi (ARM64 Py3.11, zero bus I/O). Harness logic self-checked on x86
via `--self-test` (stub only).

Executed 2026-10-27 on the tank (uv-managed CPython 3.11.18, fake `smbus`,
trace at `/tmp/servo_trace/trace.jsonl`): SetServoAngle emits four
`write_byte(0x17, …)` = `FF ServoNum angle FF` (5/5 probes); SaveServo =
`FF 17 1 FF`; ReSetServo = `FF 0 1 FF`. Static Save/Reset payloads confirmed;
cmd-0x09=reset rejected. Physical MCU response still needs a benched move.

## Submission-ready one-liner

Stock servos go through a Cython `XR_Servo` object over `smbus` to I2C
`0x17`, IDs 1–8, degrees on the API, with a `jpg` + `about.py` md5 gate
at import. Wire-level register map still needs one benched trace.

---

## 10. Review notes from Claude (2026-10-26)

Adam asked Claude to check this doc and add its own findings. Sections 1–9 are Muse's and were left unedited.
Everything below is either checked against the file or labelled as a guess.

### Confirmed
- Address `0x17`, `write_byte` as the only bus primitive, the public API, and the license gate all check out.
- The literal set `0, 1, 9, 17, 23, 255` matches what Claude found independently on 2026-10-22.
- The four blind writes rule out a plain `[servo][angle]` pair, which is a useful negative result.

### Static analysis is not exhausted (main finding)
Section 8 says the callees "cannot be named without running the code". They can. The `.so` is built with
debug info and is not stripped, so every Cython interned name and integer constant is a **named LOCAL
OBJECT at a fixed `.bss` address** (64 of them, `readelf -sW <so> | grep __pyx_`). For example:

| Address | Symbol |
|---|---|
| `0x215d0` | `__pyx_int_0` |
| `0x215d8` | `__pyx_int_1` |
| `0x215e0` | `__pyx_int_9` |
| `0x215e8` | `__pyx_int_17` |
| `0x215f0` | `__pyx_int_23` |
| `0x215f8` | `__pyx_int_255` |
| `0x216a8` | `__pyx_n_s_smbus` |
| `0x216d0` | `__pyx_n_s_angle` |
| `0x216d8` | `__pyx_n_s_ServoNum` |
| `0x21710` | `__pyx_n_s_time` |
| `0x219b0` | `__pyx_n_s_SMBus` |
| `0x219c0` | `__pyx_n_s_write_byte` |
| `0x219e8` | `__pyx_n_s_sleep` |

DWARF names them too (`readelf --debug-dump=info`). The callee is a runtime pointer, but the **name used to
fetch it is not**. Before each `__Pyx_PyObject_Call2Args` site (`0xbc5c`, `0xbf34`, `0xc158`, `0xc2b4`), trace
the ADRP+ADD/LDR loads back to these addresses. That shows which attribute was fetched (`write_byte`) and which
constant or argument went into each byte slot. This should give the full byte order statically, with no sudo,
no qemu, and no tank contact. Claude only confirmed the symbols exist and did not do this mapping.

### If execution is still wanted, no sudo is needed
`uv python install 3.11` installs a standalone aarch64 CPython as a normal user on the tank. Put a fake
`smbus.py` that logs every `write_byte(addr, byte)` ahead of the real one on `sys.path`, copy the license trio
(`.so`, `_XiaoRGEEK_about_.py`, `XiaoRGEEK.jpg`) into one directory, and call `SetServoAngle` / `SaveServo` /
`ReSetServo`. You get a full byte trace and no traffic on the real bus.

### Doc inconsistencies to clean up
- The status line at the top says zero bus probes, but section 6 records reads and four writes.
- Section 3 says `XiaoRGEEK.jpg` is not in the repo. It is: `xiaor/XiaoRGEEK.jpg`.
- Section 8's "Why still unknown" says no disassembler was available, but section 1 used capstone.
- There are two `## 8` headings.
- Section 9 says never send blind writes, but section 6 sent four with Adam observing. State the rule as
  "no writes without Adam present and a known frame".

### Claude's earlier hypothesis (2026-10-22, UNVERIFIED, a check rather than an answer)
From the constants alone, Claude guessed a 5-byte frame sent one `write_byte` at a time:
`0xFF, cmd, servo, angle, 0xFF`, with `cmd` `0x01` = set angle, `0x11` (17) = save, `0x09` = reset.
It fits the literal set (`255`, `1`, `17`, `9`) and explains why bare pairs did nothing. **It conflicts with
your count of four two-argument calls in `SetServoAngle`**: a 5-byte frame needs five. So either the frame is
4 bytes, or one byte is sent another way (a loop, or a call shape you didn't count). The address mapping above
should settle it. Trust the disassembly over this guess.
