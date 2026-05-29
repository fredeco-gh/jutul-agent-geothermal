# jutul-agent

A scientific AI assistant for AD-enabled simulators on the
[Jutul](https://github.com/sintefmath/Jutul.jl) framework. Drive
[JutulDarcy](https://github.com/sintefmath/JutulDarcy.jl),
[BattMo](https://github.com/BattMoTeam/BattMo.jl), and other Jutul-based
simulators from a terminal TUI — the agent runs Julia in a persistent REPL,
reads the actual package source on disk, writes implementation files into
your workspace, and keeps a per-session trace.

## Install

Works on Linux, macOS, and Windows. You need three things on PATH:

- **Python 3.12+**
- **Julia 1.12+** — install via [juliaup](https://github.com/JuliaLang/juliaup)
- **uv** — Astral's Python project manager (handles the venv and entry points)

### 1. Install `uv`

If `uv` is not already on your PATH, use Astral's standalone installer
(recommended — handles PATH, shell completions, and doesn't need a
pre-existing Python):

- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

Package-manager alternatives if you prefer:

- Windows (WinGet): `winget install --id=astral-sh.uv -e`
- macOS (Homebrew): `brew install uv`
- Any platform via [pipx](https://pipx.pypa.io/): `pipx install uv`

Open a new terminal afterwards so the updated PATH is picked up. Full
instructions and other install methods:
[docs.astral.sh/uv/getting-started/installation](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Make sure Julia 1.12+ is the default

If `juliaup` gave you an older channel, switch:

```sh
juliaup add 1.12 && juliaup default 1.12
```

Check with `julia --version`.

### 3. Clone and sync

```sh
git clone <this-repo>
cd jutul-agent
uv sync
```

`uv sync` creates `.venv/` and installs all Python deps from `pyproject.toml`
+ `uv.lock`. Re-run it whenever those files change.

### 4. Add a provider API key

```sh
cp .env.example .env            # PowerShell: Copy-Item .env.example .env
```

Then edit `.env` — set `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY`. The
default model is `openai:gpt-5.4-mini`; override with `JUTUL_AGENT_MODEL`
if needed.

## Use it in any folder

`jutul-agent` runs in the directory you invoke it from — that directory is
your *workspace*. Initialise once:

```sh
mkdir my-reservoir-study && cd my-reservoir-study
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

### Supported simulators

| `--sim`      | Package                                                      | Domain                                         |
|--------------|--------------------------------------------------------------|------------------------------------------------|
| `jutuldarcy` | [JutulDarcy.jl](https://github.com/sintefmath/JutulDarcy.jl) | Reservoir / multi-phase flow                   |
| `battmo`     | [BattMo.jl](https://github.com/BattMoTeam/BattMo.jl)         | Lithium-ion (and other) battery cells          |
| `fimbul`     | [Fimbul.jl](https://github.com/sintefmath/Fimbul.jl)         | Geothermal (ATES, BTES, doublet, EGS, …)       |
| `mocca`      | [Mocca.jl](https://github.com/sintefmath/Mocca.jl)           | Adsorption-based CO₂ capture (PSA / VSA / TSA) |
| `vocsim`     | VOCSim.jl *(unreleased — placeholder slot)*                  | VOC / methane emissions from hydrocarbon storage |

## Example: BattMo

Start from an empty folder, bootstrap, and ask for a discharge run:

```sh
mkdir my-battery-run && cd my-battery-run
uv run jutul-agent init --sim battmo --precompile
```

`--precompile` runs `Pkg.instantiate` and warms up CairoMakie. The very
first time can take ~15 min (Julia compiles BattMo + plotting); subsequent
starts are seconds.

Then either launch the TUI:

```sh
uv run jutul-agent
```

…or run a one-shot headless turn:

```sh
uv run jutul-agent "Set up a constant-current discharge for the chen_2020 cell and plot the voltage curve."
```

## Troubleshooting

If `jutul-agent` fails to start, run the built-in setup check first — it
inspects everything the agent needs and tells you exactly what's wrong:

```sh
uv run jutul-agent doctor
```

It checks, with a one-line fix for each problem:

- `julia` is on PATH and is **1.12+**
- a provider API key is set (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`)
- which Julia project this workspace resolves to (see the gotcha below)
- that project has a `Project.toml` containing `AgentREPL`
- `using AgentREPL` actually loads in that project

**Gotcha — workspace vs. launch directory.** `jutul-agent` uses the
directory you launch it from as the workspace, not where you ran `init`.
`cd` into the initialised folder before launching, or pass
`--workspace <path>` explicitly. Note too that a `Project.toml` in the 
root of your workspace takes precedence over `.jutul-agent/julia-env/`
— if that root project doesn't include `AgentREPL`, startup will fail.
`doctor` flags this case.

**"Julia failed to start before the agent could connect".** This means the
Julia subprocess crashed during startup; the message now includes Julia's
own error and the path to a full log
(`…/sessions/<id>/julia-startup.log`). The most common cause is an
out-of-date or incomplete env — rebuild it with:

```sh
uv run jutul-agent init --sim <name> --precompile --force
```

`init --precompile` verifies `using AgentREPL` loads as its final step, so a
clean `init` rules out this whole class of failure.

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

For one-shot, non-interactive use, pass the prompt as a positional argument
(see the BattMo example above).

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
```

Persist via environment variable:

```sh
export JUTUL_AGENT_MODEL=anthropic:claude-sonnet-4-6        # bash / zsh
$Env:JUTUL_AGENT_MODEL = "anthropic:claude-sonnet-4-6"      # PowerShell
```

…or set `JUTUL_AGENT_MODEL` in your `.env`. Default: `openai:gpt-5.4-mini`.

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
tests/             pytest suite
```

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
