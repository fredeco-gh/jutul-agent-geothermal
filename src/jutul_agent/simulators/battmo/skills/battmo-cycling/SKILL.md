---
name: battmo-cycling
description: Choose and customize BattMo cell parameter sets and cycling protocols
---

# Cycling protocols and cell parameters

## When to use

Use this skill when the task is about default parameter sets, custom cell parameters, or cycling protocols.

Parameter sets and cycling protocols are first-class inputs in BattMo. They
are loaded by name from curated default sets, or constructed by editing a
loaded set.

## Cell parameters

```julia
cell_parameters = load_cell_parameters(; from_default_set = "chen_2020")
```

To enumerate other default sets that ship with your installed version,
search the installed source with the file tools (its path is given to you up front):

```text
grep("from_default_set", path="/.../BattMo/src")
read_file("/.../BattMo/examples/beginner_tutorials/5_create_parameter_sets.jl")
```

Edit a loaded parameter set as a dictionary-like structure before passing it
to `Simulation`.

## Cycling protocols

```julia
cycling_protocol = load_cycling_protocol(; from_default_set = "cc_discharge")
```

Common defaults include constant-current discharge and CC/CV cycles. The
tutorial in `examples/beginner_tutorials/7_handle_cycling_protocols.jl`
walks through composing and customising protocols.

## Common task to reference mapping

| Task | Reference example |
| --- | --- |
| Minimal CC discharge | `examples/beginner_tutorials/2_run_a_simulation.jl` |
| Inspect or plot outputs | `examples/beginner_tutorials/3_handle_outputs.jl` |
| Choose a different model | `examples/beginner_tutorials/4_select_a_model.jl` |
| Edit cell parameters | `examples/beginner_tutorials/6_handle_cell_parameters.jl` |
| Custom cycling protocol | `examples/beginner_tutorials/7_handle_cycling_protocols.jl` |
| Compute KPIs | `examples/beginner_tutorials/8_compute_cell_kpis.jl` |
| Grid or time resolution | `examples/beginner_tutorials/10_handling_grid_time_resolution.jl` |
| Solver settings | `examples/beginner_tutorials/11_handling_solver_settings.jl` |
| 3D, cylindrical, or pouch | `examples/example_3D_cylindrical.jl`, `example_3D_pouch.jl` |
| MATLAB input | `examples/example_battery.jl` |

These paths are correct for the version shipped at the time of writing; if
a file is not where the table says, list the directory via the shell
(`ls "$SRC/examples"`) to find the current layout.