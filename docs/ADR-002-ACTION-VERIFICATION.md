# ADR-002: Action journals and conservative audit comparisons

**Status:** Accepted  
**Date:** 2026-10-25  
**Deciders:** Repository maintainer through the authorised v1.6 implementation request

## Context

An audit's findings describe an evidence snapshot. Assignments, estimates and
delivery status change after that snapshot. A missing finding in a follow-up
does not prove that a fix worked. Comparisons must preserve uncertainty and the
existing scope and rubric requirements.

## Decision

Keep run schema 1.4.0, rubric 1.2.0 and workflow configuration 1.1.0 unchanged.
Store a frozen baseline and append-only local action events separately. Actions
retain the original acceptance check. Completion queues verification; a passing
named human or agent review must cite fresh successful evidence for every
affected page in a compatible follow-up. Preserve that exact follow-up snapshot.

Match findings deterministically using category, normalised claim and page set.
Renaming an ID alone does not create a new finding. Changed wording or scope
requires reconciliation; no semantic matching is attempted. Only a passing
review bound to the exact current bytes can classify a dropped issue as
resolved. New, recurring and unresolved issues remain explicit.

Delivery approval 1.1.0 binds the run, previous snapshot and journal fingerprint
when those sections are requested. Existing approval 1.0.0 remains valid for
reports without those attachments. Assignments and reviews never award scores.

## Options considered

| Option | Cost and complexity | Fit |
|---|---|---|
| Local immutable events and frozen snapshots | Moderate; existing Python runtime | Portable, reviewable, no service migration |
| Mutable fields inside run.json | Low initially | Mixes post-audit work with the original evidence and approvals |
| Hosted task database and semantic matching | High; identity and service operations | Beyond the local toolkit's current scope |

## Consequences

Local file locks serialize updates; each event binds its predecessor. Loading
revalidates the full history and referenced snapshots. This detects accidental
edits and breaks in the chain, not a malicious rewrite or deletion of a complete
tail. Named local reviews do not authenticate a person's identity. Freshness
uses recorded timestamps and cannot establish truthful capture by itself.

Comparisons remain editorial readiness comparisons. Changed capture conditions
must be interpreted in the report; matching scope does not establish causality,
search indexing, AI citations, traffic or revenue changes. The analyst must
review the actual acceptance check and declare human versus agent review.

## Validation

Exercise dependency cycles and reopening, stale and incomplete evidence,
incompatible scopes, absent versus verified findings, context-bound approvals,
concurrent writers, input preservation and real HTML/PDF output. Run a scoped
acceptance check on a real public business site and preserve its original data.
