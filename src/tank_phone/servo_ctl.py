#!/usr/bin/env python3
"""servo_ctl.py — stdlib-only servo writer for the tank phone page.

Speaks the physically proven frame (DEVLOG 2026-10-27): four single-byte
writes to I2C addr 0x17 — FF, ServoNum, angle, FF — with ~10us gaps.
Uses /dev/i2c-1 via ioctl directly: no smbus package, no vendor .so,
works under the Pi's system python3.

Channels 1-6 only. 7/8 stay unprobed (bigger-arm SKU scope rule).
Angles are degrees 0..180 per every vendor caller.
"""

import fcntl
import os
import time

I2C_SLAVE = 0x0703
ADDR = 0x17
CHANNELS = (1, 2, 3, 4, 5, 6)
LABELS = {1: "Arm ch1", 2: "Arm ch2", 3: "Arm ch3", 4: "Claw ch4",
          5: "Cam tilt ch5", 6: "Cam pan ch6"}  # Adam-confirmed 2026-10-27: pan/tilt were swapped
# HOME pose, set by Adam at the tank 2026-10-27 ("current values should
# be home values"). Slider start positions ONLY — never sent on page load
# or server start. Commanded state, not measured (no telemetry exists).
DEFAULTS = {1: 140, 2: 20, 3: 87, 4: 100, 5: 72, 6: 74}

# Allowed travel per channel [min, max], as calibrated by Adam at the
# tank 2026-10-27 (started from the physically swept ranges, then widened
# deliberately per channel). There is NO position telemetry on this MCU
# (write-only frames), so these limits are the only guard against awkward
# arm geometry. Editable live from the page; persisted on the Pi to
# servo_limits.json, which overrides these defaults when present.
LIMITS = {1: (0, 140), 2: (20, 180), 3: (0, 180),
          4: (40, 100), 5: (30, 120), 6: (0, 75)}


def clamp_state(state, limits):
    return {ch: min(max(a, limits[ch][0]), limits[ch][1])
            for ch, a in state.items()}


def check(channel, angle):
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}")
    if int(angle) != angle or not 0 <= angle <= 180:
        raise ValueError("angle must be an integer in 0..180")


def frame(channel, angle):
    check(channel, angle)
    return (0xFF, int(channel), int(angle), 0xFF)


class ServoBus:
    """One shared /dev/i2c fd. Caller serializes writes (server lock)."""

    def __init__(self, device="/dev/i2c-1", addr=ADDR, _fd=None):
        self._fd = _fd if _fd is not None else os.open(device, os.O_RDWR)
        fcntl.ioctl(self._fd, I2C_SLAVE, addr)

    def set_angle(self, channel, angle):
        for byte in frame(channel, angle):
            os.write(self._fd, bytes([byte]))
            time.sleep(0.00001)

    def close(self):
        os.close(self._fd)


class FakeBus:
    """Test double: records frames, touches nothing."""

    def __init__(self):
        self.frames = []

    def set_angle(self, channel, angle):
        self.frames.append(frame(channel, angle))

    def close(self):
        pass
