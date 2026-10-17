# Phase 1 verification and handoff

> Historical record of the Phase 1 handoff on 2026-09-10. Test counts,
> behaviour and limitations below describe the toolkit on that date; see
> README.md and docs/RUN-FORMAT.md for the current toolkit.

Date: 2026-09-10. Scope: reliability foundation requested in the pasted brief's
execution order. The later SaaS phases are intentionally not implemented.

## Implemented outcome

The source toolkit now validates captured evidence and findings, calculates a
fixed editorial rubric, and generates HTML/PDF from the same validated run JSON.
It rejects missing references, invalid values, report path collisions and silent
output replacement. Legacy Markdown is explicitly labeled unverified. Linux
installation stages complete resources and backs up the prior package before
atomic activation. Real global installations have not been changed.

## Requirement-by-requirement evidence

| Requirement | Implementation | Verification |
|---|---|---|
| Inspect current source/audit and create plan | Existing release audit read; initial source and test failure inspected; PHASE-1-PLAN.md | Baseline was the unconnected evidence validator plus old scoring/report logic, not assumed from conversation |
| Structured evidence IDs, source, time, method, content, status and integrity | evidence.py: validate_registry, resolve_ids, record CLI | test_evidence_contract; test_cli_contract record round trip, duplicate IDs, invalid dates and content hashes |
| Every finding resolves evidence; failed collection remains unknown | run_contract.py: validate_run | test_run_contract references and failed-collection tests; assessed criteria also reject failed evidence |
| Observations, hypotheses, recommendations and unknowns distinct | Exact finding kind/status vocabulary and checks; plain-text report fields | test_run_contract; model does not mutate input; structured markup-injection regression |
| Stable versioned criteria, anchors, weights and applicability | rubrics/1.2.0.json, pinned content hash in score.py | test_scoring_contract fixed means, altered-rubric refusal, unknown IDs, invalid numeric values and N/A rejection |
| Coverage separate from score; omitted checks cannot appear complete | Fixed denominator, missing lists, unknown/N/A counts, withheld overall | Cherry-picked half-sample fixture reports 0.5 coverage and null overall; all-N/A schema reports 0.8 total coverage, no overall |
| Sample-aware validation | Run validator requires successful referenced captures for every sample URL for assessed/N/A criteria | Extra sample URL without supporting capture fails; scope changes reject comparison |
| Preserve historical methodology and avoid prediction claims | Version/hash recorded in calculations/reports; immutable rubric; old input rejected or explicitly unverified | Modified-rubric regression; legacy-warning tests; README/format/skill disclaimers |
| Structured report source of truth | JSON validates before report_data; score recomputed, not accepted from free text | Valid structured render; injected overall_score field rejected; JSON CLI tested |
| Input/output safety and atomic publication | safe_io.py checks aliases/inodes and uses temporary sibling + atomic publication | Same file, hardlink, symlink, existing output, simulated interrupted publication, simultaneous output tests |
| Complete tested content and safe markup | Parse before allowlist sanitization; fixed wrapping; preserved preamble/code/Unicode | Real short PDF contains original code and Unicode; actual 14-page long PDF retains all 100 finding markers; no table DOM overflow |
| Graceful malformed inputs and optional dependencies | Strict CLI errors, lazy reporting imports, parser validation | Invalid/duplicate JSON, malformed URLs/metadata/fences, missing file, missing Markdown/Playwright, help under Python -S |
| Temporary cleanup and concurrent runs | Scoped temporary directories; no-clobber publication | Render-failure temp cleanup; same-output one winner; two real concurrent PDF exports succeed |
| Install reliability | Stage, resource validation, backup, renameat2 exchange, package hashes | Isolated install/upgrade, source/bundle layouts, obsolete-file removal with recoverable backup, copy/exchange failures, global-role collision diagnosis |
| Updated use instructions | README, RUN-FORMAT, example run, skill and six roles, CLAUDE routing | Example validation/HTML CLI, skill quick validator, installed manifest content checks |

## Executed tests

The complete suite ran with actual browser tests enabled: **64 tests passed**.
The original 11 tests remain, adapted where the intentionally stricter input
contract requires complete metadata and registry-backed scoring.

Test environment: Python 3.14.4, Markdown 3.10.2, Playwright 1.58.0, system
Chrome 153 and pdftotext. Direct reporting dependencies are pinned to the tested
versions; transitive dependencies are not a full cross-platform lockfile.

Command used on this machine:

```sh
GEO_RUN_RENDER_TESTS=1 \
PYTHONPATH=~/.local/share/pipx/venvs/playwright/lib/python3.14/site-packages \
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

The PYTHONPATH selects an existing local Playwright installation, not a new
package installation. A normal setup can instead use the README's virtualenv.
The initial browser attempts failed at a denied socket operation. After network
permission was granted, both real browser tests and the full suite succeeded.
Tests that were blocked initially are not counted as successful attempts.

Additional checks: Python syntax parse; git diff --check; skill quick_validate
(passed). No commit, push, live collection, paid service, global installation or
deployment was performed.

## Visual evidence

Retained outputs are under the task's outputs/phase-1-render-checks directory:

- geo-render-check-3wz4ct9q: short.pdf, long.pdf (14 pages), long.html,
  long-extracted.txt, short-page2.png, long-page3.png and long-page14.png.
- geo-render-check-h4li1pf8: two successful concurrent structured PDFs and
  structured-page3.png.

Visually inspected the short content page, middle and last long-table pages, and
a structured assessment page. Code characters, quote formatting and Unicode
are visible; both long-table columns are within the page; the last marker 099
is visible. Earlier failed-attempt directories contain fixtures only and are
not successful rendering evidence. The final full suite repeated actual renders
in temporary directories and cleaned them afterward.

## Remaining limitations, not completed SaaS capabilities

- Evidence integrity is not truth verification. Human review must determine
  whether captures actually support conclusions and whether scope is sufficient.
- The fixed ten-check rubric is deliberately coarse and editorial. It is not
  calibrated against citations, traffic or sales. Missing schema alone is not a
  penalty; an all-N/A category withholds the overall score instead.
- JSON validation allows incomplete audits while clearly reporting missing data.
  Passing validation is not a claim that an audit is complete.
- No autonomous crawler, robots enforcement engine, live AI provider adapter,
  accounts, multi-tenant security, billing, attribution or deployment exists.
- Fresh-session agent discovery/delegation was not exercised. Bundled loading is
  explicit and global collisions are diagnosed, but runtime obedience is not
  proved by unit tests. Installed copies remain at their prior version.
- The PDF's branding header/footer are flow elements, not guaranteed repeating
  page furniture. Long content is preserved in tested cases, but pagination of
  every possible input and every font/language is not proved. PDF accessibility
  and cross-platform layout still need dedicated work.
- HTML links remain clickable; embedded resource fetching is blocked by the
  renderer. No packet-level egress audit or hardened multi-tenant browser sandbox
  was performed. This is a local CLI, not an untrusted public rendering service.
- Atomic upgrade support is Linux-specific. Normal failure paths are tested;
  sudden power loss, arbitrary concurrent external filesystem edits and every
  filesystem implementation are not covered.

## Recommended next slice

Research and present permitted collection methods, surface differences, costs
and credentials before choosing a provider. Then build one narrow flow: confirm
business and questions, capture real labeled answers, show mentions/citations
with evidence. Keep fixtures visibly synthetic until credentials are provided.
Do not add subscriptions or promise AI recommendations before this works.
