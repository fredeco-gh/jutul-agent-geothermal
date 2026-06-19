---
name: plotting-basics
description: "How to plot with plot_julia: native plotters, live windows, and seeing your own plots"
---

# Plotting basics

## When to use

Use this skill whenever the user asks for a plot, chart, figure, or visualization,
or when a plot would make simulation results easier to understand.

## The model: `plot_julia` captures whatever you draw

Use `plot_julia` for **anything that produces a figure** — never build a `Figure`
in `run_julia` (that saves no artifact and the user can't see it). `plot_julia`:

- activates the right Makie backend for this session (you don't manage backends),
- evaluates your code, and
- captures the resulting figure to an image file — whether your code **returns** a
  `Figure`, returns a `(fig, ax, plot)` tuple, or calls a native plotter that opens
  a window / calls `display` internally.

So you do **not** need to end on `fig`, and you do **not** need to avoid `display`.
Just call the plotter.

## Prefer native plotters

Call your simulator's own documented plotters first — they are the canonical,
best-looking views, they run on GLMakie, and `plot_julia` captures them
automatically. The `<sim>-overview` skill lists the plotters for your simulator.

Build a `Figure` inline when no native plotter fits, or when you want a specific
custom view:

```julia
fig = Figure(size = (600, 400))
ax = Axis(fig[1, 1], title = "History match", xlabel = "t", ylabel = "rate")
lines!(ax, t, sim); scatter!(ax, t, obs)
fig
```

## Seeing your own plot: `view=true`

Pass `view=true` to get the (downscaled) image back so **you** can look at it —
to verify a curve overlays the data, spot an anomaly, or check a 3D view. Use it
deliberately, not on every plot (each image costs tokens). The user always sees
the saved artifact regardless of `view`.

```text
plot_julia(code="<your plot code>", view=true)   # then reason about what you see
```

## How the user sees a plot

In an interactive session `plot_julia` **opens a live Makie window** for the user,
a real plot window they can rotate, zoom, and step; a PNG is saved too. There's no
separate "interactive" mode, just plot. (Headless and one-shot runs can't show a
window and only save the PNG.)

- `view` is for **you**, not the user — it returns the image to you; it opens
  nothing for them.
- Pass `window=false` only to compute/inspect a plot without opening a window.
- If the user says they can't see a plot, you probably built it in `run_julia`
  (use `plot_julia`) or set `window=false` — fix that, don't just re-describe it.

## Windows: slots, recapture, close

Each plot opens a window keyed by its `slot`:

- **Reuse** a window: the same `slot` refreshes that one window in place — use this
  when iterating so you don't spawn a window per attempt.
- **Separate** windows: give distinct plots distinct slots (`slot="reservoir"`,
  `slot="wells"`) so they open as separate windows you can address individually.
- **Recapture** after the user rotates/zooms/steps a window:
  `recapture_plot(slot="reservoir")` re-renders that plot's figure at its current
  state and returns the image. Omit `slot` for the most recent. It renders the
  figure jutul-agent still holds, so it works even if the user closed the window
  (you get its last state); only `close_plots` discards it. You can't advance the
  timestep yourself — ask the user to step the window, then recapture.
- **Close** windows with `close_plots(slot="reservoir")` (one) or `close_plots()` (all).

## Diagnostics & model structure

- **Solver performance/convergence**: build these **inline** from the result's
  reports (the native `plot_solve_breakdown`/`plot_cumulative_solve` family is
  finicky about argument types — prefer this). `reports = result.result.reports`,
  then per report step `r`: `length(r[:ministeps])`, `r[:total_time]`, and per
  ministep `m`: `m[:linear_iterations]`, `m[:convergence_time]`. Plot vs report
  step with `Figure`/`Axis`/`lines!` through `plot_julia`.
- **Model structure** (Jutul-based simulators): the dependency graph is drawn by a
  Jutul package extension that only activates once the GraphMakie stack is loaded.
  Load all three first, in the same `plot_julia` call, then call the plotter:
  ```julia
  using GraphMakie, NetworkLayout, LayeredLayouts
  plot_variable_graph(reservoir_model(model))   # per-variable dependencies
  # or: plot_model_graph(model)
  ```
  If it errors with "no method matching plot_variable_graph", the extension hasn't
  loaded yet — re-run the `using` line and the plotter together in one call.

## Sizing and slots

- Output is **PNG**. `size=(width, height)` sets a specific resolution.
- `slot="name"` overwrites the same artifact path when refreshing a comparison
  during calibration (e.g. `slot="saturation_final"`).

## Loading tabular data

```julia
using CSV, DataFrames
obs = CSV.read("experiments/observations/data.csv", DataFrame)   # workspace-relative, no leading slash
```

## Performance

- **Do not re-run a full simulation inside `plot_julia`** if the REPL already holds
  the result/arrays from a recent `run_julia` — plot from the cached objects.
  Plotting should take seconds, not minutes.
- Reuse `slot=` for comparison plots you refresh during calibration.
