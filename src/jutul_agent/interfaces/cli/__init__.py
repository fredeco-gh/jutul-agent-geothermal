"""jutul-agent command-line entrypoint package.

``main`` is the public surface used by ``__main__.py`` and tests. The
subcommand modules (``init.py``, ``run.py``, ``transcript.py``) handle
one ``argv[0]`` each; ``_helpers.py`` holds shared argparse plumbing.
"""

from jutul_agent.interfaces.cli.main import main

__all__ = ["main"]
