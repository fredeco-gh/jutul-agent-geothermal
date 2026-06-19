# jutul-agent demo app

A minimal, runnable webapp driven by jutul-agent. It shows the moving parts in
one place and is meant to be copied as a starting point. The wire contract it
uses is documented in [docs/server-interface.md](../../docs/server-interface.md).

What it demonstrates:

- A session created and driven over the server (REST + WebSocket).
- Streamed assistant replies and tool calls.
- An **interactive plot** (WGLMakie exported to self-contained HTML) embedded in
  the page.
- The **two-way UI link**: the agent can move the parameter slider (`set_param`),
  and moving the slider yourself tells the agent.
- **Capability composition**: the example's simulator and web tools are added
  through the extension seam, not the built-in registry.

## Run it

Install the server extra, then start the app:

```bash
pip install 'jutul-agent[server]'      # or: uv sync --extra server
python examples/demo-app/demo.py       # first run instantiates the Julia env
```

Open <http://127.0.0.1:8742>. Set a model first if needed (any provider key in
your environment), then try: *"plot the response for p=3"*, or *"set the
parameter to 5 and plot it"*.

## Layout

- `DemoSim/` — a tiny Julia library: one function, `response(p)`, no physics.
- `julia_env/` — the Julia environment (DemoSim, WGLMakie, Bonito).
- `demo.py` — the adapter, the web capability (the `plot_response` and
  `set_param` tools), and the app wiring.
- `frontend/` — a framework-free page (`index.html` + `app.js`) over the wire
  protocol. Replace it with a real front end.

## Extending it

- Swap `DemoSim` for a real simulator: point the adapter at it and add it to the
  Julia env.
- Add tools, skills, or subagents by extending the `Capability` in `demo.py`, or
  publish your own under the `jutul_agent.extensions` entry point.
- Drive richer UI (a diagram, a map) by emitting `ui` commands from a tool and
  handling them in the front end.
