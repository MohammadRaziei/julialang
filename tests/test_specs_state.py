"""Version specs and the local state (config.json, installed versions, uninstall)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from julialang import __main__ as cli  # noqa: E402
from julialang import _state as S  # noqa: E402
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


def test_self_uninstall_purges_then_calls_pip(home, monkeypatch, capsys):
    for v in ("1.10.1", "1.12.4"):
        fake_install(home, v)
    S.set_default("1.12.4")
    M.cache_path().write_text("{}")
    calls = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: calls.append(cmd) or 0)

    # without a terminal it refuses unless --yes is given
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(SystemExit, match="--yes"):
        cli.main(["self-uninstall"])
    assert (home / "versions/1.12.4").exists() and not calls

    assert cli.main(["self-uninstall", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Removed Julia 1.10.1" in out and "Removed Julia 1.12.4" in out
    assert not home.exists()
    assert calls == [[cli.sys.executable, "-m", "pip", "uninstall", "-y", "julialang"]]


def test_purge_never_runs_pip_and_keeps_foreign_files(home, monkeypatch):
    fake_install(home, "1.12.4")
    (home / "mine.txt").write_text("not julialang's")
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: pytest.fail("purge must not run pip"))
    assert cli.main(["purge", "-y"]) == 0
    assert (home / "mine.txt").exists() and not (home / "versions").exists() and not (home / "config.json").exists()


def test_declining_the_prompt_changes_nothing(home, monkeypatch):
    fake_install(home, "1.12.4")
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: pytest.fail("pip must not run after Abort"))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["self-uninstall"]) == 1
    assert (home / "versions/1.12.4").exists()


def test_self_uninstall_reports_a_pip_failure(home, monkeypatch, capsys):
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: 3)
    assert cli.main(["self-uninstall", "--yes"]) == 3
    assert "run the command above" in capsys.readouterr().err


def test_run_hands_its_arguments_to_julia(home, monkeypatch):
    from julialang import julia_cli

    fake_install(home, "1.12.4")
    S.set_default("1.12.4")
    seen = []
    monkeypatch.setattr(julia_cli.os, "execve", lambda exe, argv, env: seen.append((exe, argv)))
    monkeypatch.setattr(julia_cli.subprocess, "call", lambda argv, env=None: seen.append((argv[0], argv)) or 0)
    exe = str(S.exe_in(S.version_root("1.12.4")))
    for argv in (["run", "-e", "print(1)", "--check"], ["run", "--", "-e", "print(1)", "--check"]):
        seen.clear()
        try:
            cli.main(argv)
        except SystemExit:  # the Windows branch exits with Julia's status
            pass
        assert seen == [(exe, [exe, "-e", "print(1)", "--check"])]


@pytest.mark.parametrize("flag", ["-v", "--version"])
def test_version_flags(flag, capsys):
    from julialang import __version__

    with pytest.raises(SystemExit) as e:
        cli.main([flag])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"julialang {__version__}"


def test_bare_julialang_introduces_itself_before_the_status(home, capsys):
    from julialang import __version__

    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"julialang {__version__}: a cross-platform Julia version manager built on pip and GitHub")
    assert "julialang.org" in out.splitlines()[0] and "platform" in out and "installed" in out
    assert cli.main(["status"]) == 0
    assert "cross-platform" not in capsys.readouterr().out  # the explicit command stays plain


# --------------------------------------------------------------------------- .julialang project file


def test_project_file_parsing(tmp_path):
    f = tmp_path / ".julialang"
    f.write_text('# settings\n\njulia-version = "1.10"   # the LTS line\nfuture-key=abc\n')
    assert S.read_project_file(f) == {"julia-version": "1.10", "future-key": "abc"}
    f.write_text("julia-version = '>=1.10,<1.13'\n")
    assert S.read_project_file(f)["julia-version"] == ">=1.10,<1.13"


def test_pin_is_found_in_parent_directories_and_the_home_directory_is_ignored(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    deep = project / "src" / "deep"
    deep.mkdir(parents=True)
    (tmp_path / ".julialang").mkdir()  # like ~/.julialang: a DIRECTORY, never a pin
    monkeypatch.chdir(deep)
    assert S.find_project_file() is None
    (project / ".julialang").write_text('julia-version = "1.10"\n')
    assert S.find_project_file() == (project / ".julialang").resolve()
    assert S.project_pin() == ("1.10", (project / ".julialang").resolve())


def test_julia_runs_the_pinned_version_with_the_right_precedence(home, tmp_path, monkeypatch):
    for v in ("1.10.1", "1.10.5", "1.12.4"):
        fake_install(home, v)
    S.set_default("1.12.4")
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".julialang").write_text('julia-version = "1.10"\n')
    monkeypatch.delenv("JULIALANG_VERSION", raising=False)

    monkeypatch.chdir(tmp_path)
    assert S.active_version() == "1.12.4"  # outside the project: the default
    monkeypatch.chdir(project)
    assert S.active_version() == "1.10.5"  # inside: the pin (newest 1.10.x)
    monkeypatch.setenv("JULIALANG_VERSION", "1.10.1")
    assert S.active_version() == "1.10.1"  # the environment variable beats the pin

    monkeypatch.delenv("JULIALANG_VERSION")
    (project / ".julialang").write_text('julia-version = "1.9"\n')
    with pytest.raises(SystemExit, match="julialang install 1.9"):
        S.active_version()
    (project / ".julialang").write_text('julia-version = "banana"\n')
    with pytest.raises(SystemExit, match="julia-version"):
        S.active_version()


def test_pin_command_writes_shows_and_removes(home, tmp_path, monkeypatch, capsys):
    fake_install(home, "1.10.5")
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.delenv("JULIALANG_VERSION", raising=False)

    assert cli.main(["pin"]) == 0 and "Not pinned" in capsys.readouterr().out
    assert cli.main(["pin", "1.10"]) == 0
    assert (project / ".julialang").read_text().splitlines()[-1] == 'julia-version = "1.10"'
    assert "Not installed yet" not in capsys.readouterr().out
    assert cli.main(["pin"]) == 0 and "Julia 1.10.5" in capsys.readouterr().out
    assert cli.main(["status"]) == 0 and "pinned      1.10" in capsys.readouterr().out

    # a pin for a version that is not installed says so; other lines of the file survive a change
    (project / ".julialang").write_text('# mine\nother = 1\njulia-version = "1.10"\n')
    assert cli.main(["pin", ">=1.12"]) == 0 and "julialang install >=1.12" in capsys.readouterr().out
    assert (project / ".julialang").read_text() == '# mine\nother = 1\njulia-version = ">=1.12"\n'
    with pytest.raises(SystemExit):
        cli.main(["pin", "banana"])

    assert cli.main(["pin", "--remove"]) == 0  # `other = 1` keeps the file alive
    assert (project / ".julialang").read_text() == "# mine\nother = 1\n"
    (project / ".julialang").write_text('julia-version = "1.10"\n')
    assert cli.main(["pin", "--remove"]) == 0 and not (project / ".julialang").exists()
    with pytest.raises(SystemExit, match="no .julialang"):
        cli.main(["pin", "--remove"])


def test_use_mentions_a_pin_that_overrides_the_default(home, tmp_path, monkeypatch, capsys):
    for v in ("1.10.5", "1.12.4"):
        fake_install(home, v)
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".julialang").write_text('julia-version = "1.10"\n')
    monkeypatch.chdir(project)
    assert cli.main(["use", "1.12"]) == 0
    assert "pins Julia 1.10" in capsys.readouterr().out


# --------------------------------------------------------------------------- JULIA_PKG_SERVER


def test_pkg_server_is_disabled_by_default_unless_the_user_set_it(home, monkeypatch):
    monkeypatch.delenv("JULIA_PKG_SERVER", raising=False)
    assert S.get_setting("disable-pkg-server") is True  # the default, with no config file at all
    assert S.julia_env()["JULIA_PKG_SERVER"] == ""

    S.set_setting("disable-pkg-server", False)
    assert "JULIA_PKG_SERVER" not in S.julia_env()
    S.set_setting("disable-pkg-server", True)

    for explicit in ("https://my.pkg.server", ""):  # an explicit variable always wins, even an empty one
        monkeypatch.setenv("JULIA_PKG_SERVER", explicit)
        assert S.julia_env()["JULIA_PKG_SERVER"] == explicit
    monkeypatch.setenv("JULIA_PKG_SERVER", "https://my.pkg.server")
    S.set_setting("disable-pkg-server", False)
    assert S.julia_env()["JULIA_PKG_SERVER"] == "https://my.pkg.server"  # and the config file never overrides it


def test_the_setting_survives_other_config_changes_and_garbage_falls_back_to_the_default(home):
    fake_install(home, "1.12.4")
    S.set_setting("disable-pkg-server", False)
    S.set_default("1.12.4")
    S.sync_config()
    assert S.get_setting("disable-pkg-server") is False and S.default_version() == "1.12.4"
    cfg = S.load_config()
    cfg["disable_pkg_server"] = "maybe"
    S.save_config(cfg)
    assert S.get_setting("disable-pkg-server") is True


def test_config_command(home, monkeypatch, capsys):
    monkeypatch.delenv("JULIA_PKG_SERVER", raising=False)
    assert cli.main(["config"]) == 0 and "disable-pkg-server = true" in capsys.readouterr().out
    assert cli.main(["config", "disable-pkg-server", "off"]) == 0
    assert "disable-pkg-server = false" in capsys.readouterr().out and S.get_setting("disable-pkg-server") is False
    assert cli.main(["config", "disable-pkg-server"]) == 0 and "= false" in capsys.readouterr().out
    monkeypatch.setenv("JULIA_PKG_SERVER", "https://x")
    assert cli.main(["config"]) == 0 and "it always wins" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="unknown setting"):
        cli.main(["config", "banana", "1"])
    with pytest.raises(SystemExit, match="true or false"):
        cli.main(["config", "disable-pkg-server", "maybe"])


def test_every_setting_can_be_overridden_by_an_environment_variable(home, monkeypatch, capsys):
    monkeypatch.delenv("JULIA_PKG_SERVER", raising=False)
    monkeypatch.delenv("JULIALANG_DISABLE_PKG_SERVER", raising=False)
    assert S.env_name("disable-pkg-server") == "JULIALANG_DISABLE_PKG_SERVER"
    assert S.setting_source("disable-pkg-server") == "default"
    S.set_setting("disable-pkg-server", False)
    assert S.setting_source("disable-pkg-server") == "config.json" and "JULIA_PKG_SERVER" not in S.julia_env()

    for text in ("true", "TRUE", "1", "yes", "on"):  # the variable beats config.json
        monkeypatch.setenv("JULIALANG_DISABLE_PKG_SERVER", text)
        assert S.get_setting("disable-pkg-server") is True and S.julia_env()["JULIA_PKG_SERVER"] == ""
    assert S.setting_source("disable-pkg-server") == "JULIALANG_DISABLE_PKG_SERVER"
    S.set_setting("disable-pkg-server", True)
    monkeypatch.setenv("JULIALANG_DISABLE_PKG_SERVER", "false")
    assert S.get_setting("disable-pkg-server") is False and "JULIA_PKG_SERVER" not in S.julia_env()
    monkeypatch.setenv("JULIALANG_DISABLE_PKG_SERVER", "")  # empty = not set: config.json decides
    assert S.get_setting("disable-pkg-server") is True
    monkeypatch.setenv("JULIALANG_DISABLE_PKG_SERVER", "maybe")
    with pytest.raises(SystemExit, match="JULIALANG_DISABLE_PKG_SERVER must be true or false"):
        S.get_setting("disable-pkg-server")

    monkeypatch.setenv("JULIALANG_DISABLE_PKG_SERVER", "false")  # `config` says where the value comes from
    assert cli.main(["config"]) == 0 and "false  (JULIALANG_DISABLE_PKG_SERVER)" in capsys.readouterr().out
    assert cli.main(["config", "disable-pkg-server", "true"]) == 0
    assert "overrides config.json" in capsys.readouterr().out
    monkeypatch.setenv("JULIA_PKG_SERVER", "https://x")  # an explicit JULIA_PKG_SERVER still beats both
    monkeypatch.setenv("JULIALANG_DISABLE_PKG_SERVER", "true")
    assert S.julia_env()["JULIA_PKG_SERVER"] == "https://x"
