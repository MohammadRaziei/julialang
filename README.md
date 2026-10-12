# julialang

Julia in a wheel, in the spirit of [`ziglang`](https://pypi.org/project/ziglang/): `pip install julialang` gives you a
working `julia` command, no installer, no `apt`, no access to julialang.org needed. A small manager command,
`julialang`, can fetch other Julia versions and switch the default without reinstalling the package.

```bash
pip install julialang
julia -e 'println("hello from Julia ", VERSION)'

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

```
 julialang.org ──(weekly CI: update.yml)──▶ release "julia_binary"   julia-1.13.1-linux-x86_64.tar.gz, ...
                                              + julia-list.json         (names, sizes, md5, sha256)
                                              │ also committed to the repo
                                              ▼ push / dispatch
                                           wheels.yml ──▶ one wheel per platform ──▶ release vX.Y.Z (+ PyPI)
```

* **`tools/sync.py`** reads the official `versions.json`, downloads every stable Julia (>= 1.10.0 by default) that is
  not mirrored yet, checks the upstream sha256, records md5 + sha256, uploads the archive to the `julia_binary`
  release and updates `julia-list.json`. Assets are named `julia-<version>-<os>-<arch>.<ext>`.
* **`update.yml`** runs it weekly (Julia ships patch releases every month or two, so a weekly check is cheap and
  exits at once when nothing is new), commits `julia-list.json` and starts `wheels.yml`.
* **`wheels.yml`** builds a wheel for each platform with the newest Julia, installs it on a native runner and checks
  `julia` reports the right version, then publishes a GitHub release `vX.Y.Z`. It skips if that tag already exists
  (so backfilling old versions does not cut releases); run it manually with `post_release` for a `.postN` re-release
  after a packaging fix.
* **`tools/build_wheel.py`** repacks the archive under `julialang/_julia/`, preserving executable bits. Symlinks
  cannot be stored in a wheel, so they go into `_symlinks.json` and are recreated on first run (if site-packages is
  read-only, `julia` falls back to a private copy in `~/.julialang`).

Wheel platforms: Linux x86_64 / aarch64 (glibc), macOS x86_64 / arm64, Windows x86_64. The mirror also keeps
Linux i686 and Windows i686 archives; musl, FreeBSD, ARMv7 and PowerPC are not mirrored (edit `MIRRORED` in
`tools/sync.py` to change that).

## Setting it up

1. Create the repo (this README assumes `mohammadraziei/julialang`; if you use another name, change `DEFAULT_REPO` in
   `julialang/manager.py` and `tools/sync.py`, and the URLs in `pyproject.toml`) and push.
2. Settings → Actions → General → Workflow permissions: **Read and write**.
3. Run **Sync Julia binaries** once with `dry_run` to see the plan, then again for real. The first run mirrors every
   version since 1.10 (a few GB per version across platforms; use the `limit` input to do it in slices). It then
   starts **Build wheels** by itself.
4. PyPI (optional): the wheels are about 150–250 MB, above PyPI's default 100 MB per-file limit, so ask PyPI support
   for a size increase first. Then configure trusted publishing for this repo and workflow
   (`wheels.yml`), and set the repository variable `PUBLISH_PYPI=true`. Without PyPI, install from the release:
   `pip install julialang --find-links https://github.com/<owner>/julialang/releases/latest`.

## Notes

* Julia is MIT-licensed, but its binary distribution bundles third-party libraries under their own licenses (see
  `share/julia/` and `share/licenses` inside the bundle). The code in this repository is MIT.
* GitHub pauses scheduled workflows after 60 days without repository activity; if the weekly sync stops, re-enable it
  in the Actions tab.
* Checksums: md5 is recorded because it is handy for quick comparisons, but verification uses both md5 and the
  stronger sha256 from upstream.
