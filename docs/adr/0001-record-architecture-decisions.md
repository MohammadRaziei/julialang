# 0001. Record architecture decisions

- Status: Accepted
- Date: 2026-10-17

## Context

`julialang` has made many design decisions through conversation and commit messages: the pure-Python wheel, the
`__download__` release as the mirror, the two independent workflows, the `.julialang` pin file, the checksum model.
The reasons live in chat history and are easy to lose. A security review found places where the code no longer matches
the intent behind earlier choices, which is hard to judge without written intent.

## Decision

We will record significant decisions as ADRs in `docs/adr/`, using the template in this directory. A decision is
significant if it changes the trust model, a public command or file format, the release process, or the on-disk layout.

## Consequences

### Positive
Intent is reviewable and new contributors can see why things are the way they are.

### Negative / trade-offs
Small overhead per significant change.

### Follow-up work
Link each ADR from the changelog entry that implements it.

## Alternatives considered

- Keep decisions in the README: mixes rationale with user documentation and cannot record rejected options.
- Rely on commit messages: not discoverable and not organised by topic.
