"""julialang: `pip install julialang`, then `julialang install` and run `julia`."""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("julialang")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0.0.0.dev0"


def julia_executable() -> str:
    """Path of the Julia executable that the `julia` command would run."""
    from . import _state

    return str(_state.exe_in(_state.resolve_root()))
