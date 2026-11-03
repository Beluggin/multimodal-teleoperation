#!/usr/bin/env python3
"""drive_step.py — send ONE bench move from the Pi itself (token stays here).

    python3 drive_step.py go 0.5 30 17
    python3 drive_step.py stop

One connection per step: disconnect stops the tank (listener behaviour),
so a crashed caller can never leave it driving.
"""
import socket
import sys

tok = open("/tmp/claude-1000/bench_token").read().strip()
cmd = " ".join(sys.argv[1:]) or "stop"
c = socket.create_connection(("127.0.0.1", 5098), timeout=5)
c.sendall(f"{tok} {cmd}\n".encode())
print(c.makefile("r").readline().strip())
# The listener stops on disconnect: HOLD the connection for the move's
# full duration (the original bench tools do exactly this), then stop.
parts = cmd.split()
if parts and parts[0] != "stop":
    import time
    secs = float(parts[1]) if len(parts) > 1 else 1.0
    time.sleep(secs + 0.2)
    c.sendall(f"{tok} stop\n".encode())
c.close()
