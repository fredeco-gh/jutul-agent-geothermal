# The agent's filesystem

The agent sees one virtual filesystem and touches it only through the file
tools (`read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`) and
`execute`. Underneath it is a deepagents `CompositeBackend`: a default
backend plus prefix routes, each backed by its own backend with its own
root and write policy. A path goes to the longest matching route;
everything else falls through to the workspace. Assembled in
`agent/builder.py:build_backend`.

| Route | Backing | Access | Contents |
|---|---|---|---|
| `/` (default) | workspace shell backend | read/write + shell | the user's workspace (the launch directory) |
| `/skills/shared/`, `/skills/simulator/` | filesystem | read | skill markdown |
| `/memory/` | filesystem | read/write | the workspace's agent memory |
| `/session/` | filesystem | read | live session state |
| `/packages/<Pkg>/` | packages backend | read (write for dev checkouts) | source of every package in the Julia env |
| `/dirs/<name>/` | filesystem | read/write | folders mounted with `--add-dir` / `/add-dir` |

Why a virtual tree at all: it co-locates things that live in very different
places on disk (the workspace, the Julia depot, skill markdown shipped in
the package, per-user state) under one small, legible namespace, with each
route keeping its own real location and write policy. The agent works
inside a known tree instead of roaming the host filesystem.

## Paths in the workspace

The workspace route has one deliberate deviation from a naive virtual
filesystem. The agent constantly encounters real absolute paths: from
`pwd()`, from Julia stack traces, from earlier tool output. A stock virtual
backend would re-root `/home/user/ws/model.jl` into a phantom
`<ws>/home/user/ws/model.jl`: the write "succeeds", Julia cannot see the
file, and the agent loops on "No such file". jutul-agent's workspace
backend recognizes absolute paths that point inside the workspace (or any
mounted folder) and resolves them to the real file, so the file tools,
`execute`, and the Julia REPL always agree on what a path means.

The conventions the agent is taught (and the prompt enforces):

- Workspace files are plain relative paths: `model.jl`,
  `experiments/foo.csv`. The same string works in the file tools, in
  `execute`, and in Julia's `include`.
- Leading-slash paths are reserved for the mounts (`/skills/...`,
  `/packages/...`, `/memory/...`, `/dirs/...`). There is no `/workspace/`
  prefix.
- For an added folder, the `/dirs/<name>/` route serves the file tools,
  while in `julia_eval` and `execute` the agent uses the folder's real
  absolute path.

`include("file.jl")` inside `julia_eval` resolves from the workspace
because the kernel rewrites top-level relative includes against its working
directory (see [the Julia kernel](julia-kernel.md)).

## The packages route

`/packages/` is dynamic and environment-scoped: every package the active
Julia env resolves gets a `/packages/<Name>/` mount of its source. Registry
installs are read-only. A `Pkg.develop` checkout (from
`init --source-path`) is writable, so the agent can edit the simulator
package itself. After each `julia_eval` the mounts are refreshed, so a
package the agent just added with `Pkg.add` becomes browsable immediately.

This is what backs the "read the real source" workflow: instead of
guessing an API from training data, the agent greps and reads the installed
version under `/packages/<Pkg>/`, including its `examples/`.
