"""`julia` command: runs the active Julia (JULIALANG_VERSION > `julialang use` default > bundled)."""
from __future__ import annotations

import os
import subprocess
import sys

from . import manager as M


def main() -> None:
    exe = str(M.exe_in(M.resolve_root()))
    argv = [exe, *sys.argv[1:]]
    if os.name == "nt":  # os.execv misbehaves with consoles on Windows
        sys.exit(subprocess.call(argv))
    os.execv(exe, argv)
