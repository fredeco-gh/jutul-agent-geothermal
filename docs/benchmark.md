# Benchmark results

Snapshot generated 2026-06-17 from runs 2026-06-16T07-24-28 … 2026-06-16T09-14-26 (jutul-agent 3f7882978, 3f7882978-dirty, d969844f3, d969844f3-dirty, f6bc9231f). Every sample runs the real agent end to end in a fresh workspace and is graded on the session trace as well as the answer. See [how evaluation works](evaluation.md). Each model ran the suite **once**, and cells aggregate across runs, so a fraction like 2/3 means the sample passed two of three runs.

## Overview

Pass rate is passing runs over runs that completed (infrastructure errors excluded). Tool calls and tokens are the per-run totals across the suite, the harness-efficiency signals: at equal pass rate, fewer means the harness got the agent there in less work. Input tokens note how many were served from the prompt cache (a cheap fraction of the input price); a model that caches aggressively processes a large input cheaply, which is why cost doesn't track raw token counts and is shown alongside them. Cost and wall time are for **one** pass over the suite (the per-run average), measured on a single machine. Within a model samples run one at a time, but wall time still depends on that machine and on how many models shared it during the run, so read it as indicative and comparable only within this snapshot; pass rate and cost are unaffected by either. Dollar costs use provider prices as of 2026-06-15 (see `eval/report.py`) and include prompt-cache reads/writes; the self-hosted model is priced against a hosted reference.

| Model | Pass rate | Tool calls / run | Input tokens / run | Output tokens / run | Cost / run | Wall / run |
|---|---|---|---|---|---|---|
| claude-haiku-4-5 | <span class="bench-partial">46/48</span> | 243 | 5.1M (4.6M cached, 91%) | 60k | $1.37 | 0.7 h |
| gemini-3.1-flash-lite | <span class="bench-partial">44/48</span> | 297 | 7.7M (6.2M cached, 80%) | 52k | $0.63 | 1.0 h |
| gpt-5.4-mini | <span class="bench-partial">43/48</span> | 346 | 3.6M (3.1M cached, 87%) | 24k | $0.69 | 0.7 h |
| qwen3.6:27b | <span class="bench-partial">42/48</span> | 357 | 5.5M | 73k | $1.82 | 1.1 h |

## By suite

| Suite | claude-haiku-4-5 | gemini-3.1-flash-lite | gpt-5.4-mini | qwen3.6:27b |
|---|---|---|---|---|
| api | <span class="bench-pass">2/2</span> | <span class="bench-pass">2/2</span> | <span class="bench-partial">1/2</span> | <span class="bench-pass">2/2</span> |
| battmo | <span class="bench-pass">2/2</span> | <span class="bench-pass">2/2</span> | <span class="bench-pass">2/2</span> | <span class="bench-partial">1/2</span> |
| calibration | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> |
| canary | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> |
| ensembles | <span class="bench-pass">8/8</span> | <span class="bench-partial">5/8</span> | <span class="bench-pass">8/8</span> | <span class="bench-partial">6/8</span> |
| filesystem | <span class="bench-pass">9/9</span> | <span class="bench-pass">9/9</span> | <span class="bench-pass">9/9</span> | <span class="bench-pass">9/9</span> |
| fimbul | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> | <span class="bench-fail">0/1</span> |
| guardrails | <span class="bench-pass">1/1</span> | <span class="bench-pass">1/1</span> | <span class="bench-fail">0/1</span> | <span class="bench-pass">1/1</span> |
| jutuldarcy | <span class="bench-partial">1/2</span> | <span class="bench-pass">2/2</span> | <span class="bench-pass">2/2</span> | <span class="bench-partial">1/2</span> |
| mocca | <span class="bench-partial">1/2</span> | <span class="bench-pass">2/2</span> | <span class="bench-fail">0/2</span> | <span class="bench-pass">2/2</span> |
| plotting | <span class="bench-pass">2/2</span> | <span class="bench-partial">1/2</span> | <span class="bench-pass">2/2</span> | <span class="bench-pass">2/2</span> |
| search | <span class="bench-pass">13/13</span> | <span class="bench-pass">13/13</span> | <span class="bench-pass">13/13</span> | <span class="bench-pass">13/13</span> |
| usage | <span class="bench-pass">4/4</span> | <span class="bench-pass">4/4</span> | <span class="bench-partial">3/4</span> | <span class="bench-partial">3/4</span> |
| **all** | <span class="bench-partial">46/48</span> | <span class="bench-partial">44/48</span> | <span class="bench-partial">43/48</span> | <span class="bench-partial">42/48</span> |

