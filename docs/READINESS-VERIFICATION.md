# Toolkit 1.5.1 verification — 25 October 2026

Implemented the changes supported by the live pilots: bounded expected-content
conditions, navigation discovery fallback and clearer capture/report presentation.
Run schema 1.4.0 and score rubric 1.2.0 remain unchanged. New workflow
configuration is 1.1.0; existing 1.0.0 files remain readable without rewriting.

## Readiness behavior

Both standalone browser collection and workflow start accept `--ready-selector`,
`--ready-min-count`, `--ready-timeout-ms` and `--settle-ms`. The condition observes
visible document elements, including elements below the viewport. It performs
no clicks and does not establish whole-page completeness or usability.

A met condition records the observed count. Without a condition, readiness is
unverified. A timeout preserves the current DOM, screenshot and measurements as
a successful observation of that partial state, with the separate condition
marked timeout and exit code 4. Explicit retries retain previous attempts and
analyst work. A condition change requires a new audit, preserving methodology.

## Discovery and reuse

When sitemaps yield no candidates, discovery inspects one starting page for up
to 100 same-site navigation suggestions. Candidate destinations are not fetched.
Scope, port, credentials, address and robots restrictions are checked. The
fallback can be disabled in the standalone collector. The workflow reuses the
captured seed if sampled, including checked original bytes, and accounts for it
in the distinct-page budget.

## Automated checks

- Full suite with `GEO_RUN_RENDER_TESTS=1`: **202 tests passed**, no skips.
- Focused checks after final print adjustments: **11 real-render/reporting tests passed**.
- Ruff: passed. `git diff --check`: passed.
- New CLI help works without loading optional browser dependencies.

Regression coverage includes delayed and hidden content, minimum counts,
preserved timeout snapshots, distinct CLI exit status, explicit timeout retries,
old configuration compatibility, robots denial, navigation scope/bounds, raw
seed reuse, distinct-page budgeting, malformed measurement values, title labels,
escaped output, unchanged scoring, and interruption guidance without a traceback.

## Live checks

New, targeted one-page validations used the same public sandbox hosts as the
earlier three-page pilots. Earlier pilot runs and reports were preserved.

| Observation | Books homepage | Quotes delayed page |
|---|---:|---:|
| Navigation suggestions | 74 | 4 |
| Configured condition | h1, minimum 1 | .quote, minimum 10 |
| Condition timeout | 5000 ms | 5000 ms |
| Met conditions | 2/2 viewports | 2/2 viewports |
| Expected content independently counted in saved DOM | 20 product cards per viewport | 10 quotation cards per viewport |
| Navigation response reused for HTTP sample | Yes | Yes |
| Original seed bytes preserved | Yes | Yes |
| Repeated resume changed run or checkpoints | No | No |

The Quotes URL remains `https://quotes.toscrape.com/js-delayed/?delay=1500`.
It previously yielded zero cards at the default settling interval. The new
configured condition captures ten in both viewports instead of treating an early
empty snapshot as verified. The initial 500 ms interval is followed by bounded
condition polling; a met count is not inferred from navigation success.

These validations are targeted integration checks, not new production-site
audits or human labor benchmarks. All candidate counts are observations from
this run. The live scripts and JSON results are retained under
`audits/validation/20261025T210000Z/`.

## Reports

The preserved three-page pilot assessments were re-exported with the new
renderer. All **126 material finding/review/limitation fields** survived PDF
text extraction, and the input run bytes remained unchanged.

The reports use saved titles and shorter URL labels, retain query distinctions,
and show latest browser capture conditions with mobile layout and blocked-resource
caveats. Older captures have no retroactive readiness verification. Capture
conditions are grouped by page; compact methodology print spacing keeps the
reviewed-page list with substantive appendix content. Scoring is unaffected.

Final report exports retain 11 pages for Books and 12 for Quotes. The Quotes
last page now has 234 extracted words rather than the earlier 16-word page.
The new capture-condition section adds useful information; pagination improvements
do not remove substantive audit detail. The action table, capture conditions
and final appendix were visually inspected after rendering.

- [Conventional report PDF](../audits/validation/20261025T210000Z/reports-final/conventional/pilot-report.pdf)
- [JavaScript report PDF](../audits/validation/20261025T210000Z/reports-final/javascript/pilot-report.pdf)
- [Live validation JSON](../audits/validation/20261025T210000Z/validation.json)
- [Final report comparison](../audits/validation/20261025T210000Z/report-comparison-final.json)

The reports remain pilot drafts with their original scope and unknowns. No
human delivery approval, actual AI visibility or production ranking outcome was
invented.
