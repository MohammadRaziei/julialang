"""End-to-end test with a fake Julia (no network): sync -> build wheel -> pip install -> use it."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import venv
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from julialang import manager as M  # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the fake Julia is a POSIX shell script")

FAKE_JULIA = """#!/bin/sh
here="$(cd "$(dirname "$0")/.." && pwd)"
echo "julia version {v}"
echo "lib: $(cat "$here/lib/libfoo.so")"
"$here/libexec/julia/helper"
"""


def make_fake_julia(directory: Path, version: str) -> Path:
    """A tiny Julia-shaped tarball: an executable, a symlinked lib and a libexec helper."""
    tree = directory / f"julia-{version}"
    (tree / "bin").mkdir(parents=True)
    (tree / "lib").mkdir()
    (tree / "libexec/julia").mkdir(parents=True)
    (tree / "bin/julia").write_text(FAKE_JULIA.format(v=version))
    (tree / "bin/julia").chmod(0o755)
    (tree / "lib/libfoo.so.1").write_text("foo\n")
    os.symlink("libfoo.so.1", tree / "lib/libfoo.so")
    (tree / "libexec/julia/helper").write_text("#!/bin/sh\necho helper ok\n")
    (tree / "libexec/julia/helper").chmod(0o755)
    archive = directory / f"upstream-julia-{version}-linux-x86_64.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        t.add(tree, arcname=f"julia-{version}")
    return archive


def write_upstream(path: Path, archives: dict[str, Path]) -> None:
    data = {}
    for version, archive in archives.items():
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        file = {"triplet": "x86_64-linux-gnu", "arch": "x86_64", "url": archive.as_uri(), "sha256": sha}
        data[version] = {
            "stable": True,
            "files": [
                {**file, "kind": "archive"},
                {**file, "kind": "installer", "url": "file:///nonexistent"},  # must be ignored
            ],
        }
    data["9.9.99-rc1"] = {"stable": False, "files": []}  # must be ignored
    path.write_text(json.dumps(data))


def run(cmd, env=None, **kw):
    full_env = {**os.environ, **(env or {})}
    return subprocess.run([str(c) for c in cmd], env=full_env, capture_output=True, text=True, check=True, **kw).stdout


def test_full_pipeline(tmp_path: Path):
    mirror = tmp_path / "mirror"
    work = tmp_path / "work"
    work.mkdir()
    list_file = work / "julia-list.json"
    upstream = work / "versions.json"

    def sync():
        return run([
            sys.executable, ROOT / "tools/sync.py", "--source", "json", "--upstream", upstream.as_uri(), "--list-file", list_file,
            "--repo", "me/julialang", "--min-version", "9.0.0", "--base-url", mirror.as_uri(), "--keep-dir", mirror,
        ])

    # 1. sync: first version lands in the list with md5 + sha256
    write_upstream(upstream, {"9.9.9": make_fake_julia(work, "9.9.9")})
    assert "9.9.9" in sync()
    lst = json.loads(list_file.read_text())
    entry = lst["versions"]["9.9.9"]["files"]["linux-x86_64"]
    assert lst["release_tag"] == "__download__" and lst["latest"] == "9.9.9" and entry["name"] == "julia-9.9.9-linux-x86_64.tar.gz"
    assert len(entry["md5"]) == 32 and len(entry["sha256"]) == 64
    assert list(lst["versions"]["9.9.9"]["files"]) == ["linux-x86_64"]  # installer + rc ignored
    assert (mirror / entry["name"]).exists()

    # 2. a second run with nothing new must not touch the file
    before = list_file.read_text()
    assert "up to date" in sync()
    assert list_file.read_text() == before

    # 3. build the wheel: no symlinks inside, exec bits kept, manifest present
    dist = work / "dist"
    run([sys.executable, ROOT / "tools/build_wheel.py", "--list", list_file, "--platform", M.platform_key(),
         "--package-version", "0.5.7", "--out", dist])
    wheel = next(dist.glob("julialang-0.5.7-py3-none-manylinux*.whl"))
    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
        assert "julialang/_julia/bin/julia" in names and "julialang/_julia/lib/libfoo.so.1" in names
        assert "julialang/_julia/lib/libfoo.so" not in names  # symlink lives in the manifest
        assert json.loads(z.read("julialang/_symlinks.json")) == {"lib/libfoo.so": "libfoo.so.1"}
        assert (z.getinfo("julialang/_julia/bin/julia").external_attr >> 16) & 0o111
        assert "julialang-0.5.7.dist-info/RECORD" in names
        assert json.loads(z.read("julialang/_bundled.json"))["version"] == "9.9.9"

    # 4. install it in a fresh venv and run it
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True)
    bindir = env_dir / "bin"
    run([bindir / "python", "-m", "pip", "install", "--no-index", "--no-deps", "-q", wheel])
    env = {"JULIALANG_HOME": str(tmp_path / "home"), "JULIALANG_LIST_URL": list_file.as_uri()}
    out = run([bindir / "julia"], env=env)
    assert "julia version 9.9.9" in out and "lib: foo" in out and "helper ok" in out
    assert "9.9.9" in run([bindir / "julialang", "status"], env=env)

    # 5. a new Julia appears upstream -> sync -> status notices -> upgrade -> downgrade
    write_upstream(upstream, {
        "9.9.9": work / "upstream-julia-9.9.9-linux-x86_64.tar.gz",
        "9.9.10": make_fake_julia(work, "9.9.10"),
    })
    sync()
    assert json.loads(list_file.read_text())["latest"] == "9.9.10"
    assert "Update available" in run([bindir / "julialang", "status"], env=env)

    run([bindir / "julialang", "upgrade"], env=env)
    assert "julia version 9.9.10" in run([bindir / "julia"], env=env)
    assert "Already up to date" in run([bindir / "julialang", "upgrade"], env=env)

    run([bindir / "julialang", "downgrade"], env=env)
    assert "julia version 9.9.9" in run([bindir / "julia"], env=env)
    assert "julia version 9.9.10" in run([bindir / "julia"], env={**env, "JULIALANG_VERSION": "9.9.10"})

    run([bindir / "julialang", "use", "9.9.10"], env=env)
    run([bindir / "julialang", "remove", "9.9.10"], env=env)  # removing the default falls back to the bundled one
    assert "julia version 9.9.9" in run([bindir / "julia"], env=env)
    assert "9.9.10" in run([bindir / "julialang", "list"], env=env)  # still offered by the mirror


def test_one_bad_file_does_not_stop_the_sync(tmp_path: Path):
    good, bad = make_fake_julia(tmp_path, "9.9.9"), make_fake_julia(tmp_path, "9.9.8")
    upstream = tmp_path / "versions.json"
    write_upstream(upstream, {"9.9.9": good, "9.9.8": bad})
    data = json.loads(upstream.read_text())
    data["9.9.8"]["files"][0]["sha256"] = "0" * 64  # upstream hash does not match the file
    upstream.write_text(json.dumps(data))
    list_file = tmp_path / "julia-list.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools/sync.py"), "--source", "json", "--upstream", upstream.as_uri(),
         "--list-file", str(list_file), "--repo", "me/julialang", "--min-version", "9.0.0"],
        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""},
    )
    assert r.returncode == 1 and "FAILED julia-9.9.8-linux-x86_64.tar.gz" in r.stderr
    versions = json.loads(list_file.read_text())["versions"]
    assert "9.9.9" in versions and "9.9.8" not in versions  # the good one was still mirrored (and will be retried)
