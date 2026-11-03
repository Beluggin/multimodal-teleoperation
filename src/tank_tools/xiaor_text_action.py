#!/usr/bin/env python3
"""
xiaor_text_action.py — fixed-phrase text → action for the XiaoR Geek tank + arm.

Stdlib only. Runs ON the Pi (no torch/transformers or LLM parse path needed).
Emits command dicts in the exact shape tank_server.execute_command() accepts.

    text → classify() → Action(commands=[...]) → run() → tank_server REST

Usage:
    python3 xiaor_text_action.py "drive forward for 3 seconds"   # dry run
    python3 xiaor_text_action.py --exec "wave"                    # send to tank
    python3 xiaor_text_action.py --list                            # phrase cheat-sheet
    python3 xiaor_text_action.py --smoke                           # self-check

Pi deploy: copy this one file next to tank_server.py (same minimum set as
tank_setup.md). --exec posts to $TANK_URL (default http://localhost:5000)
with $TANK_TOKEN (no default; set it in the environment).

Safety aim (not a guarantee, see eval/README.md): unknown, negated ("don't ..."), and
ambiguous ("forward and wave") inputs should not move. E-stop ("stop now",
"emergency stop") skips claim and always sends emergency_stop. Read-only
queries (sensors/status) skip claim too. "Go to/get the <target>" inputs
classify as kind="goto" with NO commands: this parser never moves for
them — a desktop vision loop (tank_vision/drive_run.py --text) consumes
the extracted target and drives in bounded, re-recognised steps.
"""

import argparse
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Servo map — copied from the tank's calibrated servo config (Adam's tank,
# confirmed by physical testing) so this file stays single-file deployable
# on the Pi. If the wiring changes, update both copies.
# ---------------------------------------------------------------------------
SERVO = {
    "arm_base": 1,    # shoulder rotation
    "arm_mid": 2,     # elbow
    "claw_rotate": 3,  # wrist rotation
    "claw_pinch": 4,  # grip open/close
    "cam_pan": 5,     # camera left/right
    "cam_tilt": 6,    # camera up/down
    # 7 and 8 are empty (bigger arm SKU)
}

SERVO_LIMITS = {
    1: (10, 170),   # arm base
    2: (0, 180),    # arm mid
    3: (0, 180),    # claw rotate
    4: (10, 130),   # claw pinch (10=closed, 130=wide open)
    5: (10, 170),   # cam pan
    6: (5, 130),    # cam tilt
}

HOME = {1: 115, 2: 180, 3: 0, 4: 50, 5: 95, 6: 79}  # calibrated, from data.ini

# Timed-drive ceiling: "forward for 999 seconds" still auto-stops at 30s.
MAX_DURATION = 30.0
# Speed words. The tank config's autonomous cap is 40; FAST must not exceed it.
SLOW_SPEED = 25
FAST_SPEED = 40

DEFAULT_URL = os.environ.get("TANK_URL", "http://localhost:5000")
DEFAULT_TOKEN = os.environ.get("TANK_TOKEN", "")


# ---------------------------------------------------------------------------
# Command builders (tank_server.execute_command shapes)
# ---------------------------------------------------------------------------
def _move(direction: str) -> dict:
    return {"action": "move", "direction": direction}


def _servo(num: int, angle: int) -> dict:
    return {"action": "servo", "num": num, "angle": angle}


def _gesture(seq) -> Tuple[List[dict], List[float]]:
    """Flatten a [(servo_dict, delay_after), ...] gesture (same shape as the
    tank config's GESTURE_* sequences) into commands + per-command
    pauses. The pause lands after the step's last servo command."""
    commands, delays = [], []
    for servo_dict, delay in seq:
        items = list(servo_dict.items())
        for i, (num, angle) in enumerate(items):
            commands.append(_servo(num, angle))
            delays.append(delay if i == len(items) - 1 else 0.0)
    return commands, delays


