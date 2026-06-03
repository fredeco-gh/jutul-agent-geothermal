---
name: julia-and-repl
description: Persistent Julia REPL workflow and live runtime introspection for Jutul-based work
---

# Julia REPL workflow

## When to use

Use this skill whenever a task depends on Julia execution, package APIs, or REPL state.

You drive a single persistent Julia process. Loaded modules, defined values,
and compiled methods persist across turns — pay the load cost once and re-use
the same bindings.

**Always run Julia code through `julia_eval` (or `julia_plot` for figures).**
Never reach for `execute` to spawn `julia`, `julia --project`, `julia -e ...`,
or a shell pipeline that runs Julia: every such call starts a brand-new
process with no shared state, pays the full precompile cost, and the user
has to approve a shell command. `execute` is only for non-Julia shell work
(grep, find, ls, git, …).

## Build incrementally

Construct the smallest piece first, evaluate it, look at the result, then
extend. Do not dump a full script into the REPL and hope.

## Live introspection beats memory

- `@doc f` - docstring.
- `methods(f)` - all method signatures.
- `methodswith(T)` - methods that dispatch on `T`.
- `fieldnames(typeof(x))` - fields of a value.
- `pkgdir(Module)` - package path on disk (each package is also mounted at
  `/packages/<Package>/`).

The installed package is the source of truth. If your training prior says the
API has a function but `methods` finds nothing, trust `methods`. To read
examples or source, browse the read-only `/packages/<Package>/` mounts with the
file tools (`glob`/`grep`/`read_file`).

## Code in your reply

Wrap Julia in fenced blocks. Do not paste REPL prompts. Do not claim a script
works unless you have actually run it.

## When Julia fails

Read the full stack trace. Common fixes:

- **File not found** — you probably used a virtual path (`/experiments/...`).
  Retry with a workspace-relative path (`experiments/...`) or `isfile("...")`
  in the REPL to confirm.
- **Package not found** — confirm with `using Pkg; Pkg.status()`. If a Julia
  standard library already covers the need, prefer it over adding a dependency.
  Otherwise `Pkg.add` it when the task needs it; the added package is then
  browsable under `/packages/<Package>/`.
- **Method/API error** — probe with `@doc`, `methods`, and a smaller snippet
  before retrying the full script.
- **Old version installed, or a just-added package won't precompile** — a
  long-lived env holds shared dependencies at their pinned versions, so a plain
  `Pkg.add` may only fit an old one. Inspect with `Pkg.status(outdated = true)`
  (`⌃`/`⌅` flag held-back packages) and `Pkg.why("Dep")`, then `Pkg.update()` to
  re-resolve the whole env and retry. Only a package still held back after a full
  update is a genuine compatibility limit.
- **A loaded module won't resolve (`PkgId(...) not found`)** — the session's
  loaded modules are out of sync with the env, usually after a mid-session
  package change. Julia can't reload a module from inside the REPL, so this needs
  `reset_julia` (see below).

`reset_julia` restarts Julia with an empty session. It is the right fix when a
module must be reloaded, but it clears **all** state — loaded packages, values,
and results — and recompiles on the next run. Use it deliberately, not as a
default; install the packages you need *before* building up expensive state so a
reset stays cheap.

Do not repeat the same failing expression unchanged.