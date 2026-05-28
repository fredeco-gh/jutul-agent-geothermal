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

Headless plotting: `julia_plot` with `plot_dashboard(output; plot_type="simple", new_window=false)`
or `plot_output(output, vars; new_window=false)`. These return `Figure` via `BattMoMakieExt`
(loaded with CairoMakie). For interactive viewers (`plot_dashboard` with default
`new_window=true`), use GLMakie only when the user explicitly asks.

## Inputs from MATLAB

`load_matlab_battmo_input(filename)` reads the MATLAB BattMo `.mat` format
for cross-validation against legacy cases (see `examples/example_battery.jl`
for a reference run).