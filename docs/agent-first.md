# Agent-first development

This project has been developed with coding agents from the first commit.
Agents write most of the code, the tests, and the documentation, while
humans direct, review, and decide what should exist. The premise is that working
well with these tools is a systems problem: the repository, the checks, and
the feedback loops are designed for agents to work in, rather than agents
being slotted into a process designed around human typing speed.

That choice shapes the codebase as much as any runtime requirement. This
page records how, and doubles as a goal: some of it describes what the
repository already is, some of it the way of working we are building
toward. It is a living page, updated as the process teaches us more.

There is a recursion worth noting: the product is itself an agent harness.
The development process and the product face the same question of what an
agent needs to see, run, and verify on its own, and the same machinery
often answers both.

## What the repository had to become

The agent touches everything: the simulators, the Julia runtime, the TUI,
the eval harness. Nobody re-validates all of that by hand after every
change, so each practice below exists to make verification something the
agent can run, not something a person must remember to do.

### Verification is machinery, not vigilance

An agent never gets tired of running checks, but it cannot be trusted to
"be careful", so every property worth keeping is checked by something that
runs without a human. The unit suite is deliberately kept fast enough to
run after every change, lint and format gates run beside it, and CI
repeats the suite across operating systems. Hand-written
[fakes rather than mocks](testing.md), a scripted chat model and a
scripted Julia session, stand in for the expensive edges, so a complete
agent turn (prompt in, tool calls, answer out) executes offline and
deterministically. Snapshot tests turn any change to the assembled system
prompt, and to the rendered TUI screen, into a diff a reviewer sees. Pilot
tests drive the real TUI headlessly and assert on what actually renders,
treating model output as untrusted input: text that happens to look like
terminal markup must render as text, never as formatting. The agent runs all of this in its
loop and fixes failures before a human looks.

### The repository is the whole interface

From the agent's side, anything it cannot reach from the repository may as
well not exist. Knowledge in someone's head, a chat thread, or a wiki is
invisible, so it lives here: design intent in these docs, per-simulator
knowledge in skill files, behavior expectations in bench tasks, decisions
in commit messages. The same pressure pushes every fact toward a single
home: a fact duplicated across files gets updated in one place and missed
in the other, occasionally by humans and reliably by agents, so path
policy, prompt assembly, and output limits each live in one module that
everything else imports.

