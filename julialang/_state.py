"""Local state of julialang: ~/.julialang, config.json, installed versions and version specs.

Standard library only and cheap to import: the `julia` shim loads this module on every start.

Layout of the home directory (override with $JULIALANG_HOME)::

    ~/.julialang/
        config.json        {"default": "1.12.4", "installed": {"1.12.4": {"path": "versions/1.12.4"}}}
        julia-list.json    cached copy of the mirror list (see `julialang fetch`)
        versions/<X.Y.Z>/  one unpacked Julia per version
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

DEFAULT_REPO = "mohammadraziei/julialang"
RELEASE_TAG = "__download__"  # prerelease that holds the mirrored archives and julia-list.json
EXE = "julia.exe" if os.name == "nt" else "julia"
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


class SpecError(ValueError):
    """A version spec that cannot be parsed."""


def die(msg: str) -> None:
    sys.exit(f"julialang: {msg}")


# --------------------------------------------------------------------------- paths


def home() -> Path:
    return Path(os.environ.get("JULIALANG_HOME") or Path.home() / ".julialang")


def versions_dir() -> Path:
    return home() / "versions"


def exe_in(root: Path) -> Path:
    return root / "bin" / EXE


# --------------------------------------------------------------------------- config.json


def load_config() -> dict:
    try:
        cfg = json.loads((home() / "config.json").read_text())
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def save_config(cfg: dict) -> None:
    home().mkdir(parents=True, exist_ok=True)
    path = home() / "config.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


# Settings of config.json that the user may change with `julialang config`: CLI name -> (JSON key, default)
SETTINGS = {"disable-pkg-server": ("disable_pkg_server", True)}


def env_name(name: str) -> str:
    """Environment variable that overrides a setting: `disable-pkg-server` -> JULIALANG_DISABLE_PKG_SERVER."""
    return "JULIALANG_" + name.upper().replace("-", "_")


def parse_bool(text: str) -> bool | None:
    low = text.strip().lower()
    return True if low in ("1", "true", "yes", "on") else False if low in ("0", "false", "no", "off") else None


def setting_source(name: str) -> str:
    """Where the value of a setting comes from: its environment variable, config.json or the built-in default."""
    if os.environ.get(env_name(name)):
        return env_name(name)
    return "config.json" if isinstance(load_config().get(SETTINGS[name][0]), bool) else "default"


def get_setting(name: str) -> bool:
    """A setting: its JULIALANG_* environment variable (an empty one counts as unset) > config.json > the default."""
    key, default = SETTINGS[name]
    env = os.environ.get(env_name(name))
    if env:
        value = parse_bool(env)
        if value is None:
            die(f"{env_name(name)} must be true or false, not '{env}'")
        return value
    value = load_config().get(key, default)
    return value if isinstance(value, bool) else default


def set_setting(name: str, value: bool) -> None:
    cfg = load_config()
    cfg[SETTINGS[name][0]] = value
    save_config(cfg)


def julia_env() -> dict[str, str]:
    """Environment for Julia. On networks that only reach PyPI and GitHub, pkg.julialang.org is blocked and `Pkg.add` fails,
    so unless the user decided otherwise Julia runs with JULIA_PKG_SERVER="" (Pkg then uses GitHub through git).

    A JULIA_PKG_SERVER that is already set, even to an empty string, is the user's explicit choice and is never touched;
    otherwise the `disable-pkg-server` setting decides: $JULIALANG_DISABLE_PKG_SERVER > config.json > true.
    """
    env = dict(os.environ)
    if "JULIA_PKG_SERVER" not in env and get_setting("disable-pkg-server"):
        env["JULIA_PKG_SERVER"] = ""
    return env


def _rel(path: Path) -> str:
    try:
        return path.relative_to(home()).as_posix()
    except ValueError:
        return str(path)


def version_root(version: str) -> Path:
    """Where `version` lives: the path recorded in config.json, else versions/<version>."""
    rec = (load_config().get("installed") or {}).get(version)
    if isinstance(rec, dict) and rec.get("path"):
        return home() / rec["path"]  # absolute paths stay absolute
    return versions_dir() / version


# --------------------------------------------------------------------------- installed versions


def installed_versions() -> list[str]:
    """Versions that really exist on disk (config.json entries and versions/ folders), oldest first."""
    found: set[str] = set()
    d = versions_dir()
    if d.is_dir():
        found.update(p.name for p in d.iterdir() if VERSION_RE.fullmatch(p.name) and exe_in(p).exists())
    for v in (load_config().get("installed") or {}):
        if VERSION_RE.fullmatch(v) and exe_in(version_root(v)).exists():
            found.add(v)
    return sorted(found, key=parse_version)


def sync_config() -> list[str]:
    """Make config.json agree with the disk (folders added or deleted by hand) and return the installed versions."""
    versions = installed_versions()
    cfg = load_config()
    old = cfg.get("installed") if isinstance(cfg.get("installed"), dict) else {}
    new = {v: (old[v] if isinstance(old.get(v), dict) and old[v].get("path") else {"path": _rel(versions_dir() / v)})
           for v in versions}
    if new != old:
        cfg["installed"] = new
        save_config(cfg)
    return versions


def register(version: str, root: Path) -> None:
    cfg = load_config()
    cfg.setdefault("installed", {})[version] = {"path": _rel(root)}
    save_config(cfg)


def default_version() -> str | None:
    """The default recorded by `julialang install/use/...` (ignores $JULIALANG_VERSION), if it is installed."""
    v = load_config().get("default")
    return v if v in installed_versions() else None


def set_default(version: str | None) -> None:
    cfg = load_config()
    if version is None:
        cfg.pop("default", None)
    else:
        cfg["default"] = version
    save_config(cfg)


def unregister(version: str) -> None:
    cfg = load_config()
    (cfg.get("installed") or {}).pop(version, None)
    if cfg.get("default") == version:
        cfg.pop("default", None)
    save_config(cfg)


# --------------------------------------------------------------------------- project file (.julialang)

PROJECT_FILE = ".julialang"
PROJECT_KEY = "julia-version"


def find_project_file(start: Path | None = None) -> Path | None:
    """Nearest `.julialang` *file* in `start` (default: the current directory) or one of its parents.

    Only regular files count: the default home `~/.julialang` is a directory and must never be mistaken for one.
    """
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        f = d / PROJECT_FILE
        if f.is_file():
            return f
    return None


def read_project_file(path: Path) -> dict[str, str]:
    """Settings of a `.julialang` file: `key = value` lines, `#` comments, optional quotes, unknown keys kept."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        die(f"cannot read {path}: {e}")
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip("\"'").strip()
    return out


