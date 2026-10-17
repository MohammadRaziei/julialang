# 0010. Harden the CI and release pipeline

- Status: Proposed
- Date: 2026-10-17
- Related: 0003, 0008

## Context

Review of `sync.yml` and `wheel.yml` found: `contents: write` granted to every job including tests; third-party and
first-party actions pinned to mutable tags (notably `softprops/action-gh-release@v2`); a long-lived PyPI API token
stored as a secret; the PyPI step exits successfully with only a warning when the token is missing, which already
produced a release that was never uploaded; the smoke test depends on the live mirror, so a transient GitHub problem
blocks releases; the `__beta__` release is replaced by deleting all assets and then uploading, which can leave it
empty when a run is cancelled; and the crawler checks only the file name of discovered links, not their host.

## Decision

1. Workflow default permissions are `contents: read`; only the release and sync jobs raise them, per job.
2. All actions are pinned to full commit SHAs and updated through a dependency-update bot.
3. Publish to PyPI with Trusted Publishing (OIDC) and remove the stored token; enable attestations for the artifacts.
4. On a tag build a missing publishing credential or a failed upload fails the workflow.
5. Split live-mirror smoke tests from the release gate: the gate uses a local test mirror; the live check runs on a
   schedule and reports separately.
6. Replace `__beta__` assets without a window where none exist (upload new names first, then delete old).
7. The sync crawler accepts download links only from the official Julia download hosts.
8. Protect release tags and `master` with branch/tag protection and require review for workflow changes.

## Consequences

### Positive
A compromised test dependency cannot publish; releases cannot silently skip PyPI; fewer flaky release blocks.

### Negative / trade-offs
One-time setup on PyPI and in repository settings; SHA pins need regular updates.

### Follow-up work
Add a workflow linter (for example `zizmor` or `actionlint`) to CI.

## Alternatives considered

- Keep the token but rotate it: still a stealable long-lived secret.
- Keep tag pins: convenient but allows a moved tag to run arbitrary code with write access.
