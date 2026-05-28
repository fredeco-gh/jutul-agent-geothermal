"""Entry point for the jutul-agent CLI.

Delegates to ``interfaces.cli.main`` so the CLI plumbing has one home.
"""

from __future__ import annotations

import sys

from jutul_agent.interfaces.cli import main

if __name__ == "__main__":
    sys.exit(main())
