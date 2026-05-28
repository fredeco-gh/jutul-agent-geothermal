---
name: vocsim-overview
description: Placeholder for VOCSim — package not yet released; explains current limitations
---

# VOCSim orientation (placeholder)

## When to use

Use this skill only to answer "what is VOCSim and what can the agent do
with it right now?" The `vocsim` simulator slot is wired up so workspaces
can be initialised under `--sim vocsim`, but the underlying Julia package
is not yet released.

## Status

VOCSim is a Jutul-based simulator under development at SINTEF (VOCSimPRO
project) for methane and volatile organic-compound emissions during the
storage and handling of hydrocarbons — mass transfer between liquid and
vapor phases with thermodynamic and transport closures for flashing,
dissolution, and volatilization.

**The Julia package is not registered yet.** Until it ships:

- The `vocsim` workspace env contains only `Jutul`, `AgentREPL`, and
  `CairoMakie`. There is no `VOCSim` package to `using`.
- No domain-specific tools, plotting helpers, or example corpus exist
  for the agent to draw on.
- Domain knowledge in the agent's prompt is intentionally minimal so
  the model does not fabricate APIs.

## What you can do right now

- Confirm the env boots: `julia_eval("using Jutul; @info \"ok\"")`.
- Prototype generic Jutul finite-volume scaffolding the agent might
  reuse once VOCSim ships (mesh construction, Jutul model assembly).
- Help draft the workflow the user wants once the package is available
  — but do not invent VOCSim API names; ask the user instead.

## When the package ships

The owner of jutul-agent will:

1. Add `VOCSim` to `simulators/vocsim/julia_env/Project.toml`.
2. Update `simulators/vocsim/adapter.py` (`package_imports`,
   `primary_package`, `domain_hints`).
3. Replace this skill with a real `vocsim-overview` and add topic
   skills as the four-question test (see `docs/design/skill-authoring.md`)
   warrants.
