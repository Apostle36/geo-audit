# Reliability implementation plan

Scope: implement and verify Phase 1 of the supplied SaaS brief. Phases 2–5
remain a roadmap, not implemented capabilities. No deployment, installation
into global skills, commit, purchase or live platform collection is authorized.

## Current baseline

At the start of implementation, the repository contained an agent workflow, HTML inventory, editorial score
calculator, Markdown/PDF renderer and installer. It has no autonomous crawler,
live AI-answer collector, accounts or billing. The current default Python test
run failed during import because Playwright was absent from default Python; reporting dependencies
must not prevent help or non-rendering tests from running.

## Ordered work and verification gates

1. Evidence: strict records, hashes, provenance, statuses and ID resolution.
   Test malformed references, failed collection, duplicate IDs, missing content
   and hash mismatch. Inventory tests cover nullable attributes and strict JSON.
2. Assessment: immutable versioned rules, criterion anchors, applicability,
   coverage and a run validator. Test omitted criteria, unsupported exclusions,
   non-finite numbers and score/report consistency. Unknowns suppress totals.
3. Reporting: validated structured input with a clearly labeled legacy import
   path, safe atomic outputs, sanitization and content fidelity. Test collisions,
   concurrent writes, dependency errors and render failures. Render short/long
   fixtures and verify extracted text and representative pages, not CSS alone.
4. Packaging: stage complete installs, preserve backups, remove obsolete active
   resources, and explicitly load bundled roles. Test failure rollback and paths
   with spaces without modifying real global installations.
5. Handoff: update usage examples and limitations, run all regressions, inspect
   changes and account for every Phase 1 acceptance requirement.

## Test layers

- Unit: schemas, inventory, scoring, Markdown conversion, metadata validation.
- Integration: JSON CLI, run validation, installer, file safety and concurrency.
- Rendering: real browser PDFs, text preservation and visual checks.

Tests do not establish factual truth of human-entered evidence, indexing,
ranking or real AI visibility. Record any unavailable runtime checks explicitly.

## Implementation status

Evidence, fixed-rubric scoring, structured run validation/reporting, safe output
publication, and staged Linux installation are implemented. See
PHASE-1-VERIFICATION.md for requirement coverage, executed checks and limitations.
The SaaS roadmap has not been implemented; the next slice is choosing a lawful,
costed collection adapter and capturing real, labeled AI-answer observations.
