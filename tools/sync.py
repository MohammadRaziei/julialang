#!/usr/bin/env python3
"""Mirror official Julia archives to GitHub prereleases and keep `julia-list.json` current.

Discovery: by default the script crawls the download pages of julialang.org
(https://julialang.org/downloads/manual-downloads/ = current stable + LTS, and
https://julialang.org/downloads/oldreleases/ = everything older). `--source json` uses the official
versions.json feed instead (handy as a fallback if the page layout ever changes).

For every stable Julia version (>= --min-version, default: all) that is not mirrored yet, each archive is
downloaded, verified against the upstream sha256 (and md5 when upstream publishes one), uploaded to a release with
the `gh` CLI (--upload) and recorded in julia-list.json with md5 + sha256. Files are deleted right after upload, so
a full backfill never needs more than one archive of disk space.

julia-list.json is NOT kept in git: it is an asset of the `__download__` release. The existing list is read from
there (404 = empty), a local untracked working copy is kept, and the list is uploaded again after every version, so
an interrupted run loses nothing. A GitHub release holds at most ~1000 assets, so after SHARD_CAP files the next
archives go to `__download_2__`, `__download_3__` ... (each file's `url` in the list says where it is).
`--max-minutes` stops cleanly before a CI job times out and reports `more=true`; the next run continues where this one stopped.
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
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

DEFAULT_REPO = "mohammadraziei/julialang"
TAG = "__download__"  # first mirror release; also holds julia-list.json
SHARD_CAP = 900  # archives per mirror release (GitHub allows ~1000 assets per release)
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
SCHEMA = 2  # 2: every file also records `upstream_sha256`, what julialang.org published (`sha256` is what we computed)
NOTES = (
    "Mirror of the official Julia binaries (from julialang.org), used by the `julialang` Python package.\n"
    "Managed by CI - do not edit by hand. The file list with md5/sha256 is `julia-list.json` (in `__download__`)."
)
DOWNLOAD_URL_TAG = re.compile(r"/releases/download/([^/]+)/")


def vkey(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


# --------------------------------------------------------------------------- network


def http_get(url: str, retries: int = 4) -> bytes:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "julialang-mirror"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 or i == retries - 1:  # a client error will not fix itself
                raise
            time.sleep(3 * (i + 1))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(3 * (i + 1))
    raise AssertionError("unreachable")


def download(url: str, dest: Path, sha256: str, md5: str | None, retries: int = 3) -> tuple[str, str, int]:
    """Download `url`, require the upstream sha256 to match, return (sha256, md5, size)."""
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
                # sha256 (checked above) is the authority; upstream's .md5 files are occasionally stale.
                print(f"  warning: upstream md5 for {url} is {md5} but the file is {h_md5.hexdigest()}; "
                      "sha256 matches, so the file is accepted", file=sys.stderr)
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


def ensure_release(repo: str, tag: str, ready: set[str]) -> None:
    if tag in ready:
        return
    if gh("release", "view", tag, "--repo", repo, check=False, quiet=True).returncode != 0:
        title = "Julia binaries (mirror)" if tag == TAG else f"Julia binaries (mirror, part {tag.strip('_').split('_')[-1]})"
        gh("release", "create", tag, "--repo", repo, "--title", title, "--notes", NOTES, "--prerelease", "--latest=false")
    ready.add(tag)


def shard_tag(n: int) -> str:
    return TAG if n == 1 else f"__download_{n}__"


def asset_base(repo: str, tag: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}"


def tags_in_use(lst: dict) -> dict[str, int]:
    """How many mirrored files each release tag holds, going by the urls recorded in the list."""
    counts: dict[str, int] = {}
    for meta in lst["versions"].values():
        for f in meta["files"].values():
            m = DOWNLOAD_URL_TAG.search(f.get("url", ""))
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def pick_tag(lst: dict) -> str:
    """The first mirror release that still has room (GitHub allows ~1000 assets per release)."""
    counts, n = tags_in_use(lst), 1
    while counts.get(shard_tag(n), 0) >= SHARD_CAP:
        n += 1
    return shard_tag(n)


def empty_list(repo: str) -> dict:
    return {"schema": SCHEMA, "repo": repo, "release_tag": TAG, "release_tags": [TAG], "latest": None, "updated": None, "versions": {}}


def fetch_remote_list(url: str) -> dict | None:
    """The list published as a release asset. None when it does not exist yet; any other failure is fatal,
    because carrying on with an empty list would re-mirror everything and overwrite the real one."""
    try:
        return json.loads(http_get(url))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except urllib.error.URLError as e:
        if isinstance(e.reason, FileNotFoundError):  # file:// URL (tests)
            return None
        raise


def load_list(path: Path, repo: str, list_url: str | None) -> dict:
    """The existing list: from the release asset when `list_url` is given, else from the local working copy."""
    lst = None
    if list_url:
        lst = fetch_remote_list(list_url)
        print(f"Existing list: {'found at ' + list_url if lst is not None else 'none yet (first run)'}")
    elif path.exists():
        lst = json.loads(path.read_text())
    if lst is None:
        return empty_list(repo)
    lst.setdefault("versions", {})
    return lst


def finalize(lst: dict) -> None:
    lst["latest"] = max(lst["versions"], key=vkey) if lst["versions"] else None
    lst["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lst["release_tags"] = sorted(tags_in_use(lst), key=lambda t: (t != TAG, t)) or [TAG]


def write_list(lst: dict, path: Path) -> None:
    lst["versions"] = {
        v: {"files": dict(sorted(m["files"].items()))}
        for v, m in sorted(lst["versions"].items(), key=lambda kv: vkey(kv[0]), reverse=True)
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(lst, indent=2) + "\n")
    tmp.replace(path)


def publish_list(lst: dict, a: argparse.Namespace, repo: str) -> None:
    """Write the working copy and put it where clients read it: the `__download__` release (and --keep-dir)."""
    finalize(lst)
    write_list(lst, a.list_file)
    if a.keep_dir:
        shutil.copy2(a.list_file, a.keep_dir / "julia-list.json")
    if a.upload:
        with tempfile.TemporaryDirectory() as td:  # the asset name must be julia-list.json whatever the local name
            asset = Path(td) / "julia-list.json"
            shutil.copy2(a.list_file, asset)
            gh("release", "upload", TAG, str(asset), "--clobber", "--repo", repo)


def backfill_upstream(lst: dict, catalog: dict, checksums_base: str | None = None) -> tuple[int, list[str], list[str]]:
    """Give every file of the list an `upstream_sha256` taken from what julialang.org publishes now (no downloads).

    A file gets the value only when upstream's sha256 equals the one the list records. Returns (filled, mismatched, unknown):
    files whose upstream value differs (never written: strict clients refuse them) and files upstream no longer lists.
    """
    filled, mismatched, unknown = 0, [], []
    for ver, meta in lst["versions"].items():
        upstream = catalog.get(ver, {})
        todo = [k for k, e in meta["files"].items() if not e.get("upstream_sha256")]
        if not todo:
            continue
        if checksums_base and upstream:
            add_checksums(ver, upstream, checksums_base)
        for key in todo:
            entry, up = meta["files"][key], (upstream.get(key) or {}).get("sha256")
            if not up:
                unknown.append(entry["name"])
            elif up.lower() == entry["sha256"].lower():
                entry["upstream_sha256"] = up.lower()
                filled += 1
            else:
                mismatched.append(f"{entry['name']}: list {entry['sha256']}, julialang.org {up.lower()}")
    return filled, mismatched, unknown


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


def set_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{name}={value}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["crawl", "json"], default="crawl", help="how to discover versions")
    ap.add_argument("--crawl-url", action="append", help=f"page to crawl, repeatable (default: {', '.join(PAGES)})")
    ap.add_argument("--checksums-base", default=CHECKSUMS_BASE, help="where julia-<version>.sha256/.md5 live")
    ap.add_argument("--upstream", default=os.environ.get("JULIA_VERSIONS_URL", VERSIONS_JSON), help="versions.json URL (--source json)")
    ap.add_argument("--list-file", default="julia-list.json", type=Path, help="local working copy of the list (not tracked by git)")
    ap.add_argument("--list-url", help="where to read the existing list (default with --upload/--dry-run: the __download__ release asset)")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name (default: $GITHUB_REPOSITORY)")
    ap.add_argument("--min-version", default="0.0.0", help="oldest Julia version to mirror (default: 0.0.0 = all)")
    ap.add_argument("--limit", type=int, default=0, help="max versions per run, newest first (0 = all)")
    ap.add_argument("--max-minutes", type=float, default=0, help="stop cleanly after this long (0 = no limit); prints more=true")
    ap.add_argument("--upload", action="store_true", help="upload assets to the mirror releases with `gh`")
    ap.add_argument("--dry-run", action="store_true", help="only print what would be mirrored")
    ap.add_argument("--base-url", help="asset URL prefix recorded in the list (default: the GitHub releases); disables sharding")
    ap.add_argument("--backfill-upstream", action="store_true",
                    help="no mirroring: record upstream_sha256 for list entries that lack it (compares with julialang.org, downloads nothing)")
    ap.add_argument("--keep-dir", type=Path, help="also copy downloaded assets and the list here (debugging / tests)")
    a = ap.parse_args()

    repo = a.repo or DEFAULT_REPO
    list_url = a.list_url or (f"{asset_base(repo, TAG)}/julia-list.json" if (a.upload or a.dry_run) else None)
    lst = load_list(a.list_file, repo, list_url)
    lst["repo"], lst["release_tag"] = repo, TAG
    set_output("more", "false")

    catalog = crawl_catalog(a.crawl_url or PAGES) if a.source == "crawl" else json_catalog(json.loads(http_get(a.upstream)))
    if a.backfill_upstream:
        filled, mismatched, unknown = backfill_upstream(lst, catalog, a.checksums_base.rstrip("/") if a.source == "crawl" else None)
        upgraded, lst["schema"] = lst.get("schema") != SCHEMA, SCHEMA
        print(f"upstream_sha256 recorded for {filled} file(s); {len(unknown)} not listed upstream any more; {len(mismatched)} different")
        for name in unknown:
            print(f"  not on julialang.org: {name}", file=sys.stderr)
        for line in mismatched:
            print(f"  MISMATCH {line}", file=sys.stderr)
        if (filled or upgraded) and not a.dry_run:
            publish_list(lst, a, repo)
        return 1 if mismatched else 0
    todo = plan(catalog, lst, a.min_version, a.limit)
    if not todo:
        print("Mirror is up to date.")
        return 0
    for ver, files in todo:
        print(f"Julia {ver}: {', '.join(sorted(files))}")
    if a.dry_run:
        return 0

    ready: set[str] = set()
    if a.upload:
        ensure_release(repo, TAG, ready)  # julia-list.json always lives here
    if a.keep_dir:
        a.keep_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + a.max_minutes * 60 if a.max_minutes else None

    changed = published = False
    stopped = False
    failures: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as td:
            for ver, files in todo:
                if deadline and time.monotonic() > deadline:
                    stopped = True
                    break
                if a.source == "crawl":
                    add_checksums(ver, files, a.checksums_base.rstrip("/"))
                ver_changed = False
                for key, f in sorted(files.items()):
                    if deadline and time.monotonic() > deadline:
                        stopped = True
                        break
                    if not f.get("sha256"):
                        print(f"[{ver}] {key}: no upstream sha256 found, not mirroring an unverifiable file", file=sys.stderr)
                        continue
                    name = f"julia-{ver}-{key}.{f['ext']}"
                    path = Path(td) / name
                    tag = TAG if a.base_url else pick_tag(lst)
                    print(f"[{ver}] {name} -> {tag}", flush=True)
                    try:  # one bad file must not stop the rest; it is retried by the next run
                        sha, md5, size = download(f["url"], path, f["sha256"], f.get("md5"))
                        if a.upload:
                            ensure_release(repo, tag, ready)
                            gh("release", "upload", tag, str(path), "--clobber", "--repo", repo)
                        if a.keep_dir:
                            shutil.copy2(path, a.keep_dir / name)
                    except Exception as e:
                        print(f"  FAILED {name}: {e}", file=sys.stderr)
                        failures.append(name)
                        continue
                    finally:
                        path.unlink(missing_ok=True)
                    base = a.base_url.rstrip("/") if a.base_url else asset_base(repo, tag)
                    lst["versions"].setdefault(ver, {"files": {}})["files"][key] = {
                        "name": name,
                        "url": f"{base}/{name}",
                        "size": size,
                        "md5": md5,
                        "sha256": sha,  # computed here from the bytes that were uploaded
                        "upstream_sha256": f["sha256"].lower(),  # published by julialang.org; download() required them to match
                    }
                    changed = ver_changed = True
                    write_list(lst, a.list_file)  # progress survives a crash
                if ver_changed:  # publish after every version so clients see it and a crash loses nothing
                    publish_list(lst, a, repo)
                    published = True
                if stopped:
                    break
    finally:
        if changed and not published:
            publish_list(lst, a, repo)
    if stopped:
        print("Time budget reached; more versions remain and the next run continues.", file=sys.stderr)
        set_output("more", "true")
    if failures:
        print(f"{len(failures)} file(s) failed and will be retried next run: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
