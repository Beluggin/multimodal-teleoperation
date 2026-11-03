#!/usr/bin/env python3
"""Score the fixed-phrase parser and raw-mode Llama on the same commands.

A case passes only if the moves come out in exactly the expected order, with
nothing added. Time per move isn't scored. No motors are involved.

    python3 eval/language_eval.py parser
    python3 eval/language_eval.py llama --model llama3.2:3b --out eval/results/pi_llama3.2_3b.json

Run llama on the machine you want to time, or set OLLAMA_URL.
"""
import argparse
import json
import os
import re
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src", "tank_tools"))
import llama_raw  # noqa: E402
import xiaor_text_action as tx  # noqa: E402

# Same split and label map as tank_control.py, which needs a live tank to import.
SPLIT = re.compile(r"\s*(?:\bthen\b|,|;)\s*", re.I)
LABEL_MOVE = {"drive.forward": "go", "drive.backward": "rev", "drive.left": "spinl",
              "drive.right": "spinr", "drive.around": "spinl",
              "drive.stop": "stop", "drive.estop": "stop"}


def run_parser(text):
    moves = []
    for part in filter(None, SPLIT.split(text)):
        move = LABEL_MOVE.get(tx.classify(part).label)
        if move:
            moves.append(move)
    return moves, None, ""


def run_llama(text, model, system=None):
    plan = llama_raw.interpret(
        text, lambda t: llama_raw.ask_ollama(t, model=model, system=system))
    if plan.stop:
        return ["stop"], None, "stop word; model not asked"
    note = plan.reason or ", ".join(f"{m} {s:g}s" for m, s in plan.moves)
    return [m for m, _ in plan.moves], plan.latency_s, note


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("engine", choices=["parser", "llama"])
    ap.add_argument("--model", default=llama_raw.DEFAULT_MODEL)
    ap.add_argument("--note", default="", help="where this ran, saved with the results")
    ap.add_argument("--out")
    ap.add_argument("--cases", default="commands.json", help="test list in eval/")
    ap.add_argument("--prompt", choices=["full", "tuned"], default="full",
                    help="tuned is the short prompt the fine-tuned model trained with")
    args = ap.parse_args()
    system = llama_raw.TUNED_PROMPT if args.prompt == "tuned" else None

    with open(os.path.join(HERE, args.cases), encoding="utf-8") as f:
        cases = json.load(f)
    rows = []
    for case in cases:
        if args.engine == "parser":
            got, secs, note = run_parser(case["text"])
        else:
            got, secs, note = run_llama(case["text"], args.model, system)
        ok = got == case["expect"]
        rows.append({"text": case["text"], "group": case["group"], "expect": case["expect"],
                     "got": got, "pass": ok, "latency_s": secs, "note": note})
        took = "" if secs is None else f"  {secs:.2f}s"
        print(f"{'ok  ' if ok else 'MISS'} {case['text']!r} -> {got}{took}  {note}".rstrip())

    passed = sum(r["pass"] for r in rows)
    times = [r["latency_s"] for r in rows if r["latency_s"] is not None]
    print(f"\n{passed}/{len(rows)} passed")
    if times:
        print(f"model time: median {statistics.median(times):.2f}s, first {times[0]:.2f}s (may include a cold load)")
    if args.out:
        result = {"engine": args.engine, "model": args.model if args.engine == "llama" else None,
                  "cases_file": args.cases, "prompt": args.prompt if args.engine == "llama" else None,
                  "note": args.note, "date": time.strftime("%Y-%m-%d"),
                  "passed": passed, "total": len(rows),
                  "median_model_s": statistics.median(times) if times else None, "cases": rows}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
            f.write("\n")


if __name__ == "__main__":
    main()
