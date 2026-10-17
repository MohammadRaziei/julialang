# 0009. Serialize state changes with a lock and atomic writes

- Status: Proposed
- Date: 2026-10-17
- Related: 0004

## Context

Two concurrent `install`/`uninstall` runs (parallel CI steps, two shells) can interfere: `extract_archive` removes the
destination before moving the new tree in, `config.json` is updated by read-modify-write without a lock, and the
temporary file name is fixed. Because `load_config` returns an empty dictionary on parse errors, interleaved writes can
cause a silent configuration reset.

## Decision

1. All commands that modify `~/.julialang` take an exclusive lock file in the home directory (`fcntl` on Unix,
   `msvcrt` on Windows), with a clear message and timeout when the lock is held.
2. Config writes use a unique temporary file name followed by an atomic replace.
3. Installation extracts into a unique temporary directory and moves it into place under the lock; an existing
   destination is never removed before the replacement is ready.
4. Read-only commands do not take the lock.

## Consequences

### Positive
Parallel use is safe and failures are explicit rather than silent.

### Negative / trade-offs
A stale lock after a crash must be recoverable (lock is released by the OS when the process dies).

### Follow-up work
Concurrency tests that start several installs at once.

## Alternatives considered

- Document "do not run in parallel": CI matrices make this unrealistic.
- Per-version locks only: does not protect `config.json`.
