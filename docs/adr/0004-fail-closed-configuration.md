# 0004. Fail closed when configuration cannot be read

- Status: Proposed
- Date: 2026-10-17

## Context

`load_config` returns an empty dictionary on any read or parse error, and `get_setting` ignores values that are not
booleans. Reproduced: a truncated `config.json` and a config containing the string `"true"` both made `strict` report
`false (default)` with no message. A security setting therefore turns itself off exactly when its file is damaged.

## Decision

1. A missing `config.json` means defaults. A present but unreadable or invalid file is an error that names the file
   and the problem, for every command that needs configuration.
2. Values of the wrong type for a known setting are errors, not silently replaced by defaults.
3. Unknown keys are preserved on write and ignored on read.
4. Commands that only show information (`config`, `status`) still run and print the problem prominently.

## Consequences

### Positive
Security settings cannot be disabled by corruption or typos.

### Negative / trade-offs
A damaged config now blocks installs until fixed; the error must say how (`julialang config`, or delete the file).

### Follow-up work
Tests for truncated JSON, wrong types, and unknown keys.

## Alternatives considered

- Keep defaults but warn: still fails open for `strict`.
- Fail closed only for `strict`: inconsistent and surprising.
