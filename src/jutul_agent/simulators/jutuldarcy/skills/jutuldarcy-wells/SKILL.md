---
name: jutuldarcy-wells
description: Construct wells, controls, and forces for JutulDarcy reservoir simulations
---

# Setting up wells

## When to use

Use this skill when the task involves injectors, producers, perforations, controls, or well outputs.

A complete well setup has three parts: a well object, a control, and forces
that bind them into the simulation.

## 1. Well object

`setup_vertical_well` perforates every layer at column `(i, j)`:

```julia
Prod = setup_vertical_well(domain, 1, 1, name = :Producer)
```

`setup_well` takes an explicit perforation list as cell indices or logical
tuples:

```julia
Inj = setup_well(domain, [(nx, ny, 1)], name = :Injector)
```

Pass wells to `setup_reservoir_model(domain, sys; wells = [Inj, Prod])`. The
returned model is a `MultiModel` containing a submodel per well plus a
facility submodel that owns the controls.

## 2. Controls

A control pairs a target with a kind:

```julia
Darcy, bar, kg, meter, day = si_units(:darcy, :bar, :kilogram, :meter, :day)

# Injector: total rate, gas-only mass fractions, surface density
rate_target = TotalRateTarget(inj_rate)
I_ctrl      = InjectorControl(rate_target, [0.0, 1.0], density = rhoGS)

# Producer: bottom-hole pressure
bhp_target  = BottomHolePressureTarget(50 * bar)
P_ctrl      = ProducerControl(bhp_target)
```

Other targets exist (`SurfaceVolumeTarget`, `SurfaceLiquidRateTarget`, ...).
Confirm the constructor for your installed version with `@doc <TargetName>`.

## 3. Forces

```julia
controls = Dict(:Injector => I_ctrl, :Producer => P_ctrl)
forces   = setup_reservoir_forces(model, control = controls)
```

`forces` can be one value applied to every step or a `Vector` of length
`length(dt)` for time-varying control.

## 4. Simulate and inspect

```julia
state0 = setup_reservoir_state(model, Pressure = 150 * bar, Saturations = [1.0, 0.0])
dt     = repeat([30.0] * day, 60)
wd, states, t = simulate_reservoir(state0, model, dt; parameters = parameters, forces = forces)

keys(wd[:Producer])      # what channels are available
wd[:Producer][:bhp]      # BHP per step
wd[:Producer][:rate]     # total rate
```

## Canonical example

For a worked end-to-end version, locate and read the wells intro:

```bash
SRC=$(julia --project=.jutul-agent/julia-env --startup-file=no -e 'using JutulDarcy; print(pkgdir(JutulDarcy))')
fd wells_intro "$SRC/examples"      # or: find "$SRC/examples" -name 'wells_intro*'
cat "$SRC/examples/introduction/wells_intro.jl"
```