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

The TUI's collapsed tool and reasoning cards are display only. `Ctrl+O`
toggles the full output for you, and the model's context is unaffected
either way.

## Persistence

Conversation state lives in `checkpoints.sqlite` per session (langgraph's
checkpointer). That is what makes mid-session model switching work: the
agent is rebuilt with the new model on the same checkpoint thread, and the
conversation carries over. The trace (`trace.sqlite`) is a separate,
append-only record for humans and scorers. It is never fed back to the
model.

## Growth and its limits

A session's context grows with the conversation, so growth is both visible
and managed:

- `/context` in the TUI shows measured usage: the last model call's
  `usage_metadata` is exactly what the conversation costs to send. The
  panel estimates usage by category — system prompt, memory index,
  tools/skills/framework, conversation — plus the free space up to the
  auto-compaction trigger and the buffer the trigger reserves, and it
  tracks conversation growth across model calls. The status bar keeps a
  `ctx` percentage in view (yellow at 70% of the window, red at 90%).
  The window size comes from the provider package's profile data, from
  the Ollama daemon for local models, or from the Gemini API for Gemini
  models newer than the bundled data.
- When the conversation reaches 80% of the model's window, older turns are
  automatically replaced by a structured summary (session intent, key
  decisions, artifacts, next steps) while the newest 20 messages stay
  verbatim — langchain's `SummarizationMiddleware`, wired in
  `agent/summarization.py`. For models with no discoverable window the
  trigger falls back to an absolute token count.
- `/compact` runs the same pass on demand against the checkpointed thread,
  keeping a shorter tail. Every compaction (automatic or manual) is
  recorded as a `context_compaction` trace event, and the full
  pre-compaction conversation remains in the trace.
- Keep sessions task-shaped regardless: a summary preserves conclusions,
  not everything. Durable knowledge belongs in memory, which survives the
  session boundary by design.
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
