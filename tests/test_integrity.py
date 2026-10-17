"""Integrity: the list's two sha256 values (ours / upstream), --strict, --sha256 from the user, `hashes`, and the backfill."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import sync  # noqa: E402
from test_e2e import KEY, make_fake_julia, run, write_upstream  # noqa: E402

from julialang import manager as M  # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the fake Julia is a POSIX shell script")

ENTRY = {"name": "julia-1.2.3-x.tar.gz", "sha256": "a" * 64}


# --------------------------------------------------------------------------- cross_check (unit)


def test_cross_check_is_silent_when_both_values_agree(capsys):
    M.cross_check({**ENTRY, "upstream_sha256": "a" * 64}, strict=True)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("upstream", ["b" * 64, None])
def test_cross_check_warns_by_default(upstream, capsys):
    entry = {**ENTRY, **({"upstream_sha256": upstream} if upstream else {})}
    M.cross_check(entry, strict=False)
    assert "warning" in capsys.readouterr().err


@pytest.mark.parametrize("upstream", ["b" * 64, None])
def test_cross_check_strict_refuses(upstream):
    entry = {**ENTRY, **({"upstream_sha256": upstream} if upstream else {})}
    with pytest.raises(SystemExit) as e:
        M.cross_check(entry, strict=True)
    assert "strict mode: nothing was downloaded" in str(e.value)


def test_hash_argument_is_validated():
    assert M.check_hash_arg(" " + "AB" * 32 + "\n") == "ab" * 32
    for bad in ("abc", "g" * 64, "a" * 63, ""):
        with pytest.raises(SystemExit):
            M.check_hash_arg(bad)


def test_user_sha256_decides_alone(tmp_path: Path):
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"julia")
    sha = hashlib.sha256(b"julia").hexdigest()
    M.verify_file(f, {**ENTRY, "sha256": "0" * 64}, expected=sha)  # the list is wrong, the user's hash is right: fine
    with pytest.raises(SystemExit, match="does not match the sha256 you gave"):
        M.verify_file(f, {**ENTRY, "sha256": sha}, expected="0" * 64)  # the list agrees with the file, the user does not


# --------------------------------------------------------------------------- backfill (unit)


def test_backfill_records_only_agreeing_values():
    def ent(name, sha, up=None):
        return {"name": name, "sha256": sha, **({"upstream_sha256": up} if up else {})}

    lst = {"versions": {"1.0.0": {"files": {
        "linux-x86_64": ent("same", "a" * 64), "macos-x86_64": ent("diff", "b" * 64),
        "linux-i686": ent("gone", "c" * 64), "linux-aarch64": ent("done", "d" * 64, "d" * 64)}},
        "0.9.0": {"files": {"linux-x86_64": ent("old", "e" * 64)}}}}
    catalog = {"1.0.0": {"linux-x86_64": {"sha256": "A" * 64}, "macos-x86_64": {"sha256": "f" * 64}}}  # 0.9.0 is not upstream any more
    filled, mismatched, unknown = sync.backfill_upstream(lst, catalog)
    assert filled == 1 and lst["versions"]["1.0.0"]["files"]["linux-x86_64"]["upstream_sha256"] == "a" * 64
    assert len(mismatched) == 1 and mismatched[0].startswith("diff:") and "upstream_sha256" not in lst["versions"]["1.0.0"]["files"]["macos-x86_64"]
    assert sorted(unknown) == ["gone", "old"]


# --------------------------------------------------------------------------- the whole thing, against a fake mirror


@pytest.fixture
def mirror(tmp_path: Path):
    work, mirror_dir = tmp_path / "work", tmp_path / "mirror"
    work.mkdir()
    upstream, list_file = work / "versions.json", work / "julia-list.json"
    write_upstream(upstream, {"9.9.9": make_fake_julia(work, "9.9.9")})

    def sync_run(*extra, check=True):
        return run([sys.executable, ROOT / "tools/sync.py", "--source", "json", "--upstream", upstream.as_uri(), "--list-file", list_file,
                    "--repo", "me/julialang", "--min-version", "9.0.0", "--base-url", mirror_dir.as_uri(), "--keep-dir", mirror_dir,
                    *extra], check=check)

    sync_run()

    def julialang(*args, home="home", env=None, check=True):
        e = {"JULIALANG_HOME": str(tmp_path / home), "JULIALANG_LIST_URL": list_file.as_uri(), "PYTHONPATH": str(ROOT), **(env or {})}
        return run([sys.executable, "-m", "julialang", *args], env=e, check=check)

    def edit(fn):
        data = json.loads(list_file.read_text())
        fn(data["versions"]["9.9.9"]["files"][KEY])
        list_file.write_text(json.dumps(data))

    def installed(home="home"):
        return (tmp_path / home / "versions" / "9.9.9" / "bin" / "julia").exists()

    return type("Mirror", (), {"sync": staticmethod(sync_run), "julialang": staticmethod(julialang), "edit": staticmethod(edit),
                               "installed": staticmethod(installed), "list": list_file, "upstream": upstream})


def test_clean_list_installs_quietly_even_when_strict(mirror):
    r = mirror.julialang("install", "9.9.9", "--strict", check=False)
    assert r.returncode == 0 and "warning" not in r.stderr and mirror.installed()


def test_disagreeing_list_warns_but_installs(mirror):
    mirror.edit(lambda e: e.update(upstream_sha256="0" * 64))
    r = mirror.julialang("install", "9.9.9", check=False)
    assert r.returncode == 0 and "warning" in r.stderr and "tampered" in r.stderr and mirror.installed()


@pytest.mark.parametrize("how", ["flag", "env"])
def test_strict_refuses_before_downloading(mirror, how):
    mirror.edit(lambda e: e.update(upstream_sha256="0" * 64))
    r = mirror.julialang("install", "9.9.9", *(["--strict"] if how == "flag" else []),
                         env={"JULIALANG_STRICT": "1"} if how == "env" else None, check=False)
    assert r.returncode != 0 and "strict mode: nothing was downloaded" in r.stderr and not mirror.installed()
    assert "Installing Julia" not in r.stderr  # refused before the download started


def test_strict_refuses_a_list_without_upstream_values(mirror):
    mirror.edit(lambda e: e.pop("upstream_sha256"))
    assert mirror.julialang("install", "9.9.9", check=False).returncode == 0  # old lists still work by default (with a warning)
    r = mirror.julialang("install", "9.9.9", "--strict", home="home2", check=False)
    assert r.returncode != 0 and "no upstream sha256" in r.stderr and not mirror.installed("home2")


def test_strict_can_be_set_in_config(mirror):
    mirror.julialang("config", "strict", "true")
    mirror.edit(lambda e: e.update(upstream_sha256="0" * 64))
    assert mirror.julialang("install", "9.9.9", check=False).returncode != 0 and not mirror.installed()


def test_users_sha256_is_checked_against_the_archive(mirror):
    sha = json.loads(mirror.list.read_text())["versions"]["9.9.9"]["files"][KEY]["sha256"]
    mirror.edit(lambda e: e.update(upstream_sha256="0" * 64))  # a damaged list does not matter when the user brings the hash
    r = mirror.julialang("install", "9.9.9", "--strict", "--sha256", sha.upper(), check=False)
    assert r.returncode == 0 and "warning" not in r.stderr and mirror.installed()


def test_wrong_user_sha256_installs_nothing(mirror):
    r = mirror.julialang("install", "9.9.9", "--sha256", "0" * 64, check=False)
    assert r.returncode != 0 and "does not match the sha256 you gave" in r.stderr and not mirror.installed()


def test_sha256_from_the_environment_and_exact_version_only(mirror):
    r = mirror.julialang("install", "9.9", "--sha256", "0" * 64, check=False)
    assert r.returncode != 0 and "one exact version" in r.stderr and not mirror.installed()
    r = mirror.julialang("install", "9.9.9", env={"JULIALANG_SHA256": "0" * 64}, check=False)
    assert r.returncode != 0 and "does not match" in r.stderr
    r = mirror.julialang("install", "9.9.9", "--sha256", "not-a-hash", check=False)
    assert r.returncode != 0 and "64 hex digits" in r.stderr


def test_hashes_command_shows_both_values(mirror):
    out = mirror.julialang("hashes", "9.9.9")
    sha = json.loads(mirror.list.read_text())["versions"]["9.9.9"]["files"][KEY]["sha256"]
    assert sha in out and "same as upstream" in out and "--sha256 <HEX>" in out
    mirror.edit(lambda e: e.update(upstream_sha256="0" * 64))
    assert "DIFFERS from upstream" in mirror.julialang("hashes", "9.9.9")


def test_backfill_command_restores_the_field_and_reports_differences(mirror):
    mirror.edit(lambda e: e.pop("upstream_sha256"))
    data = json.loads(mirror.list.read_text())
    data["schema"] = 1
    mirror.list.write_text(json.dumps(data))
    out = mirror.sync("--backfill-upstream")
    data = json.loads(mirror.list.read_text())
    assert "recorded for 1 file" in out and data["schema"] == 2
    assert data["versions"]["9.9.9"]["files"][KEY]["upstream_sha256"] == data["versions"]["9.9.9"]["files"][KEY]["sha256"]
    # upstream publishes another hash than the list holds: reported, exit 1, nothing written
    mirror.edit(lambda e: e.pop("upstream_sha256"))
    up = json.loads(mirror.upstream.read_text())
    for f in up["9.9.9"]["files"]:
        f["sha256"] = "1" * 64
    mirror.upstream.write_text(json.dumps(up))
    r = mirror.sync("--backfill-upstream", check=False)
    assert r.returncode == 1 and "MISMATCH" in r.stderr
    assert "upstream_sha256" not in json.loads(mirror.list.read_text())["versions"]["9.9.9"]["files"][KEY]
