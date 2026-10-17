"""julialang: `pip install julialang`, then `julialang install` and run `julia`."""

__version__ = "0.4.0"  # the only place to bump: pyproject.toml reads it (hatch); tag the release vX.Y.Z to match


def julia_executable() -> str:
    """Path of the Julia executable that the `julia` command would run."""
    from . import _state

    return str(_state.exe_in(_state.resolve_root()))
