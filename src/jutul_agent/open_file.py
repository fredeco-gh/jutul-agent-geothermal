"""Cross-platform best-effort file opener.

Opens a file or directory in the OS default application.  Failures are
swallowed silently — the caller should not depend on the file actually
opening (e.g. headless CI environments have no viewer).
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def open_path(path: Path) -> None:
    """Open *path* in the OS default application (non-blocking, best-effort).

    Set ``JUTUL_AGENT_NO_OPEN=1`` to suppress opening (e.g. in CI or tests).
    """
    if os.environ.get("JUTUL_AGENT_NO_OPEN"):
        return
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass
