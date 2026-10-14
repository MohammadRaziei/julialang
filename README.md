<div align="center">

# julialang

**Julia in a wheel: `pip install julialang`, then run `julia`.**

[![PyPI](https://img.shields.io/pypi/v/julialang.svg)](https://pypi.org/project/julialang/)
[![Python](https://img.shields.io/pypi/pyversions/julialang.svg)](https://pypi.org/project/julialang/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

</div>

---

## Why julialang?

Like [`ziglang`](https://pypi.org/project/ziglang/) does for Zig, `julialang` ships the official Julia binaries
inside a Python wheel. No installer, no `apt`, and no access to julialang.org at install time, because the
binaries are mirrored on GitHub by CI. A small manager command, `julialang`, can fetch other Julia versions and
switch the default without reinstalling the package.

<!-- release:start -->
_No release yet._
<!-- release:end -->

## Installation

```bash
pip install julialang          # or: pip install julialang --find-links https://github.com/mohammadraziei/julialang/releases/latest
julia -e 'println("hello from Julia ", VERSION)'
```

Wheels: Linux x86_64 / aarch64 (glibc), macOS x86_64 / arm64, Windows x86_64. Python >= 3.9.

## Managing versions

```bash
julialang                 # status: bundled / installed / default / latest
julialang list            # installed versions and what the mirror offers
julialang upgrade         # install the newest Julia and make it the default
julialang downgrade       # default to the next older version (or: julialang downgrade 1.11)
julialang use 1.12        # switch the default (installs it first if needed)
julialang use bundled     # back to the Julia that came inside the wheel
julialang install 1.10 --use
julialang remove 1.12.2
julialang which           # path of the executable `julia` runs
```

Version specs accept `latest`, `1.12` (newest 1.12.x) or `1.12.2`. `JULIALANG_VERSION=1.10.4 julia ...` overrides the
default for one command. Installed versions live in `~/.julialang` (override with `JULIALANG_HOME`).
`julia` never touches the network; only `julialang` does.

## How it works

Two GitHub releases act as storage, and two workflows do the work:

| Tag | Kind | Holds |
| --- | --- | --- |
| `__download__` | prerelease | mirrored Julia archives (`julia-<version>-<os>-<arch>.<ext>`) and `julia-list.json` |
| `__beta__` | prerelease | the tested wheels of the release that is being prepared |
| `v0.0.N` | release | the published wheels |

```
julialang.org (crawled) ──▶ update.yml (weekly) ──▶ __download__ + julia-list.json pushed to master
                                                           │ dispatch
                                                           ▼
                          wheels.yml, prepare:  tests → build + smoke-test 5 wheels → __beta__
                                                → commit "chore(release): v0.0.N (Julia X.Y.Z)"
                                                           │ dispatch
                                                           ▼
                          wheels.yml, release:  sees that commit message → tags v0.0.N, publishes the wheels
```

* **`tools/sync.py`** crawls <https://julialang.org/downloads/manual-downloads/> (current stable + LTS) and
  <https://julialang.org/downloads/oldreleases/>, downloads every stable Julia >= 1.10.0 that is not mirrored yet,
  verifies it against the upstream sha256 (and md5 when published), uploads it to `__download__` and records md5 +
  sha256 in `julia-list.json`. `--source json` uses the official `versions.json` feed instead.
* **`update.yml`** runs weekly (Julia ships a patch release every month or two, so this is cheap and exits at once
  when nothing is new), commits `julia-list.json` and starts `wheels.yml`.
* **`wheels.yml`** has two modes, picked from the last commit message by `tools/release.py`:
  *prepare* (a new bundled Julia is available) runs the tests, builds one wheel per platform, installs each on a native
  runner and checks `julia` reports the right version, stores the wheels in `__beta__`, then bumps the version,
  updates `CHANGELOG.md` and the block at the top of this README and pushes a `chore(release): vX.Y.Z (Julia J)` commit;
  *release* (that commit) tags `vX.Y.Z` and publishes the wheels from `__beta__`.
* **`tools/build_wheel.py`** repacks the archive under `julialang/_julia/`, preserving executable bits. Symlinks cannot
  be stored in a wheel, so they go into `_symlinks.json` and are recreated on first run (if site-packages is read-only,
  `julia` falls back to a private copy in `~/.julialang`).

Versions are `0.0.N` for now (patch bumps) while the pipeline is proven. Set the repository variable
`RELEASE_BUMP=minor` to switch to `0.N.0`. The wheel version is the package version; the bundled Julia is shown by
`julialang status` and in the changelog.

## Setting it up

1. Create the repo (default branch `master`; this README assumes `mohammadraziei/julialang`: for another name change
   `DEFAULT_REPO` in `julialang/manager.py` and `tools/sync.py`, and the URLs in `pyproject.toml`) and push.
2. Settings → Actions → General → Workflow permissions: **Read and write**.
3. Every push to `master` starts **Sync Julia binaries** (it also runs weekly, and by hand from the Actions tab, where
   `dry_run` shows the plan and `limit` mirrors in slices). An empty `julia-list.json` is simply filled from the site:
   the first run mirrors every version since 1.10 (a few GB per version across platforms). The sync skips the commits
   CI makes itself, so it never loops.
   Optional but recommended: add a secret `PUSH_TOKEN` (a personal access token with contents + actions write).
   A push made with the default `GITHUB_TOKEN` cannot trigger other workflows, so without the secret the sync starts
   **Test, build and release** by dispatching it; with the secret, its push of `julia-list.json` triggers it directly.
4. PyPI (optional): the wheels are about 150-250 MB, above PyPI's default 100 MB per-file limit, so ask PyPI support
   for a size increase first. Then configure trusted publishing for this repo and workflow (`wheels.yml`) and set the
   repository variable `PUBLISH_PYPI=true`.

## Notes

* Julia is MIT-licensed, but its binary distribution bundles third-party libraries under their own licenses (see
  `share/julia/` and `share/licenses` inside the bundle). The code in this repository is MIT.
* GitHub pauses scheduled workflows after 60 days without repository activity; if the weekly sync stops, re-enable it
  in the Actions tab.
* md5 is recorded because it is handy for quick comparisons; verification uses the upstream sha256 (and the upstream
  md5 when available).
