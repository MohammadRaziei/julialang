"""Network side of julialang: the mirror's julia-list.json, and install/uninstall of Julia versions.

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
import time
import urllib.request
import zipfile
from pathlib import Path

from . import _state as S
from ._state import die, exe_in, home, parse_version, versions_dir

CACHE_TTL = 3600  # seconds a cached julia-list.json is trusted by `list`, `status` and `latest`


# --------------------------------------------------------------------------- mirror list


def list_url() -> str:
    repo = os.environ.get("JULIALANG_REPO", S.DEFAULT_REPO)
    return os.environ.get("JULIALANG_LIST_URL") or f"https://github.com/{repo}/releases/download/{S.RELEASE_TAG}/julia-list.json"


def cache_path() -> Path:
    return home() / "julia-list.json"


def platform_key() -> str:
    os_ = {"linux": "linux", "darwin": "macos", "windows": "windows"}.get(platform.system().lower())
    arch = {
        "x86_64": "x86_64", "amd64": "x86_64",
        "arm64": "aarch64", "aarch64": "aarch64",
        "i686": "i686", "i386": "i686", "x86": "i686",
    }.get(platform.machine().lower())
    if not os_ or not arch:
        die(f"unsupported platform: {platform.system()}/{platform.machine()}")
    return f"{os_}-{arch}"


def cached_list() -> dict | None:
    try:
        data = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "versions" in data else None


def fetch_list(timeout: int = 30) -> dict:
    """Download julia-list.json from the mirror and refresh the cache."""
    req = urllib.request.Request(list_url(), headers={"User-Agent": "julialang"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    if not isinstance(data, dict) or "versions" not in data:
        raise ValueError("not a julia-list.json")
    home().mkdir(parents=True, exist_ok=True)
    tmp = cache_path().with_name("julia-list.json.tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(cache_path())
    return data


def get_list(fresh: bool = False, strict: bool = True) -> dict | None:
    """The mirror list. `fresh` always asks the network first; otherwise a recent cache is enough.

    When the network fails the cached copy is used (with a warning). Without a cache `strict` exits,
    and a non-strict call returns None.
    """
    cache = cached_list()
    if not fresh and cache is not None:
        try:
            if time.time() - cache_path().stat().st_mtime < CACHE_TTL:
                return cache
        except OSError:
            pass
    try:
        return fetch_list()
    except Exception as e:  # network, DNS, 404, bad JSON ...
        if cache is not None:
            print(f"julialang: cannot reach the mirror ({e}); using the cached list", file=sys.stderr)
            return cache
        msg = f"cannot read the mirror list ({list_url()}): {e}"
        if strict:
            die(msg)
        print(f"julialang: {msg}", file=sys.stderr)
        return None


def available_versions(lst: dict, key: str | None = None) -> list[str]:
    """Versions of the list that have a file for this platform, oldest first."""
    key = key or platform_key()
    return sorted((v for v, m in lst.get("versions", {}).items() if key in m.get("files", {})), key=parse_version)


# --------------------------------------------------------------------------- download / verify / extract


def hash_file(path: Path) -> tuple[str, str]:
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


HEX64 = re.compile(r"[0-9a-f]{64}")


def check_hash_arg(text: str) -> str:
    """A sha256 given by the user (--sha256 / JULIALANG_SHA256): 64 hex digits, any case."""
    value = text.strip().lower()
    if not HEX64.fullmatch(value):
        die(f"not a sha256 (64 hex digits expected): '{text}'")
    return value


def cross_check(entry: dict, strict: bool) -> None:
    """Compare the sha256 the mirror recorded for its own copy with the one julialang.org published.

    The list carries both (`sha256` = what the mirror computed, `upstream_sha256` = what upstream publishes). They differ
    or the upstream one is missing only if the list is damaged, outdated or was tampered with: warn, or with `strict`
    refuse before anything is downloaded.
    """
    ours, upstream, name = entry["sha256"], entry.get("upstream_sha256"), entry["name"]
    if upstream is None:
        problem = f"the mirror list has no upstream sha256 for {name}, so it cannot be cross-checked"
    elif upstream != ours:
        problem = (f"the mirror list is inconsistent for {name}: the mirror recorded sha256 {ours} but julialang.org "
                   f"published {upstream}; the list or the mirror may have been tampered with")
    else:
        return
    if strict:
        die(f"{problem} (strict mode: nothing was downloaded). Get the official sha256 from julialang.org on a machine "
            "you trust and pass it with --sha256, or drop --strict")
    print(f"julialang: warning: {problem}", file=sys.stderr)


def verify_file(path: Path, entry: dict, expected: str | None = None) -> None:
    """Check a downloaded archive. A sha256 given by the user decides alone; otherwise the list's checksums must match."""
    sha, md5 = hash_file(path)
    if expected is not None:
        if sha != expected:
            die(f"{entry['name']} does not match the sha256 you gave (expected {expected}, got {sha}); nothing was installed")
        return
    if sha != entry["sha256"] or (entry.get("md5") and md5 != entry["md5"]):
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


