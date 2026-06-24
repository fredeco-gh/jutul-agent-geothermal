"""The geothermal-viz capability: tools that let the agent drive the embedded map
and run Fimbul simulations on the agent's own Julia kernel.

Each map-control tool below emits a `ui` trace event (`session.trace.append("ui",
{...})`), which host-extension.js forwards into the map iframe as a
`postMessage`, and geothermal-viz's jutul-agent-bridge.js applies by looking the
action name up in its own dispatch table — the same agent-to-UI pattern as
examples/demo-app/demo.py's `set_param`, just on this app's map instead of a
parameter slider.

This module is the skeleton for growing the agent's reach into geothermal-viz:
adding a new ability means adding one `_make_..._tool` factory below, wiring it
into ``geothermal_viz_capability``'s ``tools`` tuple, and adding the matching
case to jutul-agent-bridge.js's action dispatch table. Nothing else needs to
change to pick it up — serve.py passes whatever this returns straight into the
session.

A tool that *asks* the map to do something (like ``set_map_view``) can return
right away — there's nothing to get wrong. But a tool that depends on data only
the browser holds (like which wells exist) must not just fire the UI action and
claim success: the browser's answer would only arrive on the *next* message (see
docs/server-interface.md's ui_event queueing), so the agent would confidently
report success in the same turn it actually failed. ``go_to_well`` instead
resolves the well itself, against geothermal-viz's own data API, so it can give
the agent an honest answer immediately.

The simulation tools (``run_simulation``, ``view_simulation_result``) reuse
geothermal-viz's own ``src/simulation.jl`` verbatim — ``include()``d once into the
agent's persistent kernel — rather than porting its Fimbul/parameter-mapping
logic into Python. ``run_simulation_action`` is the other entry point into the
same execution helper: a direct, non-LLM path for when a front end (the
sidebar's Run button) already has exact, structured parameters and there is
nothing for the model to decide — see docs/server-interface.md and
jutul_agent.interfaces.server.app.ActionHandler.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from jutul_agent.agent.capabilities import Capability
from jutul_agent.juliakernel.result import OutputChunk
from jutul_agent.session import Session

# Matched first, exactly (case-insensitive): a well or well-park number.
_EXACT_FIELDS = ("brønnNr", "brønnParkNr")
# Matched next, as a substring, so a vaguer request still has a chance to resolve.
_LOOSE_FIELDS = (*_EXACT_FIELDS, "brønnpOmrNavn", "beskrivelse", "oppdragstaker")

# Same idea, but restricted to the well-park identifier itself — excludes
# `brønnNr` so a well-park lookup can't accidentally land on an unrelated well
# whose own number happens to match the park identifier given.
_PARK_EXACT_FIELDS = ("brønnParkNr",)
_PARK_LOOSE_FIELDS = ("brønnParkNr", "brønnpOmrNavn", "beskrivelse", "oppdragstaker")

# Cached per map origin rather than per call: the dataset only changes when
# geothermal-viz's data-processing script reruns and its server restarts, so
# refetching the whole file on every `go_to_well` call would be wasted work.
_wells_cache: dict[str, list[dict[str, Any]]] = {}


async def _load_well_features(map_origin: str) -> list[dict[str, Any]]:
    cached = _wells_cache.get(map_origin)
    if cached is not None:
        return cached
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{map_origin}/api/data/all_boreholes")
        response.raise_for_status()
        features = response.json().get("features", [])
    _wells_cache[map_origin] = features
    return features


def _find_well(
    features: list[dict[str, Any]],
    identifier: str,
    *,
    exact_fields: tuple[str, ...] = _EXACT_FIELDS,
    loose_fields: tuple[str, ...] = _LOOSE_FIELDS,
) -> dict[str, Any] | None:
    needle = str(identifier).strip().lower()
    if not needle:
        return None
    for feature in features:
        props = feature.get("properties", {})
        if any(str(props.get(f, "")).lower() == needle for f in exact_fields):
            return feature
    for feature in features:
        props = feature.get("properties", {})
        if any(needle in str(props.get(f, "")).lower() for f in loose_fields):
            return feature
    return None


def _make_set_map_view_tool(session: Session):
    @tool
    async def set_map_view(lon: float, lat: float, zoom: float = 14.0) -> str:
        """Move the geothermal-viz map to a location.

        Args:
            lon: Longitude in degrees (WGS84).
            lat: Latitude in degrees (WGS84).
            zoom: Map zoom level — roughly 0 for the whole world, 18 for street
                level. Defaults to 14, which frames a single borehole site.
        """
        session.trace.append(
            "ui",
            {"action": "set_map_view", "payload": {"lon": lon, "lat": lat, "zoom": zoom}},
        )
        return f"Moved the map to ({lat}, {lon}) at zoom {zoom}."

    return set_map_view


def _make_go_to_well_tool(session: Session, map_origin: str):
    @tool
    async def go_to_well(identifier: str) -> str:
        """Fly the map to a specific well and select it, as if the user clicked it.

        Args:
            identifier: A well or well-park number (e.g. "12345"), or other
                identifying text (area name, contractor, description) to match
                loosely if no well/park number matches exactly.
        """
        try:
            features = await _load_well_features(map_origin)
        except Exception as exc:
            return f"Could not reach geothermal-viz's data API to look up wells: {exc}"
        feature = _find_well(features, identifier)
        if feature is None:
            return (
                f"No well matching '{identifier}' was found in the loaded borehole "
                "data — tell the user it doesn't exist rather than saying you moved "
                "the map."
            )
        lon, lat = feature["geometry"]["coordinates"]
        session.trace.append(
            "ui",
            {"action": "go_to_well", "payload": {"lon": lon, "lat": lat, "feature": feature}},
        )
        return f"Found well '{identifier}' and moved the map to it."

    return go_to_well


def _make_go_to_well_park_tool(session: Session, map_origin: str):
    @tool
    async def go_to_well_park(identifier: str) -> str:
        """Fly the map to a well park itself and select it, as if the user
        clicked it directly — use this when asked about a well *park* rather
        than one of the individual wells inside it.

        Args:
            identifier: A well-park number (e.g. "12345"), or other identifying
                text (area name, contractor, description) to match loosely if
                no park number matches exactly.
        """
        try:
            features = await _load_well_features(map_origin)
        except Exception as exc:
            return f"Could not reach geothermal-viz's data API to look up well parks: {exc}"
        # Well parks are their own feature ("layer" == "BrønnPark"), with their
        # own coordinates — distinct from the individual wells that merely
        # reference one via `brønnParkNr`. Restricting the search to that
        # layer is what actually lands on the park itself; without it, an
        # ordinary well sharing the same park number (the data lists those
        # before any park feature) would match first instead.
        parks = [f for f in features if f.get("properties", {}).get("layer") == "BrønnPark"]
        feature = _find_well(
            parks,
            identifier,
            exact_fields=_PARK_EXACT_FIELDS,
            loose_fields=_PARK_LOOSE_FIELDS,
        )
        if feature is None:
            return (
                f"No well park matching '{identifier}' was found in the loaded "
                "borehole data — tell the user it doesn't exist rather than "
                "saying you moved the map."
            )
        lon, lat = feature["geometry"]["coordinates"]
        # Reuses the same `go_to_well` UI action: the map only ever flies to and
        # selects one feature regardless of whether it's a well or a well park,
        # so no new action/dispatch case is needed.
        session.trace.append(
            "ui",
            {"action": "go_to_well", "payload": {"lon": lon, "lat": lat, "feature": feature}},
        )
        return f"Found well park '{identifier}' and moved the map to it."

    return go_to_well_park


# ---------------------------------------------------------------------------
# Fimbul simulation, run on the agent's own Julia kernel.
#
# simulation.jl is include()d once per kernel (the isdefined guard makes it
# idempotent) and called directly — its functions, caches, and globals
# (_sim_case, _sim_states, render_reservoir_image, ...) are reused exactly as
# geothermal-viz's own server used them, just executed in a different process.
#
# The structured result comes back through a JSON file rather than parsed from
# stdout: simulation.jl's progress lines and Fimbul's own progress-bar output
# share that stream, so splitting a "real" return value out of it by text
# parsing would be fragile. A file gives a clean, unambiguous result.

_SIMULATE_TEMPLATE = '''
begin
    if !isdefined(Main, :run_fimbul_simulation)
        include(raw"__JL_PATH__")
    end
    import JSON3
    local _setup = Dict{String,Any}(
        "case_type" => "__CASE_TYPE__",
        "parameters" => Dict{String,Any}(
        JSON3.read(raw"""__PARAMS_JSON__""", Dict{String,Float64})),
    )
    local _errors = validate_simulation_params(_setup)
    local _result = if !isempty(_errors)
        Dict{String,Any}(
            "status" => "error",
            "message" => "Invalid parameters: " * join(["$(e[1]): $(e[2])" for e in _errors], "; "),
        )
    else
        run_fimbul_simulation(_setup)
    end
    if get(_result, "status", "") == "completed"
        try
            # The HTML report draws its own well-output chart client-side from
            # well_data/timestamps below, so only the reservoir-state images need
            # rendering here. Those need Fimbul's mesh + render_reservoir_image, so
            # they can only happen here, in-kernel — the report can't fetch them
            # lazily afterwards since geothermal-viz no longer serves that. A bounded,
            # evenly-spaced subset of steps is pre-rendered (not every step) to keep
            # this from adding minutes to every run.
            local _rvars = get(_result, "reservoir_vars", String[])
            local _n = get(_result, "num_steps", 0)
            if !isempty(_rvars) && _n > 0
                local _maxshots = 15
                local _steps = _n <= _maxshots ? collect(1:_n) :
                    sort(collect(Set(round.(Int, range(1, _n; length=_maxshots)))))
                local _images = Dict{String,Any}()
                for _v in _rvars
                    local _bystep = Dict{String,Any}()
                    for _s in _steps
                        local _byd = Dict{String,Any}()
                        for _d in (false, true)
                            local _img = render_reservoir_image(_v, _s; delta=_d)
                            if !isempty(_img)
                                _byd[_d ? "true" : "false"] = _img
                            end
                        end
                        if !isempty(_byd)
                            _bystep[string(_s)] = _byd
                        end
                    end
                    _images[_v] = _bystep
                end
                _result["reservoir_images"] = _images
                _result["reservoir_steps"] = _steps
            end
        catch e
            @warn "Could not pre-render reservoir images" exception=e
        end
    end
    open(raw"__RESULT_PATH__", "w") do io
        JSON3.write(io, _result)
    end
    "ok"
end
'''

_VIEW_RESULT_TEMPLATE = """
begin
    if !isdefined(Main, :render_reservoir_image)
        include(raw"__JL_PATH__")
    end
    local _states = _sim_states[]
    if _states === nothing || isempty(_states)
        write(raw"__IMG_PATH__", "")
    else
        local _step = __STEP__ < 0 ? length(_states) : __STEP__
        local _img = render_reservoir_image("__VAR__", _step; delta=__DELTA__)
        write(raw"__IMG_PATH__", _img)
    end
    "ok"