The principle extends past our own code. The product agent learns a
simulator from what the package itself exposes (docstrings, runnable
examples, error messages), read straight from the
[installed package source](filesystem.md). So the highest-leverage
improvements are often upstream, in the applications: discoverable APIs,
runnable examples for every capability, error messages that say what to
do, hints when something fails. What makes a package agent-friendly makes
it human-friendly too. The agent is just its most systematic user
([making a simulator agent-friendly](improving-the-agent.md#making-a-simulator-agent-friendly)).

### Headless is a first-class citizen

Everything works without a display or a keyboard: the TUI runs headlessly
under a pilot, plotting renders under a managed virtual display, every
operation is scriptable through the CLI. This began as a user requirement
(the agent should be useful on a cluster) and turned out to be the
load-bearing development requirement: it is what lets an agent run the
product end to end and inspect what came out, a rendered plot, a
transcript, a built docs page, and iterate against what it sees. Plotting
is fully supported rather than stubbed out under test: CI instantiates a
real simulator environment and renders a real figure.

The same capture closes the loop on the interface itself. A small set of
scripted scenarios drives the real TUI headlessly and writes each screen
out as an image an agent can open, and a live mode runs one real prompt,
real model and real solve, and captures what actually rendered; the agent
sees a problem in the picture, edits a widget, and re-renders, with no
person at a terminal. Cold start and a turn's hot path are profiled the
same headless way, so "what is slow" is a measurement the agent takes and
acts on rather than a guess: that loop is what found and removed a heavy
import from the CLI's startup. The machinery lives in one place
([the lab](lab.md)), reused by both the tests and the agent.

### Behavior is regression-tested like code

Code changes are pinned by tests. Behavior changes (a prompt, a skill, a
tool description) are pinned by [the bench](evaluation.md). With several
simulators sharing one prompt and one toolset, a fix for one area can
quietly degrade another, and nobody notices by reading the diff. Suites
notice. Cheap suites run before and after any behavior-touching change, a
skill correction lands together with the task that exposed it, and the
[RunConfig](evaluation.md#attribution-the-runconfig) ties any score
movement to the one input that changed. The agent can run and analyze its
own evals: the eval command, logs, and transcripts are all within reach,
so "did that help?" is a question it answers with numbers.

### Drift is watched, not assumed away

Agent-written code is only as good as the upstream APIs it was written
against, and those move. Python dependencies are locked and upgraded
deliberately. The agent framework in particular is pinned to a known-good
version, and a bump gets the live smoke test and a TUI pilot pass.
Simulator environments deliberately carry no version pins, so a weekly CI
lane instantiates each one against the latest upstream releases and fails
loudly when upstream moves ([development](development.md)). A scheduled
review of upstream releases and changelogs, beyond this breakage canary,
is planned but not built yet.

### The process leaves a trace

Every session appends to a SQLite [trace](trace.md): tool calls, model
usage, recorded attempts, artifacts. Transcripts render to HTML and
markdown. Together with version control, that gives a review the
provenance it actually needs: what changed (git), what ran (the trace),
what was concluded (transcripts and reports). The bench applies the same
standard to the agent itself, grading
[the trace rather than the story](evaluation.md#scoring-the-trace-not-the-story):
a correct answer with an unrecorded process fails.

### Clear boundaries, replaceable internals

The codebase is deliberately modular: a small number of explicit
interfaces (the Julia session protocol, the filesystem backends, the turn
runner) separate parts that change for different reasons, and the tests
target those interfaces rather than the implementation behind them. That
combination is what makes change fast and safe: an implementation can be
rewritten wholesale while its tests keep meaning something, so internals
get optimized and swapped out quickly. The kernel transport has already
been replaced this way, with nothing outside its interface noticing. When
code is cheap to generate, the boundaries and the tests that define them
are the durable asset, and what sits behind a boundary is an artifact you
can afford to replace.

## From code to specifications

For an individual, the pace drops the moment generated code must be
validated: reading every line in order to vouch for it, shepherding it
through review. Reviewing every line of generated code does not scale,
and trusting it blind is not an option, so the practical line moves to
intent and evidence: a precise statement of what should exist, and
verification strong enough to show that it does. In a team the same
problem returns one level up: misaligned specifications, and context that
does not transfer, because how a solution was produced is invisible to
the next person.

In most codebases today the code is the specification and the
documentation. That has the virtue of a single source of truth, but code
is an inefficient carrier of intent: as a system grows, it drifts from
the original plan, and the overhead of recovering "what should this do,
and does it?" grows with it. Models are now capable enough to implement a
well-posed specification with few errors, repair code from test failures,
and notice when a specification and a test disagree. That shifts where
attention earns the most: writing specifications that are unambiguous and
scale, building validation that proves the real need is met, and noticing
mismatches among the three corners, specification, validation, and need.
The code itself becomes more like an artifact: still read and reviewed,
but regenerated or reshaped on demand when the specification changes or
better models arrive.

That direction is visible in the choices above: behavior pinned by
suites, intent recorded in documentation and tasks rather than only in
code, internals kept cheap to replace. The rest is a goal we are building
toward, and this page is where we keep score.

## Still open

Live questions rather than settled practice:

- Upstream watching beyond breakage: the weekly canary catches what stops
  working, not what we should adopt. A scheduled review of upstream
  releases is not built yet.
- How far review can lean on evidence (specifications, tests, traces)
  rather than line-reading, while the reviewer can still vouch for the
  result.
- Where specifications should live: today intent is spread across these
  docs, the bench tasks, and the tests, and one layer of that should
  probably become first-class.
