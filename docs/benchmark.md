# Benchmark results

Snapshot generated 2026-06-19 from runs 2026-06-19T09-40-56 … 2026-06-19T12-21-14 (jutul-agent b5ce69518). Every sample runs the real agent end to end in a fresh workspace and is graded on the session trace as well as the answer. See [how evaluation works](evaluation.md). Each model ran the suite **3 times**, and cells aggregate across runs, so a fraction like 2/3 means the sample passed two of three runs.

## Overview

Pass rate is passing runs over runs that completed (infrastructure errors excluded). Tool calls and tokens are the per-run totals across the suite, the harness-efficiency signals: at equal pass rate, fewer means the harness got the agent there in less work. Input tokens note how many were served from the prompt cache (a cheap fraction of the input price); a model that caches aggressively processes a large input cheaply, which is why cost doesn't track raw token counts and is shown alongside them. Cost and wall time are for **one** pass over the suite (the per-run average), measured on a single machine. Within a model samples run one at a time, but wall time still depends on that machine and on how many models shared it during the run, so read it as indicative and comparable only within this snapshot; pass rate and cost are unaffected by either. Dollar costs use provider prices as of 2026-06-15 (see `eval/report.py`) and include prompt-cache reads/writes; the self-hosted model is priced against a hosted reference.

| Model | Pass rate | Tool calls / run | Input tokens / run | Output tokens / run | Cost / run | Wall / run |
|---|---|---|---|---|---|---|
| claude-haiku-4-5 | <span class="bench-partial">120/123</span> | 283 | 6.0M (5.5M cached, 92%) | 75k | $1.50 | 0.7 h |
| gemini-3.1-flash-lite | <span class="bench-partial">110/123</span> | 256 | 8.7M (7.1M cached, 81%) | 72k | $0.69 | 0.5 h |
| gpt-5.4-mini | <span class="bench-partial">112/123</span> | 298 | 4.2M (3.6M cached, 87%) | 27k | $0.80 | 0.5 h |
| qwen3.6:27b | <span class="bench-partial">116/123</span> | 307 | 5.2M | 64k | $1.71 | 0.9 h |

## By suite

| Suite | claude-haiku-4-5 | gemini-3.1-flash-lite | gpt-5.4-mini | qwen3.6:27b |
|---|---|---|---|---|
| api | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-partial">5/6</span> | <span class="bench-partial">5/6</span> |
| battmo | <span class="bench-partial">5/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> |
| calibration | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> |
| canary | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> |
| ensembles | <span class="bench-pass">12/12</span> | <span class="bench-partial">9/12</span> | <span class="bench-partial">11/12</span> | <span class="bench-pass">12/12</span> |
| filesystem | <span class="bench-pass">27/27</span> | <span class="bench-pass">27/27</span> | <span class="bench-pass">27/27</span> | <span class="bench-pass">27/27</span> |
| fimbul | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> |
| guardrails | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-partial">1/3</span> | <span class="bench-pass">3/3</span> |
| jutuldarcy | <span class="bench-partial">8/9</span> | <span class="bench-partial">4/9</span> | <span class="bench-pass">9/9</span> | <span class="bench-partial">3/9</span> |
| mocca | <span class="bench-partial">5/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-partial">3/6</span> | <span class="bench-pass">6/6</span> |
| plotting | <span class="bench-pass">6/6</span> | <span class="bench-partial">4/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> |
| search | <span class="bench-pass">27/27</span> | <span class="bench-partial">24/27</span> | <span class="bench-partial">26/27</span> | <span class="bench-pass">27/27</span> |
| usage | <span class="bench-pass">12/12</span> | <span class="bench-pass">12/12</span> | <span class="bench-partial">9/12</span> | <span class="bench-pass">12/12</span> |
| **all** | <span class="bench-partial">120/123</span> | <span class="bench-partial">110/123</span> | <span class="bench-partial">112/123</span> | <span class="bench-partial">116/123</span> |

## By simulator

Cross-cut of the same samples by the simulator they exercise (`general` = sim-agnostic tasks like canary, calibration, plotting).

