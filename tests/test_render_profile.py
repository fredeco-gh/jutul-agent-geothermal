"""Tests for display detection and the window-vs-offscreen decision."""

from __future__ import annotations

import pytest

from jutul_agent.agent.render_profile import (
    can_open_windows,
    has_display,
    plotting_display_available,
    should_wrap_xvfb,
)


def test_one_shot_never_opens_windows() -> None:
    # A headless --prompt turn renders offscreen even with a display.
    assert can_open_windows(interactive_session=False, display=True) is False


def test_interactive_with_display_opens_windows() -> None:
    assert can_open_windows(interactive_session=True, display=True) is True


def test_interactive_without_display_renders_offscreen() -> None:
    # Interactive session but no display (e.g. SSH on Linux) -> offscreen.
    assert can_open_windows(interactive_session=True, display=False) is False


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_has_display_true_on_desktop_os(monkeypatch: pytest.MonkeyPatch, system: str) -> None:
    monkeypatch.setattr("jutul_agent.agent.render_profile.platform.system", lambda: system)
    assert has_display() is True


def test_has_display_linux_depends_on_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jutul_agent.agent.render_profile.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert has_display() is False

    monkeypatch.setenv("DISPLAY", ":0")
    assert has_display() is True


def _headless_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put render_profile in a headless-Linux baseline (no display, no opt-out)."""
    monkeypatch.setattr("jutul_agent.agent.render_profile.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("JUTUL_AGENT_NO_XVFB", raising=False)


def _set_xvfb_run(monkeypatch: pytest.MonkeyPatch, present: bool) -> None:
    monkeypatch.setattr(
        "jutul_agent.agent.render_profile.shutil.which",
        lambda name: "/usr/bin/xvfb-run" if (present and name == "xvfb-run") else None,
    )


def test_should_wrap_xvfb_only_on_headless_linux_with_xvfb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _headless_linux(monkeypatch)
    _set_xvfb_run(monkeypatch, present=True)
    assert should_wrap_xvfb() is True

    # Missing xvfb-run, opt-out, a real display, or a non-Linux OS all suppress it.
    _set_xvfb_run(monkeypatch, present=False)
    assert should_wrap_xvfb() is False

    _set_xvfb_run(monkeypatch, present=True)
    monkeypatch.setenv("JUTUL_AGENT_NO_XVFB", "1")
    assert should_wrap_xvfb() is False
    monkeypatch.delenv("JUTUL_AGENT_NO_XVFB", raising=False)

    monkeypatch.setenv("DISPLAY", ":0")
    assert should_wrap_xvfb() is False
    monkeypatch.delenv("DISPLAY", raising=False)

    monkeypatch.setattr("jutul_agent.agent.render_profile.platform.system", lambda: "Darwin")
    assert should_wrap_xvfb() is False


def test_plotting_display_available_on_desktop_os(monkeypatch: pytest.MonkeyPatch) -> None:
    # Desktop OSes always have a display, so plotting is available regardless of xvfb.
    monkeypatch.setattr("jutul_agent.agent.render_profile.platform.system", lambda: "Darwin")
    _set_xvfb_run(monkeypatch, present=False)
    assert plotting_display_available() is True


def test_plotting_display_available_headless_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    _headless_linux(monkeypatch)
    # Headless with xvfb -> the wrapped worker provides a display.
    _set_xvfb_run(monkeypatch, present=True)
    assert plotting_display_available() is True
    # Headless without xvfb -> no display anywhere, plotting unavailable.
    _set_xvfb_run(monkeypatch, present=False)
    assert plotting_display_available() is False
    # A real display makes it available even without xvfb.
    monkeypatch.setenv("DISPLAY", ":0")
    assert plotting_display_available() is True
