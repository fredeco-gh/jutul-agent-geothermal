"""Render the bundled web UI headlessly and capture what it looks like.

The web counterpart to :mod:`jutul_agent.lab.tui`. It serves the static files in
``interfaces/server/web`` from disk, stubs the REST endpoints, mocks the per-session
WebSocket, and then drives the UI through ``window.jutulDebug`` — the same entry
point a real WebSocket message goes through — so a screenshot is what the server
would produce, with no Julia, model, or network. Scenarios are lists of wire
protocol events (see docs/server-interface.md).

Needs Playwright with the system Chrome (no Chromium download):

    pip install playwright            # already in the dev group
    python -m jutul_agent.lab.web_ui list
    python -m jutul_agent.lab.web_ui run canvas --dark
    python -m jutul_agent.lab.web_ui all -o /tmp/web
"""

from __future__ import annotations

import argparse
import io
import json
import math
import mimetypes
import sys
from dataclasses import dataclass, field
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / "interfaces" / "server" / "web"

_MODELS = {"default": "claude-opus-4-8", "providers": ["anthropic", "google", "openai"]}
_SIMS = {
    "simulators": ["jutuldarcy", "battmo", "fimbul"],
    "default": "jutuldarcy",
    "details": {
        "jutuldarcy": {
            "display_name": "JutulDarcy",
            "examples": [
                "Build a small 3D reservoir with one water injector and one producer, run a "
                "short immiscible simulation, and show the interactive 3D view.",
                "Plot the well rates and bottom-hole pressures from the last run.",
                "Set up a CO2 injection case and plot the CO2 inventory over time.",
            ],
        },
        "battmo": {
            "display_name": "BattMo",
            "examples": [
                "Run a constant-current discharge on the Chen 2020 lithium-ion cell and plot "
                "the voltage curve.",
                "Compare discharge at 0.5C, 1C, and 2C on the same plot.",
            ],
        },
        "fimbul": {
            "display_name": "Fimbul",
            "examples": [
                "Run the geothermal doublet demo and show the temperature field over time.",
                "Plot the produced fluid temperature versus time.",
            ],
        },
    },
}

_MISSING_PLAYWRIGHT = (
    "web_ui needs Playwright and a system Chrome. Install it with "
    "`pip install playwright` (it is in the dev dependency group); it uses the "
    "installed Chrome via channel='chrome', so no Chromium download is needed."
)


# --- sample artifacts (so viz/report/image cards render realistically) -------


