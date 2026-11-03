#!/usr/bin/env python3
"""tank_control.py — drive the tank by keyboard OR by typed instructions.

Talks to the bench listener (tank_bench/motor_listen.py) on the tank. Motors only.

  DRIVE mode (default)
    arrows / WASD   hold to drive (each key repeat = a short pulse)
    space           STOP + clear the queue
    - / =           speed down / up (10..30)
    t or Enter      switch to TYPE mode
    q               quit (sends stop)

  TYPE mode
    type an instruction, Enter queues it. Chain with "then", "," or ";":
        forward 2 seconds then turn left then back up
    any stop phrase ("stop", "halt", "e-stop") jumps the queue: stops now, clears it
    Enter on an empty line or Esc  back to DRIVE mode

Typed instructions go through xiaor_text_action.classify(), so its safety
posture holds: negated, unknown and ambiguous text never moves.
Pressing any drive key also clears the queue (manual always wins).

RAW mode (--raw)
    typed instructions go to Llama on Ollama instead of the parser (llama_raw.py).
    Stop still skips the model, and a stop or manual key drops a pending answer.
"""
import argparse
import collections
import curses
import os
import re
import socket
import threading
import time

import llama_raw
import xiaor_text_action as tx

os.environ.setdefault("ESCDELAY", "25")  # make Esc respond fast in curses

TANK = os.environ.get("TANK_HOST", "tank.local")  # or <tailscale-ip> for Tailscale
PORT = 5098
PULSE = 0.6  # bridges the keyboard's initial repeat delay
TOKEN = open(os.environ.get("BENCH_TOKEN_FILE", "/tmp/mitt/bench_token")).read().strip()
LOG = open("/tmp/mitt/tank_live.log", "a")

MAX_SPEED = 30
TRIM = 17           # right-track boost so straights go straight (floor-tested 2026-10-24)
DRIVE_SECS = 1.0    # typed drive with no time given ("forward")
TURN_SECS = 0.65    # typed turn with no time given, roughly 90° at 30% on a charged battery
AROUND_SECS = 1.25  # "turn around", roughly 180°
MAX_TYPED_SECS = 3.0  # listener caps every move at 3 s anyway

KEYS = {
    curses.KEY_UP: "go", ord("w"): "go",
    curses.KEY_DOWN: "rev", ord("s"): "rev",
    curses.KEY_LEFT: "spinl", ord("a"): "spinl",
    curses.KEY_RIGHT: "spinr", ord("d"): "spinr",
}

# classify() labels -> listener moves
LABEL_MOVE = {
    "drive.forward": "go", "drive.backward": "rev",
    "drive.left": "spinl", "drive.right": "spinr", "drive.around": "spinl",
}
STOP_LABELS = {"drive.stop", "drive.estop"}
_SPLIT = re.compile(r"\s*(?:\bthen\b|,|;)\s*", re.I)


class Tank:
    """One connection shared by the keyboard and the queue worker."""

    def __init__(self):
        self.c = socket.create_connection((TANK, PORT), timeout=2)
        self.c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.c.makefile("r")
        self.lock = threading.Lock()
        self.last, self.rtt = "stop", 0.0

    def send(self, move, secs=PULSE, speed=MAX_SPEED, tag="drive"):
        trim = TRIM if move in ("go", "rev") else 0
        with self.lock:
            s = time.time()
            self.c.sendall(f"{TOKEN} {move} {secs} {speed} {trim}\n".encode())
            self.f.readline()
            self.rtt = (time.time() - s) * 1000
            if move != self.last or tag != "drive":
                LOG.write(f"{time.strftime('%T')} {tag} {move} {secs}s @{speed}% rtt {self.rtt:.1f} ms\n")
                LOG.flush()
            self.last = move


def parse(text, speed):
    """One typed line -> (queue items, messages). Each item: (move, secs, speed, label)."""
    items, msgs = [], []
    for part in filter(None, _SPLIT.split(text.strip())):
        a = tx.classify(part)
        if a.label in STOP_LABELS:
            items.append(("stop", 0, 0, a.label))
        elif a.label in LABEL_MOVE:
            secs = a.duration or (TURN_SECS if a.label in ("drive.left", "drive.right") else DRIVE_SECS)
            if a.label == "drive.around":
                secs = AROUND_SECS
            capped = secs > MAX_TYPED_SECS
            secs = min(secs, MAX_TYPED_SECS)
            # "slowly"/"fast" put a speed command in front; never go above our cap
            spd = next((min(c["left"], MAX_SPEED) for c in a.commands if c["action"] == "speed"), speed)
            items.append((LABEL_MOVE[a.label], secs, spd, a.label))
            msgs.append(f"+ {part!r} -> {a.label} {secs:g}s @{spd}%" + (" (capped)" if capped else ""))
        elif a.kind in ("unknown", "refused", "ambiguous"):
            msgs.append(f"x {part!r}: {a.reason}")
        else:
            msgs.append(f"x {part!r} -> {a.label}: not wired yet (motors only)")
    return items, msgs


