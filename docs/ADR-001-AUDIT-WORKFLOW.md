# ADR-001: Resumable local audits and reviewed delivery

**Status:** Accepted
**Date:** 2026-10-25
**Deciders:** Repository maintainer through the authorised implementation request

## Context

The toolkit has a strict, portable run format and fixed rubric. Collection,
review and delivery still require coordinating several scripts. A valid draft
can contain placeholders and incomplete work. Browser checks require separate
tools. The first release must address these gaps while preserving old runs.

## Decision

Keep run schema 1.4.0 and rubric 1.2.0. Add an immutable workflow configuration,
per-step collection checkpoints, and a separate local approval tied to the exact
run bytes. A CLI guides page selection, collection, human analysis and export.
Browser collection is opt-in, uses fresh contexts, and preserves DOM captures,
viewport screenshots and measured navigation timing. It never assigns scores.

## Options Considered

| Option | Complexity | Cost | Familiarity | Fit |
|---|---|---|---|---|
| Local files and CLI | Moderate | Existing runtime | Existing Python toolkit | Preserves portable evidence and supports interrupted runs |
| Web service and database | High | Hosting and operations | New architecture | Requires authentication, browser isolation and migrations |

## Trade-off Analysis

Local files provide inspectable checkpoints without a service dependency. A
single workspace lock prevents concurrent writers. Separate approvals preserve
the strict run contract; an edit invalidates the review. Explicit exclusions
support honestly scoped reviews. A local named attestation is not identity
verification. Browser snapshots are observations under recorded conditions,
not verified crawler access, field Core Web Vitals or a complete accessibility audit.

## Consequences

- Existing runs and helper commands remain usable; client drafts gain a label.
- Final client exports require a current review and explicit scope.
- Resuming reuses successful captures; explicit retries preserve failed attempts.
- The analyst still owns findings, interpretation, scoring and human review.
- A future hosted service would need a stronger network and browser boundary.

## Action Items

1. Implement delivery checks and visible draft/final report state.
2. Add desktop/mobile browser evidence and honest measurement limitations.
3. Add checkpointed orchestration, progress and retry guidance.
4. Verify interruption recovery, approval invalidation and real browser output.
