# 0003. Add an independent trust root for the mirror list

- Status: Proposed
- Date: 2026-10-17
- Related: 0002, 0010

## Context

The archives, `julia-list.json`, the mirror's `sha256` and the recorded `upstream_sha256` all live in one trust domain:
the GitHub repository's releases. Whoever controls the releases can change the archive and both hashes together, so
neither the warning nor `--strict` can detect it. `upstream_sha256` therefore protects against accidental corruption
only. The only real defence today is that the user supplies the official hash by hand with `--sha256`, which is
impractical for routine use. The README states the limitation honestly, but some wording ("verifies sha256 and md5")
can be read as stronger than it is.

## Decision

We will add a second, independent root of trust, in this order of preference:

1. **Signed list.** Sign `julia-list.json` in CI and verify the signature on the client with a public key shipped
   inside the wheel (distributed through PyPI, a separate channel from GitHub releases). Use an existing scheme such as
   Sigstore or GitHub artifact attestations rather than inventing one.
2. **Opportunistic upstream check.** When the official checksum files on the Julia download host are reachable, the
   client compares the archive hash with them; a disagreement is an error in strict mode.
3. **Upstream signature in CI.** The sync job verifies the release signatures that Julia publishes (to the best of our
   knowledge `.asc` files exist for releases) instead of trusting hashes served from the same origin as the files.

README wording will distinguish "detects corruption" from "protects against a compromised mirror".

## Consequences

### Positive
Compromise of the repository alone is no longer enough to ship a malicious Julia.

### Negative / trade-offs
Key management and rotation become a project responsibility. Option 2 only helps where the upstream host is reachable,
which is not the main use case of the project.

### Follow-up work
Decide the signing tool; document key rotation; add a `verify` command.

## Alternatives considered

- Keep the current model and document it: honest but leaves users exposed.
- Embed all hashes in each wheel: strongest, but new Julia versions would require a new wheel release.