## By simulator

Cross-cut of the same samples by the simulator they exercise (`general` = sim-agnostic tasks like canary, calibration, plotting).

| Simulator | claude-haiku-4-5 | gemini-3.1-flash-lite | gpt-5.4-mini | qwen3.6:27b |
|---|---|---|---|---|
| battmo | <span class="bench-pass">6/6</span> | <span class="bench-partial">5/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> |
| fimbul | <span class="bench-pass">5/5</span> | <span class="bench-partial">4/5</span> | <span class="bench-pass">5/5</span> | <span class="bench-pass">5/5</span> |
| general | <span class="bench-partial">25/27</span> | <span class="bench-partial">26/27</span> | <span class="bench-partial">22/27</span> | <span class="bench-partial">24/27</span> |
| jutuldarcy | <span class="bench-pass">4/4</span> | <span class="bench-pass">4/4</span> | <span class="bench-pass">4/4</span> | <span class="bench-partial">3/4</span> |
| mocca | <span class="bench-pass">6/6</span> | <span class="bench-partial">5/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-partial">4/6</span> |
| **all** | <span class="bench-partial">46/48</span> | <span class="bench-partial">44/48</span> | <span class="bench-partial">43/48</span> | <span class="bench-partial">42/48</span> |

<details markdown="1">
<summary>All samples (pass count, tool calls, tokens, cost, wall time)</summary>

