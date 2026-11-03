#!/usr/bin/env python3
"""usage: route.py "move secs duty pause [right_trim]" ...  -- runs moves over ONE connection (disconnect = stop)"""
import socket, sys, time
tok = open("/tmp/claude-1000/bench_token").read().strip()
log = open("/tmp/claude-1000/tank_live.log", "a")
c = socket.create_connection(("tank.local", 5098), timeout=5); c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
f = c.makefile("r")
for step in sys.argv[1:]:
    move, secs, duty, pause, *trim = step.split()
    trim = trim[0] if trim else "0"
    s = time.time(); c.sendall(f"{tok} {move} {secs} {duty} {trim}\n".encode()); f.readline()
    rtt = (time.time() - s) * 1000
    line = f"{time.strftime('%T')} route {move} {secs}s @{duty}% trim {trim} rtt {rtt:.1f} ms"
    print(line, flush=True); log.write(line + "\n"); log.flush()
    time.sleep(float(secs) + float(pause))
c.sendall(f"{tok} stop\n".encode()); f.readline(); c.close()
print("route done, stopped")