def project_pin() -> tuple[str, Path] | None:
    """(version spec, file) pinned for the current directory by the nearest `.julialang`, if any."""
    f = find_project_file()
    spec = read_project_file(f).get(PROJECT_KEY) if f else None
    return (spec, f) if spec and f else None


def write_project_pin(path: Path, spec: str | None) -> bool:
    """Set (or with None remove) the pinned version in `path`, keeping every other line. True if the file was deleted."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else ["# julialang project settings"]

    def is_pin(line: str) -> bool:
        return line.split("#", 1)[0].partition("=")[0].strip() == PROJECT_KEY

    if spec is None:
        lines = [line for line in lines if not is_pin(line)]
        if not any(line.split("#", 1)[0].strip() for line in lines):  # nothing but comments is left
            path.unlink()
            return True
    else:
        entry = f'{PROJECT_KEY} = "{spec}"'
        if any(is_pin(line) for line in lines):
            lines = [entry if is_pin(line) else line for line in lines]
        else:
            lines.append(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return False


def active_version() -> str | None:
    """What `julia` runs: $JULIALANG_VERSION > the `.julialang` pin of this directory > the default > the newest."""
    have = installed_versions()
    env = os.environ.get("JULIALANG_VERSION")
    if env:
        try:
            v = resolve(env, have)
        except SpecError as e:
            die(f"JULIALANG_VERSION: {e}")
        if v is None:
            die(f"JULIALANG_VERSION={env} matches no installed Julia (installed: {', '.join(have) or 'none'}); "
                f"run `julialang install {env}`")
        return v
    pin = project_pin()
    if pin:
        spec, f = pin
        try:
            v = resolve(spec, have)
        except SpecError as e:
            die(f"{f}: {PROJECT_KEY}: {e}")
        if v is None:
            die(f"{f} pins Julia {spec}, but no installed version matches (installed: {', '.join(have) or 'none'}); "
                f"run `julialang install {spec}`")
        return v
    return default_version() or (have[-1] if have else None)


def resolve_root() -> Path:
    """Folder of the Julia that `julia` should run; exits with a hint when there is none."""
    version = active_version()
    if version is None:
        wanted = load_config().get("default")
        if wanted:
            die(f"Julia {wanted} is the default but its files are missing; run `julialang install {wanted}`")
        die("no Julia installed yet; run `julialang install` first")
    return version_root(version)


# --------------------------------------------------------------------------- version specs


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _pad(p: tuple[int, ...]) -> tuple[int, ...]:
    return p + (0,) * (3 - len(p))


def _bump(p: tuple[int, ...]) -> tuple[int, ...]:
    """First version after the prefix `p`: (1, 12) -> (1, 13, 0)."""
    return _pad(p[:-1] + (p[-1] + 1,))


_OPS = ("==", "!=", ">=", "<=", "~=", ">", "<")


def _clause(text: str) -> Callable[[tuple[int, ...]], bool]:
    text = text.strip().lower()
    if text in ("", "latest", "stable", "*"):
        return lambda v: True
    op = next((o for o in _OPS if text.startswith(o)), "==")
    operand = text[len(op):].strip() if text.startswith(op) else text
    operand = operand.removeprefix("v")
    wildcard = operand.endswith((".*", ".x"))
    if wildcard:
        operand = operand[:-2]
    if not re.fullmatch(r"\d+(\.\d+){0,2}", operand):
        raise SpecError(f"cannot understand '{text}' (expected e.g. 1.12, 1.12.4, >=1.10, <1.13, ~=1.12.2, latest)")
    p = tuple(int(x) for x in operand.split("."))
    partial = wildcard or len(p) < 3
    lo, hi = _pad(p), _bump(p) if partial else None  # a prefix like 1.12 means the range [1.12.0, 1.13.0)

    if op == "==":
        return (lambda v: lo <= v < hi) if hi else (lambda v: v == lo)
    if op == "!=":
        return (lambda v: not lo <= v < hi) if hi else (lambda v: v != lo)
    if op == ">=":
        return lambda v: v >= lo
    if op == "<":
        return lambda v: v < lo
    if op == ">":  # ">1.12" means after the whole 1.12.x line, like npm
        return (lambda v: v >= hi) if hi else (lambda v: v > lo)
    if op == "<=":  # "<=1.12" includes every 1.12.x
        return (lambda v: v < hi) if hi else (lambda v: v <= lo)
    # "~=": compatible release, as in pip: ~=1.12.2 is >=1.12.2,<1.13 and ~=1.12 is >=1.12,<2
    if wildcard or len(p) < 2:
        raise SpecError(f"'~={operand}' needs at least major.minor")
    upper = _bump(p[:-1])
    return lambda v: lo <= v < upper


def parse_spec(spec: str | Iterable[str] | None) -> Callable[[tuple[int, ...]], bool]:
    """Compile a spec such as 'latest', '1.12', '1.12.*', '==1.10.4', '>=1.10,<1.13' into a predicate."""
    text = spec if isinstance(spec, str) else ",".join(spec or [])
    parts = text.split(",") if text.strip() else ["latest"]
    if any(not c.strip() for c in parts):
        raise SpecError(f"empty clause in '{text}'")
    clauses = [_clause(c) for c in parts]
    return lambda v: all(c(v) for c in clauses)


def matching(spec: str | Iterable[str] | None, versions: Iterable[str]) -> list[str]:
    """Every version that satisfies the spec, oldest first."""
    ok = parse_spec(spec)
    return sorted((v for v in versions if ok(parse_version(v))), key=parse_version)


def resolve(spec: str | Iterable[str] | None, versions: Iterable[str]) -> str | None:
    """The newest version that satisfies the spec, or None."""
    hits = matching(spec, versions)
    return hits[-1] if hits else None
