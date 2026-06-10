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
than guessing. The installed source is mounted read-only at `/packages/JutulDarcy/`;
browse it with the file tools (see the `workspace-and-source` skill):

```text
glob("/packages/JutulDarcy/examples/**/*.jl")                 # discover layout
grep("setup_well", path="/packages/JutulDarcy/src")            # find an API
read_file("/packages/JutulDarcy/examples/introduction/wells_intro.jl")
```

For docstrings, stay in the REPL: `julia_eval("@doc setup_reservoir_model")`.

For idiomatic "how do I do X" patterns, the examples directory is the
authoritative reference. `setup_well` and `setup_vertical_well` are the
recommended well constructors.

Industry-standard `.DATA` decks run through `setup_case_from_data_file`;
the classic SPE benchmark decks ship with GeoEnergyIO's test data:

```julia
pth = GeoEnergyIO.test_input_file_path("SPE1", "SPE1.DATA")
case = setup_case_from_data_file(pth)
result = simulate_reservoir(case)
```

## Result unpacking

```julia
result = simulate_reservoir(state0, model, dt; parameters, forces)
wd, states, t = result   # well data, reservoir states, time vector
```

Well outputs are indexed by name: `wd[:Producer][:bhp]`, `wd[:Producer][:rate]`,
etc. `keys(wd[:Producer])` lists what is available.

## Plotting

Use the **native plotters** through `julia_plot` — they run on GLMakie (the
default backend) and are captured to an image automatically, headless or not:

- `plot_reservoir(model)` — 3D reservoir mesh + well trajectories
- `plot_reservoir(model, states[end])` — a state colored on the 3D mesh. Pass the
  whole state dict, or a per-cell **vector** like `states[end][:Saturations][2, :]`
  — not a scalar slice, which raises "No plottable properties found".
- `plot_well_results(wd)` — well rate / BHP dashboard
- `plot_cell_data(physical_representation(domain), field)` — a scalar field on the mesh
- `plot_co2_inventory(t, inv)` — CO2 inventory over time (2D)
- `plot_model_graph(model)` / `plot_variable_graph(reservoir_model(model))` —
  model / variable dependency graphs. These live in a Jutul package **extension**,
  so run `using GraphMakie, NetworkLayout, LayeredLayouts` first to activate them
  (the packages are already in the env). Use the real plotter; don't hand-draw a
  graph.

Just call them — no backend juggling, no need to return a `Figure`. In an
interactive session a live window opens for the user by default (`window=false` to
suppress); pass `view=true` to inspect a plot yourself.

**Plot from the live REPL bindings.** Your run already left `model`, `states`,
`wd` in the REPL — call the plotter straight on them. Do **not** rebuild the case
and re-run `simulate_reservoir` inside `julia_plot`; that re-simulates on every
plot. Re-run only if you changed the setup.

For a **chrome-free static artifact** (3D field + wells without `plot_reservoir`'s
GUI menus), compose the native pieces into a plain `Axis3`. Note `plot_well!` wants
the `Axis3`'s `scene` in this non-GUI path:

```julia
rmodel = reservoir_model(model)
g = physical_representation(rmodel.data_domain)
fig = Figure(size = (900, 600))
ax = Axis3(fig[1, 1]; zreversed = true, title = "Reservoir")
plt = plot_cell_data!(ax, g, collect(rmodel.data_domain[:porosity]); colormap = :viridis)
Colorbar(fig[1, 2], plt)
for (_, m) in pairs(model.models)              # overlay wells (MultiModel)
    w = physical_representation(m.data_domain)
    w isa WellDomain && plot_well!(ax.scene, g, w)
end
fig
```