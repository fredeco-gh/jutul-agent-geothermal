"""Deep Agents tools that wrap jutul-agent core operations.

Only tools that bridge something the stock deep-agents tools cannot do
live here. Generic file/shell access is handled by deep-agents'
``read_file`` / ``write_file`` / ``edit_file`` / ``execute`` against the
workspace backend.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

from jutul_agent.paths import resolve_workspace_path, workspace_root
from jutul_agent.session import Session

if TYPE_CHECKING:
    from jutul_agent.agent.packages_backend import PackageMounts

# Julia can't reload a module already loaded this session, so a new version only
# takes effect in a fresh process. This is the one case where a restart is unavoidable.
_STALE_LOAD_RE = re.compile(r"restart julia to access the new version", re.IGNORECASE)
_STALE_LOAD_HINT = (
    "\n\n[harness] The new version won't load until Julia restarts (`reset_julia`), "
    "which clears all REPL state. Reset clears all REPL state, so do it when you actually "
    "need the new version."
)

# A just-added package failing to precompile is usually the env holding it at an
# old version; re-resolving the whole env normally lifts that.
_PRECOMPILE_FAIL_RE = re.compile(r"failed to precompile", re.IGNORECASE)
_PRECOMPILE_FAIL_HINT = (
    "\n\n[harness] If you just added the package, run `Pkg.update()` to re-resolve "
    "the env to newer compatible versions and retry. Treat it as a real "
    "incompatibility only if it still fails after that."
)

# `PkgId(...) not found` means the session's loaded modules no longer match the
# env, typically after a mid-session package change.
_MODULE_DESYNC_RE = re.compile(r"PkgId\(.*?\) not found", re.IGNORECASE)
_MODULE_DESYNC_HINT = (
    "\n\n[harness] The session's loaded modules are out of sync with the "
    "environment, usually after a mid-session install/update. `reset_julia` gives "
    "a fresh session that loads cleanly from the manifest. Reset clears all REPL "
    "state, so use it deliberately."
)


def make_julia_eval_tool(session: Session, *, package_mounts: PackageMounts | None = None):
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
        # A `Pkg.add`/`Pkg.develop` here changes the env; keep /packages/ in
        # sync so the new package is browsable. Cheap unless the
        # manifest actually changed, and never allowed to break the eval.
        if package_mounts is not None:
            with contextlib.suppress(Exception):
                await package_mounts.refresh()
        text = result.output if not result.error else f"ERROR: {result.error}"
        if _STALE_LOAD_RE.search(text):
            text += _STALE_LOAD_HINT
        if _PRECOMPILE_FAIL_RE.search(text):
            text += _PRECOMPILE_FAIL_HINT
        if _MODULE_DESYNC_RE.search(text):
            text += _MODULE_DESYNC_HINT
        return text

    return julia_eval


def make_reset_julia_tool(session: Session):
    @tool
    async def reset_julia() -> str:
        """Restart Julia with a fresh, empty session.

        A recovery tool, not a routine one. It clears ALL state — loaded packages,
        variables, and anything you built (models, simulation results) — and the
        next run pays compilation again. Use it deliberately, mainly when a module
        must be reloaded (Julia can't swap a module already loaded this session,
        e.g. after installing or updating one). Prefer installing packages before
        building up expensive state, and re-run your `using`/setup afterward.

        Returns:
            Confirmation that the session was restarted, or an error description.
        """
        result = await session.julia.reset()
        if result.error:
            return f"ERROR: failed to reset Julia: {result.error}"
        return (
            "Julia restarted with a fresh session. All previous state "
            "(loaded packages, variables, results) was cleared."
        )

    return reset_julia


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
            ", ".join(f"{k}={_fmt_metric(v)}" for k, v in (metrics or {}).items()) or "no metrics"
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
        output_path: str | None = None,
    ) -> str:
        """Write an HTML report for the session and open it in the browser.

        Use this when the user asks for a written summary of an investigation
        run. The HTML embeds the supplied narrative, plus any attempts you
        logged with ``record_attempt`` (rendered as a tree with metrics and
        any plot artifacts they referenced). If no attempts were logged, only
        the narrative is shown.

        Args:
            narrative: Markdown prose. You write this yourself, summarising
                what was tried, what worked, and what to do next.
            title: Optional page title (defaults to the simulator name).
            output_path: Where to write the HTML report. Defaults to the
                session output directory
                (``jutul-agent-output/sessions/<id>/report.html``).
        """
        from jutul_agent.open_file import open_path
        from jutul_agent.transcript.report import render_report

        if output_path is None:
            out = session.output_dir / "report.html"
        else:
            out = resolve_workspace_path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        ws = workspace_root()
        artifact_dirs = [
            ws,
            ws / "artifacts",
            session.output_dir / "artifacts",
            session.state_dir / "artifacts",
        ]

        render_report(
            session.trace.iter_events(),
            out,
            narrative_markdown=narrative,
            title=title,
            session_id=session.session_id,
            simulator=session.simulator.display_name,
            artifact_dirs=artifact_dirs,
        )
        open_path(out)
        return str(out)

    return write_report