def _extract_tar(archive: Path, tmp: Path) -> None:
    with tarfile.open(archive) as t:
        try:
            t.extractall(tmp, filter="data")
        except TypeError:  # Python without extraction filters
            t.extractall(tmp)
        except getattr(tarfile, "FilterError", ()):  # a link the strict filter dislikes: Julia's own are safe
            t.extractall(tmp, filter="tar")


def extract_archive(archive: Path, dest: Path) -> None:
    """Extract a Julia archive into `dest`, dropping the single top-level directory."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".extract-"))
    try:
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            _extract_tar(archive, tmp)
        children = list(tmp.iterdir())
        root = children[0] if len(children) == 1 and children[0].is_dir() else tmp
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(root), str(dest))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- install / uninstall


def install(version: str, lst: dict, strict: bool | None = None, expected: str | None = None) -> Path:
    """Download, verify and unpack one exact version from the mirror (nothing else is touched).

    `expected` is a sha256 the user got from a trusted source: the archive must match it and the list's own checksums are
    not consulted. `strict` (default: the `strict` setting) refuses a list whose two sha256 values disagree or are missing.
    """
    key = platform_key()
    entry = lst.get("versions", {}).get(version, {}).get("files", {}).get(key)
    if not entry:
        die(f"Julia {version} is not on the mirror for {key}")
    dest = S.version_root(version)
    if exe_in(dest).exists():
        print(f"Julia {version} is already installed", file=sys.stderr)
        S.register(version, dest)
        return dest
    if expected is None:
        cross_check(entry, S.get_setting("strict") if strict is None else strict)
    dest = versions_dir() / version
    versions_dir().mkdir(parents=True, exist_ok=True)
    print(f"Installing Julia {version} ({key}) ...", file=sys.stderr)
    with tempfile.TemporaryDirectory(dir=versions_dir(), prefix=".dl-") as td:
        archive = Path(td) / entry["name"]
        download(entry["url"], archive)
        verify_file(archive, entry, expected)
        extract_archive(archive, dest)
    if not exe_in(dest).exists():
        shutil.rmtree(dest, ignore_errors=True)
        die(f"{entry['name']} did not contain bin/{S.EXE}")
    S.register(version, dest)
    return dest


def uninstall(version: str) -> None:
    """Delete one installed version. If it was the default, the newest remaining one takes over."""
    if version not in S.installed_versions():
        die(f"Julia {version} is not installed")
    root = S.version_root(version)
    was_default = S.load_config().get("default") == version
    shutil.rmtree(root)
    S.unregister(version)
    if was_default:
        rest = S.installed_versions()
        if rest:
            S.set_default(rest[-1])
            print(f"Default is now Julia {rest[-1]}", file=sys.stderr)


def auto_install() -> None:
    """Install the newest Julia and make it the default (used by `julia` when JULIALANG_AUTO_INSTALL=1)."""
    lst = get_list(fresh=True)
    latest = S.resolve("latest", available_versions(lst)) or die("the mirror has no Julia for this platform")
    install(latest, lst)
    S.set_default(latest)