# Gestures ported from the tank's calibrated servo config.
_GESTURE_WAVE = [
    ({1: 90, 2: 90, 3: 90, 4: 50}, 0.5),
    ({2: 50}, 0.3),
    ({3: 40}, 0.2),
    ({3: 140}, 0.3),
    ({3: 40}, 0.3),
    ({3: 140}, 0.3),
    ({3: 90}, 0.2),
    ({2: 180, 1: 115, 3: 0, 4: 50}, 0.5),
]
_GESTURE_PET = [
    ({1: 90, 2: 120, 3: 90, 4: 130}, 0.5),
    ({2: 150}, 0.3),
    ({2: 120}, 0.3),
    ({2: 150}, 0.3),
    ({2: 120}, 0.3),
    ({2: 180, 1: 115, 3: 0, 4: 50}, 0.5),
]
_GESTURE_HOME = [({1: 115, 2: 180, 3: 0, 4: 50}, 0.8)]

_WAVE_CMDS, _WAVE_DELAYS = _gesture(_GESTURE_WAVE)
_PET_CMDS, _PET_DELAYS = _gesture(_GESTURE_PET)
_HOME_CMDS, _HOME_DELAYS = _gesture(_GESTURE_HOME)

# "turn around" duration: hallway PATROL_ROUTE notes left 1.6s ≈ 180°.
TURN_AROUND_SECONDS = 1.6


@dataclass
class ActionDef:
    kind: str            # drive|arm|camera|lights|query|speed|stop|estop
    label: str           # canonical name, e.g. "drive.forward"
    commands: List[dict]
    delays: List[float]  # pause AFTER each command
    duration: Optional[float] = None  # timed auto-stop (drive only)


# Every servo angle below was checked against SERVO_LIMITS (see --smoke and
# test_xiaor_text_action.py). Conventions to verify on hardware on first run:
# arm_base 150=left / 80=right, cam_pan 150=left / 40=right.
ACTIONS: Dict[str, ActionDef] = {
    # -- drive --
    "forward":  ActionDef("drive", "drive.forward", [_move("forward")], [0.0]),
    "backward": ActionDef("drive", "drive.backward", [_move("backward")], [0.0]),
    "left":     ActionDef("drive", "drive.left", [_move("left")], [0.0]),
    "right":    ActionDef("drive", "drive.right", [_move("right")], [0.0]),
    "around":   ActionDef("drive", "drive.around", [_move("left")], [0.0],
                          duration=TURN_AROUND_SECONDS),
    "stop":     ActionDef("stop", "drive.stop", [_move("stop")], [0.0]),
    "estop":    ActionDef("estop", "drive.estop", [{"action": "emergency_stop"}],
                          [0.0]),
    "slow_down": ActionDef("speed", "drive.slow",
                            [{"action": "speed", "left": SLOW_SPEED,
                              "right": SLOW_SPEED}], [0.0]),
    "speed_up": ActionDef("speed", "drive.fast",
                           [{"action": "speed", "left": FAST_SPEED,
                             "right": FAST_SPEED}], [0.0]),
    # -- arm --
    "arm_up":      ActionDef("arm", "arm.up", [_servo(2, 180)], [0.0]),
    "arm_down":    ActionDef("arm", "arm.down", [_servo(2, 100)], [0.0]),
    "reach":       ActionDef("arm", "arm.reach",
                              [_servo(1, 90), _servo(2, 120)], [0.3, 0.3]),
    "arm_left":    ActionDef("arm", "arm.left", [_servo(1, 150)], [0.0]),
    "arm_right":   ActionDef("arm", "arm.right", [_servo(1, 80)], [0.0]),
    "claw_open":   ActionDef("arm", "arm.claw_open", [_servo(4, 130)], [0.0]),
    "claw_close":  ActionDef("arm", "arm.claw_close", [_servo(4, 10)], [0.0]),
    "wrist_left":  ActionDef("arm", "arm.wrist_left", [_servo(3, 40)], [0.0]),
    "wrist_right": ActionDef("arm", "arm.wrist_right", [_servo(3, 140)], [0.0]),
    "wrist_center": ActionDef("arm", "arm.wrist_center", [_servo(3, 90)], [0.0]),
    "wrist_spin":  ActionDef("arm", "arm.wrist_spin",
                              [{"action": "servo_sweep", "num": 3, "start": 40,
                                "end": 140, "step": 4, "delay": 0.02}], [0.0]),
    "wave":      ActionDef("arm", "arm.wave", _WAVE_CMDS, _WAVE_DELAYS),
    "pet":       ActionDef("arm", "arm.pet", _PET_CMDS, _PET_DELAYS),
    "arm_home":  ActionDef("arm", "arm.home", _HOME_CMDS, _HOME_DELAYS),
    # -- camera --
    "look_left":   ActionDef("camera", "cam.left", [_servo(5, 150)], [0.0]),
    "look_right":  ActionDef("camera", "cam.right", [_servo(5, 40)], [0.0]),
    "look_up":     ActionDef("camera", "cam.up", [_servo(6, 110)], [0.0]),
    "look_down":   ActionDef("camera", "cam.down", [_servo(6, 30)], [0.0]),
    "look_center": ActionDef("camera", "cam.center",
                              [_servo(5, 95), _servo(6, 79)], [0.2, 0.2]),
    # -- accessories --
    "lights_on":  ActionDef("lights", "lights.on",
                             [{"action": "headlight", "on": True}], [0.0]),
    "lights_off": ActionDef("lights", "lights.off",
                             [{"action": "headlight", "on": False}], [0.0]),
    # -- read-only queries (never move, skip claim) --
    "sensors": ActionDef("query", "query.sensors", [{"action": "sensor_read"}],
                         [0.0]),
    "status":  ActionDef("query", "query.status", [{"action": "status"}],
                         [0.0]),
}

