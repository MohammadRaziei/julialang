# 0007. Confine deletions to julialang-owned paths

- Status: Proposed
- Date: 2026-10-17
- Related: 0006

## Context

`version_root` accepts an absolute path stored in `config.json`, and `uninstall`/`purge` pass it to `rmtree` after
checking only that `bin/julia` exists. `purge` also deletes `<JULIALANG_HOME>/versions` as a whole, which can destroy an
unrelated directory with that name when `JULIALANG_HOME` points at a shared location. `purge` prints "Removed" even
when `ignore_errors=True` hid a failure, and on Windows a locked file makes `uninstall` fail with a raw traceback and
leave a half-deleted installation. `upgrade`/`downgrade` catch `SystemExit` but not `OSError`.

## Decision

1. Every installed version directory contains a marker file written by `install`. Deletion requires the marker and
   that the resolved path is inside `<home>/versions`. Paths outside it, including absolute ones, are refused.
2. `purge` deletes only version directories that satisfy rule 1 and files julialang itself created.
3. Failures are reported accurately: no "Removed" message unless the directory is gone. `OSError` is handled in
   `uninstall` and in the replace step of `upgrade`/`downgrade`.
4. On Windows, rename the directory to a temporary name first, then delete it, and tell the user if a process still
   holds files.

## Consequences

### Positive
A bad config or an unusual home directory cannot cause deletion outside julialang's data. Messages match reality.

### Negative / trade-offs
Installations made before this change lack the marker; a one-time `sync_config` step must add it.

### Follow-up work
Migration of existing installs; tests for symlinked version directories and locked files.

## Alternatives considered

- Keep the `bin/julia` check: too weak to prove ownership.
- Forbid custom paths in config entirely: breaks the documented "path recorded in config" design.
