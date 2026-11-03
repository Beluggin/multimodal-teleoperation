#!/usr/bin/env python3
"""Bench test for the XiaoR tank motors (L298N via lgpio). No servos.

Usage: motor_bench.py <move> [seconds] [duty%]
  move: fwd | back | left | right   (built tank_server.py semantics, motor_flag=1)
        a+ | a- | b+ | b-           (one H-bridge channel alone: A=IN1/IN2/ENA, B=IN3/IN4/ENB)
        stop
Seconds capped at 3, duty capped at 40 (Adam's drive cap). Every exit path drives all pins low.
"""
import time
T0 = time.time()  # interpreter is up
import sys
import lgpio
T1 = time.time()  # lgpio imported


def stamp(label, t):
    print(f"@{t * 1000:.0f} {label}", flush=True)

ENA, ENB, IN1, IN2, IN3, IN4 = 13, 20, 19, 16, 21, 26
PWM_HZ = 100  # stock XiaoR frequency

MOVES = {
    #        IN1 IN2 IN3 IN4   ENA ENB
    "fwd":   (1, 0, 1, 0, 1, 1),
    "back":  (0, 1, 0, 1, 1, 1),
    "left":  (1, 0, 0, 1, 1, 1),
    "right": (0, 1, 1, 0, 1, 1),
    # measured on hardware 2026-10-24: A = right track (+ fwd), B = left track (+ back)
    "go":    (1, 0, 0, 1, 1, 1),
    "rev":   (0, 1, 1, 0, 1, 1),
    "spinl": (1, 0, 1, 0, 1, 1),
    "spinr": (0, 1, 0, 1, 1, 1),
    "a+":    (1, 0, 0, 0, 1, 0),
    "a-":    (0, 1, 0, 0, 1, 0),
    "b+":    (0, 0, 1, 0, 0, 1),
    "b-":    (0, 0, 0, 1, 0, 1),
    "stop":  (0, 0, 0, 0, 0, 0),
}


def all_low(h):
    for pin in (IN1, IN2, IN3, IN4):
        lgpio.gpio_write(h, pin, 0)
    for pin in (ENA, ENB):
        lgpio.tx_pwm(h, pin, PWM_HZ, 0)
        lgpio.gpio_write(h, pin, 0)


def main():
    move = sys.argv[1] if len(sys.argv) > 1 else "stop"
    secs = min(float(sys.argv[2]) if len(sys.argv) > 2 else 1.0, 3.0)
    duty = min(float(sys.argv[3]) if len(sys.argv) > 3 else 40.0, 40.0)
    if move not in MOVES:
        sys.exit(f"unknown move {move!r}; pick from {', '.join(MOVES)}")

    stamp("python_up", T0)
    stamp("lgpio_imported", T1)
    h = lgpio.gpiochip_open(0)
    stamp("chip_open", time.time())
    try:
        for pin in (ENA, ENB, IN1, IN2, IN3, IN4):
            lgpio.gpio_claim_output(h, pin, 0)
        i1, i2, i3, i4, ea, eb = MOVES[move]
        for pin, val in ((IN1, i1), (IN2, i2), (IN3, i3), (IN4, i4)):
            lgpio.gpio_write(h, pin, val)
        lgpio.tx_pwm(h, ENA, PWM_HZ, duty if ea else 0)
        lgpio.tx_pwm(h, ENB, PWM_HZ, duty if eb else 0)
        stamp("motors_on", time.time())
        print(f"{move} {secs:.1f}s @ {duty:.0f}%", flush=True)
        if move != "stop":
            time.sleep(secs)
    finally:
        all_low(h)
        stamp("motors_off", time.time())
        lgpio.gpiochip_close(h)
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
