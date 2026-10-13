"""Core of julialang: platform detection, the mirror's julia-list.json, install/use/remove.

Standard library only, so it works in a bare `pip install`.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_REPO = "mohammadraziei/julialang"
RELEASE_TAG = "__download__"  # prerelease that holds the mirrored archives

PKG_DIR = Path(__file__).resolve().parent
BUNDLED_DIR = PKG_DIR / "_julia"  # filled in when the wheel is built
BUNDLED_META = PKG_DIR / "_bundled.json"
SYMLINK_MANIFEST = PKG_DIR / "_symlinks.json"
READY_MARKER = ".julialang-ready"
EXE = "julia.exe" if os.name == "nt" else "julia"
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def die(msg: str) -> None:
    sys.exit(f"julialang: {msg}")


# --------------------------------------------------------------------------- paths / config


def home() -> Path:
    return Path(os.environ.get("JULIALANG_HOME") or Path.home() / ".julialang")


def versions_dir() -> Path:
    return home() / "versions"


def load_config() -> dict:
    try:
        return json.loads((home() / "config.json").read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    home().mkdir(parents=True, exist_ok=True)
    (home() / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")


def list_url() -> str:
    repo = os.environ.get("JULIALANG_REPO", DEFAULT_REPO)
    return os.environ.get("JULIALANG_LIST_URL") or (
        f"https://raw.githubusercontent.com/{repo}/master/julia-list.json"
    )


# --------------------------------------------------------------------------- platform / versions


def platform_key() -> str:
    os_ = {"linux": "linux", "darwin": "macos", "windows": "windows"}.get(platform.system().lower())
    machine = platform.machine().lower()
    arch = {
        "x86_64": "x86_64", "amd64": "x86_64",
        "arm64": "aarch64", "aarch64": "aarch64",
        "i686": "i686", "i386": "i686", "x86": "i686",
    }.get(machine)
    if not os_ or not arch:
        die(f"unsupported platform: {platform.system()}/{platform.machine()}")
    return f"{os_}-{arch}"


def parse(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def match(spec: str, versions) -> str | None:
    """Resolve 'latest' | '1' | '1.12' | '1.12.2' against a collection of versions."""
    vs = sorted(versions, key=parse)
    if spec in ("latest", "stable"):
        return vs[-1] if vs else None
    parts = spec.split(".")
    hits = [v for v in vs if v.split(".")[: len(parts)] == parts]
    return hits[-1] if hits else None


def exe_in(root: Path) -> Path:
    return root / "bin" / EXE


def bundled_version() -> str | None:
    if not BUNDLED_META.exists() or not exe_in(BUNDLED_DIR).exists():
        return None
    return json.loads(BUNDLED_META.read_text())["version"]


def installed_versions() -> list[str]:
    d = versions_dir()
    if not d.is_dir():
        return []
    names = [p.name for p in d.iterdir() if VERSION_RE.fullmatch(p.name) and exe_in(p).exists()]
    return sorted(names, key=parse)


def local_versions() -> list[str]:
    found = set(installed_versions())
    if bundled_version():
        found.add(bundled_version())
    return sorted(found, key=parse)


def active_version() -> str | None:
    return os.environ.get("JULIALANG_VERSION") or load_config().get("default") or bundled_version()


# --------------------------------------------------------------------------- mirror list


def fetch_list(timeout: int = 30) -> dict:
    req = urllib.request.Request(list_url(), headers={"User-Agent": "julialang"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def available_versions(lst: dict, key: str) -> list[str]:
    return sorted((v for v, m in lst.get("versions", {}).items() if key in m.get("files", {})), key=parse)


def hash_file(path: Path) -> tuple[str, str]:
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def verify_file(path: Path, entry: dict) -> None:
    sha, md5 = hash_file(path)
    if sha != entry["sha256"] or md5 != entry["md5"]:
        die(f"checksum mismatch for {entry['name']} (expected sha256 {entry['sha256']}, got {sha})")


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "julialang"})
    part = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        show = sys.stderr.isatty()
        while chunk := r.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if show and total:
                print(f"\r  {done / total:4.0%}  {done / 1e6:.0f}/{total / 1e6:.0f} MB", end="", file=sys.stderr)
    if show:
        print(file=sys.stderr)
    part.replace(dest)


# --------------------------------------------------------------------------- install / remove


def extract_archive(archive: Path, dest: Path) -> None:
    """Extract a Julia archive into `dest`, dropping the single top-level directory."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".extract-"))
    try:
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                try:
                    t.extractall(tmp, filter="data")
                except TypeError:  # Python without extraction filters
                    t.extractall(tmp)
        children = list(tmp.iterdir())
        root = children[0] if len(children) == 1 and children[0].is_dir() else tmp
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(root), str(dest))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install(version: str, lst: dict) -> Path:
    """Download, verify and unpack one exact version from the mirror."""
    key = platform_key()
    entry = lst.get("versions", {}).get(version, {}).get("files", {}).get(key)
    if not entry:
        die(f"Julia {version} is not on the mirror for {key}")
    dest = versions_dir() / version
    if exe_in(dest).exists():
        print(f"Julia {version} is already installed", file=sys.stderr)
        return dest
    versions_dir().mkdir(parents=True, exist_ok=True)
    print(f"Installing Julia {version} ({key}) ...", file=sys.stderr)
    with tempfile.TemporaryDirectory(dir=versions_dir(), prefix=".dl-") as td:
        archive = Path(td) / entry["name"]
        download(entry["url"], archive)
        verify_file(archive, entry)
        extract_archive(archive, dest)
    return dest


