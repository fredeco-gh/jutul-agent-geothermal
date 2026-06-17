"""Tests for the ``jutul-agent upgrade`` subcommand."""

from __future__ import annotations

import subprocess

from jutul_agent.interfaces.cli import upgrade as upgrade_cmd
from jutul_agent.update_check import InstallInfo


def _args(**overrides):
    args = upgrade_cmd.build_parser().parse_args([])
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_check_reports_newer(monkeypatch, capsys) -> None:
    monkeypatch.setattr(upgrade_cmd, "install_info", lambda: InstallInfo("registry"))
    monkeypatch.setattr(upgrade_cmd, "refresh_cache", lambda force=False: "9.9.9")

    code = upgrade_cmd.run(_args(check=True))
    out = capsys.readouterr().out
    assert code == 0
    assert "Latest:    9.9.9" in out
    assert "newer version is available" in out


def test_check_reports_up_to_date(monkeypatch, capsys) -> None:
    monkeypatch.setattr(upgrade_cmd, "install_info", lambda: InstallInfo("registry"))
    monkeypatch.setattr(upgrade_cmd, "refresh_cache", lambda force=False: "0.0.0")

    code = upgrade_cmd.run(_args(check=True))
    assert code == 0
    assert "latest version" in capsys.readouterr().out


def test_editable_prints_git_pull(monkeypatch, capsys) -> None:
    from pathlib import Path

    monkeypatch.setattr(upgrade_cmd, "install_info", lambda: InstallInfo("editable", Path("/repo")))
    monkeypatch.setattr(upgrade_cmd, "refresh_cache", lambda force=False: None)

    code = upgrade_cmd.run(_args(check=False))
    err = capsys.readouterr().err
    assert code == 0
    assert "git pull && uv sync" in err


def test_registry_runs_uv_tool_upgrade(monkeypatch, capsys) -> None:
    monkeypatch.setattr(upgrade_cmd, "install_info", lambda: InstallInfo("registry"))
    monkeypatch.setattr(upgrade_cmd, "refresh_cache", lambda force=False: "9.9.9")
    monkeypatch.setattr(upgrade_cmd.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(upgrade_cmd.os, "name", "posix")  # exercise the inline path

    calls: list[list[str]] = []

    def _fake_run(argv, check=False):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(upgrade_cmd.subprocess, "run", _fake_run)

    code = upgrade_cmd.run(_args(check=False))
    assert code == 0
    assert calls == [["uv", "tool", "upgrade", "jutul-agent"]]
    assert "rebuild its Julia env" in capsys.readouterr().out


def test_registry_windows_runs_detached(monkeypatch, capsys) -> None:
    # On Windows the running launcher is locked, so uv must run in a separate
    # process while jutul-agent exits — not inline (which would fail the copy).
    monkeypatch.setattr(upgrade_cmd, "install_info", lambda: InstallInfo("registry"))
    monkeypatch.setattr(upgrade_cmd, "refresh_cache", lambda force=False: "9.9.9")
    monkeypatch.setattr(upgrade_cmd.shutil, "which", lambda _name: "C:/uv.exe")
    monkeypatch.setattr(upgrade_cmd.os, "name", "nt")

    popened: list[list[str]] = []

    def _fake_popen(argv, creationflags=0, close_fds=True):
        popened.append(argv)
        return object()

    def _no_run(*a, **k):
        raise AssertionError("must not run uv inline on Windows (locked exe)")

    monkeypatch.setattr(upgrade_cmd.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(upgrade_cmd.subprocess, "run", _no_run)

    code = upgrade_cmd.run(_args(check=False))
    assert code == 0
    assert popened == [["uv", "tool", "upgrade", "jutul-agent"]]
    assert "new window" in capsys.readouterr().out


def test_registry_errors_without_uv(monkeypatch, capsys) -> None:
    monkeypatch.setattr(upgrade_cmd, "install_info", lambda: InstallInfo("registry"))
    monkeypatch.setattr(upgrade_cmd, "refresh_cache", lambda force=False: "9.9.9")
    monkeypatch.setattr(upgrade_cmd.shutil, "which", lambda _name: None)

    code = upgrade_cmd.run(_args(check=False))
    assert code == 1
    assert "uv` is not on PATH" in capsys.readouterr().err


def test_unknown_install_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(upgrade_cmd, "install_info", lambda: InstallInfo("unknown"))
    monkeypatch.setattr(upgrade_cmd, "refresh_cache", lambda force=False: None)

    code = upgrade_cmd.run(_args(check=False))
    assert code == 1
    assert "isn't installed as a managed package" in capsys.readouterr().err
