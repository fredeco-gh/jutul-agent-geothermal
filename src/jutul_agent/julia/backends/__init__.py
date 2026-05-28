"""Concrete ``JuliaSession`` backends.

Each backend lives in its own sub-package under ``backends/``. Add a new
one by creating a sibling whose ``__init__`` re-exports a class that
satisfies the ``jutul_agent.julia.session.JuliaSession`` Protocol. The
only place outside this package that instantiates a backend is
``interfaces/cli/run.py``.
"""