| Suite | Sample | Sim | Model | Passed | Failures | Tool calls | Input | Output | Cost | Wall |
|---|---|---|---|---|---|---|---|---|---|---|
| api | `api1-newton-residual` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 14 | 130k | 1k | $0.03 | 0 min |
| api | `api1-newton-residual` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 7 | 86k | 436 | $0.01 | 0 min |
| api | `api1-newton-residual` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 17 | 113k | 985 | $0.02 | 1 min |
| api | `api1-newton-residual` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 15 | 131k | 2k | $0.04 | 1 min |
| api | `api2-internal-darcy` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 6 | 86k | 736 | $0.02 | 0 min |
| api | `api2-internal-darcy` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 6 | 73k | 326 | $0.01 | 0 min |
| api | `api2-internal-darcy` | general | gpt-5.4-mini | <span class="bench-fail">0/1</span> | wrong answer | 6 | 37k | 285 | $0.01 | 0 min |
| api | `api2-internal-darcy` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 4 | 55k | 1k | $0.02 | 1 min |
| battmo | `bm1-chen-cc-discharge` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 4 | 64k | 611 | $0.02 | 1 min |
| battmo | `bm1-chen-cc-discharge` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 16 | 274k | 2k | $0.02 | 1 min |
| battmo | `bm1-chen-cc-discharge` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 12 | 107k | 685 | $0.02 | 1 min |
| battmo | `bm1-chen-cc-discharge` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 12 | 158k | 2k | $0.05 | 2 min |
| battmo | `bm3-crate-sweep` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 13 | 201k | 2k | $0.04 | 1 min |
| battmo | `bm3-crate-sweep` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 23 | 683k | 5k | $0.05 | 1 min |
| battmo | `bm3-crate-sweep` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 17 | 169k | 1k | $0.03 | 1 min |
| battmo | `bm3-crate-sweep` | general | qwen3.6:27b | <span class="bench-fail">0/1</span> | wrong answer | 20 | 272k | 2k | $0.09 | 2 min |
| calibration | `cal1-exp-decay-fit` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 6 | 94k | 2k | $0.03 | 1 min |
| calibration | `cal1-exp-decay-fit` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 3 | 41k | 265 | $0.00 | 0 min |
| calibration | `cal1-exp-decay-fit` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 7 | 61k | 455 | $0.01 | 0 min |
| calibration | `cal1-exp-decay-fit` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 7 | 101k | 2k | $0.04 | 1 min |
| canary | `x0-sum-from-file` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 4 | 59k | 363 | $0.01 | 0 min |
| canary | `x0-sum-from-file` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 5 | 61k | 143 | $0.01 | 0 min |
| canary | `x0-sum-from-file` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 4 | 36k | 202 | $0.01 | 0 min |
| canary | `x0-sum-from-file` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 2 | 32k | 187 | $0.01 | 0 min |
| ensembles | `ens-battmo-parallel-sweep` | battmo | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 5 | 88k | 786 | $0.02 | 1 min |
| ensembles | `ens-battmo-parallel-sweep` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 5 | 62k | 556 | $0.01 | 0 min |
| ensembles | `ens-battmo-parallel-sweep` | battmo | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 6 | 70k | 398 | $0.01 | 0 min |
| ensembles | `ens-battmo-parallel-sweep` | battmo | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 4 | 63k | 932 | $0.02 | 1 min |
| ensembles | `ens-bm-crate-sweep` | battmo | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 18 | 374k | 3k | $0.08 | 2 min |
| ensembles | `ens-bm-crate-sweep` | battmo | gemini-3.1-flash-lite | <span class="bench-fail">0/1</span> | hit budget | 0 | 2.1M | 8k | $0.13 | 2 min |
| ensembles | `ens-bm-crate-sweep` | battmo | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 16 | 181k | 971 | $0.03 | 1 min |
| ensembles | `ens-bm-crate-sweep` | battmo | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 23 | 399k | 5k | $0.13 | 3 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 18 | 434k | 6k | $0.11 | 10 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | gemini-3.1-flash-lite | <span class="bench-fail">0/1</span> | wrong answer | 3 | 216k | 3k | $0.03 | 6 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 16 | 238k | 1k | $0.04 | 7 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 20 | 345k | 5k | $0.11 | 7 min |
| ensembles | `ens-fimbul-parallel-sweep` | fimbul | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 47k | 559 | $0.01 | 1 min |
| ensembles | `ens-fimbul-parallel-sweep` | fimbul | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 4 | 52k | 549 | $0.01 | 0 min |
| ensembles | `ens-fimbul-parallel-sweep` | fimbul | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 7 | 84k | 564 | $0.02 | 1 min |
| ensembles | `ens-fimbul-parallel-sweep` | fimbul | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 4 | 67k | 936 | $0.02 | 1 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 13 | 280k | 3k | $0.07 | 3 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 8 | 119k | 976 | $0.01 | 2 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 8 | 88k | 646 | $0.02 | 1 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 4 | 54k | 1k | $0.02 | 2 min |
| ensembles | `ens-jutuldarcy-parallel-sweep` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 56k | 617 | $0.02 | 1 min |
| ensembles | `ens-jutuldarcy-parallel-sweep` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 5 | 63k | 633 | $0.01 | 0 min |
| ensembles | `ens-jutuldarcy-parallel-sweep` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 7 | 80k | 529 | $0.02 | 1 min |
| ensembles | `ens-jutuldarcy-parallel-sweep` | jutuldarcy | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 4 | 63k | 1k | $0.02 | 1 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 12 | 218k | 4k | $0.06 | 2 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | gemini-3.1-flash-lite | <span class="bench-fail">0/1</span> | serial / mechanism | 13 | 208k | 3k | $0.02 | 2 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 17 | 211k | 1k | $0.04 | 2 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | qwen3.6:27b | <span class="bench-fail">0/1</span> | serial / mechanism | 15 | 203k | 2k | $0.07 | 3 min |
| ensembles | `ens-mocca-parallel-sweep` | mocca | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 36k | 420 | $0.01 | 0 min |
| ensembles | `ens-mocca-parallel-sweep` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 8 | 110k | 855 | $0.01 | 1 min |
| ensembles | `ens-mocca-parallel-sweep` | mocca | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 7 | 85k | 576 | $0.02 | 1 min |
| ensembles | `ens-mocca-parallel-sweep` | mocca | qwen3.6:27b | <span class="bench-fail">0/1</span> | wrong answer | 4 | 63k | 841 | $0.02 | 1 min |
| filesystem | `fs1-write-and-include` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 24k | 187 | $0.02 | 0 min |
| filesystem | `fs1-write-and-include` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 2 | 30k | 88 | $0.00 | 0 min |
| filesystem | `fs1-write-and-include` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 4 | 36k | 198 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 2 | 32k | 187 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-battmo` | battmo | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 23k | 186 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-battmo` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 2 | 30k | 94 | $0.00 | 0 min |
| filesystem | `fs1-write-and-include-battmo` | battmo | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 4 | 36k | 200 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-battmo` | battmo | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 2 | 31k | 203 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-fimbul` | fimbul | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 23k | 180 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-fimbul` | fimbul | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 2 | 30k | 92 | $0.00 | 0 min |
| filesystem | `fs1-write-and-include-fimbul` | fimbul | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 2 | 27k | 82 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-fimbul` | fimbul | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 2 | 31k | 217 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-mocca` | mocca | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 24k | 187 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-mocca` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 2 | 30k | 90 | $0.00 | 0 min |
| filesystem | `fs1-write-and-include-mocca` | mocca | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 2 | 27k | 85 | $0.01 | 0 min |
| filesystem | `fs1-write-and-include-mocca` | mocca | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 2 | 32k | 267 | $0.01 | 0 min |
| filesystem | `fs2-nested-write-and-include` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 24k | 206 | $0.01 | 0 min |
| filesystem | `fs2-nested-write-and-include` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 3 | 40k | 124 | $0.00 | 0 min |
| filesystem | `fs2-nested-write-and-include` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 5 | 46k | 267 | $0.01 | 0 min |
| filesystem | `fs2-nested-write-and-include` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 2 | 32k | 316 | $0.01 | 0 min |
| filesystem | `fs3-edit-and-rerun` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 4 | 60k | 433 | $0.01 | 0 min |
| filesystem | `fs3-edit-and-rerun` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 4 | 51k | 202 | $0.00 | 0 min |
| filesystem | `fs3-edit-and-rerun` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 6 | 64k | 350 | $0.01 | 0 min |
| filesystem | `fs3-edit-and-rerun` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 3 | 43k | 310 | $0.01 | 0 min |
| filesystem | `fs4-save-output-file` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 35k | 214 | $0.01 | 0 min |
| filesystem | `fs4-save-output-file` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 2 | 30k | 96 | $0.00 | 0 min |
| filesystem | `fs4-save-output-file` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 5 | 55k | 289 | $0.01 | 0 min |
| filesystem | `fs4-save-output-file` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 3 | 32k | 351 | $0.01 | 0 min |
| filesystem | `fs5-multi-file-project` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 4 | 48k | 472 | $0.01 | 0 min |
| filesystem | `fs5-multi-file-project` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 10 | 117k | 547 | $0.01 | 0 min |
| filesystem | `fs5-multi-file-project` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 8 | 75k | 489 | $0.01 | 0 min |
| filesystem | `fs5-multi-file-project` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 4 | 43k | 430 | $0.01 | 0 min |
| filesystem | `fs6-read-transform-write` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 35k | 257 | $0.01 | 0 min |
| filesystem | `fs6-read-transform-write` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 4 | 51k | 217 | $0.00 | 0 min |
| filesystem | `fs6-read-transform-write` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 6 | 55k | 319 | $0.01 | 0 min |
| filesystem | `fs6-read-transform-write` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 5 | 70k | 4k | $0.03 | 2 min |
| fimbul | `fb1-doublet-cooldown` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 15 | 259k | 2k | $0.07 | 4 min |
| fimbul | `fb1-doublet-cooldown` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 19 | 379k | 909 | $0.03 | 4 min |
| fimbul | `fb1-doublet-cooldown` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 8 | 73k | 706 | $0.02 | 3 min |
| fimbul | `fb1-doublet-cooldown` | general | qwen3.6:27b | <span class="bench-fail">0/1</span> | wrong answer | 25 | 537k | 5k | $0.17 | 7 min |
| guardrails | `x1-no-shell-julia` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 1 | 23k | 86 | $0.01 | 0 min |
| guardrails | `x1-no-shell-julia` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 1 | 20k | 43 | $0.00 | 0 min |
| guardrails | `x1-no-shell-julia` | general | gpt-5.4-mini | <span class="bench-fail">0/1</span> | wrong answer | 1 | 18k | 66 | $0.01 | 0 min |
| guardrails | `x1-no-shell-julia` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 1 | 21k | 123 | $0.01 | 0 min |
| jutuldarcy | `jd1-gravity-segregation` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 12 | 187k | 3k | $0.05 | 1 min |
| jutuldarcy | `jd1-gravity-segregation` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 14 | 201k | 2k | $0.02 | 1 min |
| jutuldarcy | `jd1-gravity-segregation` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 13 | 138k | 1k | $0.03 | 1 min |
| jutuldarcy | `jd1-gravity-segregation` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 18 | 335k | 7k | $0.12 | 4 min |
| jutuldarcy | `jd3-halved-injection` | general | claude-haiku-4-5 | <span class="bench-fail">0/1</span> | wrong answer | 3 | 245k | 4k | $0.08 | 2 min |
| jutuldarcy | `jd3-halved-injection` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 31 | 916k | 15k | $0.08 | 2 min |
| jutuldarcy | `jd3-halved-injection` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 17 | 224k | 2k | $0.04 | 1 min |
| jutuldarcy | `jd3-halved-injection` | general | qwen3.6:27b | <span class="bench-fail">0/1</span> | wrong answer | 30 | 706k | 10k | $0.24 | 6 min |
| mocca | `mc1-vsa-cyclic-golden` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 8 | 118k | 1k | $0.03 | 1 min |
| mocca | `mc1-vsa-cyclic-golden` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 16 | 634k | 3k | $0.04 | 2 min |
| mocca | `mc1-vsa-cyclic-golden` | general | gpt-5.4-mini | <span class="bench-fail">0/1</span> | wrong answer | 15 | 171k | 1k | $0.03 | 10 min |
| mocca | `mc1-vsa-cyclic-golden` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 11 | 131k | 2k | $0.04 | 2 min |
| mocca | `mc4-tsa-toth-honesty` | general | claude-haiku-4-5 | <span class="bench-fail">0/1</span> | hit budget | 0 | 867k | 13k | $0.22 | 4 min |
| mocca | `mc4-tsa-toth-honesty` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 11 | 145k | 826 | $0.01 | 0 min |
| mocca | `mc4-tsa-toth-honesty` | general | gpt-5.4-mini | <span class="bench-fail">0/1</span> | wrong answer | 26 | 351k | 3k | $0.05 | 2 min |
| mocca | `mc4-tsa-toth-honesty` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 38 | 373k | 7k | $0.13 | 4 min |
| plotting | `x5-headless-plot` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 1 | 23k | 193 | $0.01 | 1 min |
| plotting | `x5-headless-plot` | general | gemini-3.1-flash-lite | <span class="bench-fail">0/1</span> | hit budget | 0 | 20k | 109 | $0.00 | 30 min |
| plotting | `x5-headless-plot` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 3 | 27k | 242 | $0.01 | 0 min |
| plotting | `x5-headless-plot` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 5 | 67k | 954 | $0.02 | 1 min |
| plotting | `x6-read-the-bar` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 36k | 349 | $0.01 | 1 min |
| plotting | `x6-read-the-bar` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 3 | 42k | 200 | $0.01 | 1 min |
| plotting | `x6-read-the-bar` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 7 | 60k | 730 | $0.02 | 1 min |
| plotting | `x6-read-the-bar` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 7 | 95k | 2k | $0.03 | 2 min |
| search | `se1-locate-definition` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 24k | 190 | $0.01 | 0 min |
| search | `se1-locate-definition` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 1 | 20k | 70 | $0.00 | 0 min |
| search | `se1-locate-definition` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 2 | 18k | 107 | $0.01 | 0 min |
| search | `se1-locate-definition` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 1 | 21k | 153 | $0.01 | 0 min |
| search | `se1-locate-definition-battmo` | battmo | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 48k | 328 | $0.01 | 0 min |
| search | `se1-locate-definition-battmo` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 2 | 30k | 100 | $0.00 | 0 min |
| search | `se1-locate-definition-battmo` | battmo | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 2 | 18k | 103 | $0.01 | 0 min |
| search | `se1-locate-definition-battmo` | battmo | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 1 | 21k | 136 | $0.01 | 0 min |
| search | `se1-locate-definition-fimbul` | fimbul | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 48k | 317 | $0.01 | 0 min |
| search | `se1-locate-definition-fimbul` | fimbul | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 1 | 20k | 72 | $0.00 | 0 min |
| search | `se1-locate-definition-fimbul` | fimbul | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 3 | 27k | 154 | $0.01 | 0 min |
| search | `se1-locate-definition-fimbul` | fimbul | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 1 | 21k | 167 | $0.01 | 0 min |
| search | `se1-locate-definition-mocca` | mocca | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 36k | 230 | $0.01 | 0 min |
| search | `se1-locate-definition-mocca` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 2 | 31k | 100 | $0.00 | 0 min |
| search | `se1-locate-definition-mocca` | mocca | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 2 | 27k | 95 | $0.01 | 0 min |
| search | `se1-locate-definition-mocca` | mocca | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 1 | 21k | 155 | $0.01 | 0 min |
| search | `se2-locate-example` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 1 | 23k | 121 | $0.01 | 0 min |
| search | `se2-locate-example` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 1 | 20k | 59 | $0.00 | 0 min |
| search | `se2-locate-example` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 2 | 18k | 109 | $0.01 | 0 min |
| search | `se2-locate-example` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 1 | 21k | 133 | $0.01 | 0 min |
| search | `se3-find-call-sites` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 36k | 518 | $0.01 | 0 min |
| search | `se3-find-call-sites` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 3 | 41k | 231 | $0.00 | 0 min |
| search | `se3-find-call-sites` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 2 | 18k | 173 | $0.01 | 0 min |
| search | `se3-find-call-sites` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 2 | 21k | 358 | $0.01 | 0 min |
| search | `se4-count-jl-files` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 1 | 24k | 114 | $0.01 | 0 min |
| search | `se4-count-jl-files` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 3 | 41k | 114 | $0.00 | 0 min |
| search | `se4-count-jl-files` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 1 | 18k | 64 | $0.01 | 0 min |
| search | `se4-count-jl-files` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 1 | 21k | 163 | $0.01 | 0 min |
| search | `se5-find-constant` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 5 | 72k | 508 | $0.02 | 0 min |
| search | `se5-find-constant` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 6 | 73k | 263 | $0.01 | 0 min |
| search | `se5-find-constant` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 4 | 27k | 194 | $0.01 | 0 min |
| search | `se5-find-constant` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 2 | 32k | 273 | $0.01 | 0 min |
| search | `se6-call-chain` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 9 | 125k | 872 | $0.02 | 3 min |
| search | `se6-call-chain` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 11 | 131k | 460 | $0.01 | 0 min |
| search | `se6-call-chain` | general | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 10 | 68k | 570 | $0.01 | 0 min |
| search | `se6-call-chain` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 8 | 101k | 946 | $0.03 | 1 min |
| search | `src-battmo-locate-module` | battmo | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 47k | 301 | $0.01 | 0 min |
| search | `src-battmo-locate-module` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 3 | 40k | 118 | $0.00 | 0 min |
| search | `src-battmo-locate-module` | battmo | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 5 | 45k | 297 | $0.01 | 0 min |
| search | `src-battmo-locate-module` | battmo | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 3 | 42k | 276 | $0.01 | 0 min |
| search | `src-fimbul-locate-module` | fimbul | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 2 | 36k | 263 | $0.01 | 0 min |
| search | `src-fimbul-locate-module` | fimbul | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 4 | 52k | 142 | $0.00 | 0 min |
| search | `src-fimbul-locate-module` | fimbul | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 4 | 45k | 245 | $0.01 | 0 min |
| search | `src-fimbul-locate-module` | fimbul | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 3 | 42k | 304 | $0.01 | 0 min |
| search | `src-jutuldarcy-locate-module` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 48k | 339 | $0.01 | 0 min |
| search | `src-jutuldarcy-locate-module` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 4 | 52k | 162 | $0.01 | 0 min |
| search | `src-jutuldarcy-locate-module` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 3 | 27k | 151 | $0.01 | 0 min |
| search | `src-jutuldarcy-locate-module` | jutuldarcy | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 3 | 43k | 358 | $0.01 | 1 min |
| search | `src-mocca-locate-module` | mocca | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 48k | 313 | $0.01 | 0 min |
| search | `src-mocca-locate-module` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 4 | 52k | 152 | $0.01 | 0 min |
| search | `src-mocca-locate-module` | mocca | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 2 | 27k | 99 | $0.01 | 0 min |
| search | `src-mocca-locate-module` | mocca | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 3 | 42k | 306 | $0.01 | 1 min |
| usage | `use-bm-cell-capacity` | battmo | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 5 | 77k | 2k | $0.02 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 6 | 77k | 472 | $0.01 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 9 | 67k | 570 | $0.01 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 16 | 250k | 2k | $0.08 | 2 min |
| usage | `use-csv-mean` | general | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 49k | 473 | $0.01 | 0 min |
| usage | `use-csv-mean` | general | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 4 | 51k | 293 | $0.01 | 0 min |
| usage | `use-csv-mean` | general | gpt-5.4-mini | <span class="bench-fail">0/1</span> | wrong answer | 3 | 27k | 159 | $0.01 | 0 min |
| usage | `use-csv-mean` | general | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 3 | 44k | 477 | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 7 | 106k | 1k | $0.03 | 1 min |
| usage | `use-jd-well-api` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 8 | 101k | 428 | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 9 | 55k | 540 | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | qwen3.6:27b | <span class="bench-fail">0/1</span> | wrong answer | 6 | 70k | 733 | $0.02 | 1 min |
| usage | `use-mc-list-examples` | mocca | claude-haiku-4-5 | <span class="bench-pass">1/1</span> | — | 3 | 47k | 339 | $0.01 | 0 min |
| usage | `use-mc-list-examples` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">1/1</span> | — | 2 | 30k | 161 | $0.00 | 0 min |
| usage | `use-mc-list-examples` | mocca | gpt-5.4-mini | <span class="bench-pass">1/1</span> | — | 4 | 27k | 256 | $0.01 | 0 min |
| usage | `use-mc-list-examples` | mocca | qwen3.6:27b | <span class="bench-pass">1/1</span> | — | 4 | 53k | 388 | $0.02 | 1 min |

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
