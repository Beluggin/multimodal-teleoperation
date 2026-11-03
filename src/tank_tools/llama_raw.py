#!/usr/bin/env python3
"""llama_raw.py - raw mode: Llama reads the words, with no fixed-phrase parser.

This is the project's starting baseline made runnable: words -> Llama on
Ollama -> motor moves. There is no vision and no parser in the path, so it can
be compared with the main pipeline. It is optional. The main drive path does
not use it.

Llama decides what the words mean. It doesn't get a say in these:
  - Stop never reaches the model. A plain word check runs first, so stop can't
    wait on inference or be misread ("emergency stop right now" once came back
    from Llama as stop AND turn right).
  - Replies are checked strictly. A malformed reply, or one bad move in a plan,
    moves nothing.
  - Time per move is capped here, and the listener caps it again. The model
    can't choose speed or trim.
  - A stop or manual key pressed while Llama is thinking throws its answer away.

Negation and ambiguity are NOT guaranteed here the way they are with the
parser. That is the point of the comparison. Only the limits above are hard.

Environment:
    OLLAMA_URL         default http://localhost:11434
    TANK_LLAMA_MODEL   default llama3.2:3b
"""
import json
import math
import os
import queue
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"
TIMEOUT_S = 60.0  # a cold load on the Pi took ~12 s
MOVES = ("go", "rev", "spinl", "spinr")
MAX_MOVES = 5
MAX_SECS = 3.0

# Deliberately broad: a false stop is harmless and a missed one is not.
_STOP_WORDS = re.compile(
    r"\b(stop|stops|stopping|halt|freeze|whoa|abort|brake|emergency|e-?stop)\b",
    re.I)

SYSTEM_PROMPT = """\
You turn one instruction into moves for a small tracked robot.
Reply with JSON only, in this exact form:
{"moves": [{"move": "go", "secs": 1.0}]}

Moves:
go = drive forward. rev = drive backward. spinl = turn left. spinr = turn right.

secs is how long the move lasts, from 0.1 to 3.0.
Use the time the instruction gives. Otherwise use 1.0 for go and rev.
A 90 degree turn is 0.65. Turning around is spinl for 1.25.
Do things in the order given. Use only what was asked for and add nothing extra.
If the instruction doesn't ask the robot to drive or turn, reply {"moves": []}.
If it says not to do something, reply {"moves": []}.

Examples:
"go forward" -> {"moves": [{"move": "go", "secs": 1.0}]}
"back up for 2 seconds" -> {"moves": [{"move": "rev", "secs": 2.0}]}
"turn left then go forward" -> {"moves": [{"move": "spinl", "secs": 0.65}, {"move": "go", "secs": 1.0}]}
"what is your name" -> {"moves": []}
"don't go forward" -> {"moves": []}
"""


@dataclass
class Plan:
    moves: List[Tuple[str, float]] = field(default_factory=list)
    stop: bool = False          # stop word found; the model was not asked
    reason: str = ""            # why nothing moves, when moves is empty
    capped: bool = False        # a move's time was cut to MAX_SECS
    latency_s: Optional[float] = None  # model time; None if it wasn't asked


def is_stop(text: str) -> bool:
    return bool(_STOP_WORDS.search(text))


def ask_ollama(text: str, model: Optional[str] = None,
               url: Optional[str] = None,
               timeout: float = TIMEOUT_S) -> str:
    """One instruction -> the model's raw reply text. Raises on failure."""
    base = url or os.environ.get("OLLAMA_URL") or DEFAULT_URL
    body = json.dumps({
        "model": model or os.environ.get("TANK_LLAMA_MODEL") or DEFAULT_MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": text,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0, "num_predict": 96},
    }).encode()
    req = urllib.request.Request(base.rstrip("/") + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    # No proxy: this is a box on the local network, never a third party.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())["response"]


def check_reply(reply: str) -> Plan:
    """Model text -> Plan. All or nothing: one bad move rejects the whole plan."""
    try:
        data = json.loads(reply)
    except (TypeError, ValueError):
        return Plan(reason="reply wasn't JSON")
    if not isinstance(data, dict) or not isinstance(data.get("moves"), list):
        return Plan(reason="reply has no moves list")
    raw = data["moves"]
    if not raw:
        return Plan(reason="Llama chose no motion")
    if len(raw) > MAX_MOVES:
        return Plan(reason=f"more than {MAX_MOVES} moves")
    plan = Plan()
    for item in raw:
        if not isinstance(item, dict):
            return Plan(reason="malformed move")
        move, secs = item.get("move"), item.get("secs")
        if move not in MOVES:
            return Plan(reason=f"unknown move {move!r}")
        if (isinstance(secs, bool) or not isinstance(secs, (int, float))
                or not math.isfinite(secs) or secs <= 0):
            return Plan(reason=f"bad secs {secs!r}")
        if secs > MAX_SECS:
            plan.capped = True
        plan.moves.append((move, min(float(secs), MAX_SECS)))
    return plan


def interpret(text: str, ask: Callable[[str], str] = ask_ollama) -> Plan:
    """One typed line -> Plan. Stop short-circuits; any model failure moves nothing."""
    if is_stop(text):
        return Plan(stop=True)
    start = time.monotonic()
    try:
        reply = ask(text)
    except Exception as exc:  # no network, no model, timeout, bad HTTP body
        return Plan(reason=f"Llama unavailable: {type(exc).__name__}",
                    latency_s=time.monotonic() - start)
    plan = check_reply(reply)
    plan.latency_s = time.monotonic() - start
    return plan


class RawRunner:
    """Runs model calls off the UI thread, in order, and can drop them.

    cancel() returns only after any delivery in progress has finished. A caller
    that cancels and then clears its queue therefore can't have a late plan
    added after the clear. Call cancel() before taking the queue's own lock.
    """

    def __init__(self, deliver: Callable[[str, Plan, float], None],
                 ask: Callable[[str], str] = ask_ollama):
        self._deliver = deliver
        self._ask = ask
        self._lock = threading.Lock()
        self._epoch = 0
        self._jobs: "queue.Queue[Tuple[int, str, float]]" = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, text: str, speed: float) -> None:
        with self._lock:
            self._jobs.put((self._epoch, text, speed))

    def cancel(self) -> None:
        with self._lock:
            self._epoch += 1

    def _loop(self) -> None:
        while True:
            epoch, text, speed = self._jobs.get()
            with self._lock:
                if epoch != self._epoch:
                    continue
            plan = interpret(text, self._ask)  # slow; holds no lock
            with self._lock:
                if epoch == self._epoch:
                    self._deliver(text, plan, speed)


def plan_to_queue(text: str, plan: Plan, speed: float):
    """Plan -> tank_control queue items and on-screen messages."""
    if not plan.moves:
        return [], [f"x {text!r}: {plan.reason}"]
    items = [(move, secs, speed, f"llama.{move}") for move, secs in plan.moves]
    took = "" if plan.latency_s is None else f" in {plan.latency_s:.1f}s"
    desc = ", ".join(f"{m} {s:g}s" for m, s in plan.moves)
    note = " (capped)" if plan.capped else ""
    return items, [f"+ {text!r} -> {desc}{took}{note}"]
