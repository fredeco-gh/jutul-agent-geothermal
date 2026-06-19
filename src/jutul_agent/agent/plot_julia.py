"""Julia plotting tool: capture Makie figures as session artifacts.

Plotting always runs on GLMakie. The tool opens a live window for the user only
when the session can show one (an interactive run with a display); otherwise it
renders offscreen to a PNG. Headless Linux still renders, via the xvfb-wrapped
Julia process (see the kernel). If GLMakie cannot load at all, the tool
returns a clear error rather than degrading to a backend where the native
plotters do not work.

When ``view=True`` the saved PNG is downscaled and returned to the model as a
multimodal image block, so the agent can see the plot it just made.
"""

from __future__ import annotations

import base64
import io
import re
import uuid
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import InjectedToolCallId, tool

from jutul_agent.paths import workspace_root
from jutul_agent.session import Session
from jutul_agent.simulators.base import SimulatorAdapter

_SLOT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")

# Longest-edge cap (px) for the downscaled image fed back to the model. Keeps
# per-image token cost bounded across an investigation loop.
_VIEW_MAX_EDGE = 1024

_INVALID_SLOT = "ERROR: invalid slot name (use letters, digits, '.', '_', '-'; max 64 characters)."


def _sanitize_slot(slot: str) -> str | None:
    slot = slot.strip()
    if not slot or not _SLOT_RE.match(slot):
        return None
    return slot


def _julia_size_tuple(size: list[int] | None) -> str:
    if size is None:
        return "nothing"
    return f"({int(size[0])}, {int(size[1])})"


def _julia_optional_int(value: int | None) -> str:
    if value is None:
        return "nothing"
    return str(int(value))


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "..."


async def _load_plot_backend(session: Session, adapter: SimulatorAdapter) -> str | None:
    """Load GLMakie and the capture helpers into the REPL once per session.

    Returns an error string, or ``None`` on success. The error is actionable when
    GLMakie can't load: the tool drives GLMakie for everything, so without it
    plotting is unavailable here.
    """

    gl = await session.julia.eval("using GLMakie")
    if gl.error:
        return (
            f"ERROR: GLMakie could not load in the {adapter.name} Julia environment, so "
            "plotting is unavailable here. On a headless Linux server install xvfb "
            "(jutul-agent auto-detects it) or a GL driver; otherwise rebuild the env with "
            f"`jutul-agent init --sim {adapter.name} --precompile --force`. "
            f"Julia said: {_truncate(gl.error, 300)}"
        )

    # The capture helpers (JutulAgent.JutulAgentPlots) ship precompiled in the
    # JutulAgent package, so this just loads it rather than eval-ing a script.
    helper = await session.julia.eval("using JutulAgent")
    if helper.error:
        return f"ERROR: failed to load JutulAgent plot helpers: {helper.error}"

    return None


def _build_render_call(
    *,
    user_code: str,
    abs_path: Path,
    size: list[int] | None,
    dpi: int | None,
    open_window: bool,
    window_key: str,
) -> str:
    """Julia to activate GLMakie, evaluate the user code, and capture the figure.

    One begin/end block so the backend is active before the plotter runs (native
    plotters dispatch on the active backend) and the figure is captured whether the
    code returns it or opens a window. A window is keyed by window_key (the plot's
    slot) so it can be refreshed, recaptured, or closed later.
    """

    visible = "true" if open_window else "false"
    return (
        "begin\n"
        f"    GLMakie.activate!(visible = {visible})\n"
        "    local _jap_prev = JutulAgent.JutulAgentPlots._current_fig()\n"
        "    local _jap_value = begin\n"
        f"{user_code}\n"
        "    end\n"
        "    JutulAgent.JutulAgentPlots.capture(_jap_value;\n"
        f'        path = raw"{abs_path.as_posix()}",\n'
        f"        size = {_julia_size_tuple(size)},\n"
        f"        dpi = {_julia_optional_int(dpi)},\n"
        f"        open_window = {visible},\n"
        f'        window_key = raw"{window_key}",\n'
        "        prev_figure = _jap_prev,\n"
        "    )\n"
        "end"
    )


