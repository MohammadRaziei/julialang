# 0008. Publish the mirror list atomically

- Status: Proposed
- Date: 2026-10-17
- Related: 0010

## Context

The sync job publishes `julia-list.json` as an asset of the `__download__` release with `gh release upload --clobber`,
which removes the old asset before uploading the new one. During a long backfill this happens after every version, so
clients repeatedly see a 404 window. Separately, the sync job treats a 404 on the list as "first run" and starts from
an empty list, so a transient 404 can trigger a full re-mirror and overwrite the real list.

## Decision

1. Never expose a state in which the list does not exist. Upload each new list under a versioned name first, verify it
   downloads, then switch the stable name (or publish the stable name through a mechanism that replaces in one step).
2. The sync job distinguishes "release does not exist" from "release exists but the asset is missing". Only the former
   is a first run. A missing asset on an existing release is an error unless explicitly allowed.
3. Clients treat a 404 on the list as a retryable condition, with a short bounded retry, before using the cache.

## Consequences

### Positive
No client-visible gaps during sync, and no accidental reset of the mirror state.

### Negative / trade-offs
Extra assets to clean up; a slightly more complex publish step.

### Follow-up work
A retention rule for old versioned lists.

## Alternatives considered

- Commit the list to git: rejected earlier because it triggered CI loops and noise.
- Publish only at the end of a run: loses progress when a run is interrupted.
