---
name: battmo-overview
description: High-level BattMo workflow, example discovery, and output inspection
---

# BattMo orientation

## When to use

Use this skill for general BattMo setup, example discovery, and output inspection.

BattMo is a battery simulator on the Jutul AD framework. It models
lithium-ion (and other) cells with coupled electrochemistry, transport, and
optionally thermal effects.

A simulation is four parts you compose in order:

1. **Cell parameters** - physical and geometric description of the cell.
   `load_cell_parameters(; from_default_set = "chen_2020")` gives a curated
   NMC811/Graphite-SiOx cell; other default sets exist via the same loader.
2. **Cycling protocol** - driving signal.
   `load_cycling_protocol(; from_default_set = "cc_discharge")` for constant-
   current discharge; other protocols are loaded the same way.
3. **Model** - `LithiumIonBattery()` for the standard P2D system; specialised
   constructors exist for full-cell, thermal, and 3D variants.
4. **Simulation + solve** -
   `sim = Simulation(model, cell_parameters, cycling_protocol)` performs
   validation; check `sim.is_valid`. Then `output = solve(sim)` runs it.

## Finding what you need

Find example layout and APIs on disk via `pkgdir`; see the
`workspace-and-source` skill for the idiom:

```bash
SRC=$(julia --project=.jutul-agent/julia-env --startup-file=no -e 'using BattMo; print(pkgdir(BattMo))')
ls "$SRC/examples/beginner_tutorials"      # best starting point
rg "load_cell_parameters" "$SRC/src"       # locate APIs and uses
cat "$SRC/examples/beginner_tutorials/2_run_a_simulation.jl"
```

For docstrings, stay in the REPL: `julia_eval("@doc LithiumIonBattery")`.

## Result inspection

```julia
states = output[:states]
t = [s[:Control][:Controller].time      for s in states]
E = [s[:Control][:ElectricPotential][1] for s in states]
I = [s[:Control][:Current][1]           for s in states]
```

## Plotting

**BattMo's built-in plotters (`plot_output`, `plot_dashboard`) are GLMakie-only.**
Under the default headless CairoMakie they emit
`Warning: Independent figure creation not implemented for backend CairoMakie`
and return an **empty `Figure()`** — `julia_plot` will refuse it.

For headless `julia_plot` calls, build the figure inline from `sol.time_series`:

```julia
using CairoMakie
states = sol.time_series
t = [s[:Control][:Controller].time      for s in states]
E = [s[:Control][:ElectricPotential][1] for s in states]

fig = Figure(size = (700, 400))
ax = Axis(fig[1, 1], title = "Voltage vs Time", xlabel = "t [s]", ylabel = "V")
lines!(ax, t, E)
fig
```

Only use `plot_dashboard` / `plot_output` when the user explicitly asks for an
interactive GLMakie window (and they have a display available).

## Inputs from MATLAB

`load_matlab_battmo_input(filename)` reads the MATLAB BattMo `.mat` format
for cross-validation against legacy cases (see `examples/example_battery.jl`
for a reference run).