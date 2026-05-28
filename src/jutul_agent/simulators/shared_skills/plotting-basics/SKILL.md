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
- Do **not** call `display(fig)`, `plot_well_results`, or `plot_dashboard` unless the
  user explicitly wants an interactive window.
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
obs = CSV.read("experiments/observations/cc_discharge_1C.csv", DataFrame)
```

`CSV` and `DataFrames` are in the BattMo Julia env. Prefer them over
shelling out to read files.

## Decision rule

Prefer in order:

1. A **native simulator plotter** that returns a `Figure` (e.g. BattMo
   `plot_dashboard(output; new_window=false)`, Mocca `plot_outlet(case, states, timesteps)`,
   JutulDarcy `plot_co2_inventory(t, inventory)`).
2. **Inline Makie** built against the live result object — probe with `keys(...)` /
   `propertynames(...)`, then draw with `Figure` / `Axis` / `lines!` / `heatmap!`.
3. **Thin helpers** from `plots.jl` when present (JutulDarcy/Fimbul only):
   `well_rates_figure(wd)`, `cell_field_heatmap(g, field)`.

Native plotter > inline Makie > pre-canned helper.

See each simulator's `<sim>-overview` skill for the native plotter name on that stack.

## Interactive opt-in

Only when the user asks for an interactive viewer:

```julia
using GLMakie
plot_well_results(wd, resolution = (800, 500))  # opens a window; not in transcript
```

Interactive plots are not captured as artifacts unless the user also requests a static
`julia_plot`.

## Performance

- **Do not re-run full simulations inside `julia_plot`** if the REPL already has
  `t`, `V`, and observed arrays from a recent `julia_eval`. Build the figure from
  cached vectors instead — plotting should take seconds, not minutes.
- Reuse `slot=` for comparison plots you refresh during calibration.
