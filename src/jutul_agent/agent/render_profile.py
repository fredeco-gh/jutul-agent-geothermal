"""Whether a session can show the user a live Makie window.

The plotting tool always renders with GLMakie. The only environment-dependent
choice is whether to open an on-screen window (a human is watching an interactive
session on a machine with a display) or render offscreen to a file (a headless or
one-shot run). Headless Linux still renders: the AgentREPL backend wraps the Julia
worker in xvfb, giving GLMakie a virtual display, so it draws offscreen there.
"""

from __future__ import annotations

import os
import platform
import shutil


def has_display() -> bool:
    """Best-effort check for a human-visible display server.

    Windows and macOS desktop sessions always have one. Linux and BSD need an X
    or Wayland display; a headless box (SSH, CI) has neither.
    """
    if platform.system() in ("Windows", "Darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def can_open_windows(*, interactive_session: bool, display: bool | None = None) -> bool:
    """True when julia_plot may open a live window for the user.

    Requires both an interactive (TUI) session and a display. A one-shot
    ``--prompt`` run has nobody watching, and a headless box has nowhere to draw,
    so both render offscreen to a file instead.

    Args:
        interactive_session: True for the live TUI, False for a one-shot ``--prompt``.
        display: Override for display detection (tests); defaults to ``has_display()``.
    """
    if not interactive_session:
        return False
    return has_display() if display is None else display


def xvfb_run_available() -> bool:
    """True if the ``xvfb-run`` wrapper script is on PATH."""
    return shutil.which("xvfb-run") is not None


def xvfb_opted_out() -> bool:
    """True if the user disabled the headless xvfb wrap (``JUTUL_AGENT_NO_XVFB``)."""
    return bool(os.environ.get("JUTUL_AGENT_NO_XVFB"))


def should_wrap_xvfb() -> bool:
    """True on headless Linux where ``xvfb-run`` can supply a virtual display.

    GLMakie needs an X/Wayland display (or xvfb) for its OpenGL context; it has no
    built-in OSMesa/EGL switch. So on a Linux box with no ``DISPLAY`` we run the
    Julia worker under ``xvfb-run`` to make the native 3D plotters work headless
    (the same approach JutulDarcy uses in its own CI). The worker that AgentREPL
    spawns inherits this environment. Set ``JUTUL_AGENT_NO_XVFB=1`` to opt out;
    plotting then has no display and julia_plot reports a clear error.

    This is the single source of truth for the wrap decision: the AgentREPL
    backend uses it to wrap the worker, and ``doctor`` / startup use the related
    ``plotting_display_available`` to warn when plotting won't work here.
    """

    if platform.system() != "Linux":
        return False
    if has_display():
        return False
    if xvfb_opted_out():
        return False
    return xvfb_run_available()


def plotting_display_available() -> bool:
    """Whether GLMakie will have a display to render against.

    A real X/Wayland display — or any desktop macOS/Windows session — works
    directly; headless Linux relies on the xvfb-wrapped worker. When this is
    False, ``julia_plot`` cannot render and reports a clear error, but the rest
    of the agent (simulate, eval, file tools) still works.
    """
    return has_display() or should_wrap_xvfb()
