#!/usr/bin/env python3
"""Mirror official Julia archives to the `__download__` GitHub prerelease and keep julia-list.json current.

Discovery: by default the script crawls the download pages of julialang.org
(https://julialang.org/downloads/manual-downloads/ = current stable + LTS, and
https://julialang.org/downloads/oldreleases/ = everything older). `--source json` uses the official
versions.json feed instead (handy as a fallback if the page layout ever changes).

For every stable Julia version (>= --min-version) that is not mirrored yet, each archive is downloaded,
verified against the upstream sha256 (and md5 when upstream publishes one), uploaded to the release with the
`gh` CLI (--upload) and recorded in julia-list.json with md5 + sha256. Files are deleted right after upload,
so a full backfill never needs more than one archive of disk space. Nothing is written when nothing is new.
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
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

DEFAULT_REPO = "mohammadraziei/julialang"
TAG = "__download__"
PAGES = [
    "https://julialang.org/downloads/manual-downloads/",
    "https://julialang.org/downloads/oldreleases/",
]
CHECKSUMS_BASE = "https://julialang-s3.julialang.org/bin/checksums"
VERSIONS_JSON = "https://julialang-s3.julialang.org/bin/versions.json"

# Archive file names we mirror: julia-<X.Y.Z>-<suffix>.<ext>. Pre-releases ("1.13.0-rc4-...") never match
# because the suffix must follow the version directly; installers (.exe/.dmg), musl, FreeBSD, ppc64le are not matched.
FILE_RE = re.compile(
    r"^julia-(\d+\.\d+\.\d+)-(linux-x86_64|linux-i686|linux-aarch64|mac64|macaarch64|win64|win32)\.(tar\.gz|zip)$"
)
SUFFIX_TO_KEY = {
    "linux-x86_64": "linux-x86_64", "linux-i686": "linux-i686", "linux-aarch64": "linux-aarch64",
    "mac64": "macos-x86_64", "macaarch64": "macos-aarch64",
    "win64": "windows-x86_64", "win32": "windows-i686",
}
MIRRORED = set(SUFFIX_TO_KEY.values())
HEX64 = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{64}(?![0-9a-fA-F])")
CHECKSUM_LINE = re.compile(r"^([0-9a-fA-F]{32,64})\s+\*?(\S+)\s*$")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
NOTES = (
    "Mirror of the official Julia binaries (from julialang.org), used by the `julialang` Python package.\n"
    "Managed by CI - do not edit by hand. The file list with md5/sha256 is `julia-list.json`."
)


def vkey(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


# --------------------------------------------------------------------------- network


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


def download(url: str, dest: Path, sha256: str, md5: str | None, retries: int = 3) -> tuple[str, str, int]:
    """Download `url`, verify it against the upstream hashes, return (sha256, md5, size)."""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "julialang-mirror"})
            h_sha, h_md5, size = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
                while chunk := r.read(1 << 20):
                    out.write(chunk)
                    h_sha.update(chunk)
                    h_md5.update(chunk)
                    size += len(chunk)
            if h_sha.hexdigest() != sha256.lower():
                raise RuntimeError(f"sha256 mismatch for {url}: upstream {sha256}, got {h_sha.hexdigest()}")
            if md5 and h_md5.hexdigest() != md5.lower():
                raise RuntimeError(f"md5 mismatch for {url}: upstream {md5}, got {h_md5.hexdigest()}")
            return h_sha.hexdigest(), h_md5.hexdigest(), size
        except Exception as e:
            print(f"  attempt {i + 1}/{retries} failed: {e}", file=sys.stderr)
            if i == retries - 1:
                raise
            time.sleep(5 * (i + 1))
    raise AssertionError("unreachable")


# --------------------------------------------------------------------------- discovery: crawling the site


class _Rows(HTMLParser):
    """Collect every link on a page, and the links + text of each table row."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.rows: list[dict] = []
        self._row: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = {"links": [], "text": []}
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
                if self._row is not None:
                    self._row["links"].append(href)

    def handle_endtag(self, tag):
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._row is not None:
            self._row["text"].append(data)


def classify(url: str) -> dict | None:
    """Version / platform key / extension of an archive URL we mirror, else None."""
    m = FILE_RE.match(url.split("?")[0].rsplit("/", 1)[-1])
    if not m:
        return None
    return {"version": m.group(1), "key": SUFFIX_TO_KEY[m.group(2)], "ext": m.group(3)}


def rank(entry: dict) -> int:
    """Prefer .zip on Windows and .tar.gz everywhere else (some versions offer both)."""
    return 0 if (entry["ext"] == "zip") == entry["key"].startswith("windows") else 1


def files_from_html(page_url: str, html: str) -> list[dict]:
    p = _Rows()
    p.feed(html)
    row_sha: dict[str, str] = {}
    for row in p.rows:  # the old-releases table carries a sha256 next to each link
        urls = [urljoin(page_url, h) for h in row["links"]]
        archives = [u for u in urls if classify(u)]
        hexes = HEX64.findall(" ".join(row["text"]))
        if len(archives) == 1 and len(hexes) == 1:
            row_sha[archives[0]] = hexes[0]
    out, seen = [], set()
    for href in p.links:
        url = urljoin(page_url, href)
        c = classify(url)
        if c and url not in seen:
            seen.add(url)
            out.append({**c, "url": url, "sha256": row_sha.get(url)})
    return out


