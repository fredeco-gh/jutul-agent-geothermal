# simulators/

One folder per simulator that jutul-agent knows about. Each folder is
self-contained:

```
simulators/<name>/
  adapter.py          # the SimulatorAdapter instance, exported from __init__.py
  julia_env/          # Project.toml (+ optional Manifest.toml, plots.jl)
  skills/             # one sub-folder per skill, each with a SKILL.md
```

`shared_skills/` holds skill markdown loaded for every session regardless
of the active simulator.

## Adding a new simulator

1. Create `simulators/<name>/`.
2. Write `adapter.py` exporting a `SimulatorAdapter`. Set
   `module_dir = Path(__file__).resolve().parent` — the base class derives
   `julia_env_template_path`, `skills_dir`, and `plot_helpers_path` from
   that.
3. Add `julia_env/Project.toml` with the deps the agent should be able to
   `using`. The kernel needs no special dep (its server is stdlib-only). Copy the
   bundled `JutulAgent/` package from an existing env (with its `[deps]` and
   `[sources]` entries) so the env ships the agent's Julia runtime (figure capture,
   ensemble helpers, plotting warm-up). A new simulator can also get a per-sim
   precompile extension in `JutulAgent/ext/` — see
   `docs/design/warmup-and-jutulagent-package.md`. Pin a `Manifest.toml` alongside
   when the dep graph needs locking (e.g. Makie version pins).
4. Optionally add a `julia_env/plots.jl` with thin Makie helpers — the
   adapter picks it up automatically; the agent loads it on the first
   `julia_plot` call.
5. Add at least one skill at `skills/<name>-overview/SKILL.md`.
6. Register the adapter in `simulators/registry.py`.

## Bootstrapping a workspace

`jutul-agent` copies `julia_env/` into `<workspace>/.jutul-agent/julia-env/`
on first use. To force a refresh after updating the template:

```sh
uv run jutul-agent init --sim <name> --force --precompile
```

To dev-link the simulator package against a local checkout:

```sh
uv run jutul-agent init --sim <name> --source-path /path/to/<Package>.jl
```
