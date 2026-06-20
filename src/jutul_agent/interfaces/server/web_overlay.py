"""The web-plotting overlay environment.

Interactive web plots need WGLMakie and Bonito, which are heavy to precompile.
To keep them out of the TUI/CLI path, they live in a separate Julia environment
that is stacked on top of the workspace's simulator env (via ``JULIA_LOAD_PATH``)
only for web sessions. Julia loads each package from whichever stacked env
provides it, and because WGLMakie pulls the same Makie the base env already has,
the two share one Makie instance (the plot tool verifies this at load time).

``ensure_web_overlay`` instantiates the overlay once into the state home and
returns its path; ``load_path_for`` builds the ``JULIA_LOAD_PATH`` value that
stacks it over a workspace project.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from jutul_agent.paths import state_home

# Ships in the package (src/jutul_agent/julia_runtime/web_overlay); resolved
# against this file so it works from an installed package too.
_OVERLAY_TEMPLATE = Path(__file__).resolve().parents[2] / "julia_runtime" / "web_overlay"


class WebOverlayError(RuntimeError):
    """The web-plotting overlay env could not be prepared."""


def overlay_dir() -> Path:
    """Where the instantiated overlay env lives (stable across sessions)."""
    return state_home() / "web-overlay"


def ensure_web_overlay(*, julia_executable: str = "julia") -> Path:
    """Instantiate the overlay env once and return its directory.

    Copies the template, resolves WGLMakie + Bonito, and precompiles them so the
    first web plot does not pay the full bake. A ready overlay (its ``Manifest``
    present) is returned untouched. Raises ``WebOverlayError`` if Julia cannot
    prepare it (e.g. offline on first run).
    """

    target = overlay_dir()
    if (target / "Manifest.toml").exists():
        return target

    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_OVERLAY_TEMPLATE / "Project.toml", target / "Project.toml")
    print(
        "Preparing the web-plotting environment (WGLMakie + Bonito); this runs "
        "once and can take a few minutes...",
        file=sys.stderr,
    )
    result = subprocess.run(
        [
            julia_executable,
            f"--project={target}",
            "--startup-file=no",
            "-e",
            "using Pkg; Pkg.instantiate(); Pkg.precompile()",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not (target / "Manifest.toml").exists():
        shutil.rmtree(target, ignore_errors=True)
        raise WebOverlayError(
            f"could not prepare the web-plotting overlay env. Julia said:\n{result.stderr[-2000:]}"
        )
    return target


def load_path_for(workspace_project: Path, overlay: Path) -> str:
    """The ``JULIA_LOAD_PATH`` stacking the overlay under the workspace project.

    Order is the active project (``@``, set by ``--project`` to the workspace
    env) first, then the overlay, then the standard library. WGLMakie and Bonito
    live only in the overlay, so they still resolve from it; putting the workspace
    env first means that for a package both provide (a transitive dep like JSON),
    the simulator's version wins. The overlay must not shadow a simulator's deps —
    overlay-first did, which broke BattMo (its JSON-loaded ``CellParameters``
    stopped matching once Bonito's JSON shadowed the one BattMo expects). The
    Makie/WGLMakie/GLMakie identity the plot tool guards still holds either way.
    """

    return os.pathsep.join(["@", str(overlay), "@stdlib"])