def crawl_catalog(pages: list[str]) -> dict:
    catalog: dict[str, dict[str, dict]] = {}
    for page in pages:
        print(f"Crawling {page}")
        for f in files_from_html(page, http_get(page).decode("utf-8", "replace")):
            slot = catalog.setdefault(f["version"], {})
            if f["key"] not in slot or rank(f) < rank(slot[f["key"]]):
                slot[f["key"]] = f
    return catalog


def add_checksums(version: str, files: dict[str, dict], base: str) -> None:
    """Fill sha256 (when the page had none) and md5 from upstream's julia-<version>.sha256 / .md5 files."""
    found: dict[str, dict[str, str]] = {"sha256": {}, "md5": {}}
    for kind in found:
        try:
            for line in http_get(f"{base}/julia-{version}.{kind}").decode().splitlines():
                m = CHECKSUM_LINE.match(line.strip())
                if m:
                    found[kind][m.group(2)] = m.group(1).lower()
        except Exception as e:
            print(f"  note: no upstream {kind} file for {version} ({e})", file=sys.stderr)
    for f in files.values():
        name = f["url"].rsplit("/", 1)[-1]
        f["sha256"] = f.get("sha256") or found["sha256"].get(name)
        f["md5"] = f.get("md5") or found["md5"].get(name)


# --------------------------------------------------------------------------- discovery: versions.json


def platform_of(f: dict) -> str | None:
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


def json_catalog(data: dict) -> dict:
    catalog: dict[str, dict[str, dict]] = {}
    for ver, meta in data.items():
        if not meta.get("stable") or not VERSION_RE.fullmatch(ver):
            continue
        for f in meta.get("files", []):
            key = platform_of(f)
            if key:
                ext = "zip" if f["url"].endswith(".zip") else "tar.gz"
                catalog.setdefault(ver, {}).setdefault(key, {
                    "version": ver, "key": key, "ext": ext, "url": f["url"], "sha256": f.get("sha256"),
                })
    return catalog


# --------------------------------------------------------------------------- release + list


def gh(*args: str, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.run(["gh", *args], check=check, stdout=out, stderr=out)


def ensure_release(repo: str) -> None:
    if gh("release", "view", TAG, "--repo", repo, check=False, quiet=True).returncode == 0:
        return
    gh("release", "create", TAG, "--repo", repo, "--title", "Julia binaries (mirror)", "--notes", NOTES, "--prerelease")


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


def plan(catalog: dict, lst: dict, min_version: str, limit: int) -> list[tuple[str, dict]]:
    todo = []
    for ver, files in catalog.items():
        if not VERSION_RE.fullmatch(ver) or vkey(ver) < vkey(min_version):
            continue
        have = lst["versions"].get(ver, {}).get("files", {})
        missing = {k: f for k, f in files.items() if k not in have}
        if missing:
            todo.append((ver, missing))
    todo.sort(key=lambda t: vkey(t[0]), reverse=True)  # newest first
    return todo[:limit] if limit else todo


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["crawl", "json"], default="crawl", help="how to discover versions")
    ap.add_argument("--crawl-url", action="append", help=f"page to crawl, repeatable (default: {', '.join(PAGES)})")
    ap.add_argument("--checksums-base", default=CHECKSUMS_BASE, help="where julia-<version>.sha256/.md5 live")
    ap.add_argument("--upstream", default=os.environ.get("JULIA_VERSIONS_URL", VERSIONS_JSON), help="versions.json URL (--source json)")
    ap.add_argument("--list-file", default="julia-list.json", type=Path)
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name (default: $GITHUB_REPOSITORY)")
    ap.add_argument("--min-version", default="1.10.0", help="oldest Julia version to mirror (default: 1.10.0)")
    ap.add_argument("--limit", type=int, default=0, help="max versions per run, newest first (0 = all)")
    ap.add_argument("--upload", action="store_true", help=f"upload assets to the {TAG} release with `gh`")
    ap.add_argument("--dry-run", action="store_true", help="only print what would be mirrored")
    ap.add_argument("--base-url", help="asset URL prefix recorded in the list (default: the GitHub release)")
    ap.add_argument("--keep-dir", type=Path, help="also copy downloaded assets here (debugging / tests)")
    a = ap.parse_args()

    lst = load_list(a.list_file, a.repo or DEFAULT_REPO)
    repo = a.repo or lst.get("repo") or DEFAULT_REPO
    lst["repo"], lst["release_tag"] = repo, TAG
    base = (a.base_url or f"https://github.com/{repo}/releases/download/{TAG}").rstrip("/")

    catalog = crawl_catalog(a.crawl_url or PAGES) if a.source == "crawl" else json_catalog(json.loads(http_get(a.upstream)))
    todo = plan(catalog, lst, a.min_version, a.limit)
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
                if a.source == "crawl":
                    add_checksums(ver, files, a.checksums_base.rstrip("/"))
                for key, f in sorted(files.items()):
                    if not f.get("sha256"):
                        print(f"[{ver}] {key}: no upstream sha256 found, not mirroring an unverifiable file", file=sys.stderr)
                        continue
                    name = f"julia-{ver}-{key}.{f['ext']}"
                    path = Path(td) / name
                    print(f"[{ver}] {name}", flush=True)
                    sha, md5, size = download(f["url"], path, f["sha256"], f.get("md5"))
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
