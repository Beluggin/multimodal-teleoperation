#!/usr/bin/env python3
"""LoRA fine-tune of Muse Glimmer 30B on the raw-mode data, and its test.

Same data, seed and LoRA settings as train_lora.py, so the two can be compared.
Only the language model's attention layers train. The vision encoder is untouched.

The reply is started at the answer channel, so the model goes straight to JSON
and skips its reasoning step. Stock and tuned are both tested that way.

    python3 train/glimmer_lora.py train --base <weights> --out <adapter> [--trial]
    python3 train/glimmer_lora.py test --base <weights> --adapter <adapter> --out <results dir>

modal_glimmer.py runs these on a rented GPU. train/data/ is the only training
input. The test lists in eval/ are read only by the test command.
"""
import argparse
import json
import math
import os
import random
import statistics
import sys
import time

import torch
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoModelForImageTextToText, AutoTokenizer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src", "tank_tools"))
import llama_raw  # noqa: E402
from train_lora import batches, load  # noqa: E402

ANSWER_CHANNEL = " to=user<|message|>"
END = "<|eot|>"
TARGETS = r".*language_model\.layers\.\d+\.self_attn\.(q|k|v|o)_proj"
TRIAL_STEPS = 20


def prompt_text(tok, system, text):
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    return tok.apply_chat_template(messages, tokenize=False,
                                   add_generation_prompt=True) + ANSWER_CHANNEL


def encode(tok, row):
    prompt = tok(prompt_text(tok, llama_raw.TUNED_PROMPT, row["text"]),
                 add_special_tokens=False)["input_ids"]
    answer = tok(row["target"] + END, add_special_tokens=False)["input_ids"]
    return prompt + answer, [-100] * len(prompt) + answer


def load_model(base, device):
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModelForImageTextToText.from_pretrained(
        base, dtype=torch.bfloat16, device_map={"": device})
    return tok, model


@torch.no_grad()
def reply(model, tok, system, text, device):
    ids = tok(prompt_text(tok, system, text), add_special_tokens=False,
              return_tensors="pt").to(device)
    out = model.generate(**ids, max_new_tokens=96, do_sample=False, temperature=None,
                         top_p=None, top_k=None, pad_token_id=tok.pad_token_id,
                         eos_token_id=[tok.eos_token_id, tok.convert_tokens_to_ids(END)])
    return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def validate(model, tok, rows, device):
    """Share of val rows whose reply is exactly right, and whose moves are right."""
    model.eval()
    exact = moves = 0
    misses = []
    for row in rows:
        text = reply(model, tok, llama_raw.TUNED_PROMPT, row["text"], device)
        exact += text == row["target"]
        try:
            got = [m["move"] for m in json.loads(text)["moves"]]
        except (ValueError, KeyError, TypeError):
            got = None
        want = [m["move"] for m in json.loads(row["target"])["moves"]]
        moves += got == want
        if got != want:
            misses.append((row["text"], text[:120], want))
    model.train()
    return exact / len(rows), moves / len(rows), misses


