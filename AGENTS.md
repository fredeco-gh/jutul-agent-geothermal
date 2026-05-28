# jutul-agent

## Purpose

jutul-agent is a Deep Agents–based assistant for Julia scientific simulation
work on the Jutul ecosystem.

## Working rules

- Prefer the live Julia session and simulator source code over model memory.
- Use the persistent Julia REPL incrementally. Run the smallest useful probe
  first, inspect the result, then extend.
- Treat the installed simulator packages as the source of truth for APIs and
  examples.
- Keep Julia execution serialized unless the runtime explicitly supports
  concurrency.
- Prefer Deep Agents memory and skills for reusable guidance; keep custom
  Python focused on Julia execution, simulator inspection, and trace capture.
- Workspace memory layout and stock Deep Agents wiring:
  [docs/design/memory.md](docs/design/memory.md).

## Validation

- Default suite (no Julia): `uv run pytest -q -m "not integration"`
- Integration suite (requires Julia + simulator envs): `uv run pytest -q -m integration`
- Live LLM (humans only, needs API key): `uv run pytest tests/live/`
- Update transcript / report snapshots after renderer changes:
  `uv run pytest --snapshot-update tests/test_transcript_html.py tests/test_transcript.py tests/test_report_renderer.py`
- Python style (matches CI): `uv run ruff check .` then `uv run ruff format .`
- After editing Python, run `uv run ruff format` on touched paths (or rely on
  format-on-save / pre-commit if installed).

See [docs/testing.md](docs/testing.md) for the full testing guide.

## Local git hooks

One-time per clone: `uv run pre-commit install`. Commits then run Ruff format
and check on staged `.py` files. To verify the whole tree like CI:
`uv run pre-commit run --all-files`.

## Important paths

- `src/jutul_agent/paths.py` — the three runtime anchors: `PACKAGE_ROOT`
  (install), `workspace_root()` (CWD), `state_home()` (sessions).
- `src/jutul_agent/workspace.py` — workspace config
  (`.jutul-agent/config.toml`), simulator auto-detect, Julia-env bootstrap.
- `src/jutul_agent/session.py` — `Session`, the unit of work for one
  invocation.
- `src/jutul_agent/agent/builder.py` — deepagents wiring: composite backend,
  HarnessProfile registration, `build_agent` entry point. Custom tools sit
  alongside (`tools.py`, `julia_plot.py` + `julia_plot.jl`, `memory.py`,
  `approval.py`, `turns.py`).
- `src/jutul_agent/simulators/` — adapter dataclass, registry, env bootstrap,
  shared skills, and one folder per simulator (see below).
- `src/jutul_agent/julia/` — `JuliaSession` Protocol in `session.py`; each
  backend is a self-contained sub-package under `backends/` (today just
  `backends/agentrepl/`). The bare AgentREPL env for backend tests lives
  in `agentrepl_env/`.
- `src/jutul_agent/trace/` — SQLite event log and `TraceRecorder` middleware.
- `src/jutul_agent/transcript/` — renderers that consume a trace
  (HTML transcript, markdown transcript, investigation report).
- `src/jutul_agent/interfaces/tui/approval.py` — HITL decision policy and the
  approval card markdown.
- `src/jutul_agent/interfaces/` — `cli` and the Textual `tui` package.
- `tests/` — end-to-end, chat, CLI, and tool coverage. `tests/integration/`
  needs Julia; `tests/live/` needs an LLM provider key.

## Per-simulator layout

Each simulator lives under `src/jutul_agent/simulators/<name>/` and owns
exactly three things:

- `adapter.py` — constructs the `SimulatorAdapter`. Set
  `module_dir = Path(__file__).resolve().parent` so the base class can
  derive `julia_env_template_path`, `skills_dir`, and `plot_helpers_path`.
- `julia_env/` — `Project.toml` (+ optional `Manifest.toml`, `plots.jl`)
  copied into a workspace on bootstrap.
- `skills/<skill-name>/SKILL.md` — markdown skills surfaced via the
  deep-agents skill system.

Add a simulator by creating that folder and one entry in
`simulators/registry.py`. Custom subagent factories, when they land, go on
the adapter's `subagent_factories` tuple.