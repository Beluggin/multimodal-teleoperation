#!/usr/bin/env python3
"""Fold the LoRA adapter into full weights, ready for GGUF conversion. Runs on CPU.

    python3 train/merge_lora.py --base ~/mitt-train/base --adapter ~/mitt-train/adapter \
        --out ~/mitt-train/merged
"""
import argparse

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    model = AutoModelForCausalLM.from_pretrained(args.base, dtype=torch.bfloat16, device_map="cpu")
    model = PeftModel.from_pretrained(model, args.adapter).merge_and_unload()
    model.save_pretrained(args.out)
    AutoTokenizer.from_pretrained(args.base).save_pretrained(args.out)


if __name__ == "__main__":
    main()