# ---------------------------------------------------------------------------
# Fixed phrase table: (phrase, action_id). Bare directionless "go"/"move"/
# "drive" are DELIBERATELY absent — we never guess a direction
# ("just move around" → unknown, not a random drive). Bare "kill" is absent
# too ("kill the lights" must not e-stop); use "kill it"/"stop now".
# ---------------------------------------------------------------------------
PHRASES: List[Tuple[str, str]] = [
    # -- drive --
    ("drive forward", "forward"), ("move forward", "forward"),
    ("go forward", "forward"), ("move ahead", "forward"),
    ("go ahead", "forward"), ("straight ahead", "forward"),
    ("forward", "forward"), ("ahead", "forward"), ("straight", "forward"),
    ("advance", "forward"),
    ("back up", "backward"), ("move back", "backward"),
    ("go back", "backward"), ("drive back", "backward"),
    ("move backward", "backward"), ("go backward", "backward"),
    ("backward", "backward"), ("backwards", "backward"),
    ("reverse", "backward"), ("back", "backward"),
    ("turn left", "left"), ("go left", "left"), ("move left", "left"),
    ("veer left", "left"), ("left", "left"),
    ("turn right", "right"), ("go right", "right"), ("move right", "right"),
    ("veer right", "right"), ("right", "right"),
    ("turn around", "around"), ("turn back", "around"),
    ("u-turn", "around"), ("u turn", "around"),
    ("hold still", "stop"), ("stop", "stop"), ("halt", "stop"),
    ("freeze", "stop"), ("hold", "stop"), ("wait", "stop"),
    ("stay", "stop"), ("pause", "stop"), ("whoa", "stop"),
    ("emergency stop", "estop"), ("stop now", "estop"),
    ("e-stop", "estop"), ("estop", "estop"),
    ("kill it", "estop"), ("abort", "estop"),
    ("slow down", "slow_down"), ("speed up", "speed_up"),
    # -- arm --
    ("raise the arm", "arm_up"), ("raise your arm", "arm_up"),
    ("lift the arm", "arm_up"), ("lift your arm", "arm_up"),
    ("arm raise", "arm_up"), ("arm up", "arm_up"), ("arms up", "arm_up"),
    ("lower the arm", "arm_down"), ("lower your arm", "arm_down"),
    ("drop the arm", "arm_down"), ("arm lower", "arm_down"),
    ("arm down", "arm_down"),
    ("reach forward", "reach"), ("reach out", "reach"),
    ("arm forward", "reach"), ("arm out", "reach"),
    ("stretch out", "reach"), ("stretch", "reach"), ("reach", "reach"),
    ("swing the arm left", "arm_left"), ("arm to the left", "arm_left"),
    ("swing left", "arm_left"), ("arm left", "arm_left"),
    ("swing the arm right", "arm_right"), ("arm to the right", "arm_right"),
    ("swing right", "arm_right"), ("arm right", "arm_right"),
    ("open the claw", "claw_open"), ("open your claw", "claw_open"),
    ("claw open", "claw_open"), ("open up", "claw_open"),
    ("let go", "claw_open"), ("release", "claw_open"),
    ("drop it", "claw_open"), ("drop", "claw_open"),
    ("close the claw", "claw_close"), ("close your claw", "claw_close"),
    ("claw close", "claw_close"), ("pick it up", "claw_close"),
    ("pick up", "claw_close"), ("take it", "claw_close"),
    ("grab", "claw_close"), ("grip", "claw_close"),
    ("grasp", "claw_close"), ("squeeze", "claw_close"),
    ("turn the wrist left", "wrist_left"), ("wrist left", "wrist_left"),
    ("twist left", "wrist_left"),
    ("turn the wrist right", "wrist_right"), ("wrist right", "wrist_right"),
    ("twist right", "wrist_right"),
    ("straighten the wrist", "wrist_center"), ("center the wrist",
                                                        "wrist_center"),
    ("wrist center", "wrist_center"),
    ("rotate the wrist", "wrist_spin"), ("twist the wrist", "wrist_spin"),
    ("spin the wrist", "wrist_spin"), ("rotate wrist", "wrist_spin"),
    ("wave hello", "wave"), ("say hi", "wave"),
    ("wave", "wave"), ("hello", "wave"), ("hey", "wave"), ("hi", "wave"),
    ("pet", "pet"),
    ("stow the arm", "arm_home"), ("rest the arm", "arm_home"),
    ("park the arm", "arm_home"), ("arm rest", "arm_home"),
    ("arm home", "arm_home"), ("stow", "arm_home"),
    # -- camera --
    ("look left", "look_left"), ("look right", "look_right"),
    ("look up", "look_up"), ("look down", "look_down"),
    ("center the camera", "look_center"), ("look straight", "look_center"),
    ("look forward", "look_center"), ("look ahead", "look_center"),
    ("look center", "look_center"),
    # -- accessories --
    ("turn on the lights", "lights_on"), ("turn the lights on", "lights_on"),
    ("headlights on", "lights_on"), ("headlight on", "lights_on"),
    ("lights on", "lights_on"), ("light on", "lights_on"),
    ("turn off the lights", "lights_off"),
    ("turn the lights off", "lights_off"),
    ("kill the lights", "lights_off"), ("kill the light", "lights_off"),
    ("headlights off", "lights_off"), ("headlight off", "lights_off"),
    ("lights off", "lights_off"), ("light off", "lights_off"),
    ("lights out", "lights_off"),
    # -- queries (read-only, never move) --
    ("what do you see", "sensors"), ("check the sensors", "sensors"),
    ("read the sensors", "sensors"), ("check sensors", "sensors"),
    ("any obstacles", "sensors"), ("obstacle", "sensors"),
    ("how far", "sensors"), ("distance", "sensors"), ("ping", "sensors"),
    ("what are you doing", "status"), ("how are you", "status"),
    ("report in", "status"), ("report", "status"), ("status", "status"),
]

