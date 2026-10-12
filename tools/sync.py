#!/usr/bin/env python3
"""Mirror official Julia archives to the `julia_binary` GitHub release and keep julia-list.json current.

For every stable Julia version (>= --min-version) that is missing from julia-list.json, download each
archive from julialang.org, verify the upstream sha256, compute md5 + sha256, optionally upload it to the
release (needs the `gh` CLI), and record it in julia-list.json. Files are removed right after upload, so a
full backfill never needs more than one archive of disk space.

Nothing is written when there is nothing new, so scheduled runs stay silent and commit-free.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_REPO = "mohammadraziei/julialang"
TAG = "julia_binary"
UPSTREAM = "https://julialang-s3.julialang.org/bin/versions.json"

# Platforms that get mirrored (kind == "archive" only; installers, musl, FreeBSD, ARMv7/PPC are skipped).
MIRRORED = {
    "linux-x86_64", "linux-aarch64", "linux-i686",
    "macos-x86_64", "macos-aarch64",
    "windows-x86_64", "windows-i686",
}
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
NOTES = (
    "Mirror of the official Julia binaries (from julialang.org), used by the `julialang` Python package.\n"
    "Managed by CI - do not edit by hand. The file list with md5/sha256 is `julia-list.json`."
)


def vkey(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def platform_of(f: dict) -> str | None:
    """Map an upstream versions.json file entry to one of our platform keys."""
    triplet, arch = (f.get("triplet") or "").lower(), f.get("arch")
    if f.get("kind") != "archive" or not arch or "musl" in triplet or "freebsd" in triplet:
        return None
    if "linux" in triplet:
        os_ = "linux"
    elif "apple" in triplet or "darwin" in triplet:
        os_ = "macos"
    elif "mingw" in triplet or "windows" in triplet:
        os_ = "windows"
    else:
        return None
    key = f"{os_}-{arch}"
    return key if key in MIRRORED else None


def asset_name(version: str, key: str, url: str) -> str:
    ext = "zip" if url.endswith(".zip") else "tar.gz"
    return f"julia-{version}-{key}.{ext}"


def http_get(url: str, retries: int = 4) -> bytes:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "julialang-mirror"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(3 * (i + 1))
    raise AssertionError("unreachable")


def download(url: str, dest: Path, expect_sha256: str | None, retries: int = 3) -> tuple[str, str, int]:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "julialang-mirror"})
            sha, md5, size = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
                while chunk := r.read(1 << 20):
                    out.write(chunk)
                    sha.update(chunk)
                    md5.update(chunk)
                    size += len(chunk)
            if expect_sha256 and sha.hexdigest() != expect_sha256:
                raise RuntimeError(f"sha256 mismatch for {url}: upstream says {expect_sha256}, got {sha.hexdigest()}")
            return sha.hexdigest(), md5.hexdigest(), size
        except Exception as e:
            print(f"  attempt {i + 1}/{retries} failed: {e}", file=sys.stderr)
            if i == retries - 1:
                raise
            time.sleep(5 * (i + 1))
    raise AssertionError("unreachable")


def gh(*args: str, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.run(["gh", *args], check=check, stdout=out, stderr=out)


def ensure_release(repo: str) -> None:
    if gh("release", "view", TAG, "--repo", repo, check=False, quiet=True).returncode == 0:
        return
    gh("release", "create", TAG, "--repo", repo, "--title", "Julia binaries (mirror)", "--notes", NOTES, "--latest=false")


def load_list(path: Path, repo: str) -> dict:
    if path.exists():
        lst = json.loads(path.read_text())
        lst.setdefault("versions", {})
        return lst
    return {"schema": 1, "repo": repo, "release_tag": TAG, "latest": None, "updated": None, "versions": {}}


def write_list(lst: dict, path: Path) -> None:
    lst["versions"] = {
        v: {"files": dict(sorted(m["files"].items()))}
        for v, m in sorted(lst["versions"].items(), key=lambda kv: vkey(kv[0]), reverse=True)
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(lst, indent=2) + "\n")
    tmp.replace(path)


def plan(upstream: dict, lst: dict, min_version: str, limit: int) -> list[tuple[str, dict]]:
    todo = []
    for ver, meta in upstream.items():
        if not meta.get("stable") or not VERSION_RE.fullmatch(ver) or vkey(ver) < vkey(min_version):
            continue
        have = lst["versions"].get(ver, {}).get("files", {})
        files: dict[str, dict] = {}
        for f in meta.get("files", []):
            key = platform_of(f)
            if key and key not in have:
                files.setdefault(key, f)
        if files:
            todo.append((ver, files))
    todo.sort(key=lambda t: vkey(t[0]), reverse=True)  # newest first
    return todo[:limit] if limit else todo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", default=os.environ.get("JULIA_VERSIONS_URL", UPSTREAM), help="versions.json URL")
    ap.add_argument("--list-file", default="julia-list.json", type=Path)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name (default: $GITHUB_REPOSITORY)")
    ap.add_argument("--min-version", default="1.10.0", help="oldest Julia version to mirror (default: 1.10.0)")
    ap.add_argument("--limit", type=int, default=0, help="max versions per run, newest first (0 = all)")
    ap.add_argument("--upload", action="store_true", help="upload assets to the release with `gh`")
    ap.add_argument("--dry-run", action="store_true", help="only print what would be mirrored")
    ap.add_argument("--base-url", help="asset URL prefix recorded in the list (default: the GitHub release)")
    ap.add_argument("--keep-dir", type=Path, help="also copy downloaded assets here (debugging / tests)")
    a = ap.parse_args()

    lst = load_list(a.list_file, a.repo or DEFAULT_REPO)
    repo = a.repo or lst.get("repo") or DEFAULT_REPO
    lst["repo"] = repo
    base = (a.base_url or f"https://github.com/{repo}/releases/download/{TAG}").rstrip("/")

    upstream = json.loads(http_get(a.upstream))
    todo = plan(upstream, lst, a.min_version, a.limit)
    if not todo:
        print("Mirror is up to date.")
        return 0
    for ver, files in todo:
        print(f"Julia {ver}: {', '.join(sorted(files))}")
    if a.dry_run:
        return 0

    if a.upload:
        ensure_release(repo)
    if a.keep_dir:
        a.keep_dir.mkdir(parents=True, exist_ok=True)

    changed = False
    try:
        with tempfile.TemporaryDirectory() as td:
            for ver, files in todo:
                for key, f in sorted(files.items()):
                    name = asset_name(ver, key, f["url"])
                    path = Path(td) / name
                    print(f"[{ver}] {name}", flush=True)
                    sha, md5, size = download(f["url"], path, f.get("sha256"))
                    if a.upload:
                        gh("release", "upload", TAG, str(path), "--clobber", "--repo", repo)
                    if a.keep_dir:
                        shutil.copy2(path, a.keep_dir / name)
                    path.unlink()
                    lst["versions"].setdefault(ver, {"files": {}})["files"][key] = {
                        "name": name,
                        "url": f"{base}/{name}",
                        "size": size,
                        "md5": md5,
                        "sha256": sha,
                    }
                    changed = True
                    write_list(lst, a.list_file)  # progress survives a crash
    finally:
        if changed:
            lst["latest"] = max(lst["versions"], key=vkey)
            lst["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            write_list(lst, a.list_file)
            if a.upload:
                gh("release", "upload", TAG, str(a.list_file), "--clobber", "--repo", repo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
