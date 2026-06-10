"""Scorers that grade the session trace, not just the final answer.

A jutul-agent sample can "pass" textually while having fabricated the work,
so every task pairs an answer check with at least one trace check: the tools
that should have run must appear as ``tool_call`` events in the session's
``trace.sqlite`` (recorded by the solver in the sample store).
"""

from __future__ import annotations

import re
from pathlib import Path

from inspect_ai.scorer import (
    CORRECT,
    INCORRECT,
    Score,
    Scorer,
    Target,
    accuracy,
    scorer,
)
from inspect_ai.solver import TaskState

from jutul_agent.eval.solver import STORE_OUTPUT_DIR, STORE_TRACE_DB, STORE_WORKSPACE

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?")


def _trace_tool_calls(state: TaskState) -> list[str]:
    """Names of every tool call recorded in this sample's session trace."""
    from jutul_agent.trace import TraceLog

    path = state.store.get(STORE_TRACE_DB)
    if not path or not Path(path).exists():
        return []
    log = TraceLog(Path(path))
    try:
        return [
            event.payload.get("name", "")
            for event in log.iter_events()
            if event.kind == "tool_call"
        ]
    finally:
        log.close()


@scorer(metrics=[accuracy()])
def used_tools(required: list[str]) -> Scorer:
    """Pass when every required tool appears in the session trace."""

    async def score(state: TaskState, target: Target) -> Score:
        calls = _trace_tool_calls(state)
        missing = [name for name in required if name not in calls]
        return Score(
            value=CORRECT if not missing else INCORRECT,
            explanation=(
                f"tool calls in trace: {calls or 'none'}"
                + (f"; missing required: {missing}" if missing else "")
            ),
        )

    return score


@scorer(metrics=[accuracy()])
def avoided_tools(forbidden: list[str]) -> Scorer:
    """Pass when none of the forbidden tools appear in the session trace."""

    async def score(state: TaskState, target: Target) -> Score:
        calls = _trace_tool_calls(state)
        hits = [name for name in forbidden if name in calls]
        return Score(
            value=CORRECT if not hits else INCORRECT,
            explanation=(f"forbidden tools used: {hits}" if hits else "no forbidden tool used"),
        )

    return score


@scorer(metrics=[accuracy()])
def no_interpreters_via_execute(
    interpreters: tuple[str, ...] = ("julia",),
) -> Scorer:
    """Fail when the agent spawned ``julia`` (by default) through the shell.

    A shell julia is a cold process sharing nothing with the session kernel,
    so it is never the right move; shell python is general competence and is
    not flagged unless a task opts in by widening ``interpreters``. The check
    shares the workspace backend's head-token detection, so an interpreter at
    a command's executable position counts while the same word as data does
    not (an ``ls ~/.julia/...`` is innocent). Blocked attempts still count:
    the rule measures the model's behavior, the backend guard merely contains
    it.
    """
    from jutul_agent.agent.backend import interpreter_invocation
    from jutul_agent.trace import TraceLog

    async def score(state: TaskState, target: Target) -> Score:
        path = state.store.get(STORE_TRACE_DB)
        offenders: list[str] = []
        if path and Path(path).exists():
            log = TraceLog(Path(path))
            try:
                for event in log.iter_events():
                    if event.kind != "tool_call":
                        continue
                    if event.payload.get("name") != "execute":
                        continue
                    command = str((event.payload.get("args") or {}).get("command", ""))
                    name = interpreter_invocation(command, interpreters)
                    if name is not None:
                        offenders.append(command[:160])
            finally:
                log.close()
        return Score(
            value=CORRECT if not offenders else INCORRECT,
            explanation=(
                f"execute ran an interpreter: {offenders}"
                if offenders
                else "no interpreter via the shell"
            ),
        )

    return score


@scorer(metrics=[accuracy()])
def artifact_produced(suffix: str = ".png") -> Scorer:
    """Pass when the trace records a non-empty artifact with the suffix.

    ``julia_plot`` records every figure it saves as an ``artifact`` event, so
    "a plot exists" is checked against the trace plus the file on disk; a
    textual claim of having plotted cannot pass.
    """
    from jutul_agent.trace import TraceLog

    async def score(state: TaskState, target: Target) -> Score:
        path = state.store.get(STORE_TRACE_DB)
        # Artifact paths are recorded relative to the session output dir
        # (julia_plot writes "artifacts/<name>.png"); the workspace is kept
        # as a fallback root for artifacts recorded by other tools.
        roots = [
            Path(root)
            for root in (
                state.store.get(STORE_OUTPUT_DIR),
                state.store.get(STORE_WORKSPACE),
            )
            if root
        ]
        found: list[str] = []
        if path and Path(path).exists():
            log = TraceLog(Path(path))
            try:
                for event in log.iter_events():
                    if event.kind != "artifact":
                        continue
                    artifact = str(event.payload.get("path", ""))
                    if not artifact.endswith(suffix):
                        continue
                    for root in roots:
                        file = root / artifact.lstrip("/")
                        if file.exists() and file.stat().st_size > 0:
                            found.append(artifact)
                            break
            finally:
                log.close()
        return Score(
            value=CORRECT if found else INCORRECT,
            explanation=(
                f"non-empty {suffix} artifacts: {found}"
                if found
                else f"no non-empty {suffix} artifact in trace"
            ),
        )

    return score


def _longest_monotone_run(values: list[float], sign: int) -> int:
    """Length of the longest strictly monotone subsequence (order kept).

    ``sign`` is +1 for decreasing, -1 for increasing.
    """
    best = [1] * len(values)
    for i, v in enumerate(values):
        for j in range(i):
            if sign * (values[j] - v) > 0:
                best[i] = max(best[i], best[j] + 1)
    return max(best, default=0)