def train(args):
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    cuda = args.device.startswith("cuda")
    tok, model = load_model(args.base, args.device)
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=TARGETS))
    model.print_trainable_parameters()

    rows = [encode(tok, r) for r in load("train")]
    val = load("val")
    params = [p for p in model.parameters() if p.requires_grad]
    optim = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)
    per_epoch = math.ceil(len(rows) / args.batch)
    total = args.epochs * per_epoch
    warmup = max(1, total // 20)
    sched = torch.optim.lr_scheduler.LambdaLR(optim, lambda s: min(
        (s + 1) / warmup, 0.5 * (1 + math.cos(math.pi * s / total))))

    step, start, best, history = 0, time.time(), -1.0, []
    for epoch in range(1, args.epochs + 1):
        running = 0.0
        for ids, mask, labels in batches(rows, args.batch, rng, tok.pad_token_id, args.device):
            with torch.autocast(args.device.split(":")[0], dtype=torch.bfloat16):
                loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss
            if not torch.isfinite(loss):
                raise SystemExit(f"loss is {loss.item()} at step {step}; stopping")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optim.step()
            sched.step()
            optim.zero_grad()
            step += 1
            running += loss.item()
            if step % args.log_every == 0:
                gpu = torch.cuda.max_memory_allocated() / 2**30 if cuda else 0.0
                print(f"step {step}/{total}  loss {running / args.log_every:.4f}  "
                      f"{time.time() - start:.0f}s  gpu {gpu:.1f} GB", flush=True)
                running = 0.0
            if args.trial and step >= args.trial_steps:
                trial_report(model, tok, val, args, step, total, per_epoch, start)
                return
        exact, moves, misses = validate(model, tok, val, args.device)
        print(f"epoch {epoch}: val exact {exact:.3f}, moves {moves:.3f}", flush=True)
        for miss in misses[:8]:
            print("  miss", miss, flush=True)
        history.append({"epoch": epoch, "val_exact": exact, "val_moves": moves})
        if moves + exact > best:
            best = moves + exact
            model.save_pretrained(args.out)
            print(f"  saved epoch {epoch}", flush=True)
            if args.on_save:
                args.on_save()

    with open(os.path.join(args.out, "training_log.json"), "w", encoding="utf-8") as f:
        json.dump({"args": {k: v for k, v in vars(args).items() if k != "on_save"},
                   "train_rows": len(rows), "val_rows": len(val),
                   "seconds": round(time.time() - start), "history": history}, f, indent=1)
    print(f"done in {time.time() - start:.0f}s", flush=True)


def trial_report(model, tok, val, args, step, total, per_epoch, start):
    per_step = (time.time() - start) / step
    model.eval()
    t = time.time()
    sample = reply(model, tok, llama_raw.TUNED_PROMPT, val[0]["text"], args.device)
    per_reply = time.time() - t
    train_s = per_step * total
    val_s = per_reply * len(val) * args.epochs
    print(json.dumps({
        "trial_steps": step, "seconds_per_step": round(per_step, 2),
        "seconds_per_reply": round(per_reply, 2),
        "projected_train_hours": round((train_s + val_s) / 3600, 2),
        "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 2**30, 1)
        if args.device.startswith("cuda") else None,
        "per_epoch_steps": per_epoch, "sample_input": val[0]["text"], "sample_reply": sample[:200],
    }, indent=1), flush=True)


def score(model, tok, system, cases_file, device, label, note, out_dir):
    with open(os.path.join(ROOT, "eval", cases_file), encoding="utf-8") as f:
        cases = json.load(f)
    rows = []
    for case in cases:
        raw = {}

        def ask(text):
            raw["reply"] = reply(model, tok, system, text, device)
            return raw["reply"]

        plan = llama_raw.interpret(case["text"], ask)
        got = ["stop"] if plan.stop else [m for m, _ in plan.moves]
        ok = got == case["expect"]
        rows.append({"text": case["text"], "group": case["group"], "expect": case["expect"],
                     "got": got, "pass": ok, "latency_s": plan.latency_s,
                     "note": plan.reason or ", ".join(f"{m} {s:g}s" for m, s in plan.moves),
                     "reply": raw.get("reply", "")})
        print(f"{'ok  ' if ok else 'MISS'} {case['text']!r} -> {got}  {rows[-1]['note']}", flush=True)
    passed = sum(r["pass"] for r in rows)
    # A rejected reply moves nothing, so it passes every no-motion command. Random
    # weights scored 22/50 this way, so a pass alone doesn't show the model understood.
    invalid = sum(r["reply"] != "" and r["note"] not in ("", "Llama chose no motion")
                  and not r["got"] for r in rows)
    print(f"invalid replies: {invalid}", flush=True)
    times = [r["latency_s"] for r in rows if r["latency_s"] is not None]
    result = {"engine": "transformers", "model": label, "cases_file": cases_file, "note": note,
              "date": time.strftime("%Y-%m-%d"), "passed": passed, "total": len(rows),
              "invalid_replies": invalid,
              "median_model_s": statistics.median(times) if times else None, "cases": rows}
    name = f"{label}_{os.path.splitext(cases_file)[0]}.json"
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
        f.write("\n")
    print(f"== {label} {cases_file}: {passed}/{len(rows)}", flush=True)
    return passed, len(rows)


def test(args):
    os.makedirs(args.out, exist_ok=True)
    tok, model = load_model(args.base, args.device)
    model.eval()
    note = (f"{args.note} Run through transformers at full precision, greedy, reply started at "
            "the answer channel, with no JSON constraint. Ollama's JSON mode was on for the "
            "Llama results, so these aren't strictly like for like.").strip()
    for cases in ("heldout.json", "commands.json"):
        score(model, tok, llama_raw.SYSTEM_PROMPT, cases, args.device,
              "glimmer_stock", note, args.out)
    model = PeftModel.from_pretrained(model, args.adapter).eval()
    for cases in ("heldout.json", "commands.json"):
        score(model, tok, llama_raw.TUNED_PROMPT, cases, args.device,
              "glimmer_tuned", note, args.out)


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    tr = sub.add_parser("train")
    tr.add_argument("--base", required=True)
    tr.add_argument("--out", required=True)
    tr.add_argument("--epochs", type=int, default=3)
    tr.add_argument("--batch", type=int, default=4)
    tr.add_argument("--lr", type=float, default=2e-4)
    tr.add_argument("--rank", type=int, default=16)
    tr.add_argument("--seed", type=int, default=3202)
    tr.add_argument("--device", default="cuda")
    tr.add_argument("--log-every", type=int, default=20)
    tr.add_argument("--trial", action="store_true", help="a few steps, then report speed and memory")
    tr.add_argument("--trial-steps", type=int, default=TRIAL_STEPS)
    tr.set_defaults(on_save=None)
    te = sub.add_parser("test")
    te.add_argument("--base", required=True)
    te.add_argument("--adapter", required=True)
    te.add_argument("--out", required=True)
    te.add_argument("--device", default="cuda")
    te.add_argument("--note", default="")
    return ap


def main(argv=None, on_save=None):
    args = parser().parse_args(argv)
    if args.cmd == "train":
        args.on_save = on_save
        train(args)
    else:
        test(args)


if __name__ == "__main__":
    main()
