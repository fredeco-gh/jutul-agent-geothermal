---
name: workspace-and-source
description: Workspace file layout, when to write a file vs. evaluate in the REPL, and how to search installed simulator source
---

# Workspace and source files

## Where you are working

You are running in the user's *workspace* — their current working directory.
Treat it like a project: read, write, and execute files here freely. The
workspace owns its Julia environment under `.jutul-agent/julia-env/` (or the
user's own `Project.toml` at the workspace root).

Sessions, traces, and artifacts live *outside* the workspace under the
user's state home (`$XDG_DATA_HOME/jutul-agent/workspaces/<hash>/`). Don't
write transcripts or logs into the workspace.

## Virtual paths vs Julia paths

File tools (`read_file`, `write_file`, `glob`, `ls`) use a **virtual**
filesystem rooted at the workspace. Paths may appear with a leading slash
(e.g. `/experiments/data.csv` or `experiments/data.csv`) — both refer to
the same workspace file.

**Julia and shell code run on the real filesystem.** In `julia_eval`,
`julia_plot`, and `execute`, use **workspace-relative paths without a
leading slash**:

```julia
CSV.read("experiments/observations/data.csv", DataFrame)
include("candidate.jl")
```

Do **not** pass virtual paths like `"/experiments/..."` to Julia — that
looks for a directory at the machine root and will fail.

To list workspace files, use `glob("**/*")` or `ls` with `"."` or a
relative path like `"experiments"`, not `"/workspace"`.

## When to write a file vs. evaluate in the REPL

- **Real implementation → real file.** If the user is asking you to build
  something (a simulation script, a setup function, a case definition),
  use `write_file` / `edit_file` to create a `.jl` (or `.py`, `.md`, …)
  file in the workspace. The user can then open it in their editor,
  inspect it, edit it, and run it. Iterate via `edit_file` diffs, not
  by regenerating the whole thing in chat.

- **Quick probe → REPL.** Tiny one-offs (`@doc`, `methods`, "what fields
  does this struct have?", "what does this return for a small input?")
  belong in `julia_eval`. Don't litter the workspace with one-liners.

- **Pattern for running a file you just wrote:** write the file, then
  load it into the REPL with `julia_eval('include("solve.jl")')`. The
  REPL keeps state across calls, so you can iterate on the file and
  re-`include` it without paying the package-load cost again.

## Reading installed package source and examples

The simulator's source — and the Jutul-stack packages it builds on — is
mounted **read-only under `/packages/<Package>/`**, one route per package,
each pointing where `pkgdir(<Package>)` does. The route is named by the Julia
package (e.g. `/packages/Sim1/`, `/packages/Sim2/`, `/packages/Jutul/`),
so it's the same whether the package is a registry install or your own
`Pkg.develop` checkout. `ls("/packages/")` lists what's mounted this session.
Browse them with the ordinary file tools, exactly like workspace files:

```text
glob("/packages/Sim/examples/**/*.jl")        # discover examples
read_file("/packages/Sim/examples/.../wells_intro.jl")
grep("setup_well", path="/packages/Sim/src")  # find API uses
```

A simulator built on another package mounts both,
so you can read the base package's examples for primitives the simulator reuses.

Use these to learn the real API from worked examples and from the source.
They are **reference only** — don't try to `edit_file` under `/packages/`
(registry installs are shared across projects). To change a package itself,
`Pkg.develop` it (see below); then its `/packages/<Package>/` route becomes
your writable checkout.

For exact signatures and docstrings, stay in the REPL — these read the
installed version directly and are always current:

```julia
# julia_eval
@doc some_function             # docstring
methods(solve)                 # available methods
names(SimulatorPackage)        # exported names of the active simulator's package
```

Rule of thumb: **`/packages/<Package>/` for examples and source you want to
read or grep; `@doc` / `methods` / `names` in `julia_eval` for precise API.**
You should never need to pass an absolute host path to a file tool.

If `.jutul-agent/config.toml` sets a `source_path` for the simulator, its
primary package is `Pkg.develop`-ed there, so that package's
`/packages/<Package>/` route is the checkout and is **writable** — you can
`edit_file` it to modify the library, then re-`include` to test.

## Workspace already has its own Project.toml?

If the user's workspace has a `Project.toml` at the root, that's the
Julia env you use — not `.jutul-agent/julia-env/`. The user owns it.
`Pkg.add`/`Pkg.develop` modifies *their* env; don't do that without
asking.
