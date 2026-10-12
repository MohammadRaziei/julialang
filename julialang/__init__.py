"""julialang: Julia bundled in a wheel, plus a small version manager."""
from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("julialang")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0.dev0"


def julia_executable() -> str:
    """Path of the Julia executable that the `julia` command would run."""
    from . import manager

    return str(manager.exe_in(manager.resolve_root()))