def _encode_view_image(png_path: Path, max_edge: int = _VIEW_MAX_EDGE) -> str:
    """Downscale png_path to max_edge on its longest side and return base64 PNG."""
    from PIL import Image

    with Image.open(png_path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_edge, max_edge))  # only shrinks; preserves aspect
        buf = io.BytesIO()
        im.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _finalize(
    session: Session,
    *,
    abs_path: Path,
    rel_path: str,
    caption: str,
    tool_call_id: str,
    size: list[int] | None,
    dpi: int | None,
    slot: str | None,
    source_code: str,
    view: bool,
    lead: str,
    extra_parts: list[str],
) -> str | list[dict[str, Any]]:
    """Record the artifact and build the reply (text, or text plus image when view).

    Shared by plot_julia and recapture_plot. The PNG artifact is always recorded
    for the transcript and report; the live Makie window or the TUI's open-artifact
    action is how the user actually sees it.
    """

    session.trace.append(
        "artifact",
        {
            "path": rel_path,
            "mime": "image/png",
            "caption": caption or slot or rel_path.rsplit("/", 1)[-1],
            "tool_call_id": tool_call_id,
            "format": "png",
            "size_px": list(size) if size is not None else None,
            "dpi": dpi,
            "slot": slot,
            "source_code": source_code,
        },
    )
    try:
        shown = abs_path.relative_to(workspace_root()).as_posix()
    except ValueError:
        shown = abs_path.as_posix()
    parts = [f"{lead} {shown}", *extra_parts]
    summary = "; ".join(p for p in parts if p)
    if view:
        try:
            b64 = _encode_view_image(abs_path)
        except Exception as exc:  # vision is best-effort; never fail the plot
            return f"{summary}; (could not attach image for viewing: {exc})"
        return [
            {"type": "text", "text": summary},
            {"type": "image", "mime_type": "image/png", "base64": b64},
        ]
    return summary


def make_plot_julia_tool(session: Session):
    artifacts_dir = session.output_dir / "artifacts"
    adapter = session.simulator
    ready: list[bool] = []  # one-shot memo: the backend loads once per session

    async def ensure_ready() -> str | None:
        """Load the backend on first use; return an error string if it can't load."""
        if ready:
            return None
        err = await _load_plot_backend(session, adapter)
        if err is None:
            ready.append(True)
        return err

    @tool
    async def plot_julia(
        code: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        caption: str = "",
        size: list[int] | None = None,
        dpi: int | None = None,
        slot: str | None = None,
        view: bool = False,
        window: bool = True,
    ) -> str | list[dict[str, Any]]:
        """Run Julia plotting code and turn the figure into something the user can see.

        `plot_julia` is the bridge between a figure drawn in the REPL and a shareable
        result: it saves the figure as a PNG artifact (recorded in the transcript and
        report) and, in an interactive session, opens a live Makie window. Build
        figures only here, never in `run_julia` (that draws a figure nobody can see).

        Prefer your simulator's documented native plotters (the `plotting-basics` and
        per-simulator skills name them); otherwise build a `Figure` inline. Just run
        the code: you don't need to return a `Figure` or avoid `display`, since the
        tool captures whatever figure your code produced. Plotting runs on GLMakie
        like normal Julia.

        Give related plots a stable `slot`: the same `slot` refreshes one window
        in place (good for iterating), distinct slots get distinct windows, and
        `recapture_plot(slot=...)` / `close_plots(slot=...)` address that window.

        Args:
            code: Julia plotting code (a native plotter call or inline figure).
            caption: Optional caption shown in the transcript.
            size: Optional `(width, height)` in pixels.
            dpi: Optional DPI for the PNG.
            slot: Stable name (`artifacts/<slot>.png`) and window key; reuse it to
                refresh the same plot/window.
            view: Also return the downscaled image so you can see it, to verify a
                fit or diagnose. Not needed for every plot.
            window: Open a live window for the user (default true). Set false to
                compute/inspect a plot without opening a window for them.

        Returns:
            A confirmation string, or, when `view`, a text+image content list.
        """
        err = await ensure_ready()
        if err is not None:
            return err

        safe_slot = _sanitize_slot(slot) if slot else None
        if slot and safe_slot is None:
            return _INVALID_SLOT

        if safe_slot:
            rel_path = f"artifacts/{safe_slot}.png"
            plot_id = safe_slot
        else:
            plot_id = uuid.uuid4().hex[:12]
            rel_path = f"artifacts/plot-{plot_id}.png"

        abs_path = session.output_dir / rel_path
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        open_window = window and session.open_windows
        window_key = safe_slot or plot_id
        result = await session.julia.eval(
            _build_render_call(
                user_code=code,
                abs_path=abs_path,
                size=size,
                dpi=dpi,
                open_window=open_window,
                window_key=window_key,
            )
        )
        if result.error:
            return f"ERROR: {result.error}"

        extra: list[str] = []
        if safe_slot:
            extra.append(f"slot={safe_slot}")
        if size is not None:
            extra.append(f"size={size[0]}x{size[1]}")
        if open_window:
            extra.append("opened window")
        return _finalize(
            session,
            abs_path=abs_path,
            rel_path=rel_path,
            caption=caption,
            tool_call_id=tool_call_id,
            size=size,
            dpi=dpi,
            slot=safe_slot,
            source_code=code,
            view=view,
            lead="saved plot to",
            extra_parts=extra,
        )

    return plot_julia