| Simulator | claude-haiku-4-5 | gemini-3.1-flash-lite | gpt-5.4-mini | qwen3.6:27b |
|---|---|---|---|---|
| battmo | <span class="bench-pass">12/12</span> | <span class="bench-partial">11/12</span> | <span class="bench-pass">12/12</span> | <span class="bench-pass">12/12</span> |
| fimbul | <span class="bench-pass">9/9</span> | <span class="bench-partial">7/9</span> | <span class="bench-partial">8/9</span> | <span class="bench-pass">9/9</span> |
| general | <span class="bench-partial">81/84</span> | <span class="bench-partial">74/84</span> | <span class="bench-partial">74/84</span> | <span class="bench-partial">77/84</span> |
| jutuldarcy | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> |
| mocca | <span class="bench-pass">12/12</span> | <span class="bench-pass">12/12</span> | <span class="bench-pass">12/12</span> | <span class="bench-pass">12/12</span> |
| **all** | <span class="bench-partial">120/123</span> | <span class="bench-partial">110/123</span> | <span class="bench-partial">112/123</span> | <span class="bench-partial">116/123</span> |

<details markdown="1">
<summary>All samples (pass count, tool calls, tokens, cost, wall time)</summary>

| Suite | Sample | Sim | Model | Passed | Failures | Tool calls | Input | Output | Cost | Wall |
|---|---|---|---|---|---|---|---|---|---|---|
| api | `api1-newton-residual` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 13 | 139k | 1k | $0.03 | 0 min |
| api | `api1-newton-residual` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 8 | 97k | 786 | $0.01 | 0 min |
| api | `api1-newton-residual` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 12 | 79k | 738 | $0.02 | 0 min |
| api | `api1-newton-residual` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 12 | 101k | 2k | $0.03 | 1 min |
| api | `api2-internal-darcy` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 8 | 116k | 916 | $0.02 | 0 min |
| api | `api2-internal-darcy` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 5 | 69k | 320 | $0.01 | 0 min |
| api | `api2-internal-darcy` | general | gpt-5.4-mini | <span class="bench-partial">2/3</span> | wrong answer | 8 | 66k | 474 | $0.01 | 0 min |
| api | `api2-internal-darcy` | general | qwen3.6:27b | <span class="bench-partial">2/3</span> | wrong answer | 4 | 53k | 770 | $0.02 | 1 min |
| battmo | `bm1-chen-cc-discharge` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 7 | 106k | 1k | $0.03 | 1 min |
| battmo | `bm1-chen-cc-discharge` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 18 | 309k | 2k | $0.02 | 1 min |
| battmo | `bm1-chen-cc-discharge` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 9 | 92k | 658 | $0.02 | 1 min |
| battmo | `bm1-chen-cc-discharge` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 5 | 70k | 872 | $0.02 | 1 min |
| battmo | `bm3-crate-sweep` | general | claude-haiku-4-5 | <span class="bench-partial">2/3</span> | wrong answer | 21 | 404k | 5k | $0.09 | 1 min |
| battmo | `bm3-crate-sweep` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 19 | 696k | 3k | $0.05 | 1 min |
| battmo | `bm3-crate-sweep` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 8 | 88k | 754 | $0.02 | 1 min |
| battmo | `bm3-crate-sweep` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 13 | 199k | 2k | $0.06 | 2 min |
| calibration | `cal1-exp-decay-fit` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 4 | 73k | 1k | $0.02 | 0 min |
| calibration | `cal1-exp-decay-fit` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 5 | 64k | 596 | $0.01 | 1 min |
| calibration | `cal1-exp-decay-fit` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 5 | 62k | 458 | $0.01 | 0 min |
| calibration | `cal1-exp-decay-fit` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 4 | 59k | 1k | $0.02 | 1 min |
| canary | `x0-sum-from-file` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 49k | 261 | $0.02 | 0 min |
| canary | `x0-sum-from-file` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 4 | 56k | 144 | $0.01 | 0 min |
| canary | `x0-sum-from-file` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 34k | 174 | $0.01 | 0 min |
| canary | `x0-sum-from-file` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 4 | 52k | 404 | $0.02 | 0 min |
| ensembles | `ens-bm-crate-sweep` | battmo | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 13 | 254k | 4k | $0.07 | 2 min |
| ensembles | `ens-bm-crate-sweep` | battmo | gemini-3.1-flash-lite | <span class="bench-partial">2/3</span> | serial / mechanism | 19 | 384k | 3k | $0.03 | 1 min |
| ensembles | `ens-bm-crate-sweep` | battmo | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 18 | 224k | 1k | $0.04 | 2 min |
| ensembles | `ens-bm-crate-sweep` | battmo | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 18 | 296k | 3k | $0.10 | 3 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 20 | 528k | 6k | $0.13 | 11 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | gemini-3.1-flash-lite | <span class="bench-partial">1/3</span> | hit budget, serial / mechanism | 13 | 1.1M | 4k | $0.09 | 7 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | gpt-5.4-mini | <span class="bench-partial">2/3</span> | serial / mechanism | 14 | 206k | 1k | $0.05 | 5 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 27 | 619k | 7k | $0.20 | 8 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 4 | 71k | 823 | $0.02 | 1 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 2 | 37k | 282 | $0.00 | 1 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 8 | 87k | 673 | $0.02 | 1 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 6 | 89k | 2k | $0.03 | 2 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 21 | 473k | 5k | $0.10 | 3 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 9 | 135k | 2k | $0.01 | 2 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 18 | 314k | 2k | $0.06 | 3 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 31 | 624k | 7k | $0.20 | 6 min |
| filesystem | `fs1-write-and-include` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 2 | 24k | 191 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 2 | 31k | 95 | $0.00 | 0 min |
| filesystem | `fs1-write-and-include` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 34k | 162 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 2 | 33k | 233 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-battmo` | battmo | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 37k | 227 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-battmo` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 2 | 31k | 95 | $0.00 | 0 min |
| filesystem | `fs1-write-and-include-battmo` | battmo | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 2 | 24k | 86 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-battmo` | battmo | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 2 | 33k | 180 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-fimbul` | fimbul | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 2 | 24k | 191 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-fimbul` | fimbul | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 2 | 31k | 94 | $0.00 | 0 min |
| filesystem | `fs1-write-and-include-fimbul` | fimbul | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 31k | 132 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-fimbul` | fimbul | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 2 | 33k | 196 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-mocca` | mocca | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 2 | 29k | 198 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-mocca` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 2 | 31k | 94 | $0.00 | 0 min |
| filesystem | `fs1-write-and-include-mocca` | mocca | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 4 | 34k | 187 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-mocca` | mocca | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 2 | 29k | 223 | $0.01 | 0 min |
| filesystem | `fs2-nested-write-and-include` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 37k | 253 | $0.01 | 0 min |
| filesystem | `fs2-nested-write-and-include` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 3 | 42k | 126 | $0.00 | 0 min |
| filesystem | `fs2-nested-write-and-include` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 6 | 60k | 302 | $0.01 | 0 min |
| filesystem | `fs2-nested-write-and-include` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 3 | 41k | 309 | $0.01 | 0 min |
| filesystem | `fs3-edit-and-rerun` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 50k | 343 | $0.01 | 0 min |
| filesystem | `fs3-edit-and-rerun` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 4 | 53k | 183 | $0.01 | 0 min |
| filesystem | `fs3-edit-and-rerun` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 6 | 64k | 326 | $0.01 | 0 min |
| filesystem | `fs3-edit-and-rerun` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 3 | 44k | 302 | $0.01 | 0 min |
| filesystem | `fs4-save-output-file` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 41k | 255 | $0.01 | 0 min |
| filesystem | `fs4-save-output-file` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 2 | 31k | 108 | $0.00 | 0 min |
| filesystem | `fs4-save-output-file` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 5 | 51k | 296 | $0.01 | 0 min |
| filesystem | `fs4-save-output-file` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 3 | 33k | 338 | $0.01 | 0 min |
| filesystem | `fs5-multi-file-project` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 4 | 46k | 424 | $0.01 | 0 min |
| filesystem | `fs5-multi-file-project` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 4 | 53k | 190 | $0.01 | 0 min |
| filesystem | `fs5-multi-file-project` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 8 | 74k | 458 | $0.01 | 0 min |
| filesystem | `fs5-multi-file-project` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 3 | 33k | 308 | $0.01 | 0 min |
| filesystem | `fs6-read-transform-write` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 2 | 37k | 261 | $0.01 | 0 min |
| filesystem | `fs6-read-transform-write` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 6 | 71k | 400 | $0.01 | 0 min |
| filesystem | `fs6-read-transform-write` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 28k | 135 | $0.01 | 0 min |
| filesystem | `fs6-read-transform-write` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 3 | 50k | 1k | $0.02 | 1 min |
| fimbul | `fb1-doublet-cooldown` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 12 | 199k | 3k | $0.05 | 5 min |
| fimbul | `fb1-doublet-cooldown` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 13 | 256k | 2k | $0.02 | 3 min |
| fimbul | `fb1-doublet-cooldown` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 13 | 164k | 823 | $0.03 | 3 min |
| fimbul | `fb1-doublet-cooldown` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 16 | 275k | 4k | $0.09 | 4 min |
| guardrails | `x1-no-shell-julia` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 1 | 24k | 77 | $0.01 | 0 min |
| guardrails | `x1-no-shell-julia` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 1 | 21k | 37 | $0.00 | 0 min |
| guardrails | `x1-no-shell-julia` | general | gpt-5.4-mini | <span class="bench-partial">1/3</span> | wrong answer | 2 | 25k | 87 | $0.01 | 0 min |
| guardrails | `x1-no-shell-julia` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 4 | 53k | 479 | $0.02 | 0 min |
| jutuldarcy | `jd-millidarcy-conversion` | general | claude-haiku-4-5 | <span class="bench-partial">2/3</span> | wrong answer | 21 | 417k | 7k | $0.11 | 2 min |
| jutuldarcy | `jd-millidarcy-conversion` | general | gemini-3.1-flash-lite | <span class="bench-fail">0/3</span> | hit budget, wrong answer | 10 | 1.6M | 19k | $0.10 | 2 min |
| jutuldarcy | `jd-millidarcy-conversion` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 20 | 737k | 2k | $0.12 | 1 min |
| jutuldarcy | `jd-millidarcy-conversion` | general | qwen3.6:27b | <span class="bench-partial">1/3</span> | wrong answer | 19 | 410k | 7k | $0.14 | 4 min |
| jutuldarcy | `jd1-gravity-segregation` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 15 | 275k | 4k | $0.06 | 1 min |
| jutuldarcy | `jd1-gravity-segregation` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 19 | 384k | 4k | $0.03 | 1 min |
| jutuldarcy | `jd1-gravity-segregation` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 14 | 168k | 2k | $0.04 | 1 min |
| jutuldarcy | `jd1-gravity-segregation` | general | qwen3.6:27b | <span class="bench-fail">0/3</span> | wrong answer | 17 | 347k | 5k | $0.12 | 4 min |
| jutuldarcy | `jd3-halved-injection` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 23 | 502k | 8k | $0.12 | 2 min |
| jutuldarcy | `jd3-halved-injection` | general | gemini-3.1-flash-lite | <span class="bench-partial">1/3</span> | hit budget | 14 | 1.4M | 16k | $0.09 | 2 min |
| jutuldarcy | `jd3-halved-injection` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 13 | 167k | 2k | $0.03 | 1 min |
| jutuldarcy | `jd3-halved-injection` | general | qwen3.6:27b | <span class="bench-partial">2/3</span> | wrong answer | 14 | 268k | 4k | $0.09 | 3 min |
| mocca | `mc1-vsa-cyclic-golden` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 8 | 135k | 2k | $0.03 | 1 min |
| mocca | `mc1-vsa-cyclic-golden` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 9 | 151k | 2k | $0.01 | 1 min |
| mocca | `mc1-vsa-cyclic-golden` | general | gpt-5.4-mini | <span class="bench-partial">2/3</span> | wrong answer | 13 | 132k | 1k | $0.03 | 4 min |
| mocca | `mc1-vsa-cyclic-golden` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 10 | 151k | 3k | $0.05 | 2 min |
| mocca | `mc4-tsa-toth-honesty` | general | claude-haiku-4-5 | <span class="bench-partial">2/3</span> | wrong answer | 12 | 1.0M | 15k | $0.28 | 4 min |
| mocca | `mc4-tsa-toth-honesty` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 0 | 787k | 8k | $0.06 | 2 min |
| mocca | `mc4-tsa-toth-honesty` | general | gpt-5.4-mini | <span class="bench-partial">1/3</span> | wrong answer | 18 | 541k | 4k | $0.09 | 3 min |
| mocca | `mc4-tsa-toth-honesty` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 24 | 352k | 3k | $0.11 | 2 min |
| plotting | `x5-headless-plot` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 1 | 29k | 300 | $0.01 | 0 min |
| plotting | `x5-headless-plot` | general | gemini-3.1-flash-lite | <span class="bench-partial">1/3</span> | wrong answer | 4 | 119k | 350 | $0.01 | 2 min |
| plotting | `x5-headless-plot` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 31k | 233 | $0.01 | 0 min |
| plotting | `x5-headless-plot` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 3 | 50k | 978 | $0.02 | 1 min |
| plotting | `x6-read-the-bar` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 52k | 604 | $0.02 | 1 min |
| plotting | `x6-read-the-bar` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 4 | 52k | 246 | $0.01 | 1 min |
| plotting | `x6-read-the-bar` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 5 | 50k | 498 | $0.02 | 1 min |
| plotting | `x6-read-the-bar` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 13 | 191k | 3k | $0.07 | 2 min |
| search | `se1-locate-definition` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 4 | 59k | 391 | $0.01 | 0 min |
| search | `se1-locate-definition` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 4 | 50k | 165 | $0.01 | 0 min |
| search | `se1-locate-definition` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 28k | 128 | $0.01 | 0 min |
| search | `se1-locate-definition` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 1 | 22k | 162 | $0.01 | 0 min |
| search | `se1-locate-definition-battmo` | battmo | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 4 | 62k | 393 | $0.01 | 0 min |
| search | `se1-locate-definition-battmo` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 2 | 35k | 121 | $0.00 | 0 min |
| search | `se1-locate-definition-battmo` | battmo | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 4 | 41k | 207 | $0.01 | 0 min |
| search | `se1-locate-definition-battmo` | battmo | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 2 | 33k | 236 | $0.01 | 0 min |
| search | `se1-locate-definition-fimbul` | fimbul | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 5 | 59k | 432 | $0.02 | 0 min |
| search | `se1-locate-definition-fimbul` | fimbul | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 3 | 43k | 145 | $0.00 | 0 min |
| search | `se1-locate-definition-fimbul` | fimbul | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 28k | 149 | $0.01 | 0 min |
| search | `se1-locate-definition-fimbul` | fimbul | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 1 | 22k | 156 | $0.01 | 0 min |
| search | `se1-locate-definition-mocca` | mocca | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 41k | 279 | $0.01 | 0 min |
| search | `se1-locate-definition-mocca` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 4 | 57k | 197 | $0.01 | 0 min |
| search | `se1-locate-definition-mocca` | mocca | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 2 | 19k | 108 | $0.01 | 0 min |
| search | `se1-locate-definition-mocca` | mocca | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 1 | 22k | 164 | $0.01 | 0 min |
| search | `se2-locate-example` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 2 | 37k | 230 | $0.01 | 0 min |
| search | `se2-locate-example` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 5 | 64k | 235 | $0.01 | 0 min |
| search | `se2-locate-example` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 28k | 131 | $0.01 | 0 min |
| search | `se2-locate-example` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 1 | 22k | 136 | $0.01 | 0 min |
| search | `se3-find-call-sites` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 2 | 29k | 343 | $0.01 | 0 min |
| search | `se3-find-call-sites` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 4 | 58k | 341 | $0.01 | 0 min |
| search | `se3-find-call-sites` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 3 | 25k | 212 | $0.01 | 0 min |
| search | `se3-find-call-sites` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 2 | 22k | 317 | $0.01 | 0 min |
| search | `se4-count-jl-files` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 1 | 25k | 77 | $0.01 | 0 min |
| search | `se4-count-jl-files` | general | gemini-3.1-flash-lite | <span class="bench-fail">0/3</span> | wrong answer | 1 | 21k | 29 | $0.00 | 0 min |
| search | `se4-count-jl-files` | general | gpt-5.4-mini | <span class="bench-partial">2/3</span> | wrong answer | 1 | 19k | 61 | $0.01 | 0 min |
| search | `se4-count-jl-files` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 1 | 26k | 194 | $0.01 | 0 min |
| search | `se5-find-constant` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 7 | 104k | 707 | $0.02 | 0 min |
| search | `se5-find-constant` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 6 | 80k | 284 | $0.01 | 0 min |
| search | `se5-find-constant` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 4 | 28k | 173 | $0.01 | 0 min |
| search | `se5-find-constant` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 3 | 41k | 360 | $0.01 | 0 min |
| search | `se6-call-chain` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 8 | 99k | 840 | $0.02 | 0 min |
| search | `se6-call-chain` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 8 | 95k | 429 | $0.01 | 0 min |
| search | `se6-call-chain` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 11 | 60k | 592 | $0.01 | 0 min |
| search | `se6-call-chain` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 6 | 54k | 671 | $0.02 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 4 | 58k | 661 | $0.02 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 6 | 78k | 608 | $0.01 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 8 | 74k | 546 | $0.01 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 9 | 121k | 2k | $0.04 | 1 min |
| usage | `use-csv-mean` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 51k | 436 | $0.01 | 0 min |
| usage | `use-csv-mean` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 4 | 55k | 266 | $0.01 | 0 min |
| usage | `use-csv-mean` | general | gpt-5.4-mini | <span class="bench-fail">0/3</span> | wrong answer | 4 | 42k | 249 | $0.01 | 0 min |
| usage | `use-csv-mean` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 2 | 37k | 295 | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 6 | 98k | 909 | $0.03 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 3 | 47k | 243 | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 5 | 47k | 418 | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 5 | 74k | 677 | $0.02 | 1 min |
| usage | `use-mc-list-examples` | mocca | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | 3 | 45k | 340 | $0.01 | 0 min |
| usage | `use-mc-list-examples` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | 2 | 31k | 166 | $0.00 | 0 min |
| usage | `use-mc-list-examples` | mocca | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | 4 | 44k | 260 | $0.01 | 0 min |
| usage | `use-mc-list-examples` | mocca | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | 6 | 108k | 703 | $0.03 | 1 min |

</details>

## Reading the results

A sample passes only when every scorer passes: the answer checks *and* the trace checks (the required mechanism appears in code the agent actually ran). Failures fall into:

- **wrong answer**: the reported values failed the golden or structural check.
- **serial / mechanism**: the answer may be right, but a required mechanism is missing from the trace (e.g. a sweep that ran serially when the prompt asked for a parallel ensemble).
- **hit budget**: the sample reached its message or time cap before finishing.
- **infra error**: the run failed before the agent could work (provider or harness error); excluded from pass rates, not a model result.

Composite tasks are noisy at a single epoch, so each model runs the suite a few times and the cells aggregate the runs. Regenerate this page with:

```sh
uv run jutul-agent eval <suite> --model <provider/model> --epochs 3
uv run python -m jutul_agent.eval.report <log-prefix> -o docs/benchmark.md
```

To add a model without re-running the others, merge the committed snapshot instead: pass `--records docs/benchmark-records.jsonl` and write it back with `--json docs/benchmark-records.jsonl`.
