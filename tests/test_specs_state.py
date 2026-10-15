"""Version specs and the local state (config.json, installed versions, uninstall)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from julialang import _state as S  # noqa: E402
from julialang import cli  # noqa: E402
from julialang import manager as M  # noqa: E402

VERSIONS = ["1.0.5", "1.9.4", "1.10.0", "1.10.12", "1.11.9", "1.12.0", "1.12.4", "1.12.7", "1.13.1"]


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("latest", "1.13.1"), ("", "1.13.1"), ("1", "1.13.1"), ("1.12", "1.12.7"), ("1.12.*", "1.12.7"), ("v1.11", "1.11.9"),
        ("1.10.0", "1.10.0"), ("==1.12.4", "1.12.4"), ("==1.0.5", "1.0.5"), ("==1.12", "1.12.7"),
        (">=1.10,<1.13", "1.12.7"), (">=1.10", "1.13.1"), ("<1.12", "1.11.9"), ("<=1.12", "1.12.7"), ("<=1.12.4", "1.12.4"),
        (">1.12", "1.13.1"), (">1.12.4", "1.13.1"), ("!=1.13.1", "1.12.7"), (">=1.10,!=1.13.1,<1.13", "1.12.7"),
        ("~=1.12.4", "1.12.7"), ("~=1.10", "1.13.1"), (">=2", None), ("<1.0", None), ("==1.12.9", None),
    ],
)
def test_resolve_picks_the_newest_match(spec, expected):
    assert S.resolve(spec, VERSIONS) == expected


def test_matching_lists_everything_oldest_first():
    assert S.matching("<1.10", VERSIONS) == ["1.0.5", "1.9.4"]
    assert S.matching([">=1.12", "<1.13"], VERSIONS) == ["1.12.0", "1.12.4", "1.12.7"]  # words of a command line


@pytest.mark.parametrize("bad", ["abc", ">=", "~=1", "1.2.3.4", ",,", ">=1.10,", "=>1.2"])
def test_bad_specs_are_rejected(bad):
    with pytest.raises(S.SpecError):
        S.parse_spec(bad)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("JULIALANG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("JULIALANG_VERSION", raising=False)
    return tmp_path / "home"


def fake_install(home: Path, version: str) -> None:
    exe = S.exe_in(home / "versions" / version)
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    S.register(version, home / "versions" / version)


def test_config_tracks_installed_versions_and_default(home):
    assert S.installed_versions() == [] and S.default_version() is None
    fake_install(home, "1.12.4")
    fake_install(home, "1.10.1")
    S.set_default("1.12.4")
    assert S.installed_versions() == ["1.10.1", "1.12.4"] and S.default_version() == "1.12.4"
    assert S.load_config()["installed"]["1.10.1"] == {"path": "versions/1.10.1"}
    assert S.active_version() == "1.12.4"


def test_folders_added_by_hand_are_picked_up_and_vanished_ones_dropped(home):
    fake_install(home, "1.12.4")
    S.set_default("1.12.4")
    exe = S.exe_in(home / "versions/1.11.0")  # not registered in config.json
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert S.sync_config() == ["1.11.0", "1.12.4"] and "1.11.0" in S.load_config()["installed"]
    exe.unlink()
    assert S.sync_config() == ["1.12.4"] and "1.11.0" not in S.load_config()["installed"]


def test_without_a_default_the_newest_installed_runs(home):
    fake_install(home, "1.10.1")
    fake_install(home, "1.12.4")
    assert S.active_version() == "1.12.4"


def test_env_override_takes_a_spec(home, monkeypatch):
    fake_install(home, "1.10.1")
    fake_install(home, "1.12.4")
    S.set_default("1.12.4")
    monkeypatch.setenv("JULIALANG_VERSION", "1.10")
    assert S.active_version() == "1.10.1"
    monkeypatch.setenv("JULIALANG_VERSION", "1.9")
    with pytest.raises(SystemExit, match="matches no installed Julia"):
        S.active_version()


def test_resolve_root_explains_what_to_do(home):
    with pytest.raises(SystemExit, match="julialang install"):
        S.resolve_root()
    fake_install(home, "1.12.4")
    S.set_default("1.12.4")
    assert S.resolve_root() == home / "versions/1.12.4"
    S.exe_in(home / "versions/1.12.4").unlink()
    with pytest.raises(SystemExit, match="files are missing"):
        S.resolve_root()


def test_uninstalling_the_default_promotes_the_newest_remaining(home):
    for v in ("1.10.1", "1.11.2", "1.12.4"):
        fake_install(home, v)
    S.set_default("1.12.4")
    M.uninstall("1.12.4")
    assert not (home / "versions/1.12.4").exists() and S.default_version() == "1.11.2"
    M.uninstall("1.10.1")
    assert S.default_version() == "1.11.2"  # removing a non-default leaves the default alone
    M.uninstall("1.11.2")
    assert S.default_version() is None and S.installed_versions() == []
    with pytest.raises(SystemExit, match="not installed"):
        M.uninstall("1.11.2")


def test_downgrade_requires_a_spec(home, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["downgrade"])
    assert e.value.code == 2 and "SPEC" in capsys.readouterr().err


def test_list_url_defaults_to_the_download_release(monkeypatch):
    monkeypatch.delenv("JULIALANG_LIST_URL", raising=False)
    monkeypatch.delenv("JULIALANG_REPO", raising=False)
    assert M.list_url() == "https://github.com/mohammadraziei/julialang/releases/download/__download__/julia-list.json"
    monkeypatch.setenv("JULIALANG_REPO", "me/fork")
    assert M.list_url().startswith("https://github.com/me/fork/")
    assert os.environ["JULIALANG_REPO"] == "me/fork"
