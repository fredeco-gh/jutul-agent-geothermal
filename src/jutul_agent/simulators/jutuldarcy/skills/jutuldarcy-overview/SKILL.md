---
name: jutuldarcy-overview
description: High-level JutulDarcy workflow, example discovery, and result unpacking
---

# JutulDarcy orientation

## When to use

Use this skill for general JutulDarcy setup, example discovery, and result inspection.

JutulDarcy is a reservoir simulator on the Jutul AD framework. A simulation is
five layers that you compose in order:

1. **Grid** - `CartesianMesh(dims, physical_dims)` for structured cases.
   Unstructured grids come from `UnstructuredMesh` or `.DATA`/MRST imports.
2. **Domain** - `reservoir_domain(grid; permeability=K, porosity=ϕ)` attaches
   petrophysics. SI units throughout: `Darcy = si_units(:darcy)`.
3. **Wells** - `setup_vertical_well(domain, i, j; name=:P)` or
   `setup_well(domain, [(i,j,k), ...]; name=:I)`. Pass via `wells=[...]` to
   `setup_reservoir_model`.
4. **Fluid system** - `ImmiscibleSystem`, `BlackOilSystem`,
   `CompositionalSystem`. Pick the smallest system that captures the physics.
5. **Model + run** - `setup_reservoir_model(domain, sys; wells=...)` ->
   `setup_reservoir_state(...)` -> controls + forces -> `simulate_reservoir`.

## Finding what you need

Example layout and APIs change between versions — find them on disk rather
than guessing. The installed package source is reachable from the shell via
`pkgdir`. See the `workspace-and-source` skill for the idiom:

```bash
SRC=$(julia --project=.jutul-agent/julia-env --startup-file=no -e 'using JutulDarcy; print(pkgdir(JutulDarcy))')
ls "$SRC/examples"                              # discover layout
rg "setup_well" "$SRC/src"                      # find an API
cat "$SRC/examples/introduction/wells_intro.jl" # read a candidate file
```

For docstrings, stay in the REPL: `julia_eval("@doc setup_reservoir_model")`.

For idiomatic "how do I do X" patterns, the examples directory is the
authoritative reference. `setup_well` and `setup_vertical_well` are the
recommended well constructors.

## Result unpacking

```julia
result = simulate_reservoir(state0, model, dt; parameters, forces)
wd, states, t = result   # well data, reservoir states, time vector
```

Well outputs are indexed by name: `wd[:Producer][:bhp]`, `wd[:Producer][:rate]`,
etc. `keys(wd[:Producer])` lists what is available.

## Plotting

Headless plotting: `julia_plot` with `well_rates_figure(wd)` /
`cell_field_heatmap(g, field)` from `plots.jl`, `plot_co2_inventory(t, inv)` (Makie
ext, reachable headlessly), or inline Makie. Interactive viewers (`plot_well_results`,
`plot_reservoir`) require GLMakie and are opt-in.