# 0005. Extract archives only with a safe, explicit policy

- Status: Proposed
- Date: 2026-10-17
- Related: 0002

## Context

The tar extraction code catches `TypeError` to detect Python versions without extraction filters and then calls
unfiltered `extractall`. That handler also catches unrelated `TypeError`s raised during extraction. When the strict
`data` filter rejects a member, the code retries with the weaker `tar` filter. Zip extraction relies on the standard
library's path sanitising and does not limit total size or file count. Extraction happens after hash verification, so
the risk exists mainly if the mirror is compromised (see 0003), but extraction is the last line of defence.

## Decision

1. Detect filter support by checking for the filter feature (version or attribute), never by catching `TypeError`.
2. On interpreters without filters, extract member by member with our own checks: reject absolute names, `..`
   components, device files, and links whose resolved target leaves the destination.
3. Do not fall back to a weaker filter after a filter error. Allow only the relative symlinks that official Julia
   archives are known to contain, through an explicit allow-list reviewed per release layout.
4. Apply upper bounds on member count and total unpacked size, generous enough for real Julia releases.

## Consequences

### Positive
Extraction behaves the same on every supported Python and cannot silently downgrade its protection.

### Negative / trade-offs
More code to maintain; an unexpected new link layout in a future Julia release fails closed until the allow-list is
updated.

### Follow-up work
Test with crafted archives (traversal, absolute symlink, hardlink, oversize) on every supported Python version.

## Alternatives considered

- Require Python 3.12+: simple, but drops supported versions and the project advertises 3.9+.
- Use an external extractor: adds a dependency and breaks the zero-dependency goal.
