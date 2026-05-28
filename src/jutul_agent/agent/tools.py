"""Deep Agents tools that wrap jutul-agent core operations.

Only tools that bridge something the stock deep-agents tools cannot do
live here. Generic file/shell access is handled by deep-agents'
``read_file`` / ``write_file`` / ``edit_file`` / ``execute`` against the
workspace backend.
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.tools import tool

from jutul_agent.paths import resolve_workspace_path, workspace_root
from jutul_agent.session import Session


def make_julia_eval_tool(session: Session):
    @tool
    async def julia_eval(code: str) -> str:
        """Evaluate Julia code in a persistent REPL session.

        State (variables, functions, loaded packages) persists across calls.
        Compilation cost is paid once per package per session.

        Args:
            code: Julia code to evaluate. Can be multi-line.

        Returns:
            REPL-style output: printed output plus the return value, or an
            error description if the evaluation failed.
        """
        result = await session.julia.eval(code)
        if result.error:
            return f"ERROR: {result.error}"
        return result.output

    return julia_eval


def make_record_attempt_tool(session: Session):
    # Session-scoped attempt counter; the tool returns 1-based indices so the
    # agent can refer to "attempt #N" in user-visible output. We track ids ↦
    # index in a dict so the parent lookup is O(1) per call.
    indices: dict[str, int] = {}

    @tool
    async def record_attempt(
        rationale: str,
        metrics: dict[str, float] | None = None,
        parameters_changed: dict[str, Any] | None = None,
        parent_attempt_id: str | None = None,
        candidate_path: str | None = None,
        plot_artifact_path: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Log one step of an iterative investigation to the session trace.

        Call this once **per tried configuration**, not once at the end with
        everything bundled in. The baseline is itself an attempt (the
        "root"); each hypothesis you actually evaluate is its own call with
        the previous one as ``parent_attempt_id``.

        Pair every call with ``julia_plot`` and pass the resulting
        ``artifacts/<slot>.<format>`` path as ``plot_artifact_path`` so the
        report can embed one figure per attempt. See the
        ``investigation-loop`` skill.

        Args:
            rationale: Short reason for this step.
            metrics: Named scalar metrics (optional).
            parameters_changed: Mapping of param paths to new values or
                ``(old, new)`` pairs (optional).
            parent_attempt_id: Id returned by an earlier call. Omit for
                the root (baseline) attempt.
            candidate_path: Workspace path to the file being edited (optional).
            plot_artifact_path: Workspace-relative path of the comparison
                plot created with ``julia_plot`` for this attempt — usually
                ``artifacts/<slot>.png``.
            notes: Free-form short label (optional).

        Returns ``"attempt #N (parent #M) · key=value · id=<uuid>"`` — the
        last token is the id to pass back as ``parent_attempt_id`` next time.
        """
        attempt_id = str(uuid.uuid4())
        index = len(indices) + 1
        indices[attempt_id] = index
        parent_index = indices.get(parent_attempt_id) if parent_attempt_id else None

        session.trace.append(
            "attempt",
            {
                "id": attempt_id,
                "parent_id": parent_attempt_id,
                "rationale": rationale,
                "parameters_changed": dict(parameters_changed or {}),
                "metrics": dict(metrics or {}),
                "candidate_path": candidate_path,
                "plot_artifact_path": plot_artifact_path,
                "notes": notes,
            },
        )

        metric_str = (
            ", ".join(f"{k}={_fmt_metric(v)}" for k, v in (metrics or {}).items())
            or "no metrics"
        )
        parent_str = f" (parent #{parent_index})" if parent_index else ""
        return f"attempt #{index}{parent_str} · {metric_str} · id={attempt_id}"

    return record_attempt


def _fmt_metric(value: Any) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{f:.4g}"


def make_write_report_tool(session: Session):
    @tool
    async def write_report(
        narrative: str,
        title: str | None = None,
        output_path: str = "experiments/report.html",
    ) -> str:
        """Write an HTML report for the session.

        Use this when the user asks for a written summary of an investigation
        run. The HTML embeds the supplied narrative, plus any attempts you
        logged with ``record_attempt`` (rendered as a tree with metrics and
        any plot artifacts they referenced). If no attempts were logged, only
        the narrative is shown.

        Args:
            narrative: Markdown prose. You write this yourself, summarising
                what was tried, what worked, and what to do next.
            title: Optional page title (defaults to the simulator name).
            output_path: Where to write the HTML report.
        """
        from jutul_agent.transcript.report import render_report

        out = resolve_workspace_path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        ws = workspace_root()
        artifact_dirs = [ws, ws / "artifacts", session.state_dir / "artifacts"]

        render_report(
            session.trace.iter_events(),
            out,
            narrative_markdown=narrative,
            title=title,
            session_id=session.session_id,
            simulator=session.simulator.display_name,
            artifact_dirs=artifact_dirs,
        )
        return str(out)

    return write_report
