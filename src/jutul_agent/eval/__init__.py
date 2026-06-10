"""The eval harness: run jutul-agent under Inspect AI and grade the trace.

This package is the harness: the solver, the scorers, and RunConfig.
jutul-bench is the benchmark built on it; its public suites live in
:mod:`jutul_agent.eval.tasks` and run via ``jutul-agent eval``::

    uv run jutul-agent eval canary

The agent under test runs unchanged (its own tools, skills, prompt, and
trace) inside Inspect's agent bridge, which routes every model call to the
eval's ``--model``. Scorers grade the final answer plus the session trace
and workspace, so a pass means the agent did the work, not just said so.

Requires the ``eval`` extra: ``uv sync --extra eval``.
"""

from __future__ import annotations

try:
    import inspect_ai  # noqa: F401
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError("jutul_agent.eval requires the 'eval' extra (uv sync --extra eval).") from exc
