<div align="center">

# julialang

**Install and switch Julia versions from pip: `pip install julialang`, `julialang install`, then run `julia`.**

[![PyPI](https://img.shields.io/pypi/v/julialang.svg)](https://pypi.org/project/julialang/)
[![Python](https://img.shields.io/pypi/pyversions/julialang.svg)](https://pypi.org/project/julialang/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

</div>

---

## Why julialang?

Like [`ziglang`](https://pypi.org/project/ziglang/) does for Zig, `julialang` makes Julia installable from Python
tooling. The wheel is tiny (a few KB, pure Python); the official Julia binaries are mirrored on GitHub by CI and
downloaded on demand by the `julialang` command, so you need no access to julialang.org, no `apt`, no installer, and
you can keep several Julia versions side by side and switch between them.

**Releases:** [GitHub releases](https://github.com/MohammadRaziei/julialang/releases/latest) · [PyPI](https://pypi.org/project/julialang/)

## Installation

```bash
pip install julialang
julialang install                 # downloads the latest Julia from the GitHub mirror and makes it the default
julia -e 'println("hello from Julia ", VERSION)'
```

Works on Linux x86_64 / aarch64 / i686, macOS x86_64 / arm64 and Windows x86_64 / i686. Python >= 3.9.

## Commands

```bash
julialang                         # status: installed, default, latest
julialang list [--all|--installed]  # installed versions and what the mirror offers
julialang fetch                   # refresh the cached list of mirrored versions
julialang latest                  # newest version on the mirror

julialang install                 # latest; becomes the default; nothing is removed
julialang install 1.10 --no-default
julialang install ">=1.10,<1.13"  # newest version that satisfies the spec
julialang uninstall 1.12.2        # also: uninstall "<1.12" --yes
julialang use 1.10                # switch the default among installed versions

julialang upgrade                 # install latest (or a spec), make it the default, REMOVE the old default
julialang downgrade 1.10          # same, towards an older version; a spec is required
julialang which                   # path of the executable `julia` runs
```

* **`julia`** is a thin shim: it runs the selected Julia with your arguments (`os.execv` on Linux/macOS, a subprocess
  on Windows). It never touches the network. Which Julia: `JULIALANG_VERSION=<spec>` for one command, else the default
  chosen by `julialang`, else the newest installed. Before anything is installed it tells you to run `julialang install`
  (set `JULIALANG_AUTO_INSTALL=1` to let `julia` install the latest by itself on first use).
* **`install`** only adds a version and makes it the default (`--no-default` to keep the current one).
  **`upgrade`** / **`downgrade`** install the target, make it the default and then delete the previous default.
  **`uninstall`** deletes versions (a spec matching several asks for confirmation, or pass `--yes`).
* Installed versions live in `~/.julialang/versions/<version>` (override with `JULIALANG_HOME`); `~/.julialang/config.json`
  records the default and the installed versions, and is re-synchronised with the folders on every command.

### Version specs

| Spec | Meaning |
| --- | --- |
| `latest` (or nothing) | the newest version |
| `1.12`, `1.12.*`, `==1.12` | the newest 1.12.x |
| `1.12.4`, `==1.12.4` | exactly that version |
| `!=1.12.4` | anything but 1.12.4 |
| `>=1.10`, `<1.13` | comparison, as in pip |
| `<=1.12`, `>1.12` | with a partial version the whole line counts (`<=1.12` includes 1.12.x, `>1.12` starts at 1.13), like npm |
| `~=1.12.2` | compatible release: `>=1.12.2,<1.13` (`~=1.12` is `>=1.12,<2`) |
| `>=1.10,<1.13` | comma-joined: every part must hold; the newest match wins |

Quote specs that contain `<` or `>` so the shell does not treat them as redirection. Several words are joined with
commas: `julialang install ">=1.10" "<1.13"`.

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

* **`tools/sync.py`** crawls <https://julialang.org/downloads/manual-downloads/> and
  <https://julialang.org/downloads/oldreleases/>, downloads every stable Julia that is not mirrored yet (`--min-version`
  defaults to 0.0.0 = all), verifies it against the upstream sha256 (and md5 when published), uploads it and records md5 +
  sha256 in `julia-list.json`. Only archives with a verifiable hash and a known name are mirrored: `.tar.gz` for
  Linux/macOS, `.zip` for Windows (no installers, musl, FreeBSD, pre-releases). `--source json` uses the official
  `versions.json` feed instead. A full backfill takes many hours, so the job stops itself before the 6 h limit
  (`--max-minutes`); the next run (weekly cron, a push, or a manual start) continues where it stopped.
* **`sync.yml`** ("Sync Julia binaries") runs on every push, weekly and by hand. It only updates the mirror: it makes no
  package release and starts no other workflow.
* **`wheel.yml`** ("Wheel") runs on every push to master and on tags `v*`. Since its smoke test installs Julia from the
  mirror on every OS, it doubles as a health check of the mirror.

## Releasing

Versions are bumped by hand: edit `version` in `pyproject.toml`, commit, then tag and push.

```bash
git tag v0.1.0
git push origin master v0.1.0
```

The tag must equal the version in `pyproject.toml` (otherwise `wheel.yml` fails immediately). The tag run publishes the
GitHub release (with generated notes) and uploads to PyPI. To retry a failed upload, re-run the tag's workflow run:
`twine upload --skip-existing` and the release step are safe to repeat.

Integrity: `julialang install` checks the sha256 and md5 from `julia-list.json`. Both come from the same GitHub repository
as the archives, so this protects against corrupted downloads, not against someone taking over the repository.

## Setting it up

1. Create the repo (default branch `master`; for a name other than `mohammadraziei/julialang` change `DEFAULT_REPO` in
   `julialang/_state.py` and `tools/sync.py`, and the URLs in `pyproject.toml`) and push.
2. Settings → Actions → General → Workflow permissions: **Read and write**.
3. Every push starts **Sync Julia binaries**; run it by hand from the Actions tab for a `dry_run` (shows the plan) or to
   mirror in slices with `limit`. The first full backfill needs several runs: start it again by hand (or wait for the
   weekly cron) until nothing is left.
4. PyPI (optional): add the repository secret `PYPI_PASS` (an API token; for a new project use a token with the scope
   of the whole account) under Settings → Secrets and variables → Actions. Secrets are per repository, so those of
   another repo do not apply. `PYPI_USER` is only needed for a non-token login and must be `__token__` when
   `PYPI_PASS` is a token. Every tag release then uploads itself; without the secret the run prints a warning and
   skips the upload (add the secret and re-run the tag's run). `pip install julialang -f https://github.com/mohammadraziei/julialang/releases/latest`
   works without PyPI.

## Notes

* Julia is MIT-licensed, but its binary distribution bundles third-party libraries under their own licenses (see
  `share/julia/` and `share/licenses` inside each version). The code in this repository is MIT.
* Installs live in `~/.julialang`, outside the virtual environment, and survive `pip uninstall julialang`.
* The `julia` command of this package may shadow another `julia` (or `juliaup`) earlier on your `PATH`; `julialang which`
  shows what is actually run.
* GitHub pauses scheduled workflows after 60 days without repository activity; if the weekly sync stops, re-enable it in
  the Actions tab.
