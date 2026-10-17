# Architecture Decision Records

This directory holds the Architecture Decision Records (ADRs) of `julialang`. Each record captures one significant
decision: the context that forced it, what was decided, and what follows from it. Format: Michael Nygard's
"Status / Context / Decision / Consequences", plus a short "Alternatives considered" section.

Records are immutable once **Accepted**. To change a decision, add a new ADR and mark the old one **Superseded by NNNN**.
Copy `template.md` to start a new record; numbers are sequential and never reused.

Statuses: `Proposed` -> `Accepted` -> (`Deprecated` | `Superseded by NNNN`). `Rejected` records are kept too.

## Index

| # | Title | Status | Area |
|---|-------|--------|------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | Process |
| [0002](0002-never-trust-paths-or-urls-from-the-mirror-list.md) | Never trust paths or URLs taken from the mirror list | Proposed | Security |
| [0003](0003-independent-trust-root-for-the-mirror-list.md) | Add an independent trust root for the mirror list | Proposed | Security |
| [0004](0004-fail-closed-configuration.md) | Fail closed when configuration cannot be read | Proposed | Security |
| [0005](0005-safe-archive-extraction.md) | Extract archives only with a safe, explicit policy | Proposed | Security |
| [0006](0006-destructive-commands-require-explicit-specs.md) | Destructive commands require explicit version specs | Proposed | CLI |
| [0007](0007-confine-deletions-to-julialang-owned-paths.md) | Confine deletions to julialang-owned paths | Proposed | Safety |
| [0008](0008-atomic-publication-of-the-mirror-list.md) | Publish the mirror list atomically | Proposed | Mirror / CI |
| [0009](0009-serialize-state-changes-with-a-lock.md) | Serialize state changes with a lock and atomic writes | Proposed | Robustness |
| [0010](0010-harden-the-ci-and-release-pipeline.md) | Harden the CI and release pipeline | Proposed | CI / Supply chain |
| [0011](0011-default-for-pkg-server-setting.md) | Revisit the default of `disable-pkg-server` | Proposed | Behaviour |
| [0012](0012-robust-platform-detection-and-read-only-commands.md) | Robust platform detection; read-only commands must not write | Proposed | Robustness |

## Origin

Records 0002-0012 come from the security and quality review of 2026-10-17 (version 0.4.0). Findings marked
"reproduced" in a record were confirmed by running the code; the others come from reading it.
