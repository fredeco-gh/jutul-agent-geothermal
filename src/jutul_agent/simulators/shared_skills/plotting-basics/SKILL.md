---
name: plotting-basics
description: Headless Makie plotting contract and session artifact capture via julia_plot
---

# Plotting basics

## When to use

Use this skill whenever the user asks for a plot, chart, figure, or visualization,
or when a plot would make simulation results easier to understand.

## Headless contract

- Use `julia_plot` — not `julia_eval` — to produce plots that appear in the transcript.
- Code must evaluate to a **Makie `Figure`**. The last expression should be `fig`.
- Do **not** call `display(fig)` or any plotter that opens an interactive
  window unless the user explicitly asks for one.
- Prefer **CairoMakie** (loaded automatically by `julia_plot`). Do not `using GLMakie`
  in routine agent plots.

## Formats and sizing

- Default format is **PNG** (`format="png"`).
- Use **SVG** (`format="svg"`) for simple line plots when vector output is useful.
- Pass `size=(width, height)` when you need a specific resolution.
- Use `slot="name"` to overwrite the same artifact path when comparing iterations
  (e.g. `slot="saturation_final"`).

## Raw Makie example

```julia
using CairoMakie
fig = Figure(size = (600, 400))
ax = Axis(fig[1, 1], title = "Example", xlabel = "x", ylabel = "y")
x = range(0, 2pi, length = 100)
lines!(ax, x, sin.(x))
fig
```

Then call `julia_plot` with that code (or paste the body into `julia_plot`'s `code` arg).

## Loading tabular data

Observations and metrics often live in CSV files under `experiments/`.
Use workspace-relative paths in Julia (no leading slash):

```julia
using CSV, DataFrames
obs = CSV.read("experiments/observations/data.csv", DataFrame)
```

Prefer `CSV` + `DataFrames` (when available in the simulator's Julia env)
over shelling out to read files.

## Decision rule

Prefer in order:

1. **Inline Makie** built against the live result object — probe with `keys(...)` /
   `propertynames(...)`, then draw with `Figure` / `Axis` / `lines!` / `heatmap!`.
   Guaranteed to work headlessly under CairoMakie.
2. A **native simulator plotter** that returns a populated `Figure` and is
   documented as CairoMakie-compatible. Verify it isn't a GLMakie-only plotter
   (see the empty-figure trap below).
3. **Thin helpers** from `plots.jl` when the simulator provides them.

See each simulator's `<sim>-overview` skill for the native plotter names.

## The empty-figure trap

Some simulator plotters are wired to GLMakie and silently return an empty
`Figure()` under CairoMakie (Julia log shows a warning like
`Warning: Independent figure creation not implemented for backend CairoMakie`).
`julia_plot` detects this and errors with "Figure has no content". When you
see that error, **do not retry the same call** — switch to inline Makie.

## Interactive opt-in

Only when the user explicitly asks for an interactive viewer, load `GLMakie`
and call the simulator's interactive plotter. Interactive plots open a window
but are not captured as artifacts — pair them with a static `julia_plot` if
the user also wants something in the transcript.

## Performance

- **Do not re-run full simulations inside `julia_plot`** if the REPL already has
  `t`, `V`, and observed arrays from a recent `julia_eval`. Build the figure from
  cached vectors instead — plotting should take seconds, not minutes.
- Reuse `slot=` for comparison plots you refresh during calibration.
