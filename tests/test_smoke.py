"""CLI smoke tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jutul_agent.interfaces.cli import main


def test_help_exits_zero_subprocess() -> None:
    """Sanity check that the installed entry-point script wires up correctly."""

    result = subprocess.run(
        [sys.executable, "-m", "jutul_agent", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "jutul-agent" in result.stdout.lower()
    assert "--sim" in result.stdout
    assert "init" in result.stdout
    assert "transcript" in result.stdout


def test_version_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "0.0.0" in capsys.readouterr().out


def test_default_invocation_without_sim_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invocation without ``--sim`` must fail fast when no simulator is configured.

    Pass an isolated ``--workspace``: the repo checkout has
    ``.jutul-agent/config.toml`` with ``simulator = "battmo"``, and ``main``
    resets workspace overrides via ``_apply_workspace_flags`` (``None`` → cwd).
    Without isolation the CLI would launch AgentREPL/Julia and hang or crash
    under pytest capture (stderr has no fileno).
    """
    ws = tmp_path / "workspace"
    ws.mkdir()
    state = tmp_path / "state"
    state.mkdir()

    code = main(["--workspace", str(ws), "--state-home", str(state)])
    captured = capsys.readouterr()
    assert code == 2
    assert "--sim is required" in captured.err
