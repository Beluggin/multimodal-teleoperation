#!/usr/bin/env python3
"""LoRA fine-tune of Llama 3.2 3B for raw mode. Needs a GPU; this ran on 8 GB.

Prompts are built by hand so they match train/Modelfile token for token. Testing
through a different template than the one it trained on would quietly hurt it.

    python3 train/train_lora.py --base ~/mitt-train/base --out ~/mitt-train/adapter

Only train/data/{train,val}.jsonl are read here. The test lists in eval/ are not.
"""
import argparse
import json
import math
import os
import random
import sys
import time

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src", "tank_tools"))
from llama_raw import TUNED_PROMPT  # noqa: E402

HEADER = ("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>"
          "<|start_header_id|>user<|end_header_id|>\n\n{text}<|eot_id|>"
          "<|start_header_id|>assistant<|end_header_id|>\n\n")


def load(name):
    with open(os.path.join(HERE, "data", f"{name}.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def encode(tok, row):
    prompt = tok(HEADER.format(system=TUNED_PROMPT, text=row["text"]),
                 add_special_tokens=False)["input_ids"]
    answer = tok(row["target"] + "<|eot_id|>", add_special_tokens=False)["input_ids"]
    return prompt + answer, [-100] * len(prompt) + answer


def batches(encoded, size, rng, pad_id, device):
    order = list(range(len(encoded)))
    rng.shuffle(order)
    for start in range(0, len(order), size):
        part = [encoded[i] for i in order[start:start + size]]
        width = max(len(ids) for ids, _ in part)
        ids = [i + [pad_id] * (width - len(i)) for i, _ in part]
        labels = [l + [-100] * (width - len(l)) for _, l in part]
        mask = [[1] * len(i) + [0] * (width - len(i)) for i, _ in part]
        yield (torch.tensor(ids, device=device), torch.tensor(mask, device=device),
               torch.tensor(labels, device=device))


@torch.no_grad()
def validate(model, tok, rows, device):
    """Share of val rows whose reply is exactly right, and whose moves are right."""
    model.eval()
    exact = moves = 0
    misses = []
    for row in rows:
        ids = tok(HEADER.format(system=TUNED_PROMPT, text=row["text"]),
                  add_special_tokens=False, return_tensors="pt").to(device)
        out = model.generate(**ids, max_new_tokens=96, do_sample=False, temperature=None,
                             top_p=None, pad_token_id=tok.pad_token_id,
                             eos_token_id=tok.convert_tokens_to_ids("<|eot_id|>"))
        text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        exact += text == row["target"]
        try:
            got = [m["move"] for m in json.loads(text)["moves"]]
        except (ValueError, KeyError, TypeError):
            got = None
        want = [m["move"] for m in json.loads(row["target"])["moves"]]
        moves += got == want
        if got != want:
            misses.append((row["text"], got, want))
    model.train()
    return exact / len(rows), moves / len(rows), misses


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--seed", type=int, default=3202)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    device = "cuda"
    tok = AutoTokenizer.from_pretrained(args.base)
    tok.pad_token = "<|finetune_right_pad_id|>"
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                               bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=quant,
                                                 device_map={"": 0})
    # Not prepare_model_for_kbit_training: it casts the 128k-token embedding table
    # to 32-bit, and that ran an 8 GB card out of memory.
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    model.print_trainable_parameters()

    train = [encode(tok, r) for r in load("train")]
    val = load("val")
    params = [p for p in model.parameters() if p.requires_grad]
    optim = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)
    total = args.epochs * math.ceil(len(train) / args.batch)
    warmup = max(1, total // 20)
    sched = torch.optim.lr_scheduler.LambdaLR(optim, lambda s: min(
        (s + 1) / warmup, 0.5 * (1 + math.cos(math.pi * s / total))))

    step, start, best, history = 0, time.time(), -1.0, []
    for epoch in range(1, args.epochs + 1):
        running = 0.0
        for ids, mask, labels in batches(train, args.batch, rng, tok.pad_token_id, device):
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optim.step()
            sched.step()
            optim.zero_grad()
            step += 1
            running += loss.item()
            if step % 20 == 0:
                print(f"step {step}/{total}  loss {running / 20:.4f}  "
                      f"{time.time() - start:.0f}s  "
                      f"gpu {torch.cuda.max_memory_allocated() / 2**30:.1f} GB", flush=True)
                running = 0.0
        exact, moves, misses = validate(model, tok, val, device)
        print(f"epoch {epoch}: val exact {exact:.3f}, moves {moves:.3f}", flush=True)
        for miss in misses[:8]:
            print("  miss", miss, flush=True)
        history.append({"epoch": epoch, "val_exact": exact, "val_moves": moves})
        if moves + exact > best:
            best = moves + exact
            model.save_pretrained(args.out)
            print(f"  saved epoch {epoch}", flush=True)

    with open(os.path.join(args.out, "training_log.json"), "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "train_rows": len(train), "val_rows": len(val),
                   "seconds": round(time.time() - start), "history": history}, f, indent=1)
    print(f"done in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
