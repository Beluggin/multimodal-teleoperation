#!/usr/bin/env python3
"""Bench listener: holds the L298N pins open and takes moves over TCP. No servos.

Protocol (one line per command): "<token> <move> [seconds] [duty%] [right_trim%]"
right_trim scales channel A (right track) to correct veer, e.g. 10 = +10%.
Reply: "ok <move> recv=<ms> on=<ms>" (tank epoch ms). Moves from motor_bench.py.
Every move is timed (cap 3 s, duty cap 40). A new command replaces the current one.
A dropped client, a bad line, or exit drives all pins low. Exits after LIFETIME s.
"""
import os
import socket
import sys
import threading
import time

import lgpio

ENA, ENB, IN1, IN2, IN3, IN4 = 13, 20, 19, 16, 21, 26
PWM_HZ = 100
MAX_SECS, MAX_DUTY = 3.0, 40.0
LIFETIME = 60 * 60
PORT = 5098
TOKEN = os.environ["BENCH_TOKEN"]

MOVES = {
    #        IN1 IN2 IN3 IN4   ENA ENB    measured 2026-10-24: A = right (+fwd), B = left (+back)
    "go":    (1, 0, 0, 1, 1, 1),
    "rev":   (0, 1, 1, 0, 1, 1),
    "spinl": (1, 0, 1, 0, 1, 1),
    "spinr": (0, 1, 0, 1, 1, 1),
    "stop":  (0, 0, 0, 0, 0, 0),
}

h = lgpio.gpiochip_open(0)
for pin in (ENA, ENB, IN1, IN2, IN3, IN4):
    lgpio.gpio_claim_output(h, pin, 0)
lock = threading.Lock()
gen = 0  # bumps on every command so a stale timer can't stop a newer move


def now_ms():
    return round(time.time() * 1000)


def apply(move, duty, trim=0.0):
    i1, i2, i3, i4, ea, eb = MOVES[move]
    duty_a = min(duty * (1 + trim / 100), MAX_DUTY)  # A = right track
    for pin, val in ((IN1, i1), (IN2, i2), (IN3, i3), (IN4, i4)):
        lgpio.gpio_write(h, pin, val)
    lgpio.tx_pwm(h, ENA, PWM_HZ, duty_a if ea else 0)
    lgpio.tx_pwm(h, ENB, PWM_HZ, duty if eb else 0)


def all_low():
    with lock:
        apply("stop", 0)


def timed_stop(my_gen, secs):
    time.sleep(secs)
    with lock:
        if gen == my_gen:
            apply("stop", 0)


def handle(conn):
    global gen
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    f = conn.makefile("r")
    try:
        for line in f:
            recv = now_ms()
            parts = line.split()
            if len(parts) < 2 or parts[0] != TOKEN or parts[1] not in MOVES:
                all_low()
                conn.sendall(b"err\n")
                continue
            move = parts[1]
            secs = min(float(parts[2]) if len(parts) > 2 else 1.0, MAX_SECS)
            duty = min(float(parts[3]) if len(parts) > 3 else 40.0, MAX_DUTY)
            trim = max(-50.0, min(float(parts[4]) if len(parts) > 4 else 0.0, 50.0))
            with lock:
                gen += 1
                apply(move, duty if move != "stop" else 0, trim)
                on = now_ms()
                my_gen = gen
            if move != "stop":
                threading.Thread(target=timed_stop, args=(my_gen, secs), daemon=True).start()
            conn.sendall(f"ok {move} recv={recv} on={on}\n".encode())
    finally:
        all_low()
        conn.close()


def main():
    def expire():
        all_low()
        os._exit(0)
    threading.Timer(LIFETIME, expire).start()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(2)
    print(f"listening :{PORT} for {LIFETIME}s", flush=True)
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
    finally:
        all_low()
        lgpio.gpiochip_close(h)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
