# Memory

Memory is how a workspace gets smarter over time without retraining
anything: a small set of markdown notes the agent maintains itself,
persisted across sessions.

## The model: an index plus notes

Memory lives in a real directory under the state home, keyed by workspace
(the agent reads and edits the files at their real paths, and you can open
them directly). It has one structural rule:

- `MEMORY.md` is the index. It is loaded into the system prompt of every
  session, so its contents are always visible. It holds one line per note:
  a link and a hook for when the note matters.
- Every fact is its own markdown file next to the index, read on demand
  with `read_file` and edited with the ordinary file tools.

This is the same progressive-disclosure shape as skills: the model always
knows what it knows (the index), and pays context for a note only when it
is relevant. A fat always-loaded memory file would crowd the context,
while an index of one-liners stays cheap at any size.

## How it gets written

The agent writes memory through the `remember` tool (append a note and
index it) and through normal file edits when revising or deleting. It is
prompted to record durable, non-obvious facts: a user preference, a quirk
of this workspace's data, a hard-won fix. If the agent keeps re-learning
something, ask it to remember the fact, then check what it wrote. Memory
is plain markdown, and editing it by hand is fine: `/memory` in the TUI
shows the index and the notes, `/memory <note>` prints one, and
`/memory edit [note]` opens it in your editor: `$VISUAL`/`$EDITOR` if
set, else a platform default (nano/vim/vi on Unix, Notepad on Windows).
The agent sees the edit from its next turn.

A note of caution that applies to any self-written memory: notes reflect
what was true when written. The agent is instructed to verify stale-looking
claims (a path, an API) before acting on them.

## Scope

- Per workspace: the state home hashes the workspace path, so each project
  folder has independent memory. There is no global tier yet, though the
  design leaves room for one (a second memory directory alongside the
  per-workspace one).
- `--ephemeral-memory` swaps in a throwaway directory: nothing read from or
  written to the real memory. The bench uses this so evaluation runs cannot
  learn from each other. It is also the right flag for one-off experiments.

## Memory versus skills

Both are markdown the model reads, but they answer different questions.
Skills are curated, shipped knowledge about how to do a kind of task, the
same for every user. Memory is what this workspace's agent has learned
about this project and this user. If a memory note turns out to be
generally true, promote it into a skill (see
[improving the agent](improving-the-agent.md)).
