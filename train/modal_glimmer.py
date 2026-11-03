#!/usr/bin/env python3
"""Run the Muse Glimmer fine-tune on Modal, one stage at a time.

    modal run --detach train/modal_glimmer.py::download
    modal run --detach train/modal_glimmer.py::trial
    modal run --detach train/modal_glimmer.py::train
    modal run --detach train/modal_glimmer.py::test
    modal volume get mitt-glimmer adapter ./adapter
    modal volume get mitt-glimmer results ./results

Every stage has a hard time limit and no retries, so a stuck job can't run up a
bill. The weights are ungated, so no Hugging Face token goes to Modal.
"""
import os

import modal

BASE_REPO = "meta-models/Muse-Glimmer-30B"
BASE_REVISION = "cec94fcfd6512f2cfe708138c32533b346ea4f69"
WEIGHTS = "/vol/base"
ADAPTER = "/vol/adapter"
RESULTS = "/vol/results"
TRIAL_ADAPTER = "/tmp/trial"
REMOTE = "/root/mitt"
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(THIS_DIR)

app = modal.App("mitt-glimmer-tune")
vol = modal.Volume.from_name("mitt-glimmer", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.15.0", "transformers==5.22.1", "peft==0.21.2", "accelerate==1.15.0",
                 "huggingface_hub==2.4.0", "safetensors==0.8.0", "jinja2")
    .add_local_file(os.path.join(THIS_DIR, "glimmer_lora.py"), f"{REMOTE}/train/glimmer_lora.py")
    .add_local_file(os.path.join(THIS_DIR, "train_lora.py"), f"{REMOTE}/train/train_lora.py")
    .add_local_dir(os.path.join(THIS_DIR, "data"), f"{REMOTE}/train/data")
    .add_local_file(os.path.join(REPO, "src", "tank_tools", "llama_raw.py"),
                    f"{REMOTE}/src/tank_tools/llama_raw.py")
    .add_local_file(os.path.join(REPO, "eval", "heldout.json"), f"{REMOTE}/eval/heldout.json")
    .add_local_file(os.path.join(REPO, "eval", "commands.json"), f"{REMOTE}/eval/commands.json")
)
GPU = dict(image=image, volumes={"/vol": vol}, gpu="A100-80GB", cpu=4, memory=98304, retries=0)


def _lora():
    import sys
    sys.path.insert(0, f"{REMOTE}/train")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import glimmer_lora
    return glimmer_lora


@app.function(image=image, volumes={"/vol": vol}, cpu=2, memory=8192, timeout=3600, retries=0)
def download():
    """Fetch by name and check sizes. `hf download --include` once skipped weights with no error."""
    from huggingface_hub import HfApi, hf_hub_download
    info = HfApi().model_info(BASE_REPO, revision=BASE_REVISION, files_metadata=True)
    for item in info.siblings:
        name = item.rfilename
        if name.startswith(".eval_results") or name == ".gitattributes":
            continue
        path = hf_hub_download(BASE_REPO, name, revision=BASE_REVISION, local_dir=WEIGHTS)
        got = os.path.getsize(path)
        if got != item.size:
            raise SystemExit(f"{name}: expected {item.size} bytes, got {got}")
        print(f"ok {name} {got / 1e9:.3f} GB", flush=True)
        vol.commit()
    print("download complete", flush=True)


@app.function(timeout=1800, **GPU)
def trial():
    """Load, run a few steps, report speed and memory. Saves nothing."""
    _lora().main(["train", "--base", WEIGHTS, "--out", TRIAL_ADAPTER, "--trial", "--log-every", "5"])


@app.function(timeout=3 * 3600, **GPU)
def train():
    """Commits each time a better epoch is saved, so a timeout keeps the best so far."""
    _lora().main(["train", "--base", WEIGHTS, "--out", ADAPTER], on_save=vol.commit)
    vol.commit()


@app.function(timeout=3600, **GPU)
def test():
    _lora().main(["test", "--base", WEIGHTS, "--adapter", ADAPTER, "--out", RESULTS,
                  "--note", "A100 80 GB on Modal."])
    vol.commit()