def set_default(version: str) -> None:
    cfg = load_config()
    cfg["default"] = version
    save_config(cfg)


def remove(version: str) -> None:
    d = versions_dir() / version
    if not d.exists():
        if version == bundled_version():
            die(f"Julia {version} is the copy bundled in the wheel; use `pip uninstall julialang` to remove it")
        die(f"Julia {version} is not installed")
    shutil.rmtree(d)
    cfg = load_config()
    if cfg.get("default") == version:
        cfg.pop("default")
        save_config(cfg)


# --------------------------------------------------------------------------- bundled julia


def _link_all(root: Path) -> None:
    """Recreate the symlinks that cannot live inside a wheel."""
    if not SYMLINK_MANIFEST.exists():
        return
    for rel, target in sorted(json.loads(SYMLINK_MANIFEST.read_text()).items()):
        p = root / rel
        if p.is_symlink() or p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, p)


def _ensure_exec(root: Path) -> None:
    if os.name == "nt":
        return
    for sub in ("bin", "libexec"):
        for p in (root / sub).rglob("*"):
            if p.is_file() and not os.access(p, os.X_OK):
                p.chmod(p.stat().st_mode | 0o111)


def prepare_bundled() -> Path:
    """Return a ready-to-run root for the Julia bundled in the wheel."""
    root = BUNDLED_DIR
    if (root / READY_MARKER).exists():
        return root
    try:
        _link_all(root)
        _ensure_exec(root)
        (root / READY_MARKER).write_text("ok\n")
        return root
    except OSError:
        # Read-only site-packages (e.g. a system-wide install): run from a private copy.
        version = bundled_version()
        copy = versions_dir() / version
        if not exe_in(copy).exists():
            print(f"Preparing a private copy of Julia {version} in {copy} ...", file=sys.stderr)
            versions_dir().mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, copy, symlinks=True)
            _link_all(copy)
            _ensure_exec(copy)
        return copy


def root_for(version: str) -> Path | None:
    d = versions_dir() / version
    if exe_in(d).exists():
        return d
    if version == bundled_version():
        return prepare_bundled()
    return None


def resolve_root() -> Path:
    version = active_version()
    if version is None:
        die("no Julia available here; run `julialang install latest`")
    root = root_for(version)
    if root is None:
        die(f"Julia {version} is not installed; run `julialang install {version}`")
    return root
