"""End-to-end test with a fake Julia and a fake mirror on disk (no network):
sync -> thin wheel -> pip install -> julialang install / upgrade / downgrade / uninstall -> julia."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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

TRIPLETS = {
    "linux-x86_64": ("x86_64-linux-gnu", "x86_64"),
    "linux-aarch64": ("aarch64-linux-gnu", "aarch64"),
    "macos-x86_64": ("x86_64-apple-darwin14", "x86_64"),
    "macos-aarch64": ("aarch64-apple-darwin14", "aarch64"),
}
KEY = M.platform_key() if os.name != "nt" else "linux-x86_64"
if KEY not in TRIPLETS:
    pytest.skip(f"no fake-mirror triplet for {KEY}", allow_module_level=True)

FAKE_JULIA = """#!/bin/sh
here="$(cd "$(dirname "$0")/.." && pwd)"
echo "julia version {v}"
echo "args: $*"
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
    archive = directory / f"upstream-julia-{version}-{KEY}.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        t.add(tree, arcname=f"julia-{version}")
    return archive


def write_upstream(path: Path, archives: dict[str, Path]) -> None:
    triplet, arch = TRIPLETS[KEY]
    data = {}
    for version, archive in archives.items():
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        file = {"triplet": triplet, "arch": arch, "url": archive.as_uri(), "sha256": sha}
        data[version] = {
            "stable": True,
            "files": [
                {**file, "kind": "archive"},
                {**file, "kind": "installer", "url": "file:///nonexistent"},  # must be ignored
            ],
        }
    data["9.9.99-rc1"] = {"stable": False, "files": []}  # must be ignored
    path.write_text(json.dumps(data))


