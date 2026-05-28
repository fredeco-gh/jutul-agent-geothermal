"""Tests for the init subcommand."""

from __future__ import annotations

from pathlib import Path

import pytest

from jutul_agent.interfaces.cli import main
from jutul_agent.workspace import workspace_config_path, workspace_julia_env


def test_init_bootstraps_workspace_and_writes_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    state = tmp_path / "state"

    code = main(
        [
            "init",
            "--sim",
            "jutuldarcy",
            "--workspace",
            str(ws),
            "--state-home",
            str(state),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert workspace_config_path(ws).exists()
    assert (workspace_julia_env(ws) / "Project.toml").exists()
    assert "Workspace ready" in captured.out


def test_setup_alias_bootstraps_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws2"
    ws.mkdir()

    code = main(["setup", "--sim", "jutuldarcy", "--workspace", str(ws)])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert (workspace_julia_env(ws) / "Project.toml").exists()


def test_instantiate_alias_runs_precompile_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = tmp_path / "ws3"
    ws.mkdir()
    captured_cmds: list[list[str]] = []

    class _Result:
        returncode = 0

    def _fake_run(argv, check=False):
        captured_cmds.append(argv)
        return _Result()

    import jutul_agent.simulators.env_setup as env_setup

    monkeypatch.setattr(env_setup.shutil, "which", lambda _: "/usr/bin/julia")
    monkeypatch.setattr(env_setup.subprocess, "run", _fake_run)

    code = main(
        [
            "init",
            "--sim",
            "jutuldarcy",
            "--instantiate",
            "--workspace",
            str(ws),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "precompile:    done" in captured.out
    assert len(captured_cmds) >= 2
    assert any("Pkg.instantiate()" in cmd[-1] for cmd in captured_cmds)
