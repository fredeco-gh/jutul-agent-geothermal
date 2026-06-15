# Benchmark results

Snapshot generated 2026-06-15 from runs 2026-06-15T16-05-46 … 2026-06-15T18-10-34 (jutul-agent 1ff0d2029, 1ff0d2029-dirty). Every sample runs the real agent end to end in a fresh workspace and is graded on the session trace as well as the answer — see [how evaluation works](evaluation.md). Each model ran the suite **3 times**; cells aggregate across runs, so a fraction like 2/3 means the sample passed two of three runs.

## Overview

Pass rate is passing runs over runs that completed (infrastructure errors excluded). Cost and wall time are for **one** pass over the suite (the per-run average), measured on a single machine. Within a model samples run one at a time, but wall time still depends on that machine and on how many models shared it during the run, so read it as indicative and comparable only within this snapshot; pass rate and cost are unaffected by either. Dollar costs use provider prices as of 2026-06-15 (see `eval/report.py`) and include prompt-cache reads/writes; the self-hosted model is priced against a hosted reference.

| Model | Pass rate | Cost / run | Wall / run |
|---|---|---|---|
| claude-haiku-4-5 | <span class="bench-pass">51/51</span> | $0.52 | 0.5 h |
| gemini-3.1-flash-lite | <span class="bench-partial">40/51</span> | $0.27 | 0.6 h |
| gpt-5.4-mini | <span class="bench-partial">45/51</span> | $0.25 | 0.4 h |
| qwen3.6:27b | <span class="bench-partial">44/51</span> | $0.74 | 0.6 h |

## By suite

| Suite | claude-haiku-4-5 | gemini-3.1-flash-lite | gpt-5.4-mini | qwen3.6:27b |
|---|---|---|---|---|
| calibration | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> |
| canary | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> |
| ensembles | <span class="bench-pass">24/24</span> | <span class="bench-partial">17/24</span> | <span class="bench-partial">23/24</span> | <span class="bench-partial">18/24</span> |
| guardrails | <span class="bench-pass">3/3</span> | <span class="bench-pass">3/3</span> | <span class="bench-partial">1/3</span> | <span class="bench-pass">3/3</span> |
| plotting | <span class="bench-pass">6/6</span> | <span class="bench-partial">3/6</span> | <span class="bench-pass">6/6</span> | <span class="bench-pass">6/6</span> |
| usage | <span class="bench-pass">12/12</span> | <span class="bench-partial">11/12</span> | <span class="bench-partial">9/12</span> | <span class="bench-partial">11/12</span> |
| **all** | <span class="bench-pass">51/51</span> | <span class="bench-partial">40/51</span> | <span class="bench-partial">45/51</span> | <span class="bench-partial">44/51</span> |

## By simulator

Cross-cut of the same samples by the simulator they exercise (`general` = sim-agnostic tasks like canary, calibration, plotting).

| Simulator | claude-haiku-4-5 | gemini-3.1-flash-lite | gpt-5.4-mini | qwen3.6:27b |
|---|---|---|---|---|
| battmo | <span class="bench-pass">9/9</span> | <span class="bench-partial">8/9</span> | <span class="bench-pass">9/9</span> | <span class="bench-partial">7/9</span> |
| fimbul | <span class="bench-pass">6/6</span> | <span class="bench-partial">3/6</span> | <span class="bench-partial">5/6</span> | <span class="bench-partial">3/6</span> |
| general | <span class="bench-pass">18/18</span> | <span class="bench-partial">14/18</span> | <span class="bench-partial">13/18</span> | <span class="bench-pass">18/18</span> |
| jutuldarcy | <span class="bench-pass">9/9</span> | <span class="bench-pass">9/9</span> | <span class="bench-pass">9/9</span> | <span class="bench-pass">9/9</span> |
| mocca | <span class="bench-pass">9/9</span> | <span class="bench-partial">6/9</span> | <span class="bench-pass">9/9</span> | <span class="bench-partial">7/9</span> |
| **all** | <span class="bench-pass">51/51</span> | <span class="bench-partial">40/51</span> | <span class="bench-partial">45/51</span> | <span class="bench-partial">44/51</span> |

<details markdown="1">
<summary>All samples (pass count, cost, wall time)</summary>

| Suite | Sample | Sim | Model | Passed | Failures | Cost | Wall |
|---|---|---|---|---|---|---|---|
| calibration | `cal1-exp-decay-fit` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.02 | 0 min |
| calibration | `cal1-exp-decay-fit` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| calibration | `cal1-exp-decay-fit` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| calibration | `cal1-exp-decay-fit` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.03 | 1 min |
| canary | `x0-sum-from-file` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| canary | `x0-sum-from-file` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.00 | 0 min |
| canary | `x0-sum-from-file` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| canary | `x0-sum-from-file` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| ensembles | `ens-battmo-parallel-sweep` | battmo | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.02 | 0 min |
| ensembles | `ens-battmo-parallel-sweep` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| ensembles | `ens-battmo-parallel-sweep` | battmo | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| ensembles | `ens-battmo-parallel-sweep` | battmo | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.02 | 1 min |
| ensembles | `ens-bm-crate-sweep` | battmo | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.10 | 2 min |
| ensembles | `ens-bm-crate-sweep` | battmo | gemini-3.1-flash-lite | <span class="bench-partial">2/3</span> | serial / mechanism | $0.05 | 2 min |
| ensembles | `ens-bm-crate-sweep` | battmo | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.04 | 1 min |
| ensembles | `ens-bm-crate-sweep` | battmo | qwen3.6:27b | <span class="bench-partial">2/3</span> | wrong answer | $0.09 | 3 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.14 | 15 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | gemini-3.1-flash-lite | <span class="bench-fail">0/3</span> | hit budget, serial / mechanism | $0.10 | 12 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | gpt-5.4-mini | <span class="bench-partial">2/3</span> | serial / mechanism | $0.05 | 9 min |
| ensembles | `ens-fb-injtemp-sweep` | fimbul | qwen3.6:27b | <span class="bench-partial">1/3</span> | wrong answer | $0.15 | 11 min |
| ensembles | `ens-fimbul-parallel-sweep` | fimbul | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.02 | 1 min |
| ensembles | `ens-fimbul-parallel-sweep` | fimbul | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| ensembles | `ens-fimbul-parallel-sweep` | fimbul | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| ensembles | `ens-fimbul-parallel-sweep` | fimbul | qwen3.6:27b | <span class="bench-partial">2/3</span> | wrong answer | $0.03 | 1 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.02 | 1 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.01 | 2 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.02 | 1 min |
| ensembles | `ens-jd-porosity-sweep` | jutuldarcy | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.03 | 2 min |
| ensembles | `ens-jutuldarcy-parallel-sweep` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| ensembles | `ens-jutuldarcy-parallel-sweep` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| ensembles | `ens-jutuldarcy-parallel-sweep` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| ensembles | `ens-jutuldarcy-parallel-sweep` | jutuldarcy | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.02 | 1 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.09 | 4 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | gemini-3.1-flash-lite | <span class="bench-fail">0/3</span> | serial / mechanism | $0.01 | 1 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.04 | 3 min |
| ensembles | `ens-mc-cycles-sweep` | mocca | qwen3.6:27b | <span class="bench-partial">2/3</span> | wrong answer | $0.14 | 6 min |
| ensembles | `ens-mocca-parallel-sweep` | mocca | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| ensembles | `ens-mocca-parallel-sweep` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| ensembles | `ens-mocca-parallel-sweep` | mocca | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| ensembles | `ens-mocca-parallel-sweep` | mocca | qwen3.6:27b | <span class="bench-partial">2/3</span> | wrong answer | $0.02 | 1 min |
| guardrails | `x1-no-shell-julia` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.00 | 0 min |
| guardrails | `x1-no-shell-julia` | general | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.00 | 0 min |
| guardrails | `x1-no-shell-julia` | general | gpt-5.4-mini | <span class="bench-partial">1/3</span> | wrong answer | $0.00 | 0 min |
| guardrails | `x1-no-shell-julia` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| plotting | `x5-headless-plot` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| plotting | `x5-headless-plot` | general | gemini-3.1-flash-lite | <span class="bench-partial">1/3</span> | hit budget, wrong answer | $0.00 | 12 min |
| plotting | `x5-headless-plot` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.00 | 0 min |
| plotting | `x5-headless-plot` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| plotting | `x6-read-the-bar` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.01 | 3 min |
| plotting | `x6-read-the-bar` | general | gemini-3.1-flash-lite | <span class="bench-partial">2/3</span> | hit budget | $0.01 | 4 min |
| plotting | `x6-read-the-bar` | general | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 3 min |
| plotting | `x6-read-the-bar` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.05 | 4 min |
| usage | `use-bm-cell-capacity` | battmo | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| usage | `use-bm-cell-capacity` | battmo | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 1 min |
| usage | `use-bm-cell-capacity` | battmo | qwen3.6:27b | <span class="bench-partial">2/3</span> | hit budget | $0.08 | 2 min |
| usage | `use-csv-mean` | general | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| usage | `use-csv-mean` | general | gemini-3.1-flash-lite | <span class="bench-partial">2/3</span> | hit budget | $0.01 | 0 min |
| usage | `use-csv-mean` | general | gpt-5.4-mini | <span class="bench-fail">0/3</span> | wrong answer | $0.01 | 0 min |
| usage | `use-csv-mean` | general | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.04 | 1 min |
| usage | `use-jd-well-api` | jutuldarcy | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| usage | `use-jd-well-api` | jutuldarcy | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.02 | 1 min |
| usage | `use-mc-list-examples` | mocca | claude-haiku-4-5 | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |
| usage | `use-mc-list-examples` | mocca | gemini-3.1-flash-lite | <span class="bench-pass">3/3</span> | — | $0.00 | 0 min |
| usage | `use-mc-list-examples` | mocca | gpt-5.4-mini | <span class="bench-pass">3/3</span> | — | $0.00 | 0 min |
| usage | `use-mc-list-examples` | mocca | qwen3.6:27b | <span class="bench-pass">3/3</span> | — | $0.01 | 0 min |

</details>

## Reading the results

A sample passes only when every scorer passes — the answer checks *and* the trace checks (the required mechanism appears in code the agent actually ran). Failures fall into:

- **wrong answer** — the reported values failed the golden or structural check.
- **serial / mechanism** — the answer may be right, but a required mechanism is missing from the trace (e.g. a sweep that ran serially when the prompt asked for a parallel ensemble).
- **hit budget** — the sample reached its message or time cap before finishing.
- **infra error** — the run failed before the agent could work (provider or harness error); excluded from pass rates, not a model result.

Composite tasks are noisy at a single epoch, so each model runs the suite a few times and the cells aggregate the runs. Regenerate this page with:

```sh
uv run jutul-agent eval <suite> --model <provider/model> --epochs 3
uv run python -m jutul_agent.eval.report <log-prefix> -o docs/benchmark.md
```

To add a model without re-running the others, merge the committed snapshot instead: pass `--records docs/benchmark-records.jsonl` and write it back with `--json docs/benchmark-records.jsonl`.
