#!/usr/bin/env python3
"""Build the raw-mode fine-tuning set: one instruction -> the moves JSON.

Everything is generated from the word lists below with a fixed seed, so the set
can be rebuilt exactly. Nothing from eval/commands.json or eval/heldout.json goes
in as a whole command, and the build fails if one does. Words that only the
held-out test uses (advance, retreat, veer, gun it, take a right...) are left out
of the lists, so that test measures phrases the model never trained on.

    python3 train/make_dataset.py        # writes train/data/{train,val}.jsonl
"""
import json
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.join(os.path.dirname(HERE), "eval")
OUT = os.path.join(HERE, "data")
SEED = 3202

# Same timings as raw mode's prompt: 90 degrees is 0.65 s, turning around is 1.25 s.
DEFAULT = {"go": 1.0, "rev": 1.0, "spinl": 0.65, "spinr": 0.65}
AROUND = 1.25
SMALL = {"go": 0.5, "rev": 0.5, "spinl": 0.33, "spinr": 0.33}
BIG = {"go": 2.0, "rev": 2.0, "spinl": 0.65, "spinr": 0.65}
MAX_SECS = 3.0

PHRASES = {
    "go": ["go ahead", "go straight", "go straight ahead", "drive forward", "drive straight",
           "drive", "move forward", "proceed forward", "proceed", "keep going forward",
           "travel forward", "onward", "forward", "straight ahead", "go on ahead",
           "cruise forward", "creep forward", "ease forward", "push forward", "continue ahead"],
    "rev": ["back up", "go back", "go backward", "drive backward", "drive backwards",
            "drive in reverse", "move backward", "move backwards", "move in reverse",
            "reverse up", "backward", "backwards", "back away", "back off", "travel backward",
            "ease backward", "creep backward", "put it in reverse"],
    "spinl": ["go left", "left", "turn to the left", "turn to your left", "spin left",
              "pivot left", "pivot to the left", "bank left", "steer left", "make a left",
              "make a left turn", "hook left", "spin to the left", "turn counterclockwise"],
    "spinr": ["go right", "right", "turn to the right", "turn to your right", "spin right",
              "pivot right", "pivot to the right", "bank right", "steer right", "make a right",
              "make a right turn", "hook right", "spin to the right", "turn clockwise"],
}
# Plain core phrases, used in timed moves, chains and negation.
CORE = {
    "go": ["go forward", "drive forward", "move forward", "go ahead", "drive ahead"],
    "rev": ["back up", "reverse", "go back", "drive backward", "move backward"],
    "spinl": ["turn left", "spin left", "go left", "pivot left"],
    "spinr": ["turn right", "spin right", "go right", "pivot right"],
}
AROUND_PHRASES = ["spin around", "flip around", "turn yourself around", "turn all the way around",
                  "come about", "reverse direction by turning around", "turn back the way you came",
                  "spin all the way around"]
WRAP = ["{}", "{}", "{}", "please {}", "{} please", "can you {}", "could you {}", "i want you to {}",
        "tank, {}", "hey tank {}", "now {}", "{} now", "ok {}", "would you {}", "you should {}"]
SMALL_WORDS = ["a little", "a little bit", "a bit", "slightly", "just a touch", "a tiny bit"]
BIG_WORDS = ["a lot", "a long way", "far", "quite a ways"]
NUMS = [("1", 1.0), ("2", 2.0), ("3", 3.0), ("1.5", 1.5), ("2.5", 2.5), ("0.5", 0.5), ("0.2", 0.2),
        ("one", 1.0), ("two", 2.0), ("a quarter of a", 0.25), ("one and a half", 1.5)]
LONG_NUMS = [("5", 5.0), ("10", 10.0), ("30", 30.0), ("four", 4.0), ("sixty", 60.0)]
TIMED = ["{v} for {n} seconds", "{v} for {n} secs", "{n} seconds of {v}", "{v} {n} seconds",
         "{v} for about {n} seconds"]
JOIN = [" then ", " and then ", ", then ", ", ", " and ", " after that ", " next ", ". then ", "; "]
DONT = ["don't {}", "do not {}", "dont {}", "please don't {}", "please do not {}", "you must not {}",
        "you can't {}", "no need to {}", "i don't want you to {}", "do not ever {}", "don't {} yet",
        "don't you dare {}", "not allowed to {}", "you may not {}", "better not {}"]

