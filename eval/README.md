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

- **The parser's score is flattering.** This list was written with the parser's phrases known, and any phrase it doesn't know moves nothing, so it fails safe but misses a lot of natural speech. This shows it handles the listed commands. It doesn't show it understands English better than Llama.
- **Stop isn't scored for the model.** Raw mode catches stop words before the model runs, so Llama saw 15 of the 18 commands.
- **The Pi's 18/18 is flattering too.** Four test commands ("go forward", "turn left then go forward", "don't go forward", "what is your name") also appear word for word as examples in the system prompt, and it's one pass at temperature 0 on a short list. It shows the prompt works, not that the Pi model is reliable.
- **A bigger model did worse.** On the desktop, Llama 3.1 8B answered "do not turn left" with back up, then turn right. A negated command made it move, which is why the main path doesn't leave language to a model.
- **Raw mode costs time.** The Pi's 3.86 s median is slower than the old ~2.1 s, probably because of the longer prompt and JSON reply, but that was not tested separately. A chain of three moves took 9.12 s, and the first call after a cold load took 42.55 s.
- **The older baseline is a different test.** The 11/18 and ~2.1 s in the [build notes](../docs/MITT_BUILD_NOTES.md) are Llama 3.2 3B on the Pi against an earlier command list, which isn't in this repo. Don't compare those scores with these.

## Raw mode on the tank

Six steps on the floor, using Llama 3.2 3B on the Pi at 30% power on Nov 2. The moves are from the driver's log, and "On the floor" is what a person watching saw, by eye. It's one pass, not a reliability trial.

| Command | Llama's answer | Model time | On the floor |
|---|---|---|---|
| `go forward` | `go` 1 s | 3.9 s | Stayed square for 15 cm, then drifted right; ended about 1 cm off the seam |
| `turn left` | `spinl` 0.65 s | 4.2 s | About 80° |
| `do not turn left` | no motion | not logged | Didn't move |
| `turn left then go forward` | `spinl` 0.65 s, `go` 1 s | 6.7 s | Turned, then drove, about as far as the single moves |
| `go forward`, then `stop` 1 s later | answer thrown away | n/a | Didn't move; only the stop was sent |
| `scoot ahead a little bit` | `go` 0.5 s | 4.0 s | About 15 cm |

## Missions on the tank

Launch to the final stop the motors acknowledged. ARRIVED is what the software reported. Source: the timestamped launcher log.

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
