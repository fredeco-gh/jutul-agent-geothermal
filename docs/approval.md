# Approval and safety

The agent can edit files and run shell commands. Approval is the
human-in-the-loop checkpoint in front of those actions. This page explains
how it works and, just as importantly, what it does and does not protect
against.

## What is gated

Three tools require approval (`agent/approval.py`):

| Tool | Action |
|---|---|
| `execute` | run a shell command |
| `write_file` | write a file |
| `edit_file` | edit a file |

The gate is implemented as a langgraph interrupt: when the agent calls a
gated tool, the graph pauses, the pending call (tool name and arguments)
surfaces as an approval request, and the turn resumes with the decision.
In the TUI this is the approval card. An approved category can be added to
a per-session allowlist ("always allow file edits / shell commands for
this session"), so repetitive approvals do not pile up. Every request and
decision is recorded in the trace (`hitl_request`, `hitl_response`).

## Modes

| Mode | Behavior |
|---|---|
| `ask` (default) | prompt for all three tools |
| `workspace` | auto-allow `write_file`/`edit_file`, still prompt for `execute` |
| `auto` | auto-allow all three |

Set it at launch (`--approval-mode`), in the workspace config, with
`/approval-mode` in the TUI, or cycle with `Shift+Tab`. Headless runs
cannot prompt, so a gated call under `ask` ends the turn with an error;
scripts and the bench run with `auto`.

## What approval is not

Approval is a review checkpoint for visible side effects, not a security
boundary. Two honest limits:

- `julia_eval` and `julia_plot` are not gated. Running arbitrary Julia is
  the agent's core job (a simulation can read and write files and use the
  network like any program), so gating it would mean approving every
  working step. The design trusts Julia evaluation the way it trusts the
  user's own REPL.
- Approval inspects intent, not effect. You approve the command the agent
  *says* it will run. A reviewer skimming `execute` arguments is the
  protection, and that protection is only as good as the attention given.

The consequence: approval is the right tool for supervising an interactive
session you are watching. For unattended runs, the protection that matters
is *where the process runs*, not which tools are gated.

## Isolation for unattended runs

`--approval-mode auto` hands the agent its full toolset without review, so
match the blast radius to the trust level:

- Bench and CI runs of the bundled task suites are our own prompts against
  major-provider models, where the practical risk is accidental damage, not
  malice. CI runners are ephemeral VMs, which is already strong isolation,
  so scheduled bench runs belong there.
- On a workstation, prefer a dedicated workspace directory and
  `--ephemeral-memory`, and remember the shell is not confined to the
  workspace.
- For adversarial evaluation tiers, third-party task packs, or any prompt
  you did not write, run the whole invocation in a container or VM. That
  is the boundary that actually contains a destructive command.

See [evaluation](evaluation.md) for how the bench applies this.
