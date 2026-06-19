# Architecture

jutul-agent is a Python harness around a persistent Julia process. The Python
side runs the agent loop, the tools, and all bookkeeping, while the Julia
side runs the simulator. One session means one workspace, one Julia process,
one trace.

![jutul-agent architecture](assets/architecture-light.svg#only-light)
![jutul-agent architecture](assets/architecture-dark.svg#only-dark)

<p class="ja-legend">
  <span class="ja-dot" style="background:#2563eb"></span> Python
  <span class="ja-dot" style="background:#7c3aed"></span> Julia
  <span class="ja-dot" style="background:#b45309"></span> on-disk state
  <span class="ja-dot" style="background:#047857"></span> simulator data
  <span class="ja-dot" style="background:#475569"></span> external
</p>

## Interfaces

`jutul-agent` (no arguments) launches the Textual TUI. A positional prompt
runs one headless turn instead, which is what scripts, CI, and the bench use.
Subcommands handle the rest: `init` bootstraps a workspace, `doctor` diagnoses
a broken setup, `transcript` renders a past session, `eval` runs bench suites.
All of them live in `src/jutul_agent/interfaces/cli/`, and the TUI is
`interfaces/tui/`.

Every interface funnels into the same place: build a `Session`, build the
agent, hand prompts to `TurnRunner` (`agent/turns.py`). The TurnRunner
consumes the agent's event stream, surfaces streaming output and approval
interrupts, and writes the trace events that make a session reconstructable.
The turn lifecycle has its own page: [turns](turns.md).

## Session and agent core

A `Session` (`session.py`) is the unit of one invocation: a session id, a
state directory, the trace log, and a handle to the Julia kernel.

`build_agent` (`agent/builder.py`) assembles a
[deepagents](https://github.com/langchain-ai/deepagents) agent around the
session: the system prompt, the custom tools, the filesystem, and the
model. The agent loop itself (planning, tool dispatch, streaming) is
deepagents/langgraph: jutul-agent deliberately does not own a loop. Generic
agent machinery is built and improved elsewhere at a pace not worth
competing with. The value of this project is the scientific harness around
the loop and the specialization for the simulators, so that is where the
code goes.

The system prompt (`agent/prompts.py`) is assembled per session from the
harness ground rules, the active simulator's description, and the runtime
context. Two things ride along with it: the index of available skills (names
and descriptions only) and the workspace memory index `MEMORY.md`. Always-on
behavior rules belong here, not in skill bodies, because skills are read on
demand (see [improving the agent](improving-the-agent.md)).

Custom tools (`agent/tools.py`, `agent/plot_julia.py`, `agent/memory.py`):

- `run_julia` runs code in the persistent Julia kernel and streams output.
- `plot_julia` builds a figure, saves a PNG artifact, and records it in the
  trace. `recapture_plot` and `close_plots` manage live figure windows.
- `reset_julia` restarts the kernel process when the REPL state is wedged.
- `record_attempt` logs one step of a parameter investigation (id, rationale,
  metrics, plot) so calibration runs form an auditable tree.
- `write_report` renders an investigation report from those attempts.
- `remember` appends a note to workspace memory.

Standard deepagents tools (`read_file`, `write_file`, `edit_file`, `glob`,
`grep`, `ls`, `execute`) operate on a real-path filesystem backend rooted at
the workspace: a relative path resolves against it and an absolute path as
itself, the same file the shell and the Julia REPL see. Skills, memory,
installed package source (each at its `pkgdir`), and folders added with
`--add-dir` are all read and written at their real paths through this one
backend; writes into the shared Julia depot (installed package source) are
refused so the agent can study a package without corrupting it. Side-effecting
tools go through the approval middleware (`ask`, `workspace`, or `auto` mode).

## The Julia kernel

`juliakernel/` is a standalone package (stdlib-only on the Julia side) that
supervises one Julia process per session. Python launches
`julia server.jl <port>` and connects one loopback TCP socket. Everything
travels over that socket as length-prefixed frames:

```
Julia -> Python   RDY <token>            handshake
                  OUT <stream> <n>       live stdout/stderr bytes
                  RES <id> <status> <n>  one result per eval
Python -> Julia   EXE <id> <n>           code to evaluate
```

The server redirects file descriptors 1 and 2 into in-process pipes, so
output from C and Fortran libraries is captured, not just Julia prints. Pump
tasks forward those bytes as `OUT` frames, and a drain marker guarantees all
of an eval's output is on the wire before its `RES` frame. TCP ordering does
the rest, and the Python side is one reader task and one pending future
(`juliakernel/connection.py`).

Interrupts are cooperative: `interrupt()` sends SIGINT, which Julia delivers
to the eval as an `InterruptException`, so a stuck simulation cancels without
losing the session. The kernel is launched with an interactive thread
(`--threads N,1`) so the eval loop and the output pumps never share one. If a
cancelled eval cannot be recovered within a timeout, the supervisor restarts
the process and says so.

Reset is cheap by design: Julia cannot unload code, so `reset_julia` always
starts a fresh process and relies on precompile caches to make that fast (see
warm packages below). The protocol and its design constraints are covered in
[the Julia kernel](julia-kernel.md).

## Simulators are data

Everything simulator-specific lives in one folder per simulator under
`simulators/` (see [adding a simulator](adding-a-simulator.md)):

- `adapter.py` declares the metadata: name, packages to import, domain
  hints, the warm package, optional subagents.
- `julia_env/Project.toml` is the environment template copied into a
  workspace at `init`. No `Manifest.toml` is committed, so envs resolve at
  instantiate time.
- `julia_env/JutulAgent<Sim>/` is the warm package. Its precompile workload
  bakes the simulator's solve and plot paths into Julia's cache, which is why
  a first solve takes seconds rather than minutes.
- `skills/` holds the simulator's skill markdown.

The shared `JutulAgent` Julia package (`julia_runtime/`) is synced into every
env at bootstrap and carries cross-simulator runtime helpers, including the
ensemble runner.

Adding a simulator adds data in that folder plus a registry entry. No agent
code changes.

## Memory

Memory is per workspace and maintained by the agent itself
(`agent/memory.py`). Only the index file `MEMORY.md` is loaded into the
prompt. Each fact is a sibling markdown file the agent reads on demand and
edits with the normal file tools. `--ephemeral-memory` swaps in a throwaway
directory, which the bench uses so runs cannot learn from each other.

## Trace, transcripts, artifacts

Every session appends events to `trace.sqlite` in the session state
directory: user and assistant messages, reasoning, every tool call with
arguments and result, token usage per model turn, plot artifacts,
investigation attempts, and approval round-trips. The recorder is a
middleware (`trace/recorder.py`), so it sees the same stream the model does.

The trace is the source of truth. Transcripts (HTML or markdown, via
`jutul-agent transcript`) are renderings of it, and bench scorers grade
against it rather than trusting the model's final text. Conversation state
for resuming and model switching lives separately in `checkpoints.sqlite`
(langgraph's checkpointer). The event schema is documented in
[the trace database](trace.md).

## Models

Model ids are opaque `provider:model` strings resolved by precedence:
`--model` flag, workspace config, user config, `$JUTUL_AGENT_MODEL`, default.
`/model` in the TUI opens a selector that can also pull Ollama models and
collect missing API keys. Keys live in a user-global `.env`
(`credentials.py`), never in config files. Switching models mid-session
rebuilds the agent on the same checkpointer, so the conversation carries
over.

## Evaluation

jutul-bench drives this whole stack, unchanged, through Inspect AI: a solver
builds a real session per sample and scorers read the resulting trace. See
[evaluation](evaluation.md).