_NEGATOR = re.compile(r"\b(?:don't|dont|do\s+not|won't|wont|never|not|no)\b",
                      re.I)
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(?:s\b|sec|secs|second|seconds)",
                       re.I)
_SLOW = re.compile(r"\bslow(ly)?\b|\bslow\s+down\b", re.I)
_FAST = re.compile(r"\bfast\b|\bspeed\s+up\b", re.I)
_WORD = re.compile(r"[a-z0-9']+")


def _normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _phrase_re(phrase: str) -> "re.Pattern":
    return re.compile(r"\b" + r"\s+".join(map(re.escape, phrase.split())) +
                      r"\b")


_PHRASE_RES: List[Tuple["re.Pattern", str, str]] = [
    (_phrase_re(_normalize(p)), p, aid) for p, aid in PHRASES
]


@dataclass
class Action:
    kind: str                 # drive|arm|camera|lights|query|speed|stop|estop|
                              # goto|unknown|refused|ambiguous
    label: str                # canonical name, e.g. "drive.forward"
    commands: List[dict] = field(default_factory=list)
    delays: List[float] = field(default_factory=list)
    duration: Optional[float] = None   # timed drive: auto-stop after N s
    matched: str = ""                  # phrase that fired
    reason: str = ""
    target: str = ""                   # goto only: vision target, e.g. "shoe"
    targets: List[str] = field(default_factory=list)  # goto: every mission, in order


