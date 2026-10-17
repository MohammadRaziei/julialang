# 0002. Never trust paths or URLs taken from the mirror list

- Status: Proposed
- Date: 2026-10-17
- Related: 0003 (trust root), 0005 (extraction)

## Context

`install` builds the local download path from the `name` field of `julia-list.json` and downloads from its `url`
field. Both come from a file that anyone who controls the GitHub release can change.

Reproduced: with `name` set to an absolute path and `url` set to a `file://` URL, the downloaded bytes were written to
that absolute path **before** the checksum was verified. This happened even with `--strict` and with a wrong
`--sha256`, so the strongest verification options in the README do not cover this path. Other effects: any URL scheme
or host is accepted, and one malformed key in `versions` makes every command fail, because the list is not validated.

## Decision

1. The local file name is derived by the program from the version and platform key. The `name` field is never used to
   build a path. The download goes to a fixed file name inside a fresh temporary directory.
2. Only `https` URLs are accepted, and only for an allow-list of hosts (the GitHub release download host and its
   asset CDN host; a user-set `JULIALANG_LIST_URL`/`JULIALANG_REPO` may extend the list explicitly).
3. The list is validated when loaded: types of every field, version strings in strict ASCII `X.Y.Z` form, platform
   keys from a fixed set, sha256 as 64 lowercase hex digits. Invalid entries are skipped with a warning; an invalid
   top level is an error.
4. The verified archive is moved to its final place only after verification succeeds.

## Consequences

### Positive
A hijacked list can no longer write outside the temporary directory or redirect downloads to arbitrary hosts. One bad
entry no longer breaks every command.

### Negative / trade-offs
Custom mirrors on other hosts need an explicit opt-in. The list schema becomes a compatibility surface.

### Follow-up work
Add regression tests for absolute names, `..` names, `file://` and non-allow-listed URLs, and malformed keys.

## Alternatives considered

- Sanitise `name` with a basename: still leaves URL and schema problems and keeps list-controlled data in a path.
- Rely on `--sha256` alone: verification happens after the write, so it cannot prevent this.
