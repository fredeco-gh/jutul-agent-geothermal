"""Tests for the investigation report HTML renderer."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fakes import make_event
from jutul_agent.transcript.report import render_report


def _attempt(
    eid: int,
    attempt_id: str,
    *,
    parent_id: str | None = None,
    rationale: str,
    metrics: dict,
    notes: str | None = None,
    plot: str | None = None,
) -> dict:
    return {
        "id": attempt_id,
        "parent_id": parent_id,
        "rationale": rationale,
        "parameters_changed": {"param.a": [1.0, 1.1]},
        "metrics": metrics,
        "notes": notes,
        "plot_artifact_path": plot,
    }


def test_render_report_minimal_shell() -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(
            2,
            "attempt",
            _attempt(2, "a1", rationale="baseline", metrics={"rmse": 0.05}),
        ),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.html"
        doc = render_report(
            events,
            out,
            narrative_markdown="## Summary\n\nDone.",
            session_id="abc",
            simulator="BattMo",
        )
        assert doc.startswith("<!doctype html>")
        # Title defaults to a generic investigation-report heading; explicit
        # title arg overrides it.
        assert "BattMo investigation report" in doc
        assert '<section class="narrative">' in doc
        # The page is now split into "Exploration map" + "Attempt details"
        # sections (instead of one monolithic "Attempts" section).
        assert '<section class="exploration">' not in doc
        assert '<section class="attempt-details">' in doc
        assert "<script" not in doc
        assert "cytoscape" not in doc


def test_render_report_writes_transcript_beside_report(tmp_path) -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(2, "message_user", {"content": "run it"}),
    ]
    out = tmp_path / "experiments" / "report.html"
    doc = render_report(events, out, session_id="abc", simulator="BattMo")

    transcript = out.parent / "transcript.html"
    assert transcript.exists()  # generated so the footer link resolves
    assert 'href="transcript.html"' in doc  # same-dir link, not ../ or trace.sqlite
    assert "trace.sqlite" not in doc


def test_render_report_hero_stat_and_tones(tmp_path) -> None:
    # Baseline at rmse=0.05; child improves; grandchild regresses; second
    # branch stays neutral (no metric on the second child). Tone classes
    # must reflect each step relative to its parent.
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(2, "attempt", _attempt(2, "a1", rationale="baseline", metrics={"rmse": 0.05})),
        make_event(
            3,
            "attempt",
            _attempt(3, "a2", parent_id="a1", rationale="refine", metrics={"rmse": 0.02}),
        ),
        make_event(
            4,
            "attempt",
            _attempt(4, "a3", parent_id="a2", rationale="too far", metrics={"rmse": 0.07}),
        ),
        make_event(
            5,
            "attempt",
            _attempt(5, "a4", parent_id="a1", rationale="sibling", metrics={}),
        ),
    ]
    out = tmp_path / "report.html"
    doc = render_report(events, out, session_id="abc", simulator="BattMo")

    # Hero stat: best value, baseline reference, percent change.
    assert "(best)" in doc
    assert "0.02" in doc  # best metric value
    assert "baseline 0.05" in doc
    assert "vs baseline" in doc

    # Tally on the side.
    assert "4 attempts" in doc

    # Exploration + Attempt details sections.
    assert "Exploration map" in doc
    assert "Attempt details" in doc

    # Tone classes are assigned by parent comparison.
    assert "box baseline" in doc
    assert "box improved" in doc
    assert "box regressed" in doc
    assert "box neutral" in doc


def test_render_report_uses_supplied_title(tmp_path) -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(2, "attempt", _attempt(2, "a1", rationale="baseline", metrics={"rmse": 0.05})),
    ]
    out = tmp_path / "report.html"
    doc = render_report(
        events,
        out,
        narrative_markdown="## Summary",
        title="Coating sensitivity study",
        session_id="abc",
        simulator="BattMo",
    )
    assert "Coating sensitivity study" in doc
    # The default heading must not also leak in.
    assert "BattMo investigation report" not in doc


def test_render_report_lists_attempts_with_metrics(tmp_path) -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(
            2,
            "attempt",
            _attempt(2, "a1", rationale="baseline", metrics={"rmse": 0.01706}),
        ),
        make_event(
            3,
            "attempt",
            _attempt(
                3,
                "a2",
                parent_id="a1",
                rationale="branch",
                metrics={"rmse": 0.01041},
                notes="Branch A: kinetics",
            ),
        ),
    ]
    out = tmp_path / "report.html"
    doc = render_report(events, out, session_id="abc", simulator="BattMo")
    # Raw scalar formatting; the caller controls units via metric key naming.
    assert "rmse=0.01706" in doc
    assert "rmse=0.01041" in doc
    # Parent link is shown in the summary line.
    assert "from #1" in doc
    # Anchor for cross-linking from narrative.
    assert 'id="attempt-1"' in doc
    assert 'id="attempt-2"' in doc


def test_render_report_embeds_plot_from_artifact_dir(tmp_path) -> None:
    plot_dir = tmp_path / "artifacts"
    plot_dir.mkdir()
    plot_file = plot_dir / "plot-1.png"
    plot_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 32)

    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(
            2,
            "attempt",
            _attempt(
                2,
                "a1",
                rationale="baseline",
                metrics={"rmse": 0.05},
                plot="artifacts/plot-1.png",
            ),
        ),
    ]
    out = tmp_path / "report.html"
    doc = render_report(events, out, session_id="abc", simulator="BattMo", artifact_dirs=[plot_dir])
    assert "data:image/png;base64," in doc


def test_render_report_single_attempt_omits_best_suffix_and_exploration(tmp_path) -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(
            2,
            "attempt",
            _attempt(
                2,
                "a1",
                rationale="baseline",
                metrics={
                    "baseline_end_voltage_V": 1.014,
                    "baseline_rmse_V": 0.2977,
                    "calibrated_end_voltage_V": 1.375,
                    "calibrated_rmse_V": 0.2263,
                },
            ),
        ),
    ]
    out = tmp_path / "report.html"
    doc = render_report(events, out, session_id="abc", simulator="BattMo")

    # No comparison possible with a single attempt — no Results section.
    assert "(best)" not in doc
    assert '<section class="results">' not in doc
    assert '<section class="exploration">' not in doc
    # The primary metric still appears in the attempt detail card body.
    assert "baseline_rmse_V=0.2977" in doc
    assert "baseline_end_voltage_V=1.014" not in doc
    # Leaf pill is hidden when the tally would just be "1 attempt · 1 leaf".
    assert "1 leaf" not in doc


def test_render_report_param_strings_are_not_json_quoted(tmp_path) -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(
            2,
            "attempt",
            {
                "id": "a1",
                "parent_id": None,
                "rationale": "baseline",
                "parameters_changed": {"thickness": "5.86e-6 → 6.3288e-6 m"},
                "metrics": {"rmse": 0.05},
                "notes": None,
                "plot_artifact_path": None,
            },
        ),
    ]
    out = tmp_path / "report.html"
    doc = render_report(events, out, session_id="abc", simulator="BattMo")
    assert "5.86e-6 → 6.3288e-6 m" in doc
    assert '"5.86e-6' not in doc


def test_render_report_writes_file(tmp_path, snapshot) -> None:
    events = [
        make_event(1, "session_start", {"session_id": "abc", "simulator": "battmo"}),
        make_event(
            2,
            "attempt",
            _attempt(2, "a1", rationale="baseline", metrics={"rmse": 0.05}),
        ),
        make_event(
            3,
            "attempt",
            _attempt(
                3,
                "a2",
                parent_id="a1",
                rationale="increase surface area",
                metrics={"rmse": 0.02},
                plot="artifacts/plot-1.png",
            ),
        ),
        make_event(
            4,
            "attempt",
            _attempt(
                4, "a3", parent_id="a1", rationale="try mass fraction", metrics={"rmse": 0.03}
            ),
        ),
        make_event(5, "session_end", {"session_id": "abc"}),
    ]
    out = tmp_path / "report.html"
    doc = render_report(
        events,
        out,
        narrative_markdown="## Summary\n\nConverged after two branches.",
        session_id="abc",
        simulator="BattMo",
    )
    assert out.exists()
    assert doc == snapshot
