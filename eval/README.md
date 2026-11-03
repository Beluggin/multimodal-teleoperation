# Evaluation

These are measured numbers only. They come from test runs in one room, not a controlled trial.

## Language: parser vs raw-mode Llama

The same 18 commands (`commands.json`) go through each engine. A case passes only if the moves come out in exactly the expected order, with nothing added. Time per move isn't scored, and no motors are involved.

| Engine | Where | Passed | Model time |
|---|---|---|---|
| Fixed-phrase parser | any machine | 18/18 | none |
| Llama 3.2 3B, raw mode | Raspberry Pi 5, 4 GB, CPU | 18/18 | 3.86 s median, 42.55 s cold first call |
| Llama 3.1 8B, raw mode | desktop | 17/18 | 1.67 s median, 8.90 s first call |

Full results are in `results/`. To reproduce:

```
make eval
python3 eval/language_eval.py llama --model llama3.2:3b --note "where it ran" --out eval/results/my_run.json
```

How to read these:

- **The parser's score is flattering.** This list was written with the parser's phrases known, so it shows the parser handles these commands, not that it understands speech. See the new list below for what happened when it met wording it hadn't seen. This shows it handles the listed commands. It doesn't show it understands English better than Llama.
- **Stop isn't scored for the model.** Raw mode catches stop words before the model runs, so Llama saw 15 of the 18 commands.
- **The Pi's 18/18 is flattering too.** Four test commands ("go forward", "turn left then go forward", "don't go forward", "what is your name") also appear word for word as examples in the system prompt, and it's one pass at temperature 0 on a short list. It shows the prompt works, not that the Pi model is reliable.
- **A bigger model did worse.** On the desktop, Llama 3.1 8B answered "do not turn left" with back up, then turn right. A negated command made it move, which is why the main path doesn't leave language to a model.
- **Raw mode costs time.** The Pi's 3.86 s median is slower than the old ~2.1 s, probably because of the longer prompt and JSON reply, but that was not tested separately. A chain of three moves took 9.12 s, and the first call after a cold load took 42.55 s.
- **The older baseline is a different test.** The 11/18 and ~2.1 s in the [build notes](../docs/MITT_BUILD_NOTES.md) are Llama 3.2 3B on the Pi against an earlier command list, which isn't in this repo. Don't compare those scores with these.

## Fine-tuned Llama on 50 new commands

[`heldout.json`](heldout.json) was written before any training and wasn't used to tune anything. A LoRA fine-tune of Llama 3.2 3B was then trained on [generated examples](../train/) that leave out every whole command in both test lists. The model is on [Hugging Face](https://huggingface.co/Beluggin/Llama-3.2-3B-MITT-Tank).

| Engine | Where | 50 new commands | Moved when it shouldn't | Median model time |
|---|---|---|---|---|
| Fine-tuned, short prompt | Raspberry Pi 5, 4 GB, CPU | 49/50 | 0 | 3.97 s |
| Stock Llama 3.2 3B, full prompt | same Pi | 45/50 | 5 | 4.16 s |
| Fine-tuned, short prompt | desktop | 49/50 | 0 | 0.39 s |
| Stock Llama 3.2 3B, full prompt | desktop | 42/50 | 8 | 0.40 s |
| Fixed-phrase parser, before the fix below | any machine | 36/50 | 6 | none |
| Fixed-phrase parser, after the fix below | any machine | 38/50 | 0 | none |

