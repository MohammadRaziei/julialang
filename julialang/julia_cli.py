"""`julia` command: a thin shim that runs the Julia selected by `julialang` with the given arguments.

It never touches the network (unless JULIALANG_AUTO_INSTALL=1 and nothing is installed yet). Julia itself runs with
JULIA_PKG_SERVER="" unless that variable is set or `julialang config disable-pkg-server false` was used
(see `_state.julia_env`).
Selection order: $JULIALANG_VERSION > the `.julialang` file of this project (`julialang pin`) > the default
(`julialang use`) > the newest installed.
"""
from __future__ import annotations

import os
import subprocess
import sys

from . import _state as S


def _auto_install_enabled() -> bool:
    return os.environ.get("JULIALANG_AUTO_INSTALL", "").lower() in ("1", "true", "yes", "on")


def main(args: list[str] | None = None) -> None:
    """Run Julia with `args` (default: this process's arguments). Does not return: it replaces/ends the process."""
    if _auto_install_enabled() and not S.installed_versions():
        from . import manager

        manager.auto_install()
    exe = str(S.exe_in(S.resolve_root()))
    argv = [exe, *(sys.argv[1:] if args is None else args)]
    env = S.julia_env()
    if os.name == "nt":  # os.execv misbehaves with consoles on Windows
        try:
            sys.exit(subprocess.call(argv, env=env))
        except KeyboardInterrupt:
            sys.exit(130)
    os.execve(exe, argv, env)


if __name__ == "__main__":
    main()
