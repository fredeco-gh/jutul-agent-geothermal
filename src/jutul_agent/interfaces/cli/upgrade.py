"""``jutul-agent upgrade``: update the install, the right way for how it was installed.

One command users can run to get the latest, instead of remembering whether they
did ``uv tool install`` or a dev checkout. ``--check`` just reports the latest
without changing anything.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from jutul_agent import __version__
from jutul_agent.interfaces.cli._helpers import add_workspace_flags
from jutul_agent.update_check import (
    InstallInfo,
    install_info,
    refresh_cache,
    upgrade_command,
)

# Printed after a successful upgrade: a new template ships with the package, but
# existing workspace envs are only rebuilt from it on request.
_REBUILD_HINT = (
    "If a workspace was set up with an older version, rebuild its Julia env with "
    "`jutul-agent init --sim <name> --force --precompile`."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jutul-agent upgrade",
        description="Upgrade jutul-agent to the latest version.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only report the latest available version; don't upgrade.",
    )
    add_workspace_flags(parser)
    return parser


def run(args: argparse.Namespace) -> int:
    info = install_info()
    latest = refresh_cache(force=True)  # synchronous, bypasses the cache TTL

    print(f"Installed: {__version__}")
    if latest is not None:
        print(f"Latest:    {latest}")
    else:
        print("Latest:    unknown (offline, or no release published yet)")

    if args.check:
        return _report_check(info, latest)

    if info.method == "editable":
        return _report_editable(info)
    if info.method == "unknown":
        print(
            "\njutul-agent isn't installed as a managed package, so there's nothing "
            "to upgrade here. Install it with `uv tool install jutul-agent` to get "
            "`jutul-agent upgrade`.",
            file=sys.stderr,
        )
        return 1
    return _run_uv_tool_upgrade()


def _report_check(info: InstallInfo, latest: str | None) -> int:
    from jutul_agent.update_check import is_newer

    if latest is not None and is_newer(latest):
        print(f"\nA newer version is available. Upgrade with `{upgrade_command(info)}`.")
    elif latest is not None:
        print("\nYou're on the latest version.")
    return 0


def _report_editable(info: InstallInfo) -> int:
    where = f" (in {info.location})" if info.location else ""
    print(
        f"\nThis is an editable/dev checkout{where}. Upgrade it with:\n"
        "    git pull && uv sync\n"
        f"{_REBUILD_HINT}",
        file=sys.stderr,
    )
    return 0


def _run_uv_tool_upgrade() -> int:
    if shutil.which("uv") is None:
        print(
            "\nerror: `uv` is not on PATH, so the install can't be upgraded "
            "automatically. Install uv (https://docs.astral.sh/uv/), then run "
            "`uv tool upgrade jutul-agent`.",
            file=sys.stderr,
        )
        return 1

    argv = ["uv", "tool", "upgrade", "jutul-agent"]
    if os.name == "nt":
        return _upgrade_detached_windows(argv)

    print(f"\n$ {' '.join(argv)}", flush=True)
    result = subprocess.run(argv, check=False)
    if result.returncode != 0:
        print(
            f"\nerror: upgrade failed (uv exited {result.returncode}).",
            file=sys.stderr,
        )
        return result.returncode
    print(f"\n{_REBUILD_HINT}")
    return 0


def _upgrade_detached_windows(argv: list[str]) -> int:
    """Run the upgrade in a separate console, then let this process exit.

    On Windows the running ``jutul-agent.exe`` launcher is locked, so ``uv tool
    upgrade`` can't overwrite it from within this process (it fails copying the
    entrypoint). Launch uv in its own console and return so jutul-agent exits and
    frees the executable; uv builds and updates the venv first, reaching the
    launcher copy only after we're gone. Falls back to manual instructions if the
    detached launch can't start.
    """

    new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        subprocess.Popen(argv, creationflags=new_console, close_fds=True)
    except OSError as exc:
        print(
            f"\nerror: couldn't start the upgrade ({exc}). Run it yourself from a "
            "new terminal (not from inside jutul-agent):\n    uv tool upgrade jutul-agent",
            file=sys.stderr,
        )
        return 1
    print(
        "\nUpgrading in a new window. Windows can't replace jutul-agent's own "
        "running executable, so this process will exit to release it — reopen "
        f"jutul-agent once the other window finishes.\n{_REBUILD_HINT}"
    )
    return 0
