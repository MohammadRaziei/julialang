# 0011. Revisit the default of `disable-pkg-server`

- Status: Proposed
- Date: 2026-10-17

## Context

By default the `julia` shim starts Julia with an empty `JULIA_PKG_SERVER` so that `Pkg` uses GitHub directly. This is
what makes the tool useful on networks that reach only PyPI and GitHub. The same default applies everywhere: on normal
networks it is slower (the whole General registry is cloned), loses the package server's cached copies of packages
whose repositories were deleted or rewritten, and cannot fetch packages hosted outside GitHub. The README's statement
that package installation works "with nothing but GitHub reachable" is therefore too broad.

## Decision

1. Keep the explicit-user-choice rule: a `JULIA_PKG_SERVER` already set in the environment is never changed.
2. Change the default to automatic: the shim leaves the package server enabled, and the setting `disable-pkg-server`
   accepts `true`, `false` and `auto`. In `auto` mode, `julialang` checks reachability of the package server once (with a
   short timeout, cached) and disables it only when it is unreachable. The decision is printed once.
3. State the limits in the README: packages hosted outside GitHub cannot be installed in GitHub-only environments.

## Consequences

### Positive
Normal networks keep the faster, more reproducible path; restricted networks still work without configuration.

### Negative / trade-offs
The shim gains a small network probe, which conflicts with "the shim never touches the network". The probe must be
cached and skippable (`false`/`true` skip it).

### Follow-up work
Measure the probe cost; decide the cache lifetime.

## Alternatives considered

- Keep `true` as the default and document it: simple but surprising for most users.
- Make `false` the default: breaks the main use case without configuration.