end
"""


def _render_template(template: str, **values: str) -> str:
    code = template
    for key, value in values.items():
        code = code.replace(f"__{key}__", value)
    return code


async def _execute_fimbul_simulation(
    session: Session,
    simulation_jl_path: str,
    case_type: str,
    parameters: dict[str, Any],
    *,
    on_chunk: Callable[[OutputChunk], None] | None = None,
) -> dict[str, Any]:
    """Run a Fimbul simulation in the agent's persistent Julia kernel.

    Validates first (mirroring what geothermal-viz's own server used to do
    before running), then calls simulation.jl's existing run_fimbul_simulation
    unchanged. ``on_chunk``, if given, receives the live progress output exactly
    as ``run_julia`` does for any other long Julia computation.
    """
    result_path = session.output_dir / "artifacts" / f"sim-result-{uuid.uuid4().hex[:8]}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    jl_path = Path(simulation_jl_path).resolve().as_posix()
    code = _render_template(
        _SIMULATE_TEMPLATE,
        JL_PATH=jl_path,
        CASE_TYPE=case_type,
        PARAMS_JSON=json.dumps({k: float(v) for k, v in parameters.items()}),
        RESULT_PATH=result_path.as_posix(),
    )
    result = await session.julia.eval(code, on_chunk=on_chunk)
    if result.error:
        raise RuntimeError(result.error)
    return json.loads(result_path.read_text(encoding="utf-8"))


async def _render_simulation_view(
    session: Session, simulation_jl_path: str, var: str, step: int, delta: bool
) -> str:
    """The base64 PNG for one reservoir-state step of the most recent simulation
    still held in the kernel ("" if there isn't one)."""
    img_path = session.output_dir / "artifacts" / f"sim-view-{uuid.uuid4().hex[:8]}.b64"
    img_path.parent.mkdir(parents=True, exist_ok=True)
    code = _render_template(
        _VIEW_RESULT_TEMPLATE,
        JL_PATH=Path(simulation_jl_path).resolve().as_posix(),
        VAR=var,
        STEP=str(int(step)),
        DELTA="true" if delta else "false",
        IMG_PATH=img_path.as_posix(),
    )
    result = await session.julia.eval(code)
    if result.error:
        raise RuntimeError(result.error)
    return img_path.read_text(encoding="ascii")


def _summarize_simulation_result(
    case_type: str, parameters: dict[str, Any], result: dict[str, Any]
) -> str:
    wells = ", ".join(result.get("well_data", {}).keys()) or "none"
    return (
        f"{case_type} simulation completed: {result.get('num_steps', '?')} timesteps, "
        f"well(s): {wells}. Parameters used: {parameters}."
    )


# Placeholder-substituted like the Julia templates above (not an f-string) so the
# literal JS/CSS braces below don't need escaping. The well-output chart and the
# reservoir-state playback are ported straight from geothermal-viz's old sidebar
# Results tab (git history, web/js/simulation.js pre-removal): same dropdowns,
# same canvas line-chart drawing, same step/delta controls — except all reading
# from the JSON embedded below instead of fetching a live API, since that API
# (geothermal-viz's own simulation server) no longer runs simulations.
_REPORT_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  margin: 2rem; color: #1f2328;
}
table { border-collapse: collapse; margin: 1rem 0; }
td { padding: 4px 14px; border-bottom: 1px solid #e3e3df; }
h1 { font-size: 1.4rem; }
h2 {
  font-size: 1.1rem; margin-top: 2rem;
  border-top: 1px solid #e3e3df; padding-top: 1rem;
}
.controls {
  display: flex; gap: 1.5rem; align-items: center;
  margin: 0.5rem 0 1rem; flex-wrap: wrap;
}
.controls label { font-size: 0.85rem; color: #475569; margin-right: 0.35rem; }
select { padding: 4px 8px; border: 1px solid #cbd5e1; border-radius: 4px; }
.chart-wrap {
  border: 1px solid #e2e8f0; border-radius: 6px;
  padding: 8px; max-width: 900px;
}
.playback { display: flex; align-items: center; gap: 0.5rem; margin: 0.5rem 0; }
.playback button {
  border: 1px solid #cbd5e1; background: #f8fafc;
  border-radius: 4px; padding: 4px 10px; cursor: pointer;
}
.playback button:hover { background: #eef2f7; }
.playback input[type=range] { flex: 1; max-width: 300px; }
.step-label { font-size: 0.85rem; color: #475569; white-space: nowrap; }
.delta-label { font-size: 0.85rem; color: #475569; }
.reservoir-image-wrap { max-width: 700px; }
.reservoir-image-wrap img { max-width: 100%; border: 1px solid #e2e8f0; border-radius: 6px; }
.muted { color: #94a3b8; font-size: 0.85rem; }
</style></head><body>
<h1>__TITLE__</h1>
<p>__MESSAGE__</p>
<p><strong>Wells:</strong> __WELLS__ &middot; <strong>Timesteps:</strong> __NUM_STEPS__</p>
<table>__ROWS__</table>

<h2>Well Output</h2>
<div class="controls">
  <span><label for="well-select">Well</label><select id="well-select"></select></span>
  <span><label for="var-select">Variable</label><select id="var-select"></select></span>
</div>
<div class="chart-wrap"><canvas id="chart-canvas"></canvas></div>

<div id="reservoir-section" style="display:none;">
<h2>Reservoir States</h2>
<div class="controls">
  <span>
    <label for="reservoir-var-select">Variable</label>
    <select id="reservoir-var-select"></select>
  </span>
  <span class="delta-label">
    <label><input type="checkbox" id="show-delta"> Show difference from initial state</label>
  </span>
</div>
<div class="playback">
  <button id="step-first" title="First step">|&lt;</button>
  <button id="step-prev" title="Previous step">&lt;</button>
  <button id="step-next" title="Next step">&gt;</button>
  <button id="step-last" title="Last step">&gt;|</button>
  <input type="range" id="step-slider" min="0" max="0" value="0">
  <span class="step-label" id="step-label"></span>
</div>
<p class="muted">Only a sampled subset of steps was pre-rendered with the result
  (rendering every step would make this report very large).</p>
<div class="reservoir-image-wrap">
  <img id="reservoir-image" alt="Reservoir state visualization" style="display:none;">
  <p id="reservoir-placeholder" class="muted">No image for this step/variable/delta combination.</p>
</div>
</div>

<script id="sim-result-data" type="application/json">__DATA_JSON__</script>
<script>
const result = JSON.parse(document.getElementById("sim-result-data").textContent);

function populateVarSelect(wellName) {
  const select = document.getElementById("var-select");
  select.innerHTML = "";
  const wellVars = (result.well_data && result.well_data[wellName]) || {};
  for (const vname of Object.keys(wellVars)) {
    const opt = document.createElement("option");
    opt.value = vname;
    opt.textContent = vname;
    select.appendChild(opt);
  }
}

function drawResultChart() {
  const wellName = document.getElementById("well-select").value;
  const varName = document.getElementById("var-select").value;
  if (!wellName || !varName) return;
  const wellVars = result.well_data[wellName];
  if (!wellVars || !wellVars[varName]) return;

  const values = wellVars[varName];
  const timestamps = result.timestamps;
  const canvas = document.getElementById("chart-canvas");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  const w = Math.max(200, rect.width - 10);
  const h = 320;

  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  canvas.width = w * dpr;
  canvas.height = h * dpr;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const DAYS_PER_YEAR = 365.25;
  const timeVals = timestamps.map(t => t / DAYS_PER_YEAR);
  const tMin = Math.min(...timeVals);
  const tMax = Math.max(...timeVals);
  let vMin = Math.min(...values);
  let vMax = Math.max(...values);
  if (vMin === vMax) { vMin -= 1; vMax += 1; }
  const vPad = (vMax - vMin) * 0.05;
  vMin -= vPad;
  vMax += vPad;

  const pad = { top: 15, right: 15, bottom: 42, left: 70 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  ctx.fillStyle = "#fafbfc";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "#94a3b8";
  ctx.lineWidth = 1;
  ctx.strokeRect(pad.left, pad.top, plotW, plotH);

  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 0.5;
  for (let i = 1; i < 5; i++) {
    const y = pad.top + (plotH * i / 5);
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + plotW, y); ctx.stroke();
  }
  for (let i = 1; i < 5; i++) {
    const x = pad.left + (plotW * i / 5);
    ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + plotH); ctx.stroke();
  }

  const tRange = (tMax - tMin) || 1;
  const vRange = (vMax - vMin) || 1;
  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < values.length; i++) {
    const x = pad.left + ((timeVals[i] - tMin) / tRange) * plotW;
    const y = pad.top + (1 - (values[i] - vMin) / vRange) * plotH;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  ctx.save();
  ctx.fillStyle = "#475569";
  ctx.font = "11px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "center";
  ctx.translate(13, pad.top + plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText(varName, 0, 0);
  ctx.restore();

  ctx.fillStyle = "#475569";
  ctx.font = "11px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("Time [years]", pad.left + plotW / 2, h - 3);

  ctx.fillStyle = "#64748b";
  ctx.font = "10px -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "right";
  for (let i = 0; i <= 5; i++) {
    const val = vMax - (i / 5) * (vMax - vMin);
    const y = pad.top + (plotH * i / 5);
    ctx.fillText(val.toFixed(1), pad.left - 6, y + 4);
  }
  ctx.textAlign = "center";
  for (let i = 0; i <= 5; i++) {
    const val = tMin + (i / 5) * (tMax - tMin);
    const x = pad.left + (plotW * i / 5);
    ctx.fillText(val.toFixed(1), x, pad.top + plotH + 16);
  }
}

const wellNames = Object.keys(result.well_data || {});
const wellSelect = document.getElementById("well-select");
for (const wname of wellNames) {
  const opt = document.createElement("option");
  opt.value = wname; opt.textContent = wname;
  wellSelect.appendChild(opt);
}
if (wellNames.length) {
  populateVarSelect(wellNames[0]);
  wellSelect.addEventListener("change", () => {
    populateVarSelect(wellSelect.value);
    drawResultChart();
  });
  document.getElementById("var-select").addEventListener("change", drawResultChart);
  window.addEventListener("resize", drawResultChart);
  drawResultChart();
}

const reservoirImages = result.reservoir_images || {};
const reservoirSteps = (result.reservoir_steps || []).slice().sort((a, b) => a - b);
const reservoirVars = Object.keys(reservoirImages)
  .filter(v => Object.keys(reservoirImages[v] || {}).length > 0);

if (reservoirVars.length && reservoirSteps.length) {
  document.getElementById("reservoir-section").style.display = "block";
  const varSelect = document.getElementById("reservoir-var-select");
  for (const v of reservoirVars) {
    const opt = document.createElement("option");
    opt.value = v; opt.textContent = v;
    varSelect.appendChild(opt);
  }
  const slider = document.getElementById("step-slider");
  slider.min = 0;
  slider.max = reservoirSteps.length - 1;
  slider.value = reservoirSteps.length - 1;

  function updateReservoirImage() {
    const varName = varSelect.value;
    const delta = document.getElementById("show-delta").checked;
    const step = reservoirSteps[parseInt(slider.value, 10)];
    const img = document.getElementById("reservoir-image");
    const placeholder = document.getElementById("reservoir-placeholder");
    const byStep = (reservoirImages[varName] || {})[String(step)] || {};
    const b64 = byStep[delta ? "true" : "false"];
    document.getElementById("step-label").textContent = "Step " + step + " / " + result.num_steps;
    if (b64) {
      img.src = "data:image/png;base64," + b64;
      img.style.display = "block";
      placeholder.style.display = "none";
    } else {
      img.style.display = "none";
      placeholder.style.display = "block";
    }
  }

  function setStepIndex(idx) {
    idx = Math.max(0, Math.min(idx, reservoirSteps.length - 1));
    slider.value = idx;
    updateReservoirImage();
  }

  varSelect.addEventListener("change", updateReservoirImage);
  document.getElementById("show-delta").addEventListener("change", updateReservoirImage);
  slider.addEventListener("input", updateReservoirImage);
  document.getElementById("step-first").addEventListener("click", () => setStepIndex(0));
  document.getElementById("step-prev").addEventListener("click", () => {
    setStepIndex(parseInt(slider.value, 10) - 1);
  });
  document.getElementById("step-next").addEventListener("click", () => {
    setStepIndex(parseInt(slider.value, 10) + 1);
  });
  document.getElementById("step-last").addEventListener("click", () => {
    setStepIndex(reservoirSteps.length - 1);
  });
  updateReservoirImage();
}
</script>
</body></html>"""


def _build_simulation_report_html(
    case_type: str, parameters: dict[str, Any], result: dict[str, Any]
) -> str:
    import html

    rows = "".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in parameters.items()
    )
    wells = ", ".join(result.get("well_data", {}).keys()) or "none"
    title = html.escape(case_type) + " simulation results"
    # </script> inside the embedded JSON (won't normally occur, but a stray well
    # or parameter name could in principle contain it) would otherwise close the
    # tag early.
    data_json = json.dumps(result).replace("</", "<\\/")
    return _render_template(
        _REPORT_TEMPLATE,
        TITLE=title,
        MESSAGE=html.escape(str(result.get("message", ""))),
        WELLS=html.escape(wells),
        NUM_STEPS=str(result.get("num_steps", "?")),
        ROWS=rows,
        DATA_JSON=data_json,
    )


def _record_simulation_artifact(
    session: Session, case_type: str, parameters: dict[str, Any], result: dict[str, Any]
) -> str:
    """Pin the results as a report tab in the chat's canvas (not geothermal-viz's
    sidebar). A fixed filename + stable slot means a later run refreshes the
    same tab instead of stacking a new one each time."""
    rel = "artifacts/simulation-results.html"
    out = session.output_dir / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_build_simulation_report_html(case_type, parameters, result), encoding="utf-8")
    session.trace.append(
        "artifact",
        {
            "path": rel,
            "mime": "text/html",
            "format": "html",
            "caption": f"{case_type} simulation results",
            "kind": "report",
            "slot": "simulation-results",
        },
    )
    return rel


def _make_run_simulation_tool(session: Session, simulation_jl_path: str):
    # Reuses the same ContextVar-based streaming writer run_julia uses, so this
    # tool's progress shows up live in its tool card exactly the same way.
    from jutul_agent.agent.tools import _capture_delta_writer

    @tool
    async def run_simulation(case_type: str, parameters: dict[str, float]) -> str:
        """Run a Fimbul geothermal simulation (an AGS or BTES case).

        Args:
            case_type: "AGS" (single energy well) or "BTES" (well-park array).
            parameters: Simulation parameters by name (e.g. well_depth,
                surface_temperature, geothermal_gradient, flow_rate, num_years,
                ...). Prefer values already resolved for the well in question
                (e.g. from a well's metadata) over invented ones, and confirm
                with the user before changing key parameters yourself.
        """
        try:
            result = await _execute_fimbul_simulation(
                session, simulation_jl_path, case_type, parameters, on_chunk=_capture_delta_writer()
            )
        except Exception as exc:
            return f"ERROR: simulation failed: {exc}"
        if result.get("status") != "completed":
            return f"ERROR: {result.get('message', 'simulation failed')}"
        _record_simulation_artifact(session, case_type, parameters, result)
        return _summarize_simulation_result(case_type, parameters, result)

    return run_simulation


def _make_view_simulation_result_tool(session: Session, simulation_jl_path: str):
    @tool
    async def view_simulation_result(
        var: str = "Temperature", step: int = -1, delta: bool = False
    ) -> str | list[dict[str, Any]]:
        """Show a reservoir-state image from the most recent simulation.

        Lets you actually see (and describe) the reservoir field, rather than
        only knowing the summary numbers — call this when asked what a result
        "looks like". Errors if no simulation has run yet this session.

        Args:
            var: Reservoir variable to render (e.g. "Temperature", "Pressure").
            step: 1-based timestep to show; -1 (default) for the last step.
            delta: Show the change from the initial state instead of the
                absolute value.
        """
        try:
            b64 = await _render_simulation_view(session, simulation_jl_path, var, step, delta)
        except Exception as exc:
            return f"ERROR: {exc}"
        if not b64:
            return "No simulation result is available yet — run a simulation first."
        return [
            {"type": "text", "text": f"Reservoir {var} at the requested step."},
            {"type": "image", "mime_type": "image/png", "base64": b64},
        ]

    return view_simulation_result


def make_run_simulation_action(simulation_jl_path: str):
    """The direct (non-LLM) counterpart to ``run_simulation``.

    For when a front end (geothermal-viz's sidebar) already has exact,
    structured parameters chosen by the user — nothing for the model to
    interpret, so this bypasses it entirely (see
    jutul_agent.interfaces.server.app.ActionHandler) rather than risking the
    model paraphrasing or re-deriving the parameters from a synthetic prompt.
    It still sends the same `tool`-shaped wire messages a real tool call would
    (started/delta/finished), so it looks identical in the chat.
    """

    async def run_simulation_action(
        session: Session,
        args: dict[str, Any],
        send_wire: Callable[[dict[str, Any]], Awaitable[None]],
        queue_ui_event: Callable[[Any], None],
    ) -> None:
        case_type = str(args.get("case_type") or "")
        raw_parameters = args.get("parameters")
        parameters = raw_parameters if isinstance(raw_parameters, dict) else {}
        tool_call_id = f"sim-{uuid.uuid4().hex[:8]}"
        label = f"Run {case_type or 'Fimbul'} simulation"

        await send_wire(
            {
                "type": "tool",
                "event": "started",
                "name": "run_simulation",
                "label": label,
                "tool_call_id": tool_call_id,
                "args": {"case_type": case_type, "parameters": parameters},
                "content": None,
            }
        )

        # on_chunk fires synchronously from the kernel's own read loop; queue the
        # chunks and drain them through a consumer task so they reach send_wire
        # (a coroutine) one at a time, in order, while the simulation keeps running.
        chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def on_chunk(chunk: OutputChunk) -> None:
            if chunk.text:
                chunk_queue.put_nowait(chunk.text)

        async def drain_chunks() -> None:
            while True:
                item = await chunk_queue.get()
                if item is None:
                    return
                await send_wire(
                    {
                        "type": "tool",
                        "event": "delta",
                        "name": "run_simulation",
                        "tool_call_id": tool_call_id,
                        "content": item,
                    }
                )

        consumer = asyncio.create_task(drain_chunks())
        try:
            result = await _execute_fimbul_simulation(
                session, simulation_jl_path, case_type, parameters, on_chunk=on_chunk
            )
        except Exception as exc:
            await chunk_queue.put(None)
            await consumer
            await send_wire(
                {
                    "type": "tool",
                    "event": "error",
                    "name": "run_simulation",
                    "tool_call_id": tool_call_id,
                    "content": str(exc),
                }
            )
            return
        await chunk_queue.put(None)
        await consumer

        if result.get("status") != "completed":
            message = str(result.get("message") or "simulation failed")
            await send_wire(
                {
                    "type": "tool",
                    "event": "error",
                    "name": "run_simulation",
                    "tool_call_id": tool_call_id,
                    "content": message,
                }
            )
            return

        _record_simulation_artifact(session, case_type, parameters, result)
        # The new/refreshed report tab: the same mechanism a real tool's artifact
        # gets, since nothing else flushes side outputs outside of a real turn.
        from jutul_agent.interfaces.server.app import artifact_wire_events

        events = session.trace.iter_events()
        latest_artifact = next((e for e in reversed(events) if e.kind == "artifact"), None)
        if latest_artifact is not None:
            for wire in artifact_wire_events([latest_artifact.payload], session.session_id):
                await send_wire(wire)

        summary = _summarize_simulation_result(case_type, parameters, result)
        await send_wire(
            {
                "type": "tool",
                "event": "finished",
                "name": "run_simulation",
                "tool_call_id": tool_call_id,
                "content": summary,
            }
        )
        # The model wasn't involved in running this, so it has no memory of it —
        # fold a note into whatever the user sends next (see app.py's
        # _with_pending_ui_events), the same mechanism well clicks already use.
        queue_ui_event(
            {
                "event": "simulationCompleted",
                "case_type": case_type,
                "parameters": parameters,
                "summary": summary,
            }
        )

    return run_simulation_action


_PROMPT_FRAGMENT = (
    "This app embeds the geothermal-viz map (a MapLibre view of Norwegian "
    "borehole data) next to the chat, always visible. Call `set_map_view` to fly "
    "it to a raw location, `go_to_well` to fly to and select a specific well "
    "by its number or other identifying text, or `go_to_well_park` to do the "
    "same for a well park itself (e.g. when asked about a BTES site as a "
    "whole, not one of its individual wells) — both tell you directly if no "
    "such well/park exists, so trust their return value rather than assuming "
    "success. The "
    "user can also click things on the map themselves (e.g. selecting a well); "
    "when they do, a note describing it is prepended to their next message as "
    "'[UI events since your last message]', so you'll see it as part of what "
    "they sent. Call `run_simulation` to run a Fimbul AGS/BTES simulation; its "
    "results appear as a report tab next to the chat. The user can also run one "
    "from the map's sidebar directly — when they do, you'll see a "
    "`simulationCompleted` UI event the same way. Call `view_simulation_result` "
    "when asked what a result looks like, to actually see the rendered field."
)


def geothermal_viz_capability(map_origin: str, simulation_jl_path: str) -> Capability:
    """The web capability for the geothermal-viz integration: map-control and
    Fimbul-simulation tools.

    ``map_origin`` is geothermal-viz's own server (e.g. ``http://127.0.0.1:8080``)
    — tools that need to check the map's data, like ``go_to_well``, query it
    directly rather than trusting the browser to report back in time.
    ``simulation_jl_path`` is the absolute path to geothermal-viz's
    ``src/simulation.jl``, ``include()``d once into the agent's kernel so its
    Fimbul/parameter-mapping logic runs unmodified.
    """
    return Capability(
        name="geothermal-viz",
        tools=(
            _make_set_map_view_tool,
            lambda session: _make_go_to_well_tool(session, map_origin),
            lambda session: _make_go_to_well_park_tool(session, map_origin),
            lambda session: _make_run_simulation_tool(session, simulation_jl_path),
            lambda session: _make_view_simulation_result_tool(session, simulation_jl_path),
        ),
        prompt_fragment=_PROMPT_FRAGMENT,
        surfaces=("web",),
    )
