<div align="center">

# julialang

**Install, switch and remove [Julia](https://julialang.org) versions with `pip`: no installer, no `apt`, no `juliaup`.**

[![PyPI](https://img.shields.io/pypi/v/julialang.svg)](https://pypi.org/project/julialang/)
[![Python](https://img.shields.io/pypi/pyversions/julialang.svg)](https://pypi.org/project/julialang/)
[![Wheel](https://github.com/MohammadRaziei/julialang/actions/workflows/wheel.yml/badge.svg)](https://github.com/MohammadRaziei/julialang/actions/workflows/wheel.yml)
[![Sync](https://github.com/MohammadRaziei/julialang/actions/workflows/sync.yml/badge.svg)](https://github.com/MohammadRaziei/julialang/actions/workflows/sync.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

```bash
pip install julialang && julialang install && julia
```

</div>

---

## Contents

- [Why julialang?](#why-julialang)
- [Quick start](#quick-start)
- [Everyday use](#everyday-use)
  - [Install Julia](#install-julia) · [Run Julia](#run-julia) · [See what you have](#see-what-you-have) · [Switch version](#switch-version) · [Upgrade and downgrade](#upgrade-and-downgrade) · [Remove versions](#remove-versions) · [Remove everything](#remove-everything)
- [Version specs](#version-specs)
- [Command reference](#command-reference)
- [Environment variables](#environment-variables)
- [How it works](#how-it-works)
- [For maintainers](#for-maintainers)
- [Notes](#notes)

## Why julialang?

Like [`ziglang`](https://pypi.org/project/ziglang/) does for Zig, `julialang` makes Julia installable from Python
tooling.

- **Tiny wheel.** `pip install julialang` downloads a pure-Python wheel of a few KB (`py3-none-any`), the same on every platform.
- **No julialang.org needed.** The official binaries are mirrored on GitHub by CI; `julialang` downloads from there and verifies sha256 and md5.
- **Many versions side by side.** Install as many as you like, switch with one command, upgrade, downgrade, remove.
- **pip-style version specs.** `julialang install ">=1.10,<1.13"`, `julialang install 1.12`, `julialang install ~=1.12.2`.
- **Every stable release.** The mirror covers all stable Julia versions, from 0.x to the latest.
- **Zero dependencies.** Standard library only. Works on Linux (x86_64, aarch64, i686), macOS (x86_64, arm64) and Windows (x86_64, i686) with Python 3.9+.

## Quick start

```bash
pip install julialang
julialang install                 # latest Julia, becomes the default
julia -e 'println("hello from Julia ", VERSION)'
```

Julia itself is **not** inside the wheel: `julialang install` downloads it into `~/.julialang`.

## Everyday use

### Install Julia

```bash
julialang install                 # the latest version
julialang install 1.12            # the newest 1.12.x
julialang install 1.10.5          # exactly this version
julialang install ">=1.10,<1.13"  # the newest version that satisfies the spec
julialang install 1.10 1.12       # several at once
```

`install` only **adds** versions: nothing is removed, and the installed version becomes the default. Pass
`--no-default` to keep the current default:

```bash
julialang install 1.10 --no-default
```

### Run Julia

`julia` is a thin shim that runs the selected Julia with your arguments. When only Python is on your `PATH`,
`julialang run` does the same (everything after `run` goes to Julia):

```bash
julia                             # REPL
julia script.jl                   # run a script
julia -e 'print(VERSION)'
JULIALANG_VERSION=1.10 julia -e 'print(VERSION)'   # one command with another installed version
julialang run script.jl           # the same as `julia script.jl`
python -m julialang run -e 'print(VERSION)'
```

Which Julia runs: `JULIALANG_VERSION` (a spec, must be installed), else the default chosen by `julialang`, else the
newest installed one. The shim never touches the network. If nothing is installed yet it tells you to run
`julialang install` (set `JULIALANG_AUTO_INSTALL=1` to let `julia` install the latest on first use instead).

### See what you have

```bash
julialang                         # status: installed versions, the default, the latest on the mirror
julialang list                    # installed versions and the ones the mirror offers
julialang list --installed        # only what is on your machine
julialang list --all              # everything the mirror has
julialang latest                  # newest version on the mirror
julialang which                   # path of the executable `julia` runs
julialang fetch                   # refresh the cached list of mirrored versions now
```

### Switch version

Switch the default among the versions you have installed:

```bash
julialang use 1.10
julia -e 'print(VERSION)'         # 1.10.x
julialang use latest
```

`use` never downloads: if the version is not installed it tells you to `julialang install` it first.

### Upgrade and downgrade

`install` keeps old versions; `upgrade` and `downgrade` **replace** the current default:

```bash
julialang upgrade                 # install the latest, make it the default, remove the previous default
julialang upgrade 1.12            # ... or the newest 1.12.x
julialang downgrade 1.10          # same, towards an older version (the spec is required)
```

The previous default is deleted only after the new version is downloaded and its checksum verified. Asking `upgrade`
for an older version (or `downgrade` for a newer one) is an error that points you to the other command; asking for
the version you already use just says so.

### Remove versions

```bash
julialang uninstall 1.12.2        # one version
julialang uninstall 1.10 1.11     # several
julialang uninstall "<1.12" --yes # a spec that matches many versions asks first; --yes skips the question
```

Uninstalling the default promotes the newest remaining version to be the new default.

### Remove everything

```bash
julialang purge                   # delete every installed Julia and julialang's data; the pip package stays
julialang self-uninstall          # purge, then `pip uninstall julialang`
```

Both ask first (`--yes` skips the question). `purge` deletes every installed Julia and julialang's own files in
`~/.julialang`; `self-uninstall` does the same and then runs `python -m pip uninstall -y julialang` for you. (A
directory set with `JULIALANG_HOME` is only removed if nothing else lives in it.)

Installed versions live outside your virtual environment, so a plain `pip uninstall julialang` leaves them in place:
run `julialang self-uninstall` instead, or delete `~/.julialang` (Windows: `%USERPROFILE%\.julialang`) by hand afterwards.

## Version specs

Specs work like pip's, with npm-style handling of partial versions:

| Spec | Meaning |
| --- | --- |
| `latest` (or nothing) | the newest version |
| `1`, `1.12`, `1.12.*`, `==1.12` | the newest 1.x / 1.12.x |
| `1.12.4`, `==1.12.4` | exactly that version |
| `!=1.12.4` | anything but 1.12.4 |
| `>=1.10`, `<1.13` | comparison, as in pip |
| `<=1.12`, `>1.12` | with a partial version the whole line counts: `<=1.12` includes 1.12.x, `>1.12` starts at 1.13 |
| `~=1.12.2` | compatible release: `>=1.12.2,<1.13` (and `~=1.12` is `>=1.12,<2`) |
| `>=1.10,<1.13` | comma-joined: every part must hold, the newest match wins |

Quote specs that contain `<` or `>` so the shell does not treat them as redirection. Several words are joined with
commas, so `julialang install ">=1.10" "<1.13"` means the same as `julialang install ">=1.10,<1.13"`.

## Command reference

| Command | What it does |
| --- | --- |
| `julialang` / `julialang status` | installed versions, the default and the latest available |
| `julialang list [--all\|--installed]` | installed and mirrored versions |
| `julialang fetch` | refresh the cached list of mirrored versions |
| `julialang latest` | print the newest mirrored version |
| `julialang install [SPEC...] [--no-default]` | download and install (latest if no spec); makes it the default |
| `julialang uninstall SPEC... [--yes]` | delete versions (aliases: `remove`, `rm`) |
| `julialang use SPEC` | set the default among installed versions |
| `julialang upgrade [SPEC]` | install the target (latest by default), make it the default, delete the old default |
| `julialang downgrade SPEC` | the same towards an older version (spec required) |
| `julialang purge [--yes]` | remove all Julia versions and julialang's data; the pip package stays |
| `julialang self-uninstall [--yes]` | `purge`, then `pip uninstall julialang` |
| `julialang run [ARGS...]` | run the selected Julia with `ARGS`: the same as the `julia` command (also `python -m julialang run ...`) |
| `julialang which` | path of the executable `julia` runs |
| `julialang --version` | version of this package |

The cached version list is trusted for one hour by `status`, `list` and `latest`; `install`, `upgrade`, `downgrade`
and `fetch` always try the network first and fall back to the cache when offline.

## Environment variables

| Variable | Effect |
| --- | --- |
| `JULIALANG_HOME` | where versions, `config.json` and the cache live (default `~/.julialang`) |
| `JULIALANG_VERSION` | spec of an installed version that `julia` should run, instead of the default |
| `JULIALANG_AUTO_INSTALL=1` | let `julia` install the latest version on first use |
| `JULIALANG_REPO` | GitHub repository to read the mirror from (default `MohammadRaziei/julialang`) |
| `JULIALANG_LIST_URL` | full URL of `julia-list.json`, overriding `JULIALANG_REPO` (useful for your own mirror or tests) |

State layout: `~/.julialang/versions/<version>/` holds each Julia, and `~/.julialang/config.json` records the default
and the installed versions; it is re-synchronised with the folders on every command, so you can also delete a folder by hand.

## How it works

Three kinds of GitHub releases act as storage, and two independent workflows do the work:

| Tag | Kind | Holds |
| --- | --- | --- |
| `__download__`, `__download_2__`, ... | prerelease | mirrored Julia archives (`julia-<version>-<os>-<arch>.<ext>`); `__download__` also holds **`julia-list.json`** (md5 + sha256 and URL of every file). GitHub allows ~1000 assets per release, so the mirror starts the next one after 900 files |
| `__beta__` | prerelease | the latest tested build of master (wheel + sdist) |
| `vX.Y.Z` | release | the published wheel and sdist |

`julia-list.json` is **not** in git: it is only a release asset, uploaded again after every mirrored version.

```
julialang.org (crawled) ──▶ sync.yml ──▶ __download__ (+ __download_N__) + julia-list.json asset

push to master ──▶ wheel.yml: ruff + pytest → build wheel/sdist → smoke test on 5 OSes
                              (pip install, `julialang install` FROM THE MIRROR, run julia) → __beta__
push of tag vX.Y.Z ──▶ the same, then → GitHub release vX.Y.Z + PyPI
```

`sync.yml` and `wheel.yml` never call each other.

- **`tools/sync.py`** crawls <https://julialang.org/downloads/manual-downloads/> and
  <https://julialang.org/downloads/oldreleases/>, downloads every stable Julia that is not mirrored yet
  (`--min-version` defaults to 0.0.0 = all), verifies it against the upstream sha256 (and md5 when published), uploads
  it and records md5 + sha256 in `julia-list.json`. Only archives with a verifiable hash and a known name are mirrored:
  `.tar.gz` for Linux/macOS, `.zip` for Windows (no installers, musl, FreeBSD, pre-releases). `--source json` uses the
  official `versions.json` feed instead. A full backfill takes many hours, so the job stops itself before the 6 h limit
  (`--max-minutes`); the next run (weekly cron, a push, or a manual start) continues where it stopped.
- **`sync.yml`** ("Sync Julia binaries") runs on every push, weekly and by hand. It only updates the mirror: it makes no
  package release and starts no other workflow.
- **`wheel.yml`** ("Wheel") runs on every push to master and on tags `v*`. Its smoke test installs Julia from the mirror
  on every OS, so it doubles as a health check of the mirror.

**Integrity.** `julialang install` checks the sha256 and md5 from `julia-list.json`. Both come from the same GitHub
repository as the archives, so this protects against corrupted downloads, not against someone taking over the repository.

## For maintainers

### Set up your own copy

1. Create the repo (default branch `master`; for a name other than `mohammadraziei/julialang` change `DEFAULT_REPO` in
   `julialang/_state.py` and `tools/sync.py`, and the URLs in `pyproject.toml`) and push.
2. Settings → Actions → General → Workflow permissions: **Read and write**.
3. Every push starts **Sync Julia binaries**; run it by hand from the Actions tab for a `dry_run` (shows the plan) or to
   mirror in slices with `limit`. The first full backfill needs several runs: start it again by hand (or wait for the
   weekly cron) until nothing is left.
4. PyPI (optional): add the repository secret `PYPI_PASS` (an API token; for a new project use a token with the scope of
   the whole account) under Settings → Secrets and variables → Actions. Secrets are per repository, so those of another
   repo do not apply. `PYPI_USER` is only needed for a non-token login and must be `__token__` when `PYPI_PASS` is a
   token.

### Release a new version

Versions are bumped by hand: edit `version` in `pyproject.toml`, commit, then tag and push.

```bash
git tag v0.1.0
git push origin master v0.1.0
```

The tag must equal the version in `pyproject.toml` (otherwise `wheel.yml` fails immediately). The tag run publishes the
GitHub release (with generated notes) and uploads to PyPI. Without the `PYPI_PASS` secret it prints a warning and skips
the upload: add the secret and re-run the tag's run (`twine upload --skip-existing` and the release step are safe to
repeat).

Without PyPI, the wheel installs straight from a GitHub release:

```bash
pip install julialang --find-links https://github.com/MohammadRaziei/julialang/releases/expanded_assets/v0.1.0
```

### Develop

```bash
pip install -e . pytest setuptools wheel ruff
python -m ruff check .
python -m pytest -q tests          # about a minute; the end-to-end test builds a wheel
python tools/sync.py --dry-run     # show what would be mirrored
```

## Notes

- Julia is MIT-licensed, but its binary distribution bundles third-party libraries under their own licenses (see
  `share/julia/` and `share/licenses` inside each version). The code in this repository is MIT.
- The `julia` command of this package may shadow another `julia` (or `juliaup`) earlier on your `PATH`; `julialang which`
  shows what is actually run.
- GitHub pauses scheduled workflows after 60 days without repository activity; if the weekly sync stops, re-enable it in
  the Actions tab.
