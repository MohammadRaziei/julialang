# Changelog

All notable changes to **julialang** are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow [Semantic Versioning](https://semver.org/).
Only changes to the package (`julialang/`, `pyproject.toml`, the workflows) are listed: mirroring a new Julia release is
automatic and does not make a package release.

## [0.3.0] - 2026-10-17

### Added
- `julialang -v` as a short form of `julialang --version`.
- Running `julialang` with no command now starts with a one-line description of the tool (version, what it is and where
  its mirror comes from) before the status.

### Changed
- The package version is now **dynamic**: `__version__` in `julialang/__init__.py` is the only place that holds it, and
  `pyproject.toml` reads it from there. Bump it by hand (or with `hatch version X.Y.Z`), commit, then tag `vX.Y.Z`.
- The build backend is now `hatchling` (was `setuptools` + `wheel`); the wheel is still one pure `py3-none-any` file.
- `wheel.yml` reads the version by importing the package instead of parsing `pyproject.toml`, and still fails at once when
  the pushed tag does not match it.

### Fixed
- The `Programming Language :: Python :: 3.14` and `3.15` classifiers added in 0.2.1 are back in `pyproject.toml`.

## [0.2.1] - 2026-10-16

### Added
- Classifiers for Python 3.14 and 3.15.

### Changed
- README: removed the detailed implementation notes and the "For maintainers" section to keep it short.

## [0.2.0] - 2026-10-16

### Added
- `julialang run [ARGS...]` (also `python -m julialang run ...`): runs the selected Julia with the given arguments,
  exactly like the `julia` command. Everything after `run` goes to Julia, including options such as `-e`.
- `julialang purge`: removes every installed Julia and julialang's own files in `~/.julialang`; the pip package stays.
- `julialang self-uninstall`: `purge`, then `python -m pip uninstall -y julialang`. Both commands ask first (`--yes` skips
  the question) and only remove a `JULIALANG_HOME` directory when nothing else lives in it.
- README: a "Why julialang?" section for machines without `sudo`/admin rights or whose network only reaches PyPI and
  GitHub, and a walkthrough of installing, switching, upgrading, downgrading and removing Julia versions.

### Changed
- The CLI code moved from `julialang/cli.py` to `julialang/__main__.py`; the `julialang` entry point is now
  `julialang.__main__:main`.

## [0.1.0] - 2026-10-16

### Changed
- **Releases are now tag-driven.** The mirror and the package no longer depend on each other:
  - `sync.yml` ("Sync Julia binaries", on push, weekly and by hand) only updates the `__download__` mirror and
    `julia-list.json`. It publishes no release and starts no other workflow.
  - `wheel.yml` ("Wheel", on push and on tags `v*`) runs ruff and pytest, builds the wheel and sdist, smoke-tests them on
    five OS/arch combinations with a real `julialang install` from the mirror, and publishes: master goes to the `__beta__`
    prerelease, a tag `vX.Y.Z` goes to a GitHub release and to PyPI.
- Versions are bumped by hand and released with `git tag vX.Y.Z`; the automatic bump commits (`chore(release)`) and
  `tools/release.py` are gone.
- README reorganised with a table of contents.

## [0.0.2] - 2026-10-15

### Changed
- Sync workflow comments and defaults now describe mirroring every Julia archive, not only recent versions.

## [0.0.1] - 2026-10-14

First release.

### Added
- `julia` command: a thin shim that runs the active Julia (`JULIALANG_VERSION`, then the configured default, then the
  newest installed one).
- `julialang` version manager: `status`, `list`, `fetch`, `latest`, `install`, `uninstall`, `use`, `upgrade`,
  `downgrade` and `which`, with pip-style version specs (`1.12`, `>=1.10,<1.13`, `~=1.12.2`, ...).
- A GitHub mirror of the official Julia binaries (`__download__` release plus a `julia-list.json` asset, with extra
  `__download_N__` releases when one fills up) built by `tools/sync.py`, which crawls julialang.org and verifies every
  archive against the upstream sha256 before uploading it.
- Downloads are checked against sha256 and md5 from `julia-list.json`.
- CI: tests, wheel build, a smoke test on every OS and release to GitHub and PyPI.

### Fixed
- The sync prefers SHA256 over stale MD5 hashes and resumes after partial failures.
- Archive file handles are closed after iteration, which prevents cleanup errors on Windows.

[0.3.0]: https://github.com/MohammadRaziei/julialang/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/MohammadRaziei/julialang/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/MohammadRaziei/julialang/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/MohammadRaziei/julialang/compare/v0.0.2...v0.1.0
[0.0.2]: https://github.com/MohammadRaziei/julialang/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/MohammadRaziei/julialang/releases/tag/v0.0.1
