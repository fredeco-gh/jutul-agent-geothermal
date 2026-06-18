"""Test-suite shim: the shared fakes now live in :mod:`jutul_agent.lab.fakes`.

They were promoted into the package so the lab (TUI capture, profiling) can reuse the
same doubles the tests use. Existing tests keep importing ``from fakes import ...``.
"""

from __future__ import annotations

from jutul_agent.lab.fakes import *  # noqa: F403
