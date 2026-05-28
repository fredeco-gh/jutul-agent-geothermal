"""Julia plotting tool: capture Makie figures as session artifacts."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

from langchain_core.tools import InjectedToolCallId, tool

from jutul_agent.session import Session
from jutul_agent.simulators.base import SimulatorAdapter

_BOOTSTRAP_SCRIPT = (Path(__file__).resolve().parent / "julia_plot.jl").read_text(encoding="utf-8")

_FORMAT_MIME = {
    "png": "image/png",
    "svg": "image/svg+xml",
}

_SLOT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _sanitize_slot(slot: str) -> str | None:
    slot = slot.strip()
    if not slot or not _SLOT_RE.match(slot):
        return None
    return slot


def _julia_size_tuple(size: tuple[int, int] | None) -> str:
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


async def _ensure_plot_bootstrap(
    session: Session,
    adapter: SimulatorAdapter,
    ready: set[str],
) -> tuple[str | None, str | None]:
    """Load CairoMakie, JutulAgentPlots, and simulator helpers into the REPL once.

    Returns ``(error, warning)``. ``error`` is non-``None`` when the bootstrap
    failed hard (CairoMakie missing or helper module didn't load); the tool
    should surface it verbatim. ``warning`` is set when simulator-specific
    plot helpers couldn't load — plotting still works without them.
    """

    if session.session_id in ready:
        return None, None

    cairomakie = await session.julia.eval("using CairoMakie")
    if cairomakie.error:
        return (
            f"ERROR: CairoMakie is not available in the {adapter.name} Julia environment. "
            "Run `jutul-agent init --sim <name> --precompile` to refresh the env "
            f"(use `--force` after upgrades). Julia said: {_truncate(cairomakie.error, 300)}",
            None,
        )

    helper = await session.julia.eval(_BOOTSTRAP_SCRIPT)
    if helper.error:
        return f"ERROR: failed to load plot helper: {helper.error}", None

    warning: str | None = None
    helpers_path = adapter.plot_helpers_path
    if helpers_path is not None and helpers_path.is_file():
        sim_helpers = await session.julia.eval(f'include(raw"{helpers_path.as_posix()}")')
        if sim_helpers.error:
            warning = (
                f"WARNING: {adapter.name} plot helpers not loaded "
                f"({_truncate(sim_helpers.error, 200)}). Basic julia_plot still works."
            )

    ready.add(session.session_id)
    return None, warning


def _build_save_call(
    *,
    user_code: str,
    abs_path: Path,
    format: str,
    size: tuple[int, int] | None,
    dpi: int | None,
) -> str:
    """Build the Julia source that evaluates the user code and saves the figure.

    The Figure-check and CairoMakie save call live in ``julia_plot.jl``
    (``JutulAgentPlots.plot_and_save``); we just wrap the user's expression
    in a ``begin … end`` block so it stays a single statement.
    """

    return (
        "JutulAgentPlots.plot_and_save(\n"
        "    begin\n"
        f"{user_code}\n"
        "    end;\n"
        f'    path = raw"{abs_path.as_posix()}",\n'
        f"    format = :{format},\n"
        f"    size = {_julia_size_tuple(size)},\n"
        f"    dpi = {_julia_optional_int(dpi)},\n"
        ")"
    )


def make_julia_plot_tool(session: Session):
    artifacts_dir = session.state_dir / "artifacts"
    plot_ready: set[str] = set()
    adapter = session.simulator

    @tool
    async def julia_plot(
        code: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        caption: str = "",
        format: Literal["png", "svg"] = "png",
        size: tuple[int, int] | None = None,
        dpi: int | None = None,
        slot: str | None = None,
    ) -> str:
        """Evaluate Julia code that returns a Makie `Figure`, save it as an artifact,
        and record it for the session transcript.

        Headless by default: code must evaluate to a `Figure` (not call `display`).
        Prefer native simulator plotters or inline Makie (see `plotting-basics` skill).
        JutulDarcy/Fimbul also load thin helpers: `well_rates_figure(wd)`,
        `cell_field_heatmap(g, field)`.

        Args:
            code: Julia code expected to produce a Makie `Figure`.
            caption: Optional caption shown in the transcript.
            format: Output format (`png` or `svg`).
            size: Optional `(width, height)` in pixels before saving.
            dpi: Optional DPI for PNG output.
            slot: Optional stable name (`artifacts/<slot>.<ext>`); overwrites on reuse.

        Returns:
            Confirmation with the artifact path, or an error description.
        """
        err, warning = await _ensure_plot_bootstrap(session, adapter, plot_ready)
        if err is not None:
            return err

        safe_slot = _sanitize_slot(slot) if slot else None
        if slot and safe_slot is None:
            return (
                "ERROR: invalid slot name (use letters, digits, '.', '_', '-'; "
                "max 64 characters)."
            )

        if safe_slot:
            rel_path = f"artifacts/{safe_slot}.{format}"
            plot_id = safe_slot
        else:
            plot_id = uuid.uuid4().hex[:12]
            rel_path = f"artifacts/plot-{plot_id}.{format}"

        abs_path = session.state_dir / rel_path
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        result = await session.julia.eval(
            _build_save_call(
                user_code=code, abs_path=abs_path, format=format, size=size, dpi=dpi,
            )
        )
        if result.error:
            return f"ERROR: {result.error}"

        session.trace.append(
            "artifact",
            {
                "path": rel_path,
                "mime": _FORMAT_MIME[format],
                "caption": caption or (safe_slot or f"plot-{plot_id}"),
                "tool_call_id": tool_call_id,
                "format": format,
                "size_px": list(size) if size is not None else None,
                "dpi": dpi,
                "slot": safe_slot,
                "source_code": code,
            },
        )

        parts = [f"saved plot to {rel_path} (format={format})"]
        if safe_slot:
            parts.append(f"slot={safe_slot}")
        if size is not None:
            parts.append(f"size={size[0]}x{size[1]}")
        if warning:
            parts.append(warning)
        return "; ".join(parts)

    return julia_plot
