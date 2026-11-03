# Codex review — 2026-10-26

Scope: Muse's `servo_0x17_protocol.md`, the supplied stock binary, and
offline checks of the existing text parser. No tank contact, installs, or
controller changes. Binary inspected with the already-installed project
Capstone and pyelftools, and `readelf -sW`.

## P1 — Static-analysis blocker is disproven

Sections 7–8 claim there are zero references outside module initialization
and that names cannot be recovered without execution. In SetServoAngle:

```text
a7d4: adrp x21, #0x21000
abcc: add  x0, x21, #0x568
abd4: ldr  x1, [x0, #0x458]
```

The effective slot is `0x21000 + 0x568 + 0x458 = 0x219c0`, which
`readelf -sW` identifies as `__pyx_n_s_write_byte`. The preceding attribute
load at `abb0` uses offset `0x450`, giving `0x219b8`, the `device` name.
These are direct, statically recoverable name references in the method body.
The lookup result is dynamic; the identity of the requested attribute is not.
Continue tracking base-register values through control flow instead of
treating the failed scan as proof of an execution requirement.

## P1 — Call-helper counts were mistaken for bus-write counts

The four Call2Args sites listed in section 7 (`bc5c`, `bf34`, `c158`,
`c2b4`) are bound-method alternatives for the four sleep calls. Their
argument load resolves to `0x215c8 = __pyx_float_0_00001`. Their attribute
loads use base `0x21568` plus `0x480`, giving `0x219e8 = __pyx_n_s_sleep`.
The ordinary one-argument paths are at `ad90`, `afac`, `b1bc`, `b3cc`;
the corresponding attribute loads are at `ad50`, `af6c`, `b17c`, `b38c`.
Two C helper arguments here include the bound receiver, not two source-level
bus arguments. Do not infer byte counts from these helper names.

The actual write-byte paths construct argument tuples and call indirectly:
`acd8`, `aef0`, `b104`, `b314`. Static reconstruction of this success path
supports **four bytes: `FF, ServoNum, angle, FF`**, with a 10 μs sleep after
each write. Evidence:

| Write site | Data argument source |
|---|---|
| `acd8` | `ac9c` loads base `0x21568 + 0x90`, the integer 255 |
| `aef0` | `aec4` places `x25`, the ServoNum argument, in the tuple |
| `b104` | `b0e0` places `x27`, the angle argument, in the tuple |
| `b314` | `b2d8` loads base `0x21568 + 0x90`, again integer 255 |

`a7cc`/`a7d0` load self, ServoNum, angle into `x26`, `x25`, `x27`.
The address global lookup uses name slot `0x21568 + 0x1e0 = 0x21748`
(`__pyx_n_s_ADDRESS`; e.g. `ba28`). This is a static reconstruction, not
an executed trace or proof of physical operation. Save/reset were not decoded
in this review. Confirm with an isolated fake-smbus trace before hardware use.

## Existing parser failures remain despite a green suite

`python3 -m unittest discover -s tank_tools -p 'test_*.py'`: **32 passed**.
Direct calls to `classify()` also reproduced:

| Input | Actual result |
|---|---|
| `forward 0.5 seconds` | forward, duration **5.0** |
| `no no stop` | refused |
| `forward stop` | ambiguous |
| `hey stop` | ambiguous |
| `stop right now` | ambiguous |

These are pre-existing issues already mentioned in the brief/plan, not new
servo-work regressions. The suite does not establish the advertised stop-wins
behavior. The keyboard driver's duration cap reduces 5 seconds to 3, but
still exceeds the requested half-second. Parser/controller fixes remain open.

## Reproducing the disassembly

Run from the the source project root with the existing project environment:

```python
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

with open('xiaor/_XiaoRGEEK_SERVO_.cpython-311-aarch64-linux-gnu.so', 'rb') as f:
    elf = ELFFile(f)
    section = elf.get_section_by_name('.text')
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    for insn in decoder.disasm(section.data(), section['sh_addr']):
        if 0xa784 <= insn.address < 0xc368:
            print(f'{insn.address:x}: {insn.mnemonic} {insn.op_str}')
```

Compare the slot addresses with
`readelf -sW xiaor/_XiaoRGEEK_SERVO_.cpython-311-aarch64-linux-gnu.so`.
No import or execution of the vendor binary is involved.