def _no_motion(kind: str, reason: str) -> Action:
    return Action(kind=kind, label=kind, reason=reason)


# "go to/get/find the <target>": the rest of the sentence after the verb.
# Speech synonyms ("investigate the thing", "check out the thing", ...)
# route to the same goto: they extract a target and never move anything.
# Bare "check"/"look" are deliberately NOT verbs here — "check the
# sensors" is a query and "look left" is a camera move.
_GOTO_REST = re.compile(
    r"\b(?:go\s+(?:to|get|find|fetch|chase)|drive\s+to|head\s+to|get|fetch"
    r"|find|chase"
    r"|investigate|examine|inspect|check\s+out"
    r"|take\s+a\s+look\s+at|have\s+a\s+look\s+at|go\s+look\s+at|look\s+at"
    r"|go\s+(?:investigate|examine|inspect))"
    r"\s+(.*)$")
_GOTO_DETERMINERS = {"the", "a", "an", "that", "this", "my"}
_GOTO_TRAILING = {"now", "please"}
_GOTO_CLAUSE = {"and", "then", "or", "for", "with"}
_GOTO_PRONOUNS = {"it", "there", "here"}


def _goto_rest(norm: str) -> Optional[str]:
    """Raw text after a goto verb, or None when no goto template matches."""
    m = _GOTO_REST.search(norm)
    return m.group(1) if m else None


def _clean_target(rest: str) -> Tuple[Optional[str], str]:
    """(target, "") when clean, else (None, why-not)."""
    words = rest.split()
    while words and words[0] in _GOTO_DETERMINERS:
        words.pop(0)
    while words and words[-1] in _GOTO_TRAILING:
        words.pop()
    if not words:
        return None, "empty target"
    if any(w in _GOTO_CLAUSE for w in words):
        return None, "extra clause"
    if len(words) > 4:
        return None, "target too long"
    if not all(re.fullmatch(r"[a-z0-9][a-z0-9'-]*", w) for w in words):
        return None, "bad target words"
    target = " ".join(words)
    if target in _GOTO_PRONOUNS:
        return None, "pronoun target — name the thing"
    return target, ""


_CHAIN_SPLIT = re.compile(r"\s+(?:and\s+)?then\b\s*")
MAX_CHAIN = 3


def _goto_chain(norm: str) -> Optional[List[str]]:
    """'go to the ball then go to the mug' -> ['ball', 'mug'], else None.

    Every segment must classify as a clean goto on its own (a bare
    'the mug' after 'then' is read as 'go to the mug'). One non-goto
    segment — wave, stop, a negation, a drive word — and the whole
    chain is off, so classify falls through to its normal handling.
    """
    parts = _CHAIN_SPLIT.split(norm)
    if len(parts) < 2 or len(parts) > MAX_CHAIN:
        return None
    targets = []
    for part in parts:
        a = classify(part)
        if (a.kind != "goto" and part and not _goto_rest(part)
                and part.split()[0] in _GOTO_DETERMINERS):
            a = classify("go to " + part)   # "...then the mug"
        if a.kind != "goto" or not a.target:
            return None
        targets.append(a.target)
    return targets


