#!/usr/bin/env python3
"""ultrasonic.py — HC-SR04 distance on the tank (Pi, lgpio).

Real wiring probed 2026-10-25: TRIG = BCM 4, ECHO = BCM 17 (both stock
pin claims in vendor docs are wrong). Protocol: 10 us TRIG pulse, then
ECHO stays high for the sound round-trip; cm = pulse_us / 58.

    python3 ultrasonic.py              # median of 7 pings
    python3 ultrasonic.py --samples 1  # one raw ping

Sensor reads only — no motors, no servos. Linux scheduling makes single
pings jittery, so the median is the number to trust; timeouts (no echo
in range) report as None, never as a fake distance.
"""

import argparse
import statistics
import time

TRIG, ECHO = 4, 17
TIMEOUT_S = 0.03  # ~5 m, beyond HC-SR04 useful range


def pulse_to_cm(pulse_s):
    return pulse_s * 1e6 / 58.0


def median_distance(samples):
    """samples: list of cm-or-None. Median of the hits, or None."""
    hits = [s for s in samples if s is not None]
    if not hits:
        return None
    return round(statistics.median(hits), 1)


def ping(h):
    import lgpio
    lgpio.gpio_write(h, TRIG, 0)
    time.sleep(0.000002)
    lgpio.gpio_write(h, TRIG, 1)
    time.sleep(0.00001)
    lgpio.gpio_write(h, TRIG, 0)
    deadline = time.perf_counter() + TIMEOUT_S
    while lgpio.gpio_read(h, ECHO) == 0:
        if time.perf_counter() > deadline:
            return None
    start = time.perf_counter()
    deadline = start + TIMEOUT_S
    while lgpio.gpio_read(h, ECHO) == 1:
        if time.perf_counter() > deadline:
            return None
    return pulse_to_cm(time.perf_counter() - start)


def measure(samples=7):
    import lgpio
    h = lgpio.gpiochip_open(0)
    try:
        lgpio.gpio_claim_output(h, TRIG, 0)
        lgpio.gpio_claim_input(h, ECHO)
        raw = []
        for _ in range(samples):
            raw.append(ping(h))
            time.sleep(0.06)  # HC-SR04 needs >50 ms between pings
        return median_distance(raw), raw
    finally:
        lgpio.gpiochip_close(h)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", type=int, default=7)
    args = ap.parse_args(argv)
    med, raw = measure(args.samples)
    pretty = ["—" if r is None else f"{r:.0f}" for r in raw]
    print(f"raw cm: {' '.join(pretty)}")
    print(f"distance_cm: {med}")
    return 0 if med is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
