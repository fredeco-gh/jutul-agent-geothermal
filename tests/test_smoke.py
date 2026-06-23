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
    from jutul_agent import __version__

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # Version is derived from git tags by hatch-vcs, so assert the wiring (the
    # resolved __version__ is printed) rather than a fixed string.
    assert f"jutul-agent {__version__}" in out


def test_default_invocation_without_sim_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An interface invoked without ``--sim`` must fail fast when no simulator is
    configured.

    Pass an isolated ``--workspace``: the repo checkout has
    ``.jutul-agent/config.toml`` with ``simulator = "battmo"``, and ``main``
    resets workspace overrides via ``_apply_workspace_flags`` (``None`` → cwd).
    Without isolation the CLI would launch Julia and hang or crash
    under pytest capture (stderr has no fileno).
    """
    ws = tmp_path / "workspace"
    ws.mkdir()
    state = tmp_path / "state"
    state.mkdir()

    code = main(["tui", "--workspace", str(ws), "--state-home", str(state)])
    captured = capsys.readouterr()
    assert code == 2
    assert "--sim is required" in captured.err


def test_bare_invocation_shows_interface_chooser(capsys: pytest.CaptureFixture[str]) -> None:
    # Bare `jutul-agent` no longer launches an interface silently; it names them.
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "jutul-agent web" in out and "jutul-agent tui" in out and 'run "<prompt>"' in out


def test_unknown_command_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["frobnicate"]) == 2
    assert "unknown command" in capsys.readouterr().err


def test_tui_rejects_a_prompt(capsys: pytest.CaptureFixture[str]) -> None:
    # `tui` is interactive; a prompt belongs to `run`. Guarded before any kernel start.
    assert main(["tui", "run a sim"]) == 2
    assert "takes no prompt" in capsys.readouterr().err


def test_run_requires_a_prompt(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run"]) == 2
    assert "needs a prompt" in capsys.readouterr().err