def main(scr, raw=False):
    curses.curs_set(0)
    scr.nodelay(True)
    tank = Tank()
    speed, mode, line = MAX_SPEED, "DRIVE", ""
    queue = collections.deque()
    cancel = threading.Event()  # set = drop whatever the worker is doing
    state = {"now": "", "msgs": collections.deque(maxlen=4)}

    qlock = threading.Lock()  # a stop and a queued send can't interleave

    def deliver_plan(text, plan, spd):
        items, msgs = llama_raw.plan_to_queue(text, plan, spd)
        with qlock:
            queue.extend(items)
        state["msgs"].extend(msgs)

    runner = llama_raw.RawRunner(deliver_plan) if raw else None

    def clear_queue():
        if runner:
            runner.cancel()  # first: any late plan lands before the clear below
        with qlock:
            queue.clear()
            cancel.set()

    def worker():
        while True:
            if not queue:
                time.sleep(0.02)
                continue
            with qlock:
                if not queue:
                    continue
                cancel.clear()
                move, secs, spd, label = queue.popleft()
                state["now"] = f"{label} {secs:g}s"
                tank.send(move, secs, spd, tag="queue")
            cancel.wait(secs + 0.3)  # move time plus a short settle gap; wakes early on cancel
            state["now"] = ""

    threading.Thread(target=worker, daemon=True).start()

    try:
        while True:
            k = scr.getch()
            if mode == "DRIVE":
                if k == ord("q"):
                    break
                if k == ord(" "):
                    clear_queue()
                    tank.send("stop")
                elif k in (ord("-"), ord("_")):
                    speed = max(10, speed - 5)
                elif k in (ord("="), ord("+")):
                    speed = min(MAX_SPEED, speed + 5)
                elif k in KEYS:
                    clear_queue()  # manual always wins
                    tank.send(KEYS[k], PULSE, speed)
                elif k in (ord("t"), 10, 13, curses.KEY_ENTER):
                    mode = "TYPE"
            else:
                if k == 27:  # Esc
                    mode, line = "DRIVE", ""
                elif k in (10, 13, curses.KEY_ENTER):
                    if not line.strip():
                        mode = "DRIVE"
                    else:
                        if not raw:
                            items, msgs = parse(line, speed)
                        elif llama_raw.is_stop(line):
                            items, msgs = [("stop", 0, 0, "stop")], []
                        else:
                            runner.submit(line, speed)
                            items, msgs = [], [f"? {line!r}: asking Llama"]
                        if any(m == "stop" for m, *_ in items):
                            clear_queue()  # stop jumps the queue
                            tank.send("stop", tag="queue")
                            msgs.append("STOP: queue cleared")
                        else:
                            queue.extend(items)
                        state["msgs"].extend(msgs)
                        line = ""
                elif k in (curses.KEY_BACKSPACE, 127, 8):
                    line = line[:-1]
                elif 32 <= k < 127:
                    line += chr(k)

            h, w = scr.getmaxyx()
            rows = [
                f"{'RAW LLAMA  ' if raw else ''}{mode}  speed {speed}%  last {tank.last}  rtt {tank.rtt:.0f}ms",
                f"now: {state['now'] or '-'}",
                f"queue ({len(queue)}): " + ", ".join(f"{lbl.split('.')[-1]} {s:g}s" for _, s, _, lbl in list(queue)[:6]),
                "",
                *state["msgs"],
                "",
            ]
            if mode == "TYPE":
                rows.append("> " + line + "_")
                rows.append("Enter queue · empty Enter/Esc drive mode")
            else:
                rows.append("WASD/arrows drive · SPACE stop · -/= speed")
                rows.append("t type · q quit")
            scr.erase()
            for y, text in enumerate(rows[:h]):
                scr.addstr(y, 0, text[: w - 1])  # phone screens are narrow: clip
            scr.refresh()
            time.sleep(0.01)
    finally:
        try:
            queue.clear()
            tank.send("stop")
        finally:
            tank.c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Drive the tank by keyboard or typed instructions.")
    ap.add_argument("--raw", action="store_true",
                    help="typed instructions go to Llama on Ollama, not the fixed-phrase parser")
    curses.wrapper(main, raw=ap.parse_args().raw)
