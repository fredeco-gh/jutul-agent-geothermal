# Context handling

What the model actually sees on a turn, where it comes from, and how growth
is managed.

## What enters the context

Every turn, the model receives:

- The system prompt, assembled per session (`agent/prompts.py`): the
  harness ground rules, the active simulator's description and domain
  hints, and runtime context (paths, plotting availability).
- The skills index: every skill's name and description. Skill bodies are
  not in the context until the agent reads one. That is the
  progressive-disclosure contract, and it is why always-on rules live in
  the prompt, not in skill bodies (see
  [improving the agent](improving-the-agent.md)).
- The memory index `MEMORY.md` (see [memory](memory.md)). Individual notes
  enter only when read.
- The conversation so far: messages, tool calls, and tool results.

Tool results are real content, not summaries. The Julia kernel's streamed
output is rendered through a terminal emulator (so progress bars collapse
to their final state instead of thousands of carriage-return frames) and
tail-capped at 256 KB. Result values and error messages are capped at
64 KiB on the kernel side. Within those caps, what the tool saw is what
the model sees.

The TUI's collapsed tool blocks are display only. `Ctrl+O` toggles the
full output for you, and the model's context is unaffected either way.

## Persistence

Conversation state lives in `checkpoints.sqlite` per session (langgraph's
checkpointer). That is what makes mid-session model switching work: the
agent is rebuilt with the new model on the same checkpoint thread, and the
conversation carries over. The trace (`trace.sqlite`) is a separate,
append-only record for humans and scorers. It is never fed back to the
model.

## Growth and its limits

There is no automatic summarization or compaction yet: a session's context
grows with the conversation, and a very long session will eventually
approach the model's window. Current practice:

- Keep sessions task-shaped, and start a new one for a new investigation.
  Durable knowledge belongs in memory, which is exactly the part that
  survives the session boundary.
- Token usage per model turn is recorded in the trace (`model_usage`
  events), so the cost of a workflow is measurable, and the bench records
  it per sample.
- Local models get a context window sized to what the model supports under
  a memory budget (see [models](models.md)). The large system prompt is
  the floor that budget must clear.

Subagents are the structural answer for context-heavy sub-tasks: a
subagent runs in its own context window and returns a result, so the
parent's context pays for the conclusion, not the exploration. The seam
exists per simulator (`subagent_factories`), though none are bundled yet.
