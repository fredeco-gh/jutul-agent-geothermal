"""The Windows real-path shim over deepagents' ``validate_path``.

The wrapper logic is tested directly (cross-platform, since the production install
is gated on Windows), then the real install is exercised against deepagents so a
file tool would accept a ``C:\\...`` path.
"""

from __future__ import annotations

import pytest

from jutul_agent.agent import windows_paths


def _fake_validate_path(path: str, *, allowed_prefixes=None) -> str:
    """Stand-in matching deepagents: reject Windows-absolute, normalize the rest."""
    import re

    if re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"Windows absolute paths are not supported: {path}")
    if ".." in path.split("/"):
        raise ValueError("Path traversal not allowed")
    return path if path.startswith("/") else f"/{path}"


def test_windows_absolute_path_passes_through_unchanged():
    wrapped = windows_paths._wrap_validate_path(_fake_validate_path)
    assert wrapped(r"C:\Users\jakobt\.julia\packages\JutulDarcy\x\src\foo.jl") == (
        r"C:\Users\jakobt\.julia\packages\JutulDarcy\x\src\foo.jl"
    )
    assert wrapped("C:/Users/jakobt/file.txt") == "C:/Users/jakobt/file.txt"


def test_non_windows_paths_defer_to_the_original():
    wrapped = windows_paths._wrap_validate_path(_fake_validate_path)
    # POSIX absolute: original normalizes (leading slash preserved).
    assert wrapped("/home/u/file.txt") == "/home/u/file.txt"
    # Relative: original adds the leading slash.
    assert wrapped("foo/bar.jl") == "/foo/bar.jl"
    # Traversal still rejected by the original.
    with pytest.raises(ValueError, match="traversal"):
        wrapped("../etc/passwd")


def test_wrapping_is_idempotent():
    once = windows_paths._wrap_validate_path(_fake_validate_path)
    twice = windows_paths._wrap_validate_path(once)
    assert twice is once


def _unwrap(fn):
    """The true (unpatched) ``validate_path`` under any of our wrappers."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def test_install_patches_deepagents_so_a_windows_path_validates():
    """``_install`` makes the middleware's ``validate_path`` accept ``C:\\...``.

    Independent of prior global state: on Windows an earlier ``build_agent`` may
    have already installed the patch, so we pin the genuine original first.
    """
    from deepagents.backends import utils
    from deepagents.middleware import filesystem as fs_middleware

    utils_before = utils.validate_path
    middleware_before = fs_middleware.validate_path
    original = _unwrap(utils_before)

    # The genuine deepagents helper rejects a Windows absolute path.
    with pytest.raises(ValueError, match="Windows absolute paths are not supported"):
        original(r"C:\Users\x\file.txt")

    utils.validate_path = original  # start from a known-unpatched state
    fs_middleware.validate_path = original
    try:
        windows_paths._install()
        # Both the source and the middleware-bound name now pass it through.
        assert utils.validate_path(r"C:\Users\x\file.txt") == r"C:\Users\x\file.txt"
        assert fs_middleware.validate_path(r"C:\Users\x\file.txt") == r"C:\Users\x\file.txt"
        # POSIX paths still validate as before.
        assert utils.validate_path("foo/bar.jl") == "/foo/bar.jl"
    finally:
        utils.validate_path = utils_before
        fs_middleware.validate_path = middleware_before


def test_enable_is_noop_off_windows(monkeypatch):
    monkeypatch.setattr(windows_paths.os, "name", "posix")
    from deepagents.backends import utils

    before = utils.validate_path
    windows_paths.enable_windows_real_paths()
    assert utils.validate_path is before