The fine-tune also passed the 18 commands above on both machines (4.19 s median on the Pi, against stock's 3.86 s).

- **The gain is accuracy, not speed.** The shorter prompt was expected to save time on the Pi, and it made no clear difference.
- **It's not fully unseen.** The negation and trap groups use the same kinds of sentences as training ("turn on the fan" in training, "turn on the lights" in the test). Rarer driving words like "advance" and "veer" were kept out.
- **The one miss failed safely.** "do a 180" came back with a move that doesn't exist, so the reply check rejected the plan.
- **Stock scored 42 on one machine and 45 on the other,** with the same model and temperature 0. That's unexplained, so treat small gaps as noise.
- **Some answers are judgment calls.** "don't turn left, turn right" counts as no motion, because the rule is that any negation means don't move. Stock's and the parser's right turn is arguably what the person meant.
- **This list found a real safety bug in the parser.** It looked for known phrases anywhere in a sentence and refused only on a short list of negators, so "you're right" turned right and "you shouldn't go to the mug" started a mission. It now moves only if the whole sentence is a command plus harmless words, any `n't` word or "avoid" refuses, and one unreadable part stops every move in a typed line. Stop is exempt and still wins from anywhere.
- **The parser's 38/50 isn't an unseen score.** The fix was built after seeing this list's failures. The earlier result is kept in `results/heldout_parser_before_fix.json`. New wording could still get through, and a bare "right now" still counts as "right".
- **The phone page is behind.** The Pi's copy of the parser hasn't been updated yet, so the phone page can still start a mission from the old wording.
- **The main drive path still uses the parser.** The fine-tune beat it on this list but has only run in raw mode, not in missions.

## Fine-tuned Llama on the tank

Eight steps on the floor, using the fine-tune on the Pi at 30% power on Nov 3. The moves are from the driver's log, and "On the floor" is what a person watching saw, by eye. It's one pass, not a reliability trial.

| Command | Llama's answer | Model time | On the floor |
|---|---|---|---|
| `go forward` | `go` 1 s | 3.8 s | About 30 cm |
| `turn left` | `spinl` 0.65 s | 4.0 s | About 85° |
| `do not turn left` | no motion | not logged | Didn't move |
| `turn left then go forward` | `spinl` 0.65 s, `go` 1 s | 6.5 s | Almost 90°, then forward |
| `go forward`, then `stop` 1 s later | answer thrown away | n/a | Didn't move; this one tests the code, not the model |
| `scoot ahead a little bit` | `go` 0.5 s | 3.7 s | About 20 cm |
| `pick up the ball` | no motion | not logged | Didn't move (stock turned left) |
| `what does go forward mean` | no motion | not logged | Didn't move (stock drove forward) |

Stock's answers in brackets are from the test runs above, not from the floor.

## Raw mode on the tank

Six steps on the floor, using stock Llama 3.2 3B on the Pi at 30% power on Nov 2. The moves are from the driver's log, and "On the floor" is what a person watching saw, by eye. It's one pass, not a reliability trial.

| Command | Llama's answer | Model time | On the floor |
|---|---|---|---|
| `go forward` | `go` 1 s | 3.9 s | Stayed square for 15 cm, then drifted right; ended about 1 cm off the seam |
| `turn left` | `spinl` 0.65 s | 4.2 s | About 80° |
| `do not turn left` | no motion | not logged | Didn't move |
| `turn left then go forward` | `spinl` 0.65 s, `go` 1 s | 6.7 s | Turned, then drove, about as far as the single moves |
| `go forward`, then `stop` 1 s later | answer thrown away | n/a | Didn't move; only the stop was sent |
| `scoot ahead a little bit` | `go` 0.5 s | 4.0 s | About 15 cm |

## Missions on the tank

Launch to the final stop the motors acknowledged. ARRIVED is what the software reported. Source: the timestamped launcher log, except Nov 3, which is from the run's output and a person watching.

| Date | Run | Time | Result |
|---|---|---|---|
| Oct 30 | "go to the cat", before the IPv4 fix | 10 m 52 s | ARRIVED, through two-minute stalls |
| Oct 30 | "go to the foot", after the fix | 67 s | Ran out of steps, no stalls |
| Oct 30 | "go to the blue ball" | 71 s | ARRIVED, stopped short of the ball |
| Oct 31 | Blue ball → mug | 67 s | Both ARRIVED, but the mug was short |
| Oct 31 | Blue ball → mug | 140 s | Both ARRIVED, mug reached |
| Oct 31 | Blue ball → mug | 179 s | Both ARRIVED |
| Oct 31 | Bottle → cat | 171 s | Both ARRIVED |
| Oct 31 | Blue ball → bottle | 163 s | Both ARRIVED |
| Nov 1 | Blue ball → bottle (the run in the video) | 157 s | Both ARRIVED |
| Nov 3 | Blue ball, after the parser fix | 209 s | Launched and drove to the ball, then lost it. Scans found nothing and it stopped itself. No ARRIVED |

The log holds 14 chained attempts, and 6 ended with both targets ARRIVED while the code was changing underneath them. Of the last 7, 5 finished both targets.

## Motors and link

| Metric | Result | Notes |
|---|---|---|
| Network → motor pins | 55–65 ms | 127–168 ms with Wi-Fi power saving on |
| Command round trip | 4–18 ms | Max 34 ms; 95 commands, 5 runs |
| Motor spin-up | ~0.5 s | At 40% duty; mechanical lag |
| Straight-line trim | +17% right | Compensates for the stronger left motor |
| Spin rate at 30% | 101–135°/s | About 35% faster on a charged battery |

Measured with the tools in [`src/tank_bench/`](../src/tank_bench/README.md).
