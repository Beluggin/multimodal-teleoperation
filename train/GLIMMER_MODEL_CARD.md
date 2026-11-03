---
license: apache-2.0
base_model: meta-models/Muse-Glimmer-30B
library_name: peft
language:
  - en
tags:
  - muse-glimmer
  - lora
  - robotics
  - function-calling
pipeline_tag: text-generation
---

# Muse-Glimmer-30B-MITT-Tank

A LoRA fine-tune of [Muse Glimmer 30B](https://huggingface.co/meta-models/Muse-Glimmer-30B) that turns one typed instruction into JSON moves for a small tracked robot. It's from [MITT](https://github.com/Beluggin/multimodal-teleoperation), a hackathon project. This is an independent project, not made or endorsed by Meta.

**It has never run on the robot.** The base model needs far more memory than the robot's Raspberry Pi 5 has, so the tank uses a smaller tune, [Llama-3.2-3B-MITT-Tank](https://huggingface.co/Beluggin/Llama-3.2-3B-MITT-Tank). This one was trained and tested on a rented GPU, to see what the same data does on a larger model.

```
"turn left then go forward"
{"moves": [{"move": "spinl", "secs": 0.65}, {"move": "go", "secs": 1.0}]}

"turn on the lights"
{"moves": []}
```

## Files

- `adapter_model.safetensors`, `adapter_config.json`: the LoRA adapter, 118 MB. You also need the base model's 59.6 GB of weights.
- `training_log.json`: settings and validation by epoch
- `results/`: every test reply, for stock and tuned
- `LICENSE`, `USAGE_POLICY.md`: Muse Glimmer's Apache 2.0 license and Usage Policy

## Use

It was trained with its reply started at Muse Glimmer's answer channel, skipping the reasoning step, so use it the same way.

```python
import torch
from peft import PeftModel
from transformers import AutoModelForImageTextToText, AutoTokenizer

base = "meta-models/Muse-Glimmer-30B"
tok = AutoTokenizer.from_pretrained(base)
model = AutoModelForImageTextToText.from_pretrained(base, dtype=torch.bfloat16, device_map={"": 0})
model = PeftModel.from_pretrained(model, "Beluggin/Muse-Glimmer-30B-MITT-Tank").eval()

system = "You turn one instruction into moves for a small tracked robot. Reply with JSON only."
messages = [{"role": "system", "content": system}, {"role": "user", "content": "turn left"}]
prompt = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
prompt += " to=user<|message|>"
ids = tok(prompt, add_special_tokens=False, return_tensors="pt").to(0)
out = model.generate(**ids, max_new_tokens=96, do_sample=False, temperature=None, top_p=None, top_k=None,
                     eos_token_id=[tok.eos_token_id, tok.convert_tokens_to_ids("<|eot|>")])
print(tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True))
```

At full precision it peaked at 66.8 GB of GPU memory in training. This is the setup that was tested. Quantized versions weren't.

## Results

Each command passes only if the moves come out in exactly the expected order, with nothing added. Time per move isn't scored. An invalid reply moves nothing, so it would count as a pass on a no-motion command. Random weights scored 22/50 that way in a dry run, so invalid replies are counted separately.

| Model | Where | 50 new commands | 18 original commands | Invalid replies | Moved when it shouldn't | Median model time, 50 / 18 |
|---|---|---|---|---|---|---|
| **This model**, short prompt | A100 80 GB | **50/50** | **18/18** | 0 | 0 | 1.50 s / 1.60 s |
| Stock Muse Glimmer 30B, full prompt | same | 31/50 | 13/18 | 0 | 0 | 0.44 s / 0.43 s |

### How to read these

- **Stock's score probably undersells it.** This setup skips Muse Glimmer's reasoning step and gives stock no way to use it. Stock made no wrong moves. It replied "no moves" to 19 of the 28 moving commands on the new list, including plain ones on the old list like "turn left". Stock with reasoning on wasn't tested, so this gap doesn't measure what Muse Glimmer can do. It measures this setup.
- **The times don't compare cleanly.** Stock's fast replies are mostly a short "no moves", while this model writes out the moves.
- **It's a small test, run once, and this project wrote it.** The commands and expected answers were written before any training and weren't used to tune anything, but this isn't an independent benchmark.
- **The new list isn't fully unseen.** No whole test command is in the training set, and rarer driving words like "advance" and "veer" aren't either. But the negation and trap groups use the same kinds of sentences as training. Expect worse on kinds of sentence it hasn't seen.
- **The 18 original commands aren't clean.** Their plain phrases appear inside training examples.
- **It may have memorized its data.** Training loss reached about zero, and validation reached 100%. Those validation examples come from the same generator as training, so that's an easy test.
- **It isn't comparable to the Llama tune's 49/50.** That one ran through Ollama on a Pi with JSON output on. This ran through `transformers` with no JSON constraint. One point on this list is noise anyway.
- **Some answers are judgment calls.** "don't turn left, turn right" counts as no motion, because the rule here is that any negation means don't move.
- **The result files say "Llama chose no motion"** for an empty reply. That's a label from MITT's shared reply check. These replies came from Muse Glimmer.

## Don't use this for safety

**A model must not be the thing that stops a robot.** This one guesses, and it will sometimes guess wrong. In MITT, stop is a plain word check that runs first, every reply is checked strictly, time per move is capped twice, and the model can't set speed.

It's not for real vehicles, heavy machinery or anything else that could hurt someone. It only knows four moves with open-loop timings for one small tank, and the seconds in its answers won't mean the same distance or angle on another robot.

Muse Glimmer isn't intended for anyone under 18, and use of this model must follow its [Usage Policy](USAGE_POLICY.md).

## Training

- Base: `meta-models/Muse-Glimmer-30B` at revision `cec94fcfd6512f2cfe708138c32533b346ea4f69`, full precision (bfloat16)
- Data: the same 1,006 training and 111 validation examples as the Llama tune, generated from word lists with a fixed seed ([`make_dataset.py`](https://github.com/Beluggin/multimodal-teleoperation/tree/main/train))
- LoRA: rank 16, on the language model's 208 attention projections, with the vision encoder untouched. 3 epochs, batch 4, learning rate 2e-4. The saved adapter is from epoch 2.
- Time: 19 minutes on one A100 80 GB on Modal, including validation
- Validation, moves correct: 100% from epoch 1

## License

The base model and this adapter are under Apache 2.0. See `LICENSE`.
