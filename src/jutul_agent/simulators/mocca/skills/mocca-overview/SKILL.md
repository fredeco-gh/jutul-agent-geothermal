---
name: mocca-overview
description: High-level Mocca workflow for adsorption-based CO2 capture simulations
---

# Mocca orientation

## When to use

Use this skill for any adsorption-based CO2 capture task on Mocca —
direct column breakthrough (DCB), pressure / vacuum / temperature swing
adsorption cycles (PSA / VSA / TSA), parameter optimization, or
history matching against measured breakthrough data.

## Mental model

A Mocca simulation has three composable layers:

1. **Inputs** — physical and operational parameters. Mocca reads them
   from a JSON file via `parse_input`. Reference inputs ship in
   `joinpath(pkgdir(Mocca), "..", "models", "json")`.
2. **Case** — `setup_mocca_case(constants, info)` builds the case object
   and a default time-step selector configuration.
3. **Simulate** — `simulate_process(case; timestep_selector_cfg, output_substates)`
   returns `(states, timesteps)`.

A typical run:

```julia
using Mocca
json_dir = joinpath(dirname(pathof(Mocca)), "../models/json/")
filepath = joinpath(json_dir, "dcb_haghpanah_2013_co2_n2_input_simple.json")
(constants, info) = Mocca.parse_input(filepath)
case, ts_config = Mocca.setup_mocca_case(constants, info)
states, timesteps = Mocca.simulate_process(
    case;
    timestep_selector_cfg = ts_config,
    output_substates = true,
    info_level = 0,
)
```

For custom physics, build the JSON-equivalent dictionaries in Julia and
hand them to `setup_mocca_case` directly — see
`examples/custom_setup_cyclic_vsa.jl` for the pattern.

## Finding what you need

Mocca's source is mounted read-only at `/packages/Mocca/`; browse it with the
file tools:

```text
glob("/packages/Mocca/examples/*.jl")     # dcb_haghpanah, cyclic_vsa_haghpanah, custom_setup, ...
grep("function setup_mocca_case", path="/packages/Mocca/src")
read_file("/packages/Mocca/examples/dcb_haghpanah_2013_co2_n2.jl")   # canonical starting point
```

The reference JSON inputs live *beside* the package (not under `/packages/Mocca/`)
at `joinpath(pkgdir(Mocca), "..", "models", "json")` — get that path in
`julia_eval` and read the files from the REPL.

For docstrings, stay in the REPL: `julia_eval("@doc Mocca.setup_mocca_case")`.

## Result inspection and export

```julia
Mocca.export_cell_results(
    "results.csv", case, states, timesteps; format = "csv",
)
```

## Plotting

Headless plotting: `julia_plot` with `Mocca.plot_outlet(case, states, timesteps)`
(outlet concentrations / breakthrough; returns a CairoMakie `Figure`). Also
`plot_cell`, `plot_state` for other views. Do not call `display(fig)`.

## Notes

- Implemented chemistry today is a 4-stage vacuum swing adsorption (VSA)
  process for CO2 capture from a two-component flue gas, Zeolite 13X
  sorbent, dual-site Langmuir isotherm. Other systems/isotherms are
  planned upstream — verify what is available with
  `julia_eval("methods(Mocca.setup_mocca_case)")` and by listing
  `examples/` before assuming a feature exists.
- The first run in a fresh REPL compiles a substantial dependency
  graph; budget several minutes.