CHAT = """what is your favourite colour|who built you|are you a robot|what can you do|hello there|
hey|hi tank|thanks|thank you so much|nice work|well done|that was great|how old are you|where are you from|
do you like cats|what day is it|what time is it|is it raining|how far is the moon|what is two plus two|
tell me a story|tell me something funny|recite a poem|write me some code|translate this to french|
play some jazz|what's for dinner|i am tired|i'm going to bed|my cat is hungry|the floor is dirty|
the battery looks fine|today was a long day|the dog ate my homework|this room is messy|i love pizza|
have a nice day|see you tomorrow|never mind|forget it|hmm|ok|sure|maybe later|i don't know|
why is the sky blue|who is the prime minister|how do tanks work|what are you thinking about|
are you awake|can you hear me|what's up|lol|huh|um|what was that noise""".replace("\n", "").split("|")
TRAPS = """turn off the tv|turn up the heat|turn the page|turn on the fan|turn down the volume|
it's your turn|whose turn is it|i turned left at the store|my brother went forward with the plan|
what is left of the pizza|i left my keys inside|the left one is bigger|right now i am busy|
that's right|all right|the answer is right there|i'll be right back|
come back to me later with that idea|back in my day we walked|my back hurts|forward this email to me|
looking forward to it|go team|go figure|go ahead and tell me a joke|let's go to bed|i have to go|
where did you go|how do i go forward with this|what does reverse mean|define backward|
what is a left turn|how do you say turn right in french|is it better to go left or right|
did you go forward|why did you back up|can tanks drive backward|i drove here this morning|drive safely|
go to the kitchen|go to the door|go find my shoes|go fetch the mug|go get my phone|drive to the store|
head to the fridge|find the cat|chase the cat|bring me a drink|grab the mug|pick that up|raise your arm|
lower the arm|open the gripper|close the gripper|wave hello|nod your head|look left|look right|look down|
tilt your head|take a picture|turn on the camera|shoot the target|fire the cannon|jump|fly up|dance|
sit down|go upstairs|climb the stairs|swim across""".replace("\n", "").split("|")

GERUND = ["don't try going forward", "quit going backward", "skip the left turn", "no left turns",
          "no reversing", "no driving forward", "no spinning", "hold off on going forward",
          "refrain from backing up", "cancel the right turn", "do nothing", "stay put", "stay there",
          "stay where you are", "wait here", "wait", "hold still", "don't budge", "don't do anything",
          "don't drive", "do not drive", "don't turn", "do not turn", "no moving", "not yet",
          "not now", "keep still", "remain still", "sit tight", "park it", "hold on"]


def plan(*moves):
    return {"moves": [{"move": m, "secs": round(s, 2)} for m, s in moves]}


def add(rows, text, target, group):
    rows.setdefault(" ".join(text.lower().split()), (target, group))


