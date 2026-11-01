# Action tracking and audit comparisons (toolkit 1.6.0+)

`run.json` remains an evidence snapshot. Action assignments, estimates,
dependencies and review outcomes live in a separate local journal. These
commands never edit the audited website or award scores.

## Assign and complete work

```bash
python scripts/actions.py init /path/baseline/run.json
python scripts/actions.py update /path/baseline/actions F1 \
  --owner 'Site maintainer' --effort-hours 2 --status in_progress
python scripts/actions.py update /path/baseline/actions F2 --depends-on F1
python scripts/actions.py update /path/baseline/actions F1 --status ready_to_verify
python scripts/actions.py status /path/baseline/actions
```

Use IDs from the baseline's supported improvement findings. Informational
context, hypotheses, unknowns and not-applicable findings are not improvement
tasks. The store freezes the original fix and acceptance check. Effort is an
optional positive number of hours, not a measured outcome. Dependencies must
exist and be acyclic; active work requires verified dependencies. To reopen an
upstream task, first return its active dependents to `planned`.

The statuses are `planned`, `in_progress`, `ready_to_verify`, and `verified`.
Marking work done means `ready_to_verify`. Direct assignment to `verified` is
rejected. Reopening clears its current proof while preserving prior events.
Metadata-only owner/effort edits retain proof but change the journal fingerprint.
Use repeated `--depends-on` to replace the dependency list, or
`--clear-dependencies` to remove it. Dependency changes on verified tasks require
reopening first. The Python update API also accepts null owner/effort to clear
an assignment or estimate.

## Verify against fresh evidence

Queue verification **before collecting the follow-up**. Start a new audit using
the same origin, business type, market, language, sample and sampling rationale.
Preserve the rubric and criterion applicability. Review the new evidence and
write an honest follow-up; do not remove a finding merely to make a test pass.

```bash
python scripts/actions.py review /path/baseline/actions F1 \
  --run /path/followup/run.json --evidence browser-page-1-desktop \
  --evidence browser-page-1-mobile --result passed \
  --reviewer 'Actual reviewer' --reviewer-type human \
  --rationale 'Describe how these captures satisfy the original acceptance check.'
```

Use actual evidence IDs and include successful evidence for **every affected
URL**. Captures must be newer than that URL's baseline records and no earlier
than the ready event; a different run file alone is insufficient. Collector
timestamps have one-second precision, so allow the next second before starting
fresh collection if completion was just queued. All selected evidence must pass
freshness checks, including any supporting external sources. Scope or wording
changes need explicit reconciliation; create a new baseline if scope changes.

Declare `--reviewer-type agent` when an agent performed the review. Never record
a human attestation on someone's behalf. `passed` marks verified; `failed`
returns to in progress; `inconclusive` remains ready to verify. A passing review
is rejected if the issue remains in the follow-up or its ID is reused for a
different issue. The review output lists `capture_prompts` for cited
evidence such as an error response. They are reported, not refused, because an
error can be the agreed outcome (for example a retired page now returning 404);
the client report repeats them beside the resolved item. The named reviewer is responsible for judging whether the
evidence actually satisfies the acceptance check; the CLI validates integrity,
scope and freshness, not factual or semantic truth.

## Compare and report

```bash
python scripts/compare_runs.py /path/baseline/run.json /path/followup/run.json \
  --actions /path/baseline/actions --output /path/comparison.json
python scripts/audit.py compare /path/followup --previous /path/baseline/run.json \
  --actions /path/baseline/actions
python scripts/audit.py export /path/followup /path/report.html \
  --compare /path/baseline/run.json --actions /path/baseline/actions
python scripts/geo-audit-pdf.py /path/followup/run.json /path/report.pdf \
  --compare /path/baseline/run.json --actions /path/baseline/actions
```

Matching requires the same scope and rubric, including criterion applicability.
The standalone comparison returns exit 3 for incompatible audits, without change
counts or score deltas; report export refuses incompatible comparisons. Return
2 indicates invalid input. Matching sample order may differ. Claims match by
category, normalised wording and page set, not by ID or inferred meaning.

- **New:** supported issue with no matching earlier issue.
- **Recurring:** the same supported issue in both snapshots.
- **Resolved:** no current issue or identity conflict, and a passing action
  review bound to these exact follow-up bytes.
- **Unresolved:** uncertainty, changed identity, or a dropped finding without
  that exact proof. Disappearance alone never establishes a fix.

A reformatted or edited follow-up requires a new review. A task verified against
a different snapshot remains visible as historically verified, but is qualified
in the report and cannot count as resolved here. Incomplete scores remain
withheld. Coverage changes are shown separately. Capture conditions can differ;
read both runs before attributing an apparent improvement to site changes.

`--actions` alone is for the exact baseline to which that store belongs. Use
`--compare` when reporting a follow-up. Both options also work on
`audit.py status` and `delivery.py check/approve`.

## Final report approval

Drafts require no approval. A final report containing action/comparison sections
needs approval of that whole context:

```bash
python scripts/delivery.py check /path/followup/run.json \
  --compare /path/baseline/run.json --actions /path/baseline/actions
python scripts/delivery.py approve /path/followup/run.json --reviewer 'Actual reviewer' \
  --compare /path/baseline/run.json --actions /path/baseline/actions
python scripts/audit.py export /path/followup /path/final.pdf --final \
  --compare /path/baseline/run.json --actions /path/baseline/actions
```

The usual full-review requirements, explicit scope exclusions and warning
acknowledgements still apply. Approval 1.1.0 adds the previous-run hash and/or
journal hash to the original approval fields. Changing or dropping either
attachment invalidates it. Run-only approval 1.0.0 remains readable and cannot
authorise extra sections. Action verification and delivery approval are separate.

## Storage and limits

The default store is `actions/` beside the baseline. It contains `baseline.json`,
`manifest.json`, numbered `events/*.json`, and `runs/<sha256>.json` follow-up
snapshots. Updates take a local file lock and atomically publish a new event.
Initialisation never replaces an existing directory. Copies of the same follow-up
are reused without overwriting. Reports cannot write inside the journal or
overwrite any source, including a hardlink alias.

Loading validates the baseline, event sequence/hash chain, transitions,
dependencies and all referenced follow-ups. This detects accidental edits; it
does not authenticate reviewer identities or prevent a malicious full rewrite
or deletion of a complete event tail. Preserve the whole store with the audit
backups. Local timestamps and hashes establish internal consistency, not truth.
Comparison does not establish causality or measured AI visibility.
