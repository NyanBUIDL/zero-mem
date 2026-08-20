# Maintainer Decision — Platform Scope v1.2.2

**Decision ID:** `MAINTAINER-DECISION-PLATFORM-SCOPE-v1.2.2`
**Date/context:** v1.2.2 execution
**Authority:** explicit maintainer decision recorded in the v1.2.2 work instruction

## Decision

The declared v1.2.2 release-qualification target is **Linux only**.

- Linux: `QUALIFIED` target, subject to the complete V122-06 Linux gates.
- Windows: implementation present; `EXPERIMENTAL / UNQUALIFIED / DEFERRED_TO_V1_2_3`.
- macOS: implementation present; `EXPERIMENTAL / UNQUALIFIED / DEFERRED_TO_V1_2_3`.
- Future qualification target for both deferred platforms: v1.2.3.

The current Linux environment cannot provide real Windows/macOS execution. This does not authorize a cross-platform production claim, a skipped-test PASS, or deletion/downgrade of the retained implementation and tests.

## Bounded execution amendment

The original v1.2.2 plan required Windows/Linux/macOS qualification before dependent package completion. The maintainer changes only the v1.2.2 support/qualification scope and authorizes dependent engineering after V122-01 is implementation-complete, Linux-verified, and evidence-reproducible, even while Windows/macOS are deferred.

This amendment does **not** change:

- JSONL canonical semantics;
- authorization semantics;
- public API semantics;
- derived-state semantics;
- Hermes ownership boundary;
- canonical-to-derived recovery direction;
- platform-safety obligations for future qualification;
- Git remote/tag/release/PyPI publication authorization.

## V122-01 classification

`IMPLEMENTATION_COMPLETE`; Linux `VERIFIED`; Windows `DEFERRED_TO_V1_2_3`; macOS `DEFERRED_TO_V1_2_3`; cross-platform release claim `NOT_ALLOWED`.

## Release boundary

A Linux-qualified v1.2.2 candidate must stop before final release publication and return `RELEASE_AUTHORIZATION_REQUIRED`. No tag, GitHub Release, force push, or PyPI publication is authorized by this decision.
