---
name: fimbul-overview
description: High-level Fimbul workflow, geothermal case factories, and result inspection
---

# Fimbul orientation

## When to use

Use this skill for any geothermal task on Fimbul — aquifer or borehole
thermal energy storage (ATES, BTES, FTES, HTATES), conventional and
enhanced geothermal systems (doublet, EGS, AGS, closed-loop coaxial BHE),
or analytical sanity checks.

## Mental model

Fimbul extends JutulDarcy with an energy-conservation equation that
transports heat by advection and conduction. A Fimbul simulation is
*structurally* a JutulDarcy reservoir simulation with a temperature
field, so JutulDarcy's primitives (grids, `reservoir_domain`, wells,
`simulate_reservoir`) carry over unchanged.

The simplest entry point is a **case factory** — a function in Fimbul
that returns a `JutulCase` for a named example geometry:

```julia
using Fimbul, JutulDarcy
case = egg_geothermal_doublet()        # case object
result = simulate_reservoir(case)      # run it
T = result.states[end][:Temperature]   # final-state temperature field
```

When you need a custom case, drop down to JutulDarcy primitives and add
geothermal physics through the same Fimbul/JutulDarcy API surface.

## Finding what you need

Fimbul's source is mounted read-only at `/simulator/`; browse it with the
file tools (see the `workspace-and-source` skill):

```text
glob("/simulator/examples/**/*.jl")              # analytical / production / storage
grep("function egg_geothermal", path="/simulator/src")   # a case factory's source
read_file("/simulator/examples/production/doublet_demo.jl")
```

For docstrings, stay in the REPL: `julia_eval("@doc egg_geothermal_doublet")`.

## Result inspection

Fimbul cases return JutulDarcy result objects. The key extra field is
`:Temperature` on each state:

```julia
states = result.states
T_end = states[end][:Temperature]            # temperature at the final step
T_at_cell = [s[:Temperature][cell] for s in states]   # series at one cell
```

Well data (`result.wells`) and reservoir states follow the same
conventions as JutulDarcy. See `jutuldarcy-overview` for result unpacking
and `jutuldarcy-wells` for well construction details that apply here too.

## Plotting

Headless plotting: `julia_plot` with `well_rates_figure(wd)` /
`cell_field_heatmap(g, field)` from `plots.jl`, or inline Makie against the live
result object (probe `keys` / `propertynames` first). For interactive reservoir
viewing, `plot_reservoir(case, result.states; key = :Temperature, …)` requires
GLMakie — opt-in only.
