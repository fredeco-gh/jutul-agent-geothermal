---
name: ensembles
description: Run parallel ensembles (UQ, parameter sweeps) across warm Distributed workers from the Julia REPL
---

# Ensembles and parameter sweeps

## When to use

Use this when a task runs the **same simulation many times** with different inputs —
uncertainty quantification, parameter sweeps, sensitivity studies — and the runs are
independent. For a single run, just use `julia_eval`.

## How

The session already has a helper module, `JutulAgentEnsemble`, loaded. Call it from
`julia_eval`:

```julia
JutulAgentEnsemble.run_ensemble(run_case, cases; nworkers=4, setup=:(using JutulDarcy))
```

- `run_case` — a function applied to each case; it runs **on a worker process**.
- `cases` — the inputs to sweep (a vector). Results come back in this order.
- `nworkers` — how many worker processes to spawn (capped at `length(cases)`).
- `setup` — an expression run on every worker first, to load whatever `run_case`
  needs (e.g. `:(using JutulDarcy, Jutul)`). Required whenever `run_case` uses a
  package.

It spawns **warm** workers (they inherit this session's project and system image, so
no second precompile), runs the cases in parallel, returns the results in order, and
removes the workers it spawned afterwards.

## Rules (Distributed gotchas)

- **`run_case` runs on workers, not in this session.** Anything it touches must exist
  there: load packages via `setup`, and define `run_case` as a named top-level
  function — not a closure capturing local variables.
- Build each case's input **inside** `run_case` (or pass plain data in `cases`); don't
  capture a big local model, or it gets serialised to every worker.
- Keep what each case returns small (a scalar, a NamedTuple of metrics) — large return
  objects are serialised back to this process.

## Example

```julia
# Sweep porosity; each worker builds its own model and returns a scalar metric.
function run_case(phi)
    domain = reservoir_domain(CartesianMesh((10, 10, 3)); porosity = phi, permeability = 1e-13)
    # ... set up wells, schedule, simulate ...
    return recovery_factor   # small return value
end

results = JutulAgentEnsemble.run_ensemble(
    run_case, [0.10, 0.15, 0.20, 0.25];
    nworkers = 4, setup = :(using JutulDarcy, Jutul),
)
```

For very heavy sweeps, set `nworkers` to the cores you want to use; for a one-off
parallel block you can also drop to plain `Distributed` (`addprocs`, `@everywhere`,
`pmap`) inside `julia_eval` — `run_ensemble` is just the ergonomic path.