def build(rng):
    rows = {}
    for move, phrases in PHRASES.items():
        for phrase in phrases:
            for wrap in rng.sample(WRAP, 4):
                add(rows, wrap.format(phrase), plan((move, DEFAULT[move])), "plain")
    for phrase in AROUND_PHRASES:
        for wrap in rng.sample(WRAP, 3):
            add(rows, wrap.format(phrase), plan(("spinl", AROUND)), "plain")
    for move, phrases in CORE.items():
        for phrase in phrases:
            add(rows, f"{phrase} {rng.choice(SMALL_WORDS)}", plan((move, SMALL[move])), "size")
            add(rows, f"{rng.choice(WRAP).format(phrase)} {rng.choice(SMALL_WORDS)}",
                plan((move, SMALL[move])), "size")
            add(rows, f"{phrase} {rng.choice(BIG_WORDS)}", plan((move, BIG[move])), "size")
            for word, secs in rng.sample(NUMS, 3):
                form = rng.choice(TIMED)
                unit = form.format(v=phrase, n=word)
                if word in ("1", "one", "a quarter of a"):
                    unit = unit.replace("seconds", "second").replace("secs", "sec")
                add(rows, unit, plan((move, secs)), "timed")
            word, secs = rng.choice(LONG_NUMS)
            add(rows, f"{phrase} for {word} seconds", plan((move, min(secs, MAX_SECS))), "timed")
    for side, move in (("left", "spinl"), ("right", "spinr")):
        for deg in (15, 30, 45, 60, 90, 120, 135, 180):
            secs = AROUND if deg == 180 else deg / 90 * 0.65
            add(rows, f"turn {side} {deg} degrees", plan((move, secs)), "size")
            add(rows, f"spin {deg} degrees to the {side}", plan((move, secs)), "size")

    names = list(CORE)
    for _ in range(260):
        n = rng.choice((2, 2, 2, 3, 3, 4))
        moves = [rng.choice(names)]
        while len(moves) < n:
            pick = rng.choice(names)
            if pick != moves[-1] or rng.random() < 0.15:
                moves.append(pick)
        text, steps = "", []
        for i, move in enumerate(moves):
            phrase = rng.choice(CORE[move])
            secs = DEFAULT[move]
            if rng.random() < 0.2:
                word, secs = rng.choice(NUMS[:6])
                phrase = f"{phrase} for {word} second" + ("" if word == "1" else "s")
            text += phrase if i == 0 else rng.choice(JOIN) + phrase
            steps.append((move, secs))
        if rng.random() < 0.15:
            text = "first " + text
        add(rows, rng.choice(WRAP).format(text), plan(*steps), "chain")
    # Order given backwards in the words: the moves still run in the real order.
    for _ in range(50):
        a, b = rng.sample(names, 2)
        pa, pb = rng.choice(CORE[a]), rng.choice(CORE[b])
        add(rows, rng.choice(["{b} after you {a}", "{b} once you {a}", "after you {a}, {b}"])
            .format(a=pa, b=pb), plan((a, DEFAULT[a]), (b, DEFAULT[b])), "chain")
        gerund = {"go forward": "going forward", "back up": "backing up", "turn left": "turning left",
                  "turn right": "turning right", "reverse": "reversing"}
        keys = [k for k in gerund if k != pb]
        pa = rng.choice(keys)
        move_a = {"go forward": "go", "back up": "rev", "turn left": "spinl",
                  "turn right": "spinr", "reverse": "rev"}[pa]
        add(rows, f"before {gerund[pa]}, {pb}", plan((b, DEFAULT[b]), (move_a, DEFAULT[move_a])), "chain")

    all_core = [p for ps in CORE.values() for p in ps] + ["move", "turn", "drive", "go anywhere"]
    for _ in range(170):
        form, phrase = rng.choice(DONT), rng.choice(all_core)
        add(rows, form.format(phrase), plan(), "negation")
    for _ in range(50):
        a, b = rng.choice(all_core[:18]), rng.choice(all_core[:18])
        form = rng.choice(["{a} but don't {b}", "don't {a}, {b}", "do not {a}, {b} instead",
                           "don't {a} then {b}", "{a}, no wait, don't"])
        add(rows, form.format(a=a, b=b), plan(), "negation")
    for line in GERUND:
        add(rows, line, plan(), "negation")
    for line in CHAT:
        add(rows, line.strip(), plan(), "no motion")
    for line in TRAPS:
        add(rows, line.strip(), plan(), "trap")
    return rows


def forbidden():
    out = set()
    for name in ("commands.json", "heldout.json"):
        with open(os.path.join(EVAL, name), encoding="utf-8") as f:
            out |= {" ".join(c["text"].lower().split()) for c in json.load(f)}
    return out


def main():
    rng = random.Random(SEED)
    rows = build(rng)
    banned = forbidden()
    removed = sorted(t for t in rows if t in banned)
    for text in removed:
        del rows[text]
    # Whole test commands never get in, even wrapped ("please go forward" still can:
    # the wrapper changes the command, and plain words have to be learned somewhere).
    assert not banned & set(rows), "a test command got into training"
    # Stop words never reach the model, so training on them would teach nothing.
    stop = re.compile(r"\b(stop|stops|stopping|halt|freeze|whoa|abort|brake|emergency|e-?stop)\b")
    rows = {t: v for t, v in rows.items() if not stop.search(t)}

    items = [{"text": t, "target": json.dumps(v[0]), "group": v[1]} for t, v in rows.items()]
    rng.shuffle(items)
    cut = max(30, len(items) // 10)
    os.makedirs(OUT, exist_ok=True)
    for name, part in (("val", items[:cut]), ("train", items[cut:])):
        with open(os.path.join(OUT, f"{name}.jsonl"), "w", encoding="utf-8") as f:
            for item in part:
                f.write(json.dumps(item) + "\n")
    counts = {}
    for item in items:
        counts[item["group"]] = counts.get(item["group"], 0) + 1
    print(f"{len(items) - cut} train, {cut} val; dropped {len(removed)} test commands: {removed}")
    print(counts)


if __name__ == "__main__":
    main()