def make_recapture_tool(session: Session):
    artifacts_dir = session.output_dir / "artifacts"

    @tool
    async def recapture_plot(
        tool_call_id: Annotated[str, InjectedToolCallId],
        caption: str = "",
        view: bool = True,
        slot: str | None = None,
        size: list[int] | None = None,
    ) -> str | list[dict[str, Any]]:
        """Snapshot an open plot window at its CURRENT view and show it to you.

        Use this when the user has rotated/zoomed/stepped a live window and asks
        what it looks like now. It re-renders that window's figure at its current
        camera/timestep and (by default) returns the downscaled image so you can
        describe the new view.

        `slot` selects **which** window: the slot you gave that plot in
        `plot_julia`. Omit it for the most recently opened/refreshed window. You
        can't drive the window (advance its timestep yourself); you only snapshot
        what the user currently has. Errors if there's no such open window.

        Args:
            caption: Optional caption shown in the transcript.
            view: Return the image so you can see it (default true; that's the point).
            slot: Which window to recapture (its slot); omit for the most recent.
            size: Optional `(width, height)` in pixels.

        Returns:
            A confirmation string, or, when `view`, a text+image content list.
        """
        safe_slot = _sanitize_slot(slot) if slot else None
        if slot and safe_slot is None:
            return _INVALID_SLOT
        rel_path = f"artifacts/recapture-{uuid.uuid4().hex[:12]}.png"
        abs_path = session.output_dir / rel_path
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Re-activate GLMakie offscreen before re-rendering the stored window
        # figure. The try-guard lets a session with no open window report cleanly.
        call = (
            "begin\n"
            "    try; GLMakie.activate!(visible = false); catch; end\n"
            "    JutulAgent.JutulAgentPlots.recapture(;\n"
            f'        key = raw"{safe_slot or ""}",\n'
            f'        path = raw"{abs_path.as_posix()}",\n'
            f"        size = {_julia_size_tuple(size)},\n"
            "    )\n"
            "end"
        )
        result = await session.julia.eval(call)
        if result.error:
            return f"ERROR: {result.error}"

        extra: list[str] = []
        if safe_slot:
            extra.append(f"window={safe_slot}")
        if size is not None:
            extra.append(f"size={size[0]}x{size[1]}")
        return _finalize(
            session,
            abs_path=abs_path,
            rel_path=rel_path,
            caption=caption,
            tool_call_id=tool_call_id,
            size=size,
            dpi=None,
            slot=None,
            source_code=f"recapture_plot(slot={slot!r})" if slot else "recapture_plot()",
            view=view,
            lead="recaptured view to",
            extra_parts=extra,
        )

    return recapture_plot


def make_close_plots_tool(session: Session):
    @tool
    async def close_plots(slot: str | None = None) -> str:
        """Close interactive plot windows.

        Pass a `slot` to close that one window; omit to close all of them. Use it
        when the user asks to close/clear plot windows, or to tidy up.

        Args:
            slot: The window to close (its slot); omit to close all.

        Returns:
            A short confirmation.
        """
        safe_slot = _sanitize_slot(slot) if slot else None
        if slot and safe_slot is None:
            return _INVALID_SLOT
        result = await session.julia.eval(
            f'JutulAgent.JutulAgentPlots.close_windows(raw"{safe_slot or ""}")'
        )
        if result.error:
            return f"ERROR: {result.error}"
        return f"closed plot window: {safe_slot}" if safe_slot else "closed all plot windows"

    return close_plots
