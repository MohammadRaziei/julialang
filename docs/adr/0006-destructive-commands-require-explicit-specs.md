# 0006. Destructive commands require explicit version specs

- Status: Proposed
- Date: 2026-10-17

## Context

In `install` and `use`, `latest` means "the newest version". In `uninstall` the same spec is evaluated by `matching`,
which returns every installed version. Reproduced: `julialang uninstall latest --yes` removed all installed versions,
and so did an empty spec (`uninstall "" --yes`). A script that passes an unset variable in quotes can wipe every
installed Julia.

## Decision

1. `uninstall` rejects `latest`, `stable`, `*` and an empty spec. To remove everything the user runs `purge`.
2. Any spec that matches more than one version prints the full list and the count; without a terminal it requires
   `--yes` as today.
3. Empty or whitespace-only specs are an error for every command that changes state.
4. `latest` keeps its meaning of "newest" wherever one version is selected; it is never a set.

## Consequences

### Positive
The most common scripting accident can no longer delete everything.

### Negative / trade-offs
Slight behaviour change for anyone who used `uninstall latest` to mean something else (it never did what they expected).

### Follow-up work
Document the rule in the command reference; add tests for empty and wildcard specs.

## Alternatives considered

- Make `uninstall latest` mean "newest installed": ambiguous with the set semantics of ranges.
- Only add a confirmation prompt: scripts pass `--yes`, so it would not help.