def sample_png() -> bytes:
    """A believable 2D saturation-field PNG (Pillow only)."""
    from PIL import Image

    w, h = 720, 420
    img = Image.new("RGB", (w, h), (255, 255, 255))
    px = img.load()
    for y in range(h):
        for x in range(w):
            d = math.hypot((x - 250) / 230, (y - 210) / 150)
            t = max(0.0, min(1.0, 1.2 - d))
            px[x, y] = (
                int(68 + t * (253 - 68)),
                int(1 + t * (231 - 1)),
                int(84 + (1 - t) * (140 - 84)),
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def sample_viz_html() -> bytes:
    """A draggable, interactive-looking 3D reservoir placeholder for plot views."""
    return b"""<!doctype html><html><head><meta charset=utf-8><style>
    html,body{margin:0;height:100%;background:#fff;font-family:-apple-system,Segoe UI,sans-serif}
    .wrap{width:100%;height:100%;display:grid;place-items:center;cursor:grab;
      background:radial-gradient(120% 120% at 50% 20%,#fbfdff,#eef2f6)}
    .scene{transform:rotateX(58deg) rotateZ(34deg);transform-style:preserve-3d}
    .grid{display:grid;grid-template-columns:repeat(8,30px);grid-template-rows:repeat(6,30px);gap:2px}
    .c{width:30px;height:30px}
    .bar{position:absolute;right:18px;top:24px;width:14px;height:160px;border-radius:3px;
      background:linear-gradient(#fde725,#5ec962,#21918c,#3b528b,#440154);border:1px solid #ccc}
    .lab{position:absolute;left:16px;top:16px;color:#444;font-size:13px}
    </style></head><body><div class=wrap id=w>
      <div class=lab>plot_reservoir &middot; Saturation (interactive)</div>
      <div class=bar></div>
      <div class=scene id=s><div class=grid id=g></div></div>
    </div><script>
      const cols=['#440154','#3b528b','#21918c','#5ec962','#fde725'];
      const g=document.getElementById('g');
      for(let i=0;i<48;i++){const c=document.createElement('div');c.className='c';
        c.style.background=cols[Math.floor(Math.abs(Math.sin(i*1.3))*5)%5];g.appendChild(c);}
      let rx=58,rz=34,down=false,px=0,py=0;
      const s=document.getElementById('s'),w=document.getElementById('w');
      w.onmousedown=e=>{down=true;px=e.clientX;py=e.clientY;w.style.cursor='grabbing'};
      window.onmouseup=()=>{down=false;w.style.cursor='grab'};
      window.onmousemove=e=>{if(!down)return;rz+=(e.clientX-px)*0.4;rx+=(e.clientY-py)*0.2;
        px=e.clientX;py=e.clientY;s.style.transform=`rotateX(${rx}deg) rotateZ(${rz}deg)`};
    </script></body></html>"""


def sample_report_html() -> bytes:
    """A believable session report document for report views."""
    return b"""<!doctype html><html><head><meta charset=utf-8><style>
    body{margin:0;font-family:-apple-system,Segoe UI,sans-serif;color:#1f2328;background:#fff;
      line-height:1.6}.page{max-width:720px;margin:0 auto;padding:2.4rem 2rem}
    h1{font-size:1.6rem;letter-spacing:-.02em;margin:0 0 .3rem}
    .sub{color:#6b7280;font-size:.9rem;margin-bottom:1.6rem}
    h2{font-size:1.15rem;margin:1.6rem 0 .5rem;border-bottom:1px solid #eee;padding-bottom:.3rem}
    table{border-collapse:collapse;width:100%;font-size:.9rem;margin:.6rem 0}
    td,th{border:1px solid #e3e3df;padding:.4rem .6rem;text-align:left}th{background:#f7f7f5}
    .fig{background:linear-gradient(120deg,#eef6f8,#f6f1fb);border:1px solid #e3e3df;
      border-radius:10px;height:200px;display:grid;place-items:center;color:#6b7280;margin:.8rem 0}
    </style></head><body><div class=page>
      <h1>Immiscible displacement: injector-producer sweep</h1>
      <div class=sub>jutuldarcy &middot; session demo-session-0001 &middot; 4 model calls</div>
      <p>A 20x20x5 Cartesian reservoir was initialised at hydrostatic equilibrium with a single
      water injector and a diagonal producer. The case was advanced for 10 steps; all converged.</p>
      <h2>Key results</h2>
      <table><tr><th>Quantity</th><th>Value</th></tr>
        <tr><td>Pore volume injected</td><td>0.18 PV</td></tr>
        <tr><td>Producer water cut (final)</td><td>0.34</td></tr>
        <tr><td>Recovery factor</td><td>0.41</td></tr></table>
      <h2>Saturation field</h2>
      <div class=fig>Figure: water saturation at the final step</div>
      <p>The plume advances toward the producer along the high-permeability diagonal, with
      breakthrough at step 7.</p>
    </div></body></html>"""


# --- the render harness ------------------------------------------------------


def _route_static(route):
    path = route.request.url.split("://", 1)[-1].split("/", 1)[-1].split("?", 1)[0]
    f = WEB_DIR / ("index.html" if path in ("", "index.html") else path)
    if f.is_file():
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        route.fulfill(status=200, content_type=ctype, body=f.read_bytes())
    else:
        route.fulfill(status=404, body=b"not found")


def _route_artifact(route):
    url = route.request.url
    if url.endswith(".png"):
        route.fulfill(status=200, content_type="image/png", body=sample_png())
    elif "report" in url:
        route.fulfill(status=200, content_type="text/html", body=sample_report_html())
    else:
        route.fulfill(status=200, content_type="text/html", body=sample_viz_html())


def _install_routes(page):
    # Playwright gives precedence to the most recently registered route, so the
    # catch-all is registered first and the specific stubs override it.
    page.route("**/*", _route_static)
    page.route("**/sessions/*/artifacts/**", _route_artifact)
    page.route(
        "**/simulators",
        lambda r: r.fulfill(content_type="application/json", body=json.dumps(_SIMS)),
    )
    page.route(
        "**/models",
        lambda r: r.fulfill(content_type="application/json", body=json.dumps(_MODELS)),
    )
    page.route(
        "**/sessions",
        lambda r: r.fulfill(
            content_type="application/json", body=json.dumps({"session_id": "demo-session-0001"})
        ),
    )
    page.route(
        "**/sessions/history*",
        lambda r: r.fulfill(content_type="application/json", body=json.dumps(_HISTORY)),
    )
    page.route(
        "**/sessions/*/messages",
        lambda r: r.fulfill(content_type="application/json", body=json.dumps({"messages": []})),
    )
    page.route_web_socket("**/stream", lambda ws: ws.on_message(lambda m: None))


_HISTORY = {
    "sessions": [
        {
            "id": "2026-06-21-1007-8128",
            "title": "Immiscible injector-producer sweep",
            "started": "2026-06-21T10:07:00",
            "sim": "jutuldarcy",
        },
        {
            "id": "2026-06-21-0930-2a1b",
            "title": "Well placement study",
            "started": "2026-06-21T09:30:00",
            "sim": "jutuldarcy",
        },
        {
            "id": "2026-06-20-1715-9f3c",
            "title": "CO2 injection inventory",
            "started": "2026-06-20T17:15:00",
            "sim": "jutuldarcy",
        },
    ]
}


def render(script, out, *, width=1440, height=900, settle=500, color_scheme="light"):
    """Drive the bundled UI through a list of wire events and screenshot it.

    ``script`` items are wire-protocol dicts delivered via ``jutulDebug.handle``,
    plus a few harness verbs: ``{"_user": text}``, ``{"_meta": html}``,
    ``{"_eval": js}``, ``{"_click": sel}``, ``{"_sleep": ms}``,
    ``{"_shot": path, "full": bool}``.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dep
        raise SystemExit(_MISSING_PLAYWRIGHT) from exc

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", headless=True, args=["--enable-unsafe-swiftshader"]
        )
        page = browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=2,
            color_scheme=color_scheme,
        )
        _install_routes(page)
        page.goto("http://app.local/index.html", wait_until="networkidle")
        page.wait_for_function("() => window.jutulDebug && true")
        for step in script or []:
            if "_user" in step:
                page.evaluate("(t) => window.jutulDebug.addUserBubble(t)", step["_user"])
            elif "_meta" in step:
                page.evaluate("(h) => window.jutulDebug.setMeta(h)", step["_meta"])
            elif "_eval" in step:
                page.evaluate(step["_eval"])
            elif "_click" in step:
                page.click(step["_click"])
            elif "_sleep" in step:
                page.wait_for_timeout(step["_sleep"])
            elif "_shot" in step:
                page.wait_for_timeout(settle)
                page.screenshot(path=step["_shot"], full_page=step.get("full", False))
            else:
                page.evaluate("(m) => window.jutulDebug.handle(m)", step)
        page.wait_for_timeout(settle)
        page.screenshot(path=str(out))
        browser.close()
    return out


# --- scenarios ---------------------------------------------------------------

_SID = "demo-session-0001"
_ART = f"/sessions/{_SID}/artifacts"
_META = {"_meta": "claude-opus-4-8 &middot; demo-session"}


@dataclass(frozen=True)
class WebScenario:
    name: str
    description: str
    steps: list = field(default_factory=list)
    width: int = 1440
    height: int = 900


def _convo() -> list:
    return [
        _META,
        {
            "_user": "Set up a small 3D reservoir with an injector and producer, run a short "
            "immiscible simulation, show the interactive 3D reservoir view, then write "
            "me a short report."
        },
        {
            "type": "text",
            "text": "I'll build the case, simulate, show the reservoir, and "
            "summarize the results.\n\n",
        },
        {
            "type": "tool",
            "event": "started",
            "tool_call_id": "t1",
            "name": "run_julia",
            "label": "Run Julia",
            "args": {
                "code": "using JutulDarcy, Jutul\n"
                "mesh = CartesianMesh((20, 20, 5), (200.0, 200.0, 25.0))\n"
                "model = setup_reservoir_model(domain, :immiscible, wells=[Injector, Producer])"
            },
        },
        {
            "type": "tool",
            "event": "finished",
            "tool_call_id": "t1",
            "name": "run_julia",
            "label": "Run Julia",
            "content": "MultiModel with 4 models. Simulation done, 10/10 steps.",
        },
        {"type": "text", "text": "Simulation converged. Here is the interactive 3D reservoir:"},
        {
            "type": "tool",
            "event": "finished",
            "tool_call_id": "t3",
            "name": "plot_julia",
            "label": "Plot",
            "content": "rendered an interactive plot (artifacts/reservoir.html)",
        },
        {
            "type": "viz",
            "url": f"{_ART}/reservoir.html",
            "title": "3D reservoir — Saturation",
            "kind": "plot",
            "slot": "reservoir",
        },
        {"type": "text", "text": "And a short written report of the run:"},
        {
            "type": "tool",
            "event": "finished",
            "tool_call_id": "t4",
            "name": "write_report",
            "label": "Write report",
            "content": "wrote report (artifacts/report.html)",
        },
        {
            "type": "viz",
            "url": f"{_ART}/report.html",
            "title": "Immiscible displacement",
            "kind": "report",
            "slot": "report",
        },
        {
            "type": "text",
            "text": "The plume reaches the producer at step 7 (water cut 0.34, "
            "recovery 0.41). Flip between the views with the tabs on the right.",
        },
        {
            "type": "usage",
            "input_tokens": 21840,
            "output_tokens": 712,
            "total_tokens": 22552,
            "model_calls": 4,
        },
        {"type": "turn_end", "text": ""},
    ]


def _resume_steps() -> list:
    """A resumed session replayed inline: text, reasoning, tool cards, a pinned report.

    Exercises the same renderers the live socket uses, driven through
    ``replaySession`` with the wire shape ``/sessions/{id}/messages`` returns — so
    the screenshot shows a reopened chat reconstructed tool cards and all. The live
    plot replays as its saved image (its Bonito server is gone after a restart),
    while a static report stays an interactive canvas view.
    """
    msgs = [
        {
            "type": "user",
            "text": "Set up a small reservoir, simulate it, show the 3D view, "
            "then write a short report.",
        },
        {
            "type": "reasoning",
            "text": "Build a 20x20x5 mesh with an injector and a producer, "
            "advance 10 steps, render the reservoir, then summarise.",
        },
        {
            "type": "tool",
            "event": "requested",
            "tool_call_id": "t1",
            "name": "run_julia",
            "label": "Run Julia",
            "args": {
                "code": "using JutulDarcy, Jutul\n"
                "mesh = CartesianMesh((20, 20, 5), (200.0, 200.0, 25.0))\n"
                "case = setup_reservoir_model(domain, :immiscible; wells=[inj, prod])"
            },
        },
        {
            "type": "tool",
            "event": "finished",
            "tool_call_id": "t1",
            "name": "run_julia",
            "content": "MultiModel with 4 models. Simulation done, 10/10 steps converged.",
        },
        {
            "type": "tool",
            "event": "requested",
            "tool_call_id": "t2",
            "name": "plot_julia",
            "label": "Plot",
            "args": {"caption": "3D reservoir — Saturation"},
        },
        {
            "type": "tool",
            "event": "finished",
            "tool_call_id": "t2",
            "name": "plot_julia",
            "content": "served a live interactive plot (artifacts/reservoir.png)",
        },
        {
            "type": "artifact",
            "url": f"{_ART}/reservoir.png",
            "mime": "image/png",
            "caption": "3D reservoir — Saturation",
            "slot": "reservoir",
        },
        {
            "type": "assistant",
            "text": "The run converged; the saturation field is above. "
            "The interactive plot fell back to its saved image on resume. Here's the report:",
        },
        {
            "type": "viz",
            "url": f"{_ART}/report.html",
            "title": "Immiscible displacement",
            "kind": "report",
            "slot": "report",
        },
    ]
    return [
        _META,
        {"_eval": f"window.jutulDebug.replaySession({json.dumps(msgs)})"},
        {"_sleep": 300},
    ]


def _tool(tid, name, label, args, content):
    return {
        "type": "tool",
        "event": "finished",
        "tool_call_id": tid,
        "name": name,
        "label": label,
        "args": args,
        "content": content,
    }


def _tools_steps() -> list:
    """Every tool kind, to check each card renders well (checklist, diff, code, …)."""
    return [
        _META,
        {"_user": "Read the model, edit it, run it, search, plan, and remember a note."},
        _tool(
            "p",
            "write_todos",
            "Plan",
            {
                "todos": [
                    {"content": "Read and edit the model", "status": "completed"},
                    {"content": "Re-run the simulation", "status": "in_progress"},
                    {"content": "Plot and report", "status": "pending"},
                ]
            },
            "Updated the plan.",
        ),
        _tool(
            "r", "read_file", "Read", {"file_path": "model.jl"}, "1  perm = 1e-13\n2  poro = 0.2"
        ),
        _tool(
            "e",
            "edit_file",
            "Edit",
            {"file_path": "model.jl", "old_string": "perm = 1e-13", "new_string": "perm = 5e-13"},
            "Edited model.jl (1 replacement).",
        ),
        _tool(
            "w",
            "write_file",
            "Write",
            {"file_path": "results/notes.md", "content": "# Notes\n- bumped permeability\n"},
            "Wrote results/notes.md.",
        ),
        _tool("sh", "execute", "Shell", {"command": "ls results/"}, "notes.md\nsaturation.csv"),
        _tool("g", "grep", "Search", {"pattern": "poro"}, "model.jl:2: poro = 0.2"),
        _tool(
            "j",
            "run_julia",
            "Julia",
            {"code": "result = simulate_reservoir(state0, model, dt)"},
            "Step 10/10 converged. 3.1 s.",
        ),
        _tool(
            "d",
            "task",
            "Delegate",
            {"description": "Check solver convergence", "subagent_type": "general-purpose"},
            "Subagent: all steps converged; no stalls.",
        ),
        _tool("m", "remember", "Remember", {"content": "User prefers SI units."}, "Saved."),
        {
            "type": "artifact",
            "url": f"{_ART}/data.csv",
            "mime": "text/csv",
            "caption": "well_rates.csv",
        },
        {"type": "ui", "action": "set_parameter", "payload": {"name": "perm", "value": 5e-13}},
        {"type": "text", "text": "Done — see the plan, edit diff, and outputs above."},
        {
            "type": "usage",
            "input_tokens": 32100,
            "output_tokens": 980,
            "total_tokens": 33080,
            "model_calls": 6,
        },
        {"type": "turn_end", "text": ""},
        {"_eval": "document.getElementById('conversation').scrollTop = 0"},
        {"_sleep": 300},
    ]


def _scenarios() -> dict:
    convo = _convo()
    plot_focus = [{"_eval": "window.jutulDebug.openView('slot:reservoir')"}, {"_sleep": 300}]
    closed = [{"_eval": "window.jutulDebug.closeCanvas()"}, {"_sleep": 200}]
    slash = [_META, {"_eval": "window.jutulDebug.setPrompt('/')"}, {"_sleep": 250}]
    scns = [
        WebScenario("welcome", "Empty welcome screen.", []),
        WebScenario(
            "tools",
            "Every tool kind: plan/checklist, edit diff, file, shell, "
            "search, delegate, remember, csv, ui note.",
            _tools_steps(),
            height=1500,
        ),
        WebScenario("slash", "Slash-command autocomplete menu.", slash, height=820),
        WebScenario(
            "history",
            "Left history sidebar (full height) with past chats and per-sim examples.",
            [_META],
            height=720,
        ),
        WebScenario(
            "resume",
            "A reopened session replayed inline: reasoning, tool cards, image, report.",
            _resume_steps(),
        ),
        WebScenario(
            "canvas",
            "Conversation with a plot + report pinned in the canvas (report active).",
            convo,
        ),
        WebScenario(
            "canvas_plot", "Canvas focused on the interactive 3D plot tab.", [*convo, *plot_focus]
        ),
        WebScenario(
            "canvas_closed",
            "Canvas closed: full-width chat, Views button in the top bar.",
            [*convo, *closed],
        ),
        WebScenario(
            "narrow",
            "Narrow viewport: the canvas becomes a full-width overlay.",
            convo,
            width=760,
            height=900,
        ),
    ]
    return {s.name: s for s in scns}


def capture(scenario: WebScenario, out_dir: Path, *, dark: bool = False) -> Path:
    out = out_dir / f"{scenario.name}{'_dark' if dark else ''}.png"
    return render(
        scenario.steps,
        out,
        width=scenario.width,
        height=scenario.height,
        color_scheme="dark" if dark else "light",
    )


def _default_out() -> Path:
    from jutul_agent.paths import state_home

    return state_home() / "lab" / "web_ui"


# ---- CLI -------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> int:
    scenarios = _scenarios()
    parser = argparse.ArgumentParser(prog="python -m jutul_agent.lab.web_ui")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("list", help="List scenarios.")
    p_run = sub.add_parser("run", help="Render one scenario.")
    p_run.add_argument("name", choices=sorted(scenarios))
    p_all = sub.add_parser("all", help="Render every scenario.")
    for p in (p_run, p_all):
        p.add_argument("-o", "--out", default=None, help="Output directory.")
        p.add_argument("--dark", action="store_true", help="Dark color scheme.")

    args = parser.parse_args(argv)
    if args.cmd in (None, "list"):
        for s in scenarios.values():
            print(f"{s.name:14} {s.description}")
        return 0

    out_dir = Path(args.out) if args.out else _default_out()
    chosen = [scenarios[args.name]] if args.cmd == "run" else list(scenarios.values())
    for s in chosen:
        path = capture(s, out_dir, dark=args.dark)
        print(f"{s.name:14} -> {path}")
    print(f"\nArtifacts under {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
