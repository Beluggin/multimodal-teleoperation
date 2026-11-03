---
license: llama3.2
base_model: meta-llama/Llama-3.2-3B-Instruct
library_name: peft
language:
  - en
tags:
  - llama
  - lora
  - gguf
  - robotics
  - function-calling
pipeline_tag: text-generation
---

# Llama-3.2-3B-MITT-Tank

**Built with Llama.**

A small LoRA fine-tune of Llama 3.2 3B that turns one typed instruction into JSON moves for a tracked robot. It's the raw mode model for [MITT](https://github.com/Beluggin/multimodal-teleoperation), a hackathon project, and runs on a Raspberry Pi 5 through Ollama.

The tune's job is knowing when *not* to move. Stock Llama 3.2 3B already read slang and chained commands well, but it also moved on things like "pick up the ball" and "what does go forward mean".

```
"turn left then go forward"
{"moves": [{"move": "spinl", "secs": 0.65}, {"move": "go", "secs": 1.0}]}

"turn on the lights"
{"moves": []}
```

## Files

- `adapter_model.safetensors`, `adapter_config.json`: the LoRA adapter
- `Llama-3.2-3B-MITT-Tank.Q4_K_M.gguf`: merged and quantized, about 2 GB
- `Modelfile`: Ollama config, with the prompt format it trained on
- `LICENSE.txt`, `USE_POLICY.md`, `NOTICE`: Llama 3.2 terms

```
ollama create llama-3.2-3b-mitt-tank -f Modelfile
```

Use this system prompt, which is the one it trained with:

> You turn one instruction into moves for a small tracked robot. Reply with JSON only.

## Results

Each command passes only if the moves come out in exactly the expected order, with nothing added. Time per move isn't scored. These ran through Ollama at temperature 0 with JSON output on.

| Model | Where | 50 new commands | 18 original commands | Median model time |
|---|---|---|---|---|
| **This model** | Raspberry Pi 5, 4 GB, CPU | **49/50** | 18/18 | 3.97 s on the 50, 4.19 s on the 18 |
| Stock Llama 3.2 3B, Ollama Q4 | same Pi | 45/50 | 18/18 | 4.16 s on the 50, 3.86 s on the 18 |
| **This model** | desktop, RTX 4060 | **49/50** | 18/18 | 0.39 s on the 50 |
| Stock Llama 3.2 3B, Ollama Q4 | same desktop | 42/50 | not run | 0.40 s on the 50 |
| Fixed-phrase parser (no model), at the time | any | 36/50 | 18/18 | none |

The one miss, "do a 180", came back with a move that doesn't exist (`spin`). MITT's reply check rejects a plan like that, so the robot doesn't move.

**The gain is in accuracy, not speed.** The shorter prompt was expected to save time on the Pi, and it didn't make a clear difference.

### How to read these

- **It's a small test, run once, and this project wrote it.** The 50 commands and their expected answers were written before training. The test was not used to tune anything, but this isn't an independent benchmark.
- **The new list isn't fully unseen.** No whole test command is in the training set, and rarer driving words like "advance", "retreat" and "veer" aren't either. But the negation and trap groups use the same kinds of sentences as training: "turn on the fan" is in training and "turn on the lights" is in the test. Expect worse on kinds of sentence it hasn't seen.
- **The 18 original commands aren't clean.** They were kept out of training as whole commands, but their plain phrases appear inside training examples, and they shaped the stock prompt.
- **Some answers are judgment calls.** "don't turn left, turn right" counts as no motion, because the rule here is that any negation means don't move. Stock's right turn is arguably what the person meant, and it's one of the misses counted against it.
- **Stock scored differently on two machines.** It got 42 on the desktop and 45 on the Pi, with the same model and temperature 0. That's unexplained, so treat small score gaps as noise.
- **The prompts differ.** Stock used MITT's long prompt with rules and examples, and this model used the short one above.

## On the real robot

Eight steps on the floor on Nov 3, 2026, on the Pi at 30% power. The moves are from the driver's log, and "On the floor" is what a person watching saw, by eye. It's one pass, not a reliability trial.

| Command | Answer | Model time | On the floor |
|---|---|---|---|
| `go forward` | `go` 1 s | 3.8 s | About 30 cm |
| `turn left` | `spinl` 0.65 s | 4.0 s | About 85° |
| `do not turn left` | no motion | not logged | Didn't move |
| `turn left then go forward` | `spinl` 0.65 s, `go` 1 s | 6.5 s | Almost 90°, then forward |
| `go forward`, then `stop` 1 s later | answer thrown away | n/a | Didn't move |
| `scoot ahead a little bit` | `go` 0.5 s | 3.7 s | About 20 cm |
| `pick up the ball` | no motion | not logged | Didn't move |
| `what does go forward mean` | no motion | not logged | Didn't move |

The stop step tests MITT's code, not this model: stop words are caught before the model is asked.

## Don't use this for safety

**A model must not be the thing that stops a robot.** This one guesses, and it will sometimes guess wrong. In MITT, stop is a plain word check that runs first, every reply is checked strictly, time per move is capped twice, and the model can't set speed.

It also only knows four moves with open-loop timings for one tank. The seconds in its answers won't mean the same distance or angle on another robot.

## Training

- Base: `meta-llama/Llama-3.2-3B-Instruct`, loaded in 4-bit
- Data: 1,006 training and 111 validation examples, generated from word lists with a fixed seed ([`make_dataset.py`](https://github.com/Beluggin/multimodal-teleoperation/tree/main/train))
- LoRA: rank 16, attention projections only, 3 epochs, batch 4, learning rate 2e-4
- Time: about 8.5 minutes on an RTX 4060
- Validation, moves correct: 94.6%, 98.2%, 99.1% by epoch. Those examples come from the same generator as training, so they're an easy test.

## License

Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.

Use of this model must follow the [Llama 3.2 Community License](https://www.llama.com/llama3_2/license/) and [Acceptable Use Policy](https://www.llama.com/llama3_2/use-policy).
