# CLI reference

All commands run through `uv run jutul-agent`. Two flags are accepted by
every command:

| Flag | Meaning |
|---|---|
| `--workspace <path>` | Workspace directory (default: current working directory) |
| `--state-home <path>` | Where sessions and traces live (default: `$XDG_DATA_HOME/jutul-agent`, falling back to `~/.local/share/jutul-agent`) |

## jutul-agent (run)

```sh
jutul-agent [options] [prompt]
```

Without a prompt this launches the TUI. With a prompt it runs one headless
turn and exits.

| Option | Meaning |
|---|---|
| `--sim <name>` | Active simulator. Required only if not in workspace config and not auto-detectable from a `Project.toml` |
| `--model <provider:model>` | Model for this run. Precedence: this flag, workspace config, user config, `$JUTUL_AGENT_MODEL`, default |
| `--julia-project <path>` | Override the resolved workspace Julia project |
| `--add-dir <path>` | Mount an extra folder for the agent (repeatable) |
| `--approval-mode ask\|workspace\|auto` | Human-in-the-loop policy (headless runs need `auto`) |
| `--ephemeral-memory` | Throwaway memory directory for this session |
| `--version` | Print the version |

Headless exit codes: 0 on success, 3 when the turn needed an approval that
headless mode cannot ask for.

## jutul-agent init (alias: setup)

Bootstrap the workspace: write `.jutul-agent/config.toml` and copy the
simulator's Julia env template.

| Option | Meaning |
|---|---|
| `--sim <name>` | Simulator to bootstrap (omit to auto-detect) |
| `--source-path <path>` | `Pkg.develop` a local checkout of the simulator package (persisted to the workspace config) |
| `--precompile` (synonym `--instantiate`) | `Pkg.instantiate` + precompile, including the GL plotting bake (slow the first time) |
| `--force` | Replace an existing workspace env with a fresh template copy (after upgrading jutul-agent) |

## jutul-agent doctor

Diagnose the setup: Julia version, provider key (or Ollama reachability),
which Julia project the workspace resolves to, whether the simulator package
is actually in the manifest, display/xvfb for plotting, and a boot check of
the env. Each finding comes with a fix.

| Option | Meaning |
|---|---|
| `--sim <name>` | Simulator to check against (default: workspace config / auto-detect) |

## jutul-agent transcript

Render a recorded session.

```sh
jutul-agent transcript                  # last session in this workspace, HTML
jutul-agent transcript <id>             # a specific session
jutul-agent transcript --format markdown
jutul-agent transcript --bundle         # zip including artifacts
```

## jutul-agent eval

Run bench suites through Inspect AI (needs `uv sync --extra eval`). See
[evaluation](evaluation.md).

```sh
jutul-agent eval --list
jutul-agent eval <suite> [<suite>...] --model <provider/model>[,<provider/model>...]
```

| Option | Meaning |
|---|---|
| `--model` | Inspect model id(s), comma-separated for a matrix |
| `--epochs <n>` | Repetitions per sample (default 1) |
| `--max-samples <n>` | Concurrent samples (default 1: sessions only interleave, the workspace root is process-global) |
| `--limit <n>` | Only the first n samples of each task |
| `--log-dir <path>` | Where Inspect writes logs (default: state home `/eval-logs`) |
| `--list` | List available suites |

Exit code 1 when any task errored. Note the model id form differs from the
app's: Inspect uses `provider/model`, the agent uses `provider:model`.
