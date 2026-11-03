#!/usr/bin/env python3
"""usage: benchclient.py <ip> <n> <move> [secs] [duty]  -- sends n commands, logs latency"""
import random, socket, statistics as st, sys, time
ip, n, rest = sys.argv[1], int(sys.argv[2]), " ".join(sys.argv[3:])
tok = open("/tmp/claude-1000/bench_token").read().strip()
log = open("/tmp/claude-1000/tank_live.log", "a")
c = socket.create_connection((ip, 5098), timeout=5); c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
f = c.makefile("r"); on_d, rtt = [], []
for i in range(n):
    if i: time.sleep(random.uniform(1, 4))
    cmd = rest.replace("mix", ["go", "spinl", "rev", "spinr"][i % 4])
    s = time.time(); c.sendall(f"{tok} {cmd}\n".encode()); r = f.readline().split(); e = time.time()
    on = int(r[3].split("=")[1]); on_d.append(on - s * 1000); rtt.append((e - s) * 1000)
    log.write(f"{time.strftime('%T')} [{ip}] {cmd}: send->pins {on_d[-1]:6.1f} ms  rtt {rtt[-1]:6.1f} ms\n"); log.flush()
c.close()
q = lambda v: f"median {st.median(v):5.1f}  min {min(v):5.1f}  max {max(v):5.1f}"
print(f"{ip:15} send->pins {q(on_d)}   rtt {q(rtt)}")
