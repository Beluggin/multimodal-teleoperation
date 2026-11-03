# Evaluation

These are measured numbers only. They come from test runs in one room, not a controlled trial.

## Language: parser vs raw-mode Llama

The same 18 commands (`commands.json`) go through each engine. A case passes only if the moves come out in exactly the expected order, with nothing added. Time per move isn't scored, and no motors are involved.

| Engine | Where | Passed | Model time |
|---|---|---|---|
| Fixed-phrase parser | any machine | 18/18 | none |
| Llama 3.1 8B, raw mode | desktop | 17/18 | 1.67 s median, 8.90 s first call |

Full results are in `results/`. To reproduce:

```
make eval
python3 eval/language_eval.py llama --model llama3.2:3b --note "where it ran" --out eval/results/my_run.json
```

How to read these:

- **The parser's score is flattering.** This list was written with the parser's phrases known, and any phrase it doesn't know moves nothing, so it fails safe but misses a lot of natural speech. This shows it handles the listed commands. It doesn't show it understands English better than Llama.
- **Stop isn't scored for the model.** Raw mode catches stop words before the model runs, so Llama saw 15 of the 18 commands and got 14 right.
- **The miss matters.** "do not turn left" came back as back up, then turn right. A negated command made it move, which is why the main path doesn't leave language to a model.
- **The older baseline is a different test.** The 11/18 and ~2.1 s in the [build notes](../docs/MITT_BUILD_NOTES.md) are Llama 3.2 3B on the Pi against an earlier command list, which isn't in this repo. Don't compare those scores with these.
- **Desktop timing says nothing about the Pi.** The desktop model is also larger than the one the Pi runs.

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
