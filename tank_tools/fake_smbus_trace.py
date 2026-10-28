#!/usr/bin/env python3
"""fake_smbus_trace.py — isolated byte-trace harness for the stock servo .so.

Runs ON THE PI (ARM64, CPython 3.11) with zero bus I/O. A fake ``smbus``
module records every ``write_byte`` call; the real ``.so`` talks only to the
fake. No tank contact, no hardware writes.

Pi usage (tank on the bench, no approval needed — nothing touches /dev/i2c)::

    python3 tank_tools/fake_smbus_trace.py --dir xiaor --out /tmp/servo_trace.jsonl

``--dir`` must hold the license trio (``.so`` + ``_XiaoRGEEK_about_.py`` +
``XiaoRGEEK.jpg``). ``SaveServo``/``ReSetServo`` are traced through the fake
too, so nothing persists anywhere.

Desktop (x86) usage — harness self-check only, never the real ``.so``::

    python3 tank_tools/fake_smbus_trace.py --self-test

Stdlib only.
"""

import argparse
import json
import os
import sys
import types

LOG = []  # (addr, value) in call order


class FakeSMBus:
    """Logging stand-in for ``smbus.SMBus``. Records, never touches hardware."""

    def __init__(self, bus=None):
        self.bus = bus

    def write_byte(self, addr, value):
        LOG.append([int(addr), int(value)])
        return 0

    def read_byte(self, addr):
        return 0xAF  # idle filler seen on live read-only probes

    def read_byte_data(self, addr, reg):
        return 0xAF


def install_fake_smbus():
    mod = types.ModuleType("smbus")
    mod.SMBus = FakeSMBus
    sys.modules["smbus"] = mod
    return mod


def trace_call(label, func, *args):
    """Run one servo call against the fake bus; return its byte record."""
    del LOG[:]
    func(*args)
    return {"call": label, "args": list(args), "bytes": list(LOG)}


def run_trace(servo):
    """Sequence designed to separate channel bytes from angle bytes."""
    records = []
    probes = [(1, 90), (1, 91), (2, 90), (5, 95), (6, 79)]
    for num, angle in probes:
        records.append(trace_call("SetServoAngle",
                                  servo.XiaoRGEEK_SetServoAngle, num, angle))
    records.append(trace_call("SaveServo", servo.XiaoRGEEK_SaveServo))
    records.append(trace_call("ReSetServo", servo.XiaoRGEEK_ReSetServo))
    return records


def check_frame(records):
    """Compare set-angle records against FF ServoNum angle FF. Returns notes."""
    notes = []
    for rec in records:
        if rec["call"] != "SetServoAngle":
            continue
        vals = [b for _, b in rec["bytes"]]
        num, angle = rec["args"]
        if vals == [255, num, angle, 255]:
            notes.append(f"{num}/{angle}: OK FF-num-angle-FF")
        else:
            notes.append(f"{num}/{angle}: got {vals}")
    return notes


def self_test():
    """Exercise the harness on x86 with a stub servo (never the real .so)."""
    install_fake_smbus()
    stub = types.ModuleType("_XiaoRGEEK_SERVO_")

    class XR_Servo:
        def XiaoRGEEK_SetServoAngle(self, num, angle):
            import smbus
            d = smbus.SMBus(1)
            for b in (0xFF, num, angle, 0xFF):
                d.write_byte(0x17, b)

        def XiaoRGEEK_SaveServo(self):
            import smbus
            smbus.SMBus(1).write_byte(0x17, 0x11)

        def XiaoRGEEK_ReSetServo(self):
            import smbus
            smbus.SMBus(1).write_byte(0x17, 0x09)

    stub.XR_Servo = XR_Servo
    records = run_trace(XR_Servo())
    notes = check_frame(records)
    assert all(n.endswith("OK FF-num-angle-FF") for n in notes[:5]), notes
    assert records[5]["bytes"] == [[0x17, 0x11]], records[5]
    assert records[6]["bytes"] == [[0x17, 0x09]], records[6]
    print("self-test ok:")
    for n in notes:
        print("  " + n)
    print(f"  Save bytes: {records[5]['bytes']}")
    print(f"  Reset bytes: {records[6]['bytes']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="xiaor",
                    help="trio directory (.so + about.py + jpg)")
    ap.add_argument("--out", default="",
                    help="write records as JSON lines here (default: stdout)")
    ap.add_argument("--self-test", action="store_true",
                    help="x86 harness check with a stub servo module")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    install_fake_smbus()
    sys.path.insert(0, os.path.abspath(args.dir))
    os.chdir(os.path.abspath(args.dir))
    from _XiaoRGEEK_SERVO_ import XR_Servo  # noqa: E402

    records = run_trace(XR_Servo())
    for line in (json.dumps(r) for r in records):
        print(line)
    for note in check_frame(records):
        print("# " + note, file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
