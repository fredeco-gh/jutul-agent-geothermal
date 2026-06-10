# Models

jutul-agent treats models as opaque `provider:model` strings resolved by
LangChain's `init_chat_model`. Adding a new model is configuration, not a
code change.

## Selection

Precedence, highest first: the `--model` flag, the workspace config, the
user config, `$JUTUL_AGENT_MODEL`, the built-in default.

In the TUI, `/model` opens the selector: bundled OpenAI, Anthropic, Google,
and Ollama entries, your recently used models, and a free-text field for
any `provider:model` LangChain supports. Enter saves the choice for this
workspace, and `Ctrl+A` makes it the user-wide default. Switching mid-session
rebuilds the agent on the same conversation (see
[context handling](context.md)).

Providers beyond the bundled four work once their LangChain package is
installed (for example `uv add langchain-openrouter`), and jutul-agent
names the exact package when it is missing. API keys are prompted for on first
use and stored in the user-global `.env`
([configuration](configuration.md)).

## What the harness asks of a model

The agent is tool-driven: every Julia evaluation, file edit, and plot is a
tool call, often ten or more per task. Models therefore need solid tool
calling, and weaker models fail in characteristic ways: skipping tools and
answering from memory, or calling a tool with malformed arguments. The
bench's trajectory scorers exist to catch exactly this, and the canary
suite is the quick way to qualify a new model
([evaluation](evaluation.md)).

## Local models (Ollama)

Local models run through Ollama with no key. Two things the harness handles
for you:

- Capability gating: the selector checks that a model supports tool
  calling before offering it, and can pull a model that is not installed
  yet. An outdated Ollama can mis-parse a new model's template and lose
  tool support, so keep Ollama itself current.
- Context sizing: the agent's system prompt is large, so local models are
  loaded with a context window sized to what the model reports, capped by
  a memory budget (64K tokens by default, lowered with
  `JUTUL_AGENT_OLLAMA_NUM_CTX` on tight hardware).

Expect local models to be noticeably weaker at multi-step tool use than the
hosted ones. They are best for cheap iteration and offline work, with the
bench as the honest comparison.

## Models in the bench

`jutul-agent eval` uses Inspect's model layer, so model ids there take the
`provider/model` form (`openai/gpt-5.4-mini`, `ollama/qwen3.6:27b`), and
one run can matrix several models. The agent under test runs against the
bridge regardless of the target provider, which is how the same session
code serves every model. See [evaluation](evaluation.md).