def classify(text: str) -> Action:
    """Fixed-phrase text → Action. Never raises on weird input; anything it
    can't map cleanly comes back as unknown/refused/ambiguous with NO commands.
    """
    norm = _normalize(text or "")
    if not norm:
        return _no_motion("unknown", "empty input")

    chain = _goto_chain(norm)
    if chain:
        return Action(kind="goto", label="goto", target=chain[0],
                      targets=chain, matched="goto chain",
                      reason=f"goto chain {' -> '.join(chain)} "
                             f"(vision loop, one mission at a time)")

    # All phrase hits; longest wins overlaps ("kill the lights" beats "kill",
    # "look ahead" beats "ahead"). Same-action overlaps collapse to one.
    hits = []
    for rx, phrase, aid in _PHRASE_RES:
        for m in rx.finditer(norm):
            hits.append((m.start(), m.end(), len(phrase), phrase, aid))
    hits.sort(key=lambda h: (-h[2], h[0]))
    accepted: List[Tuple[str, str]] = []  # (phrase, action_id)
    used: List[Tuple[int, int]] = []
    for s, e, _, phrase, aid in hits:
        if all(e <= u0 or s >= u1 for u0, u1 in used):
            used.append((s, e))
            accepted.append((phrase, aid))

    distinct = {}
    for phrase, aid in accepted:
        distinct.setdefault(aid, phrase)

    # Goto routing ("go get the shoe"): never a command itself. Negation
    # refuses it, stop/estop still win, any other matched action makes it
    # ambiguous, and a dirty target falls back to unknown.
    rest = _goto_rest(norm)
    if rest is not None:
        if _NEGATOR.search(norm):
            return _no_motion("refused",
                              "negated command — not executing")
        if distinct and not set(distinct) <= {"stop", "estop"}:
            labels = sorted(ACTIONS[a].label for a in distinct)
            return _no_motion("ambiguous",
                              f"goto plus {', '.join(labels)} "
                              f"— say one at a time")
        if not distinct:
            target, why = _clean_target(rest)
            if target is None:
                if why == "extra clause":
                    return _no_motion("ambiguous",
                                      "goto with an extra clause "
                                      "— say one at a time")
                return _no_motion("unknown",
                                  f"no usable target in {text!r} ({why})")
            return Action(kind="goto", label="goto", target=target,
                          targets=[target], matched="goto",
                          reason=f"goto target {target!r} "
                                 f"— vision loop required, no motion sent")
        # Only stop/estop matched alongside: fall through, stop wins.

    if not distinct:
        return _no_motion("unknown", f"no matching action for {text!r}")
    if len(distinct) > 1:
        # Negated commands never execute, even when stop is present.
        if _NEGATOR.search(norm):
            return _no_motion("refused",
                               "negated command — not executing")
        # Stop takes priority: estop beats stop beats everything else.
        # ("forward stop", "hey stop", "stop right now" must all stop.)
        if "estop" in distinct:
            distinct = {"estop": distinct["estop"]}
        elif "stop" in distinct:
            distinct = {"stop": distinct["stop"]}
        else:
            labels = sorted(ACTIONS[a].label for a in distinct)
            return _no_motion("ambiguous",
                               f"matches {len(distinct)} actions "
                               f"({', '.join(labels)}) — say one at a time")

    aid = next(iter(distinct))
    matched = distinct[aid]

    # Negated commands never execute.
    if _NEGATOR.search(norm):
        return _no_motion("refused",
                           f"negated command ({matched!r}) — not executing")

    spec = ACTIONS[aid]
    commands = [dict(c) for c in spec.commands]
    delays = list(spec.delays)
    duration = spec.duration
    notes = []

    if spec.kind == "drive":
        # Parse durations from the raw text: _normalize() strips "." so
        # "0.5 seconds" becomes "0 5 seconds" and misparses as 5s.
        m = _DURATION.search((text or "").lower())
        if m:
            if float(m.group(1)) <= 0:
                return _no_motion("refused",
                                  "zero duration — not executing")
            duration = min(float(m.group(1)), MAX_DURATION)
            notes.append(f"timed {duration:g}s")
        if _SLOW.search(norm):
            commands.insert(0, {"action": "speed", "left": SLOW_SPEED,
                                "right": SLOW_SPEED})
            delays.insert(0, 0.0)
            notes.append("slow")
        elif _FAST.search(norm):
            commands.insert(0, {"action": "speed", "left": FAST_SPEED,
                                "right": FAST_SPEED})
            delays.insert(0, 0.0)
            notes.append("fast")

    reason = f"matched {matched!r}"
    if notes:
        reason += f" ({', '.join(notes)})"
    return Action(kind=spec.kind, label=spec.label, commands=commands,
                  delays=delays, duration=duration, matched=matched,
                  reason=reason)


# ---------------------------------------------------------------------------
# Execution — claim-gated, but e-stop and read-only
# queries skip claim (e-stop must work even when unclaimed).
# ---------------------------------------------------------------------------
_CLAIM_KINDS = {"drive", "arm", "camera", "lights", "speed", "stop"}
_NO_MOTION_KINDS = {"unknown", "refused", "ambiguous", "goto"}

