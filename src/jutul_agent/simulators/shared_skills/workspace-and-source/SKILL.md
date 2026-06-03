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

Julia stack traces print **full absolute paths**. To open one with a file
tool, map it back: a workspace file (`.../<workspace>/model.jl`) opens at that
same path or just `model.jl`, and a package file
(`.../.julia/packages/<Package>/<hash>/src/foo.jl`) is browsable at
`/packages/<Package>/src/foo.jl`.

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

Every package the environment resolves — the simulator, the Jutul-stack
packages it builds on, their dependencies, and anything you `Pkg.add` — is
browsable **under `/packages/<Package>/`**, each pointing where
`pkgdir(<Package>)` does. The route is the Julia package name (e.g.
`/packages/<Package>/`, `/packages/Jutul/`), matching where Julia keeps it on
disk. Navigate straight to a package by name; `ls("/packages/")` lists them all
if you need to discover one. Browse with the ordinary file tools, like workspace
files:

```text
glob("/packages/<Package>/examples/**/*.jl")     # discover examples
read_file("/packages/<Package>/examples/.../example.jl")
grep("setup_well", path="/packages/<Package>/src")  # find API uses
```

A package you install mid-session shows up here too, so after `Pkg.add(...)`
you can read its source and examples the same way.

Use these to learn the real API from worked examples and source. Registry
installs are **read-only** — don't `edit_file` under `/packages/` (they're
shared across projects). To change a package itself, `Pkg.develop` it (see
below); its `/packages/<Package>/` route is then your writable checkout.

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
