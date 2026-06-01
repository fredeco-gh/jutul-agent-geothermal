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
   validation; check `sim.is_valid`. Then `sol = solve(sim)` runs it.
   `solve` is expensive (a full simulation): bind `sol = solve(sim)` **once**
   and reuse `sol` in later `julia_eval` / `julia_plot` calls — the REPL keeps
   it. Do not re-run `solve` just to inspect or plot the result.

## Finding what you need

BattMo's source is mounted read-only at `/packages/BattMo/` — browse it with the
file tools (see the `workspace-and-source` skill):

```text
glob("/packages/BattMo/examples/beginner_tutorials/*.jl")    # best starting point
grep("load_cell_parameters", path="/packages/BattMo/src")     # locate APIs and uses
read_file("/packages/BattMo/examples/beginner_tutorials/2_run_a_simulation.jl")
```

For docstrings, stay in the REPL: `julia_eval("@doc LithiumIonBattery")`.

## Result inspection

`solve` returns a `SimulationOutput`. Its `time_series` field is a
**`Dict{String, Any}` mapping each output variable to a `Vector` over the
report steps** — not a list of per-timestep state objects. Index it by
variable name; never iterate it or index it with an integer.

```julia
sol = solve(sim)               # SimulationOutput
ts  = sol.time_series          # Dict{String,Any}: variable name => Vector over steps
keys(ts)                       # discover what's available before assuming names
t = Float64.(ts["Time"])       # seconds
V = Float64.(ts["Voltage"])    # cell voltage
I = Float64.(ts["Current"])    # cell current
```

The vectors can be `Vector{Any}`, so wrap with `Float64.(…)` before plotting
or doing arithmetic. If a key you expect is missing, call `keys(ts)` and use
what's actually there. `sol` has no `keys`/`getindex` of its own — go through
`sol.time_series`.

## Plotting

**The BattMo example files `using ... GLMakie`, but GLMakie is NOT installed
here — only CairoMakie is.** When you adapt an example for `julia_plot`, drop
`GLMakie` and `using CairoMakie` instead, or the call fails with "Package
GLMakie not found".

**BattMo's built-in plotters (`plot_output`, `plot_dashboard`) are GLMakie-only.**
Under the default headless CairoMakie they emit
`Warning: Independent figure creation not implemented for backend CairoMakie`
and return an **empty `Figure()`** — `julia_plot` will refuse it.

For headless `julia_plot` calls, build the figure inline from the
`sol.time_series` vectors. Reuse the `sol` you already solved in a previous
`julia_eval` — `julia_plot` shares the same REPL, so there's no need to
re-`solve` inside the plot:

```julia
using CairoMakie
ts = sol.time_series
fig = Figure(size = (700, 400))
ax = Axis(fig[1, 1], title = "Voltage vs time", xlabel = "Time [s]", ylabel = "Voltage [V]")
lines!(ax, Float64.(ts["Time"]), Float64.(ts["Voltage"]))
fig
```

Only use `plot_dashboard` / `plot_output` when the user explicitly asks for an
interactive GLMakie window (and they have a display available).

## Inputs from MATLAB

`load_matlab_battmo_input(filename)` reads the MATLAB BattMo `.mat` format
for cross-validation against legacy cases (see `examples/example_battery.jl`
for a reference run).