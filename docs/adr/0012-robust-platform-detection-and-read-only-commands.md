# 0012. Robust platform detection; read-only commands must not write

- Status: Proposed
- Date: 2026-10-17
- Related: 0004, 0009

## Context

Several small issues share one theme: the tool assumes a normal, writable, glibc-based environment.

- Alpine and other musl systems get a glibc Julia, and the shim fails with an unexplained "No such file" error; exec
  errors in the shim are not caught.
- A Python built for x86_64 under Rosetta on Apple Silicon installs the x86_64 build without saying so.
- `status` and `list` call `sync_config`, which writes `config.json`, so they crash on read-only or full file systems;
  a failed cache write is reported as "cannot reach the mirror".
- A `.julialang` file saved with a UTF-8 byte order mark is silently ignored (reproduced).
- `julialang pin` run inside the home directory crashes because `~/.julialang` is a directory (reproduced).
- Hints print version specs unquoted, so copy-pasting `>=1.0,<2` into a shell redirects output (reproduced).
- `self-uninstall` may call the pip of another environment and exits successfully when the package was not found.

## Decision

1. Detect musl and report that no compatible binary exists; warn when the Python architecture differs from the
   machine architecture.
2. Catch exec errors in the shim and print a one-line explanation with the path and the platform.
3. Read-only commands never write state; failures to write a cache are warnings and are reported as such.
4. Read project files as `utf-8-sig`. `pin` refuses to treat a directory as a pin file and says so.
5. Print suggested commands with quoted specs.
6. `self-uninstall` verifies that the package belongs to the interpreter it uses and reports a non-zero status when
   nothing was removed.

## Consequences

### Positive
Errors become understandable and read-only environments work for information commands.

### Negative / trade-offs
More platform-specific code paths to test.

### Follow-up work
CI jobs on Alpine, Windows and macOS (Intel and Apple Silicon) for these paths.

## Alternatives considered

- Leave as documented limitations: cheap, but the failures are confusing and some are data-affecting.