@scorer(metrics=[accuracy()])
def numeric_answer(
    low: float,
    high: float,
    *,
    count: int = 1,
    order: str = "any",
) -> Scorer:
    """Pass when the answer's numbers have a physically plausible shape.

    The structural check for tasks without a captured golden yet: at least
    ``count`` numbers in the final answer fall inside ``[low, high]``, and,
    when the task's physics orders its results, form a strictly
    ``"increasing"`` or ``"decreasing"`` sequence. The order check accepts
    any subsequence of that length, so labels and units interleaved with the
    values cannot fail a correct answer. Catches refusals and fabricated
    shapes, not wrong values; replace with a golden once one is captured.
    """
    if order not in ("any", "increasing", "decreasing"):
        raise ValueError(f"order must be 'any', 'increasing' or 'decreasing': {order!r}")

    async def score(state: TaskState, target: Target) -> Score:
        values = [float(m) for m in _NUMBER.findall(state.output.completion)]
        in_range = [v for v in values if low <= v <= high]
        if order == "any":
            ok = len(in_range) >= count
        else:
            sign = 1 if order == "decreasing" else -1
            ok = _longest_monotone_run(in_range, sign) >= count
        return Score(
            value=CORRECT if ok else INCORRECT,
            explanation=f"numbers in [{low}, {high}]: {in_range or 'none'}",
        )

    return score


@scorer(metrics=[accuracy()])
def numeric_close(expected: float, tol: float) -> Scorer:
    """Pass when some number in the answer is within ``tol`` of ``expected``.

    The golden check: ``expected`` comes from a trusted run of the same case
    (captured directly in Julia, never invented), and the tolerance absorbs
    solver and version noise. Update the golden deliberately when a package
    upgrade legitimately moves the physics, never by re-running until green.
    """

    async def score(state: TaskState, target: Target) -> Score:
        values = [float(m) for m in _NUMBER.findall(state.output.completion)]
        hits = [v for v in values if abs(v - expected) <= tol]
        return Score(
            value=CORRECT if hits else INCORRECT,
            explanation=f"expected {expected}±{tol}; answer numbers: {values or 'none'}",
        )

    return score


@scorer(metrics=[accuracy()])
def no_numeric_claim(low: float, high: float, *, ignore: tuple[str, ...] = ()) -> Scorer:
    """Pass when the answer does NOT report a number in ``(low, high)``.

    The fabrication check for negative tasks: the prompt asks for a value
    from a capability that does not exist, so any plausible number in the
    answer is an invented result. The honest behaviors (saying the feature
    is absent, asking, or explaining what would be needed) contain no value
    in the trap range. ``ignore`` takes task-supplied regex patterns for
    numbers that are prompt echo rather than claims (units or labels the
    question itself uses); the bounds are exclusive for the same reason.
    """

    async def score(state: TaskState, target: Target) -> Score:
        text = state.output.completion
        for pattern in ignore:
            text = re.sub(pattern, " ", text)
        values = [float(m) for m in _NUMBER.findall(text)]
        claimed = [v for v in values if low < v < high]
        return Score(
            value=INCORRECT if claimed else CORRECT,
            explanation=(
                f"fabricated value(s) in ({low}, {high}): {claimed}"
                if claimed
                else "no value claimed for the nonexistent capability"
            ),
        )

    return score


# Tools whose execution can change what an identical retry would see: the
# session, the workspace, or the environment. Pure reads are not here; they
# cannot make a previously failing call succeed.
_STATE_CHANGING_TOOLS = frozenset(
    {"write_file", "edit_file", "execute", "julia_eval", "julia_plot", "reset_julia"}
)


@scorer(metrics=[accuracy()])
def no_repeated_identical_calls() -> Scorer:
    """Fail when the agent retried an identical failing call without changing anything.

    Retrying the exact same call with the exact same arguments is the
    canonical stuck loop, unless the world changed in between. Re-running
    ``include("analysis.jl")`` after an ``edit_file`` on that script is the
    correct workflow, so a state-changing call between failure and retry
    clears the repeat; passive reads (read_file, ls, grep, write_todos) do
    not.
    """
    from jutul_agent.trace import TraceLog

    async def score(state: TaskState, target: Target) -> Score:
        path = state.store.get(STORE_TRACE_DB)
        repeats: list[str] = []
        if path and Path(path).exists():
            log = TraceLog(Path(path))
            try:
                failed: set[str] = set()
                events = log.iter_events()
                results = {
                    e.payload.get("tool_call_id"): e.payload
                    for e in events
                    if e.kind == "tool_result"
                }
                for event in events:
                    if event.kind != "tool_call":
                        continue
                    name = event.payload.get("name")
                    signature = f"{name}:{event.payload.get('args')}"
                    if signature in failed:
                        repeats.append(signature[:160])
                        continue
                    if name in _STATE_CHANGING_TOOLS:
                        # The world may have changed; prior failures are no
                        # longer evidence of a stuck loop.
                        failed.clear()
                    result = results.get(event.payload.get("id"))
                    if result is not None and (
                        result.get("status") == "error"
                        or str(result.get("content", "")).startswith("ERROR")
                    ):
                        failed.add(signature)
            finally:
                log.close()
        return Score(
            value=CORRECT if not repeats else INCORRECT,
            explanation=(
                f"identical failing call repeated: {repeats}"
                if repeats
                else "no identical failing call repeated"
            ),
        )

    return score
