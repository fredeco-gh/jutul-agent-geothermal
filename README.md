# jutul-agent

A scientific AI assistant for AD-enabled simulators on the
[Jutul](https://github.com/sintefmath/Jutul.jl) framework. Drive
[JutulDarcy](https://github.com/sintefmath/JutulDarcy.jl),
[BattMo](https://github.com/BattMoTeam/BattMo.jl), and other Jutul-based
simulators from a terminal TUI — the agent runs Julia in a persistent REPL,
reads the actual package source on disk, writes implementation files into
your workspace, and keeps a per-session trace.

## Install

Requirements: Python 3.12+, Julia 1.10+.

```sh
git clone <this-repo> && cd jutul-agent
uv sync
```

Put a provider key in a project-local `.env`:

```
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...
```

## Use it in any folder

`jutul-agent` runs in the directory you invoke it from — that directory is
your *workspace*. Initialise once:

```sh
cd ~/my-reservoir-study
uv run jutul-agent init --sim jutuldarcy
```

This writes `.jutul-agent/config.toml` and copies a Julia env template
into `.jutul-agent/julia-env/`. To dev against a local checkout of the
simulator package instead of the registered version:

```sh
uv run jutul-agent init --sim jutuldarcy --source-path /path/to/JutulDarcy.jl
```

If you skip `init`, the first turn auto-bootstraps. Auto-detection picks the
simulator from a `Project.toml` in the workspace when it can.

`setup` is an alias for `init`. Use `--precompile` (or `--instantiate`) to run
`Pkg.instantiate` and warm up plotting; use `--force` to replace an existing
`.jutul-agent/julia-env/` after upgrading jutul-agent.

## TUI

```sh
uv run jutul-agent
```

Inside the TUI:

| Command           | Effect                                              |
|-------------------|-----------------------------------------------------|
| `/transcript`     | Write the session transcript to disk (HTML).        |
| `/transcript md`  | Same, as markdown.                                  |
| `/clear`          | Clear the visible log and restore the welcome card. |
| `/approval-mode`  | Set approval policy: `ask`, `workspace`, `auto`.    |
| `/help`           | List commands.                                      |
| `/quit`           | Exit (also `Ctrl+D`).                               |

Keyboard:

| Key          | Effect                                                |
|--------------|-------------------------------------------------------|
| `Ctrl+G`     | Cancel the in-flight turn (resets Julia if needed).   |
| `Ctrl+L`     | Clear the visible log.                                |
| `Ctrl+O`     | Toggle the latest tool block between preview / full.  |
| `Shift+Tab`  | Cycle approval mode.                                  |
| `Ctrl+P`/`↑` | Previous history entry.                               |

For a one-shot answer without entering the TUI:

```sh
uv run jutul-agent --sim battmo "Set up a constant-current discharge run."
```

## Transcripts

Every session writes an event log to
`$XDG_DATA_HOME/jutul-agent/workspaces/<hash>/sessions/<id>/trace.sqlite`.
Render the most recent one:

```sh
uv run jutul-agent transcript            # last session in this workspace (HTML)
uv run jutul-agent transcript <id>       # specific session
uv run jutul-agent transcript --format markdown
uv run jutul-agent transcript --bundle   # also writes transcript-bundle.zip
```

Transcripts contain user prompts, model responses, tool calls with
arguments, and tool outputs in chronological order — useful for sharing
reproducible cases or reviewing what the agent actually did.

## Model

Any `provider:model` supported by LangChain's `init_chat_model`:

```sh
uv run jutul-agent --sim jutuldarcy --model anthropic:claude-sonnet-4-6
# or persistently:
export JUTUL_AGENT_MODEL=anthropic:claude-sonnet-4-6
```

Default: `openai:gpt-5.4-mini`.

## Layout

```
src/jutul_agent/
  paths.py         install / workspace / state-home anchors
  workspace.py     config loader, simulator auto-detect, Julia-env bootstrap
  session.py       Session — unit of work for one invocation
  agent/           deepagents wiring (builder), prompts, julia_eval / julia_plot
  simulators/      adapter base, registry, env bootstrap; one folder per simulator:
                     <name>/adapter.py + julia_env/ + skills/
                   plus shared_skills/ used by every session
  julia/           JuliaSession protocol, AgentREPL backend, agentrepl_env/
  trace/           append-only SQLite event log + recorder middleware
  transcript/      renderers (HTML, markdown, investigation report)
  interfaces/      CLI + Textual TUI (TUI owns the approval card renderer)
docs/              overview, design notes, spec
tests/             pytest suite
```

See [`docs/overview.md`](docs/overview.md) for the design overview and the
three-root model (install / workspace / state home).

## Development

```sh
uv sync
uv run pre-commit install       # once per clone: format + lint on each commit

uv run ruff check .             # lint (same paths as CI)
uv run ruff format .            # format before push if hooks are not installed
uv run pre-commit run --all-files   # optional: full pre-push check

uv run pytest                   # tests (skips integration + live by default)
uv run pytest -m integration    # add the Julia-requiring tests
uv run pytest tests/live/       # live LLM tests (need provider key)
```
