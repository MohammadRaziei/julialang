#!/usr/bin/env python3
"""Assemble a platform wheel that bundles one Julia release (the same idea as the `ziglang` wheels).

The wheel version is the package version (pyproject.toml / --package-version), not the Julia version; the
bundled Julia is recorded in julialang/_bundled.json. The Julia archive comes from the mirror (julia-list.json), is verified against md5 + sha256, and is repacked
under `julialang/_julia/`. Symlinks cannot live inside a wheel, so they are stored in `_symlinks.json` and
recreated on first run (see julialang/manager.py). Unix file modes are preserved so pip restores the
executable bits.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from julialang import manager as M  # noqa: E402

WHEEL_TAGS = {
    "linux-x86_64": "manylinux_2_17_x86_64.manylinux2014_x86_64",
    "linux-aarch64": "manylinux_2_17_aarch64.manylinux2014_aarch64",
    "macos-x86_64": "macosx_10_14_x86_64",
    "macos-aarch64": "macosx_11_0_arm64",
    "windows-x86_64": "win_amd64",
}
OS_CLASSIFIER = {"linux": "POSIX :: Linux", "macos": "MacOS :: MacOS X", "windows": "Microsoft :: Windows"}
FIXED_DATE = (2020, 1, 1, 0, 0, 0)  # reproducible archives
PYPI_LIMIT = 100 * 1024 * 1024


def _parts(name: str) -> list[str]:
    return [p for p in PurePosixPath(name).parts if p not in (".", "/")]


def _top(names) -> str | None:
    tops = {p[0] for p in map(_parts, names) if p}
    return tops.pop() if len(tops) == 1 else None


def _strip(name: str, top: str | None) -> str:
    parts = _parts(name)
    if top and parts and parts[0] == top:
        parts = parts[1:]
    if ".." in parts:
        raise ValueError(f"unsafe path in archive: {name}")
    return "/".join(parts)


def iter_archive(path: Path):
    """Yield ("file", rel, mode, opener) / ("symlink", rel, target), top-level directory stripped.

    The archive is closed when the generator is exhausted (Windows cannot delete an open file).
    """
    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            top = _top(i.filename for i in infos)
            for i in infos:
                rel = _strip(i.filename, top)
                if i.is_dir() or not rel:
                    continue
                mode = ((i.external_attr >> 16) & 0o777) or 0o644
                yield "file", rel, mode, (lambda i=i: z.open(i))
    else:
        with tarfile.open(path) as t:
            members = t.getmembers()
            top = _top(m.name for m in members)
            for m in members:
                rel = _strip(m.name, top)
                if not rel:
                    continue
                if m.issym():
                    yield "symlink", rel, m.linkname
                elif m.isfile() or m.islnk():
                    yield "file", rel, m.mode & 0o777, (lambda m=m: t.extractfile(m))


def metadata_text(meta: dict, version: str, platform_key: str, readme: str) -> str:
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {meta['name']}",
        f"Version: {version}",
        f"Summary: {meta['description']}",
    ]
    for author in meta.get("authors", []):
        lines.append(f"Author-email: {author['name']} <{author['email']}>")
    if meta.get("keywords"):
        lines.append("Keywords: " + ",".join(meta["keywords"]))
    for label, url in meta.get("urls", {}).items():
        lines.append(f"Project-URL: {label}, {url}")
    lines += [
        "License: MIT (this packaging); Julia and its bundled libraries keep their own licenses",
        f"Requires-Python: {meta['requires-python']}",
        f"Classifier: Operating System :: {OS_CLASSIFIER[platform_key.split('-')[0]]}",  # this wheel's OS only
        *(f"Classifier: {c}" for c in meta.get("classifiers", []) if not c.startswith("Operating System ::")),
        "Description-Content-Type: text/markdown",
    ]
    return "\n".join(lines) + "\n\n" + readme


def build(a) -> Path:
    lst = json.loads(Path(a.list).read_text())
    julia = lst.get("latest") if a.version in (None, "latest") else a.version
    if not julia:
        sys.exit("julia-list.json has no versions yet; run the sync workflow first")
    plat = a.platform or M.platform_key()
    if plat not in WHEEL_TAGS:
        sys.exit(f"no wheel is built for {plat}")
    entry = lst["versions"].get(julia, {}).get("files", {}).get(plat)
    if not entry:
        sys.exit(f"Julia {julia} for {plat} is not in {a.list}")

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    name = pyproject["name"]
    version = a.package_version or pyproject["version"]
    tag = WHEEL_TAGS[plat]
    dist_info = f"{name}-{version}.dist-info"
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = out_dir / f"{name}-{version}-py3-none-{tag}.whl"
    readme = (ROOT / pyproject.get("readme", "README.md")).read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        if a.archive:
            archive = Path(a.archive)
        else:
            archive = Path(td) / entry["name"]
            print(f"Downloading {entry['url']}")
            M.download(entry["url"], archive)
        M.verify_file(archive, entry)
        print("Checksums OK (md5 + sha256)")

        record: list[tuple[str, str, int]] = []
        symlinks: dict[str, str] = {}
        with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:

            def zinfo(arc: str, mode: int) -> zipfile.ZipInfo:
                zi = zipfile.ZipInfo(arc, FIXED_DATE)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.create_system = 3  # Unix, so the mode bits are honoured
                zi.external_attr = (stat.S_IFREG | (0o755 if mode & 0o111 else 0o644)) << 16
                return zi

            def add_bytes(arc: str, data: bytes, mode: int = 0o644) -> None:
                zf.writestr(zinfo(arc, mode), data, compresslevel=9)
                record.append((arc, base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode(), len(data)))

            def add_stream(arc: str, opener, mode: int) -> None:
                h, size = hashlib.sha256(), 0
                with opener() as src, zf.open(zinfo(arc, mode), "w") as dst:
                    while chunk := src.read(1 << 20):
                        dst.write(chunk)
                        h.update(chunk)
                        size += len(chunk)
                record.append((arc, base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode(), size))

            for p in sorted((ROOT / "julialang").glob("*.py")):
                add_bytes(f"julialang/{p.name}", p.read_bytes())

            n_files = 0
            for kind, rel, *rest in iter_archive(archive):
                if kind == "symlink":
                    symlinks[rel] = rest[0]
                else:
                    add_stream(f"julialang/_julia/{rel}", rest[1], rest[0])
                    n_files += 1
            add_bytes("julialang/_symlinks.json", json.dumps(symlinks, indent=1, sort_keys=True).encode())
            add_bytes("julialang/_bundled.json", json.dumps({"version": julia, "platform": plat}).encode())

            scripts = "\n".join(f"{k} = {v}" for k, v in pyproject["scripts"].items())
            wheel_meta = "\n".join(
                ["Wheel-Version: 1.0", "Generator: julialang tools/build_wheel.py", "Root-Is-Purelib: false"]
                + [f"Tag: py3-none-{t}" for t in tag.split(".")]
            )
            add_bytes(f"{dist_info}/METADATA", metadata_text(pyproject, version, plat, readme).encode())
            add_bytes(f"{dist_info}/WHEEL", (wheel_meta + "\n").encode())
            add_bytes(f"{dist_info}/entry_points.txt", f"[console_scripts]\n{scripts}\n".encode())
            add_bytes(f"{dist_info}/LICENSE", (ROOT / "LICENSE").read_bytes())

            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            for arc, digest, size in record:
                w.writerow([arc, f"sha256={digest}", size])
            w.writerow([f"{dist_info}/RECORD", "", ""])
            zf.writestr(zinfo(f"{dist_info}/RECORD", 0o644), buf.getvalue(), compresslevel=9)

    size = wheel_path.stat().st_size
    print(f"Built {wheel_path} (Julia {julia}; {size / 1e6:.0f} MB; {n_files} files, {len(symlinks)} symlinks in a manifest)")
    if size > PYPI_LIMIT:
        print("NOTE: larger than PyPI's default 100 MB file limit; uploading to PyPI needs a limit increase.")
    return wheel_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", default=str(ROOT / "julia-list.json"), help="julia-list.json to read")
    ap.add_argument("--platform", help=f"one of {', '.join(WHEEL_TAGS)} (default: this machine)")
    ap.add_argument("--version", default="latest", help="Julia version to bundle (default: latest in the list)")
    ap.add_argument("--package-version", help="wheel version (default: version in pyproject.toml)")
    ap.add_argument("--archive", help="use this local archive instead of downloading (still verified)")
    ap.add_argument("--out", default="dist")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