def run(cmd, env=None, check=True, **kw):
    full_env = {**os.environ, **(env or {})}
    r = subprocess.run([str(c) for c in cmd], env=full_env, capture_output=True, text=True, **kw)
    if check and r.returncode:
        raise AssertionError(f"{cmd} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r.stdout if check else r


def test_full_pipeline(tmp_path: Path):
    pytest.importorskip("setuptools")
    pytest.importorskip("wheel")
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

    # 1. sync: the first version lands in the list with md5 + sha256, and the list is copied next to the archives
    write_upstream(upstream, {"9.9.9": make_fake_julia(work, "9.9.9")})
    assert "9.9.9" in sync()
    lst = json.loads(list_file.read_text())
    entry = lst["versions"]["9.9.9"]["files"][KEY]
    assert lst["release_tag"] == "__download__" and lst["latest"] == "9.9.9" and entry["name"] == f"julia-9.9.9-{KEY}.tar.gz"
    assert len(entry["md5"]) == 32 and len(entry["sha256"]) == 64
    assert list(lst["versions"]["9.9.9"]["files"]) == [KEY]  # installer + rc ignored
    assert (mirror / entry["name"]).exists() and (mirror / "julia-list.json").exists()

    # 2. a second run with nothing new must not touch the file
    before = list_file.read_text()
    assert "up to date" in sync()
    assert list_file.read_text() == before

    # 3. the package is ONE tiny pure wheel: no Julia inside
    src = tmp_path / "src"
    src.mkdir()
    shutil.copytree(ROOT / "julialang", src / "julialang", ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(ROOT / f, src / f)
    pyproject = src / "pyproject.toml"
    pyproject.write_text(re.sub(r'(?m)^version = ".*"$', 'version = "0.5.7"', pyproject.read_text(), count=1))
    dist = tmp_path / "dist"
    run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q", "-w", dist, src])
    wheel = next(dist.glob("julialang-0.5.7-py3-none-any.whl"))
    assert wheel.stat().st_size < 100_000
    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
        assert {"julialang/julia_cli.py", "julialang/__main__.py"} <= set(names)
        assert "julialang/cli.py" not in names
        assert not any("_julia" in n or "bundled" in n for n in names)
        scripts = z.read("julialang-0.5.7.dist-info/entry_points.txt").decode()
        assert "julia = julialang.julia_cli:main" in scripts and "julialang = julialang.__main__:main" in scripts

    # 4. install it in a fresh venv: before `julialang install` the shim explains what to do
    env_dir = tmp_path / "venv"
    venv.create(env_dir, with_pip=True)
    bindir = env_dir / "bin"
    run([bindir / "python", "-m", "pip", "install", "--no-index", "--no-deps", "-q", wheel])
    home = tmp_path / "home"
    env = {"JULIALANG_HOME": str(home), "JULIALANG_LIST_URL": list_file.as_uri()}
    r = run([bindir / "julia"], env=env, check=False)
    assert r.returncode != 0 and "julialang install" in r.stderr
    assert "No Julia installed" in run([bindir / "julialang", "status"], env=env)

    jl = lambda *a, **k: run([bindir / "julialang", *a], env={**env, **k.pop("env", {})}, **k)  # noqa: E731
    julia = lambda *a, **k: run([bindir / "julia", *a], env={**env, **k.pop("env", {})}, **k)  # noqa: E731

    jl("install")  # no spec = latest; becomes the default
    out = julia("--check", "x")
    assert "julia version 9.9.9" in out and "args: --check x" in out and "lib: foo" in out and "helper ok" in out
    assert "args: --check x" in run([bindir / "python", "-m", "julialang", "run", "--check", "x"], env=env)  # = `julia --check x`
    cfg = json.loads((home / "config.json").read_text())
    assert cfg["default"] == "9.9.9" and cfg["installed"]["9.9.9"]["path"] == "versions/9.9.9"

    # 5. a new Julia appears upstream -> sync -> status notices
    write_upstream(upstream, {
        "9.9.9": work / f"upstream-julia-9.9.9-{KEY}.tar.gz",
        "9.9.10": make_fake_julia(work, "9.9.10"),
        "9.8.0": make_fake_julia(work, "9.8.0"),
    })
    sync()
    assert json.loads(list_file.read_text())["latest"] == "9.9.10"
    assert "latest      9.9.9" in jl("status")  # the cached list is trusted for an hour ...
    assert "9.9.10" in jl("fetch")  # ... until `julialang fetch` refreshes it
    assert "Update available" in jl("status")

    # install adds a version WITHOUT removing the others; --no-default keeps the default
    jl("install", "9.8", "--no-default")
    assert "julia version 9.9.9" in julia()
    assert "julia version 9.8.0" in julia(env={"JULIALANG_VERSION": "9.8"})
    listing = jl("list", "--installed")
    assert "9.8.0" in listing and "9.9.9  (default)" in listing

    # use switches between installed versions only
    jl("use", "9.8")
    assert "julia version 9.8.0" in julia()
    r = jl("use", "9.9.10", check=False)
    assert r.returncode != 0 and "julialang install" in r.stderr
    jl("use", "9.9.9")

    # upgrade installs the target, makes it the default and deletes the previous default (9.8.0 stays)
    assert "now the default" in jl("upgrade")
    assert "julia version 9.9.10" in julia()
    assert not (home / "versions/9.9.9").exists() and (home / "versions/9.8.0").exists()
    assert "Already up to date" in jl("upgrade")

    # downgrade needs a spec; it replaces the current default
    r = jl("downgrade", check=False)
    assert r.returncode != 0 and "SPEC" in r.stderr
    jl("downgrade", "<9.9.10")  # newest version below 9.9.10 on the mirror = 9.9.9
    assert "julia version 9.9.9" in julia() and not (home / "versions/9.9.10").exists()
    r = jl("downgrade", "9.9.10", check=False)  # that would be an upgrade
    assert r.returncode != 0 and "upgrade" in r.stderr

    # uninstall: one version, then a spec that matches several (needs --yes without a terminal)
    jl("install", "9.9.10")
    r = jl("uninstall", ">=9.0", check=False)
    assert r.returncode != 0 and "--yes" in r.stderr
    jl("uninstall", "9.9.10")
    assert not (home / "versions/9.9.10").exists()
    out = jl("uninstall", "<9.9.10", "--yes")
    assert "Removed Julia 9.8.0" in out and "Removed Julia 9.9.9" in out
    assert "no Julia installed yet" in julia(check=False).stderr
    assert "9.9.10" in jl("list")  # still offered by the mirror

    # folders deleted by hand are noticed
    jl("install", "9.9.10")
    shutil.rmtree(home / "versions/9.9.10")
    assert "files are missing" in julia(check=False).stderr  # a clear message, not a crash
    assert "(none)" in jl("list", "--installed")


def test_auto_install_is_opt_in(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    list_file, upstream, mirror = work / "julia-list.json", work / "versions.json", tmp_path / "mirror"
    write_upstream(upstream, {"9.9.9": make_fake_julia(work, "9.9.9")})
    run([sys.executable, ROOT / "tools/sync.py", "--source", "json", "--upstream", upstream.as_uri(), "--list-file", list_file,
         "--repo", "me/julialang", "--min-version", "9.0.0", "--base-url", mirror.as_uri(), "--keep-dir", mirror])
    env = {"JULIALANG_HOME": str(tmp_path / "home"), "JULIALANG_LIST_URL": list_file.as_uri(), "PYTHONPATH": str(ROOT)}
    cmd = [sys.executable, "-m", "julialang.julia_cli"]
    r = run(cmd, env=env, check=False)
    assert r.returncode != 0 and "julialang install" in r.stderr
    assert "julia version 9.9.9" in run(cmd, env={**env, "JULIALANG_AUTO_INSTALL": "1"})


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
    assert r.returncode == 1 and f"FAILED julia-9.9.8-{KEY}.tar.gz" in r.stderr
    versions = json.loads(list_file.read_text())["versions"]
    assert "9.9.9" in versions and "9.9.8" not in versions  # the good one was still mirrored (and will be retried)


def test_sync_stops_at_its_time_budget(tmp_path: Path):
    a, b = make_fake_julia(tmp_path, "9.9.9"), make_fake_julia(tmp_path, "9.9.8")
    upstream, list_file, out = tmp_path / "versions.json", tmp_path / "julia-list.json", tmp_path / "gh_output"
    write_upstream(upstream, {"9.9.9": a, "9.9.8": b})
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools/sync.py"), "--source", "json", "--upstream", upstream.as_uri(), "--list-file", str(list_file),
         "--repo", "me/julialang", "--min-version", "9.0.0", "--max-minutes", "0.0000001"],
        capture_output=True, text=True, env={**os.environ, "GITHUB_OUTPUT": str(out)},
    )
    assert r.returncode == 0, r.stderr
    assert "more=true" in out.read_text()  # the workflow starts another run