Sender = Callable[[dict], dict]


def send_command(cmd: dict, url: str = DEFAULT_URL,
                 token: str = DEFAULT_TOKEN, timeout: float = 5.0) -> dict:
    """POST one command dict. urllib only (no requests on a bare Pi).
    Returns the server JSON, or {"ok": False, ...} on transport failure."""
    req = urllib.request.Request(
        url.rstrip("/") + "/api/v1/command",
        data=json.dumps(cmd).encode(),
        headers={"Content-Type": "application/json",
                 "X-Tank-Token": token},
    )
    # Tank traffic is LAN-local: never let a proxy env var reroute it.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # network down, sim not running, ...
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def run(text: str, url: str = DEFAULT_URL, token: str = DEFAULT_TOKEN,
        sender: Optional[Sender] = None,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    """classify() + execute, with claim/release and timed-drive auto-stop.
    sender/sleep are injectable so tests run with no network and no waiting.
    Always returns a transcript dict; never raises for classification reasons.
    """
    sender = sender or (lambda cmd: send_command(cmd, url, token))
    action = classify(text)
    transcript = {
        "text": text, "kind": action.kind, "label": action.label,
        "matched": action.matched, "reason": action.reason,
        "target": action.target,
        "sent": [], "responses": [],
    }
    if action.kind in _NO_MOTION_KINDS:
        return transcript

    def _send(cmd):
        transcript["sent"].append(cmd)
        try:
            transcript["responses"].append(sender(cmd))
        except Exception as e:
            transcript["responses"].append({"ok": False,
                                            "error": f"{type(e).__name__}: {e}"})

    claimed = action.kind in _CLAIM_KINDS
    if claimed:
        _send({"action": "claim"})
    for cmd, pause in zip(action.commands, action.delays):
        _send(cmd)
        if pause:
            sleep(pause)
    if action.duration:
        sleep(action.duration)
        _send({"action": "move", "direction": "stop"})
    if claimed:
        _send({"action": "release"})
    return transcript


# ---------------------------------------------------------------------------
# Validation — every emitted command must be shippable to tank_server.
# ---------------------------------------------------------------------------
_KNOWN_ACTIONS = {"move", "speed", "sensor_read", "headlight", "servo",
                  "servo_sweep", "servo_center", "servo_save", "servo_reset",
                  "claim", "release", "status", "emergency_stop"}
_DIRECTIONS = {"forward", "backward", "left", "right", "stop"}


def validate_commands(action: Action) -> List[str]:
    """Return a list of problems (empty = shippable). Used by --smoke and the
    committed test; not on the hot path."""
    problems = []
    for cmd in action.commands:
        name = cmd.get("action")
        if name not in _KNOWN_ACTIONS:
            problems.append(f"unknown action {name!r}")
            continue
        if name == "move" and cmd.get("direction") not in _DIRECTIONS:
            problems.append(f"bad direction {cmd.get('direction')!r}")
        if name == "speed":
            for side in ("left", "right"):
                v = cmd.get(side)
                if not isinstance(v, int) or not 0 <= v <= 100:
                    problems.append(f"bad speed {side}={v!r}")
        if name in ("servo", "servo_sweep"):
            num = cmd.get("num")
            angles = ([cmd.get("angle")] if name == "servo"
                      else [cmd.get("start"), cmd.get("end")])
            lo, hi = SERVO_LIMITS.get(num, (0, 180))
            if num not in SERVO_LIMITS and num not in (7, 8):
                problems.append(f"bad servo num {num!r}")
            for a in angles:
                if not isinstance(a, (int, float)) or not lo <= a <= hi:
                    problems.append(f"servo {num} angle {a!r} outside "
                                     f"({lo},{hi})")
    if len(action.delays) != len(action.commands):
        problems.append("delays/commands length mismatch")
    if action.duration is not None and not 0 < action.duration <= MAX_DURATION:
        problems.append(f"duration {action.duration!r} outside (0, "
                        f"{MAX_DURATION}]")
    return problems


def list_phrases() -> str:
    lines = ["phrase → action (say any one of these):", ""]
    by_action: Dict[str, List[str]] = {}
    for phrase, aid in PHRASES:
        by_action.setdefault(aid, []).append(phrase)
    for aid in ACTIONS:
        if aid in by_action:
            lines.append(f"  {ACTIONS[aid].label}:")
            lines.append(f"    {'; '.join(by_action[aid])}")
    lines.append("  goto (vision loop, parser sends no motion):")
    lines.append("    go to the <target>; go get the <target>; "
                 "fetch the <target>; investigate the <target>; "
                 "check out the <target>; look at the <target>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI + smoke test (repo convention: runnable module self-check)
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fixed-phrase text → action for the XiaoR tank + arm.")
    ap.add_argument("text", nargs="*", help="command text (dry run unless "
                                            "--exec)")
    ap.add_argument("--exec", action="store_true",
                    help="send to the tank instead of printing")
    ap.add_argument("--url", default=DEFAULT_URL, help="tank server base URL")
    ap.add_argument("--token", default=DEFAULT_TOKEN, help="tank token")
    ap.add_argument("--list", action="store_true",
                    help="print the phrase cheat-sheet")
    ap.add_argument("--smoke", action="store_true", help="run self-check")
    args = ap.parse_args(argv)

    if args.list:
        print(list_phrases())
        return 0
    if args.smoke:
        return 0 if smoke() else 1
    if not args.text:
        ap.print_help()
        return 2
    text = " ".join(args.text)
    if args.exec:
        print(json.dumps(run(text, url=args.url, token=args.token), indent=2))
    else:
        action = classify(text)
        print(f"{action.label}  ({action.reason})")
        if action.target:
            print(f"  target: {action.target} "
                  f"(vision loop required — no motion sent)")
        for cmd, pause in zip(action.commands, action.delays):
            extra = f"  +pause {pause}s" if pause else ""
            print(f"  {json.dumps(cmd)}{extra}")
        if action.duration:
            print(f"  +auto-stop after {action.duration:g}s")
        if not action.commands:
            print("  (no motion)")
    return 0


def smoke() -> bool:
    """Quick self-check: key phrases, safety refusals, and command validity
    for the whole table. Returns True when all pass."""
    cases = [
        # (text, expected label, expected command count, expects duration?)
        ("drive forward", "drive.forward", 1, False),
        ("drive forward for 3 seconds", "drive.forward", 1, True),
        ("back up", "drive.backward", 1, False),
        ("turn left", "drive.left", 1, False),
        ("turn around", "drive.around", 1, True),
        ("go forward slowly", "drive.forward", 2, False),
        ("stop", "drive.stop", 1, False),
        ("stop now", "drive.estop", 1, False),
        ("wave", "arm.wave", len(_WAVE_CMDS), False),
        ("grab", "arm.claw_close", 1, False),
        ("open the claw", "arm.claw_open", 1, False),
        ("arm home", "arm.home", len(_HOME_CMDS), False),
        ("look left", "cam.left", 1, False),
        ("lights on", "lights.on", 1, False),
        ("kill the lights", "lights.off", 1, False),
        ("how far", "query.sensors", 1, False),
        ("status", "query.status", 1, False),
        ("don't move forward", "refused", 0, False),
        ("just move around", "unknown", 0, False),
        ("go get the shoe", "goto", 0, False),
        ("investigate the shoe", "goto", 0, False),
        ("check out the shoe", "goto", 0, False),
        ("go to the kitchen", "goto", 0, False),
        ("don't go to the shoe", "refused", 0, False),
        ("drive forward and wave", "ambiguous", 0, False),
    ]
    failures = 0
    for text, label, n_cmds, want_dur in cases:
        a = classify(text)
        ok = (a.label == label and len(a.commands) == n_cmds and
              (a.duration is not None) == want_dur and not validate_commands(a))
        print(f"  {'ok ' if ok else 'FAIL'} {text!r:32} → {a.label}")
        failures += not ok
    # Every table phrase must classify to its own action with valid commands.
    for phrase, aid in PHRASES:
        a = classify(phrase)
        problems = validate_commands(a)
        if a.label != ACTIONS[aid].label or problems:
            print(f"  FAIL table {phrase!r} → {a.label} {problems}")
            failures += 1
    print(f"smoke: {'PASS' if not failures else f'{failures} FAILURES'}")
    return not failures


if __name__ == "__main__":
    raise SystemExit(main())

