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
- **Julia 1.10+** — install via [juliaup](https://github.com/JuliaLang/juliaup)
- **uv** — Astral's Python project manager (handles the venv and entry points)

On a **headless Linux** server, plotting also needs `xvfb` (`sudo apt-get install -y xvfb`); without it, simulation still works but plot calls error.

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

### 2. Make sure Julia is 1.10+

`juliaup`'s default channel already satisfies this. If you're on an older pin:

```sh
juliaup add 1.10 && juliaup default 1.10
```

### 3. Clone and sync

```sh
git clone <this-repo>
cd jutul-agent
uv sync
```

`uv sync` creates `.venv/` and installs all Python deps from `pyproject.toml`
+ `uv.lock`. Re-run it whenever those files change.

### 4. Add a provider API key

When a model needs a key that isn't set, jutul-agent prompts you for it (at
`init`, or when you pick a model in the selector) and saves it for future runs.
To set one up front instead, put it in your shell environment or a `.env`
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY`; see `.env.example`).
Local models via [Ollama](https://ollama.com) need no key. See [Models](#models).

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

**One simulator per workspace.** Each workspace's `.jutul-agent/julia-env/`
holds a single simulator — different simulators (e.g. BattMo and JutulDarcy)
have incompatible Julia dependencies and can't share one env. Use a separate
folder per simulator. If you point an existing workspace at a different
simulator, jutul-agent rebuilds its env from the new simulator's template on
the next run.

### Add a folder to the workspace

Sometimes the files you want the agent to use live outside the workspace — a
shared dataset, a sibling repo, a folder of reference scripts. Mount one (or
more) so the agent can read, grep, write, and edit it with the same file tools
it uses for workspace files:

```sh
# at launch (repeatable)
uv run jutul-agent --add-dir ../shared-data --add-dir ~/datasets/spe10
```

```text
# or any time inside the TUI
/add-dir ../shared-data        mount it now
/add-dir                       list the folders mounted this session
```

Each added folder shows up in the agent's filesystem at `/dirs/<name>/`
(named after the folder, disambiguated if two share a name). Mounts are
*session-scoped* — they last until you exit and aren't written to
`config.toml`. In `julia_eval`/`execute` the agent uses the folder's real
absolute path; the `/dirs/` route is for the file tools.

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

Then launch the TUI and ask for a run in plain language:

```sh
uv run jutul-agent
```

```
> Set up a constant-current discharge for the chen_2020 cell and plot the voltage curve.
```

The agent runs the simulation in its persistent Julia REPL, writes any
implementation files into your workspace, and saves the plot to the session's
artifacts.

## Troubleshooting

If `jutul-agent` fails to start, run the built-in setup check first — it
inspects everything the agent needs and tells you exactly what's wrong:

```sh
uv run jutul-agent doctor
```

It checks, with a one-line fix for each problem:

- `julia` is on PATH and is **1.10+**
- the active model's provider key is set (or, for a local model, Ollama is running)
- which Julia project this workspace resolves to (see the gotcha below)
- the simulator's package is actually resolved in the env's `Manifest.toml`
  (catches a `Project.toml` that lists it but was never instantiated)
- a display is available for plotting — and on a headless Linux box, that
  `xvfb` is installed so GLMakie can render (warns, doesn't fail)
- Julia boots cleanly in that project (a trivial eval — catches a broken manifest)

**Gotcha — workspace vs. launch directory.** `jutul-agent` uses the
directory you launch it from as the workspace, not where you ran `init`.
`cd` into the initialised folder before launching, or pass
`--workspace <path>` explicitly. Note too that a `Project.toml` in the 
root of your workspace takes precedence over `.jutul-agent/julia-env/`
— if that root project doesn't include the simulator's packages, `using
<Sim>` will fail even though the kernel starts. `doctor` flags this case.

**"Julia failed to start before the kernel was ready".** This means the
Julia subprocess crashed during startup; the message now includes Julia's
own error and the path to a full log
(`…/sessions/<id>/julia-startup.log`). The most common cause is an
out-of-date or incomplete env — rebuild it with:

```sh
uv run jutul-agent init --sim <name> --precompile --force
```

`init --precompile` verifies Julia boots in the env as its final step, so a
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
| `/add-dir <path>` | Mount an extra folder so the agent can read/edit it. |
| `/model`          | Open the model selector (or `/model <provider:model>`). |
| `/copy`           | Copy the last assistant message to the clipboard.   |
| `/clear`          | Clear the visible log and restore the welcome card. |
| `/approval-mode`  | Set approval policy: `ask`, `workspace`, `auto`.    |
| `/help`           | List commands.                                      |
| `/quit`           | Exit the TUI.                                        |

Keyboard:

| Key          | Effect                                                          |
|--------------|-----------------------------------------------------------------|
| `Ctrl+C`     | Interrupt the running turn; with text selected, copy it; press twice when idle to exit. |
| `Ctrl+G`     | Cancel the in-flight turn (resets Julia if needed).             |
| `Ctrl+L`     | Clear the visible log.                                          |
| `Ctrl+O`     | Toggle the latest tool block between preview / full.            |
| `Shift+Tab`  | Cycle approval mode.                                            |
| `Ctrl+P`/`↑` | Previous history entry.                                         |

Select text with the mouse and press `Ctrl+C` to copy it (or use `/copy`
for the whole last reply — handy when your terminal doesn't play nicely with
in-app selection).

### Non-interactive use

The TUI is the intended way to use jutul-agent. For scripting or CI you can
also run a single turn by passing the prompt as a positional argument. Headless
mode can't pause to ask for approval, so pass `--approval-mode auto`:

```sh
uv run jutul-agent --approval-mode auto "Plot the voltage curve for the chen_2020 cell."
```

Without `auto` (or `workspace`), a turn that needs to run a shell command or
edit a file stops with an "approval required" message — use the TUI for that.

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

## Models

Type `/model` to open the selector. It lists a set of models (OpenAI,
Anthropic, Google, and local Ollama models) and lets you type any other
`provider:model` that LangChain's `init_chat_model` supports. You can switch
mid-session; the conversation carries over. Press Enter to save the choice for
this workspace, or Ctrl+A to set it as the default for every workspace.

If the model's provider needs an API key that isn't set, the selector prompts
you for it and saves it for future runs.

```
/model                                  open the selector
/model anthropic:claude-sonnet-4-6      switch directly
```

You can also set the model for one run from the command line:

```sh
uv run jutul-agent --sim jutuldarcy --model anthropic:claude-sonnet-4-6
```

### Local models (Ollama)

Run models locally through [Ollama](https://ollama.com) — no API key needed.
Install Ollama and start it (`ollama serve`), then pick an `ollama:` model in
the selector. The list includes a few recommended models you can pull on the
spot, your already-installed ones, and Ollama Cloud (`:cloud`) models. If a
model isn't pulled yet, jutul-agent pulls it for you.

jutul-agent is tool-driven, so a local model must support **tool calling**
(`ollama show <model>` lists `tools` under Capabilities). A recent model can
report no tools if your Ollama is too old to parse its template — keep Ollama
up to date (`curl -fsSL https://ollama.com/install.sh | sh`) and re-pull. Local
models are convenient but generally weaker at tool use than the hosted ones.

The agent's prompt is large, so local models are loaded with a context window
sized to the model (what Ollama reports it supports), capped at a memory budget
— 64K by default. On memory-tight hardware, lower the cap with
`JUTUL_AGENT_OLLAMA_NUM_CTX` (e.g. `32768`).

### Other providers

Models from providers beyond the bundled ones (OpenAI, Anthropic, Google,
Ollama) work once you install that provider's LangChain package — for example
`uv add langchain-openrouter` — then enter its `provider:model` in the
selector. jutul-agent tells you the exact package to install if it's missing.

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
  julia/           JuliaSession protocol + Julia toolchain checks
  juliakernel/     supervised Julia runtime (kernel.py + server.jl) — the backend
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
