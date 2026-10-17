# GEO Audit
Version 1.4.0: comprehensive website readiness review with readable reports and separately preserved evidence. This is a local agent-assisted toolkit, not a SaaS or live AI-visibility tracker.

The audit covers 34 detailed topics across five areas, with business-specific
guidance, page-level findings, strengths, missing checks and an action plan.
The ten scored core criteria remain on immutable rubric 1.2.0 for continuity;
they do not replace the detailed analysis or establish complete website health.
New runs use schema 1.4.0, which adds strict evidence-provenance checks to the
1.3.0 detailed review records. Existing 1.2.0 and 1.3.0 runs still validate and
render, with missing detail labelled rather than fabricated and provenance
problems reported as warnings.

The five core roles assess citability, independent authority, content quality, technical eligibility, and structured data. A sixth optional role can guide separately recorded AI observations; no live-platform collection integration exists. Readiness scores are not predictions of citations or empirically validated ranking metrics.

## Install
Python 3.10+ and a supported agent runtime are required. From this repository:
```bash
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
.venv/bin/playwright install chromium
.venv/bin/python scripts/install.py /absolute/path/to/skills
```
The installer bundles instructions, role definitions, scripts, rubric and format documentation into geo-audit/. It stages a complete package and preserves prior customisations in .backups/, keeping the five newest (`--keep-backups N` to change). Obsolete active files are removed from the new package, but remain in the backup. Atomic upgrades require Linux renameat2; unsupported systems fail without changing the prior install. Global role conflicts are reported, never overwritten. The orchestrator must explicitly read the bundled role files. Restart/reload the agent session after installing. This source update does not automatically update existing global installations.

## Run
Invoke /geo-audit https://example.com with the updated skill installed. Each run uses a unique audits/<hostname>/<UTC timestamp>/ directory. Its authoritative artifact is run.json, embedding metadata, captured evidence, findings and assessment. Reports derive from that validated data.

Collection is done by `scripts/collect.py`, a bounded, polite HTTP collector:

1. `collect.py discover` reads robots.txt (RFC 9309), expands sitemap indexes and
   lists candidate pages, with the robots decision for common search, training and
   user-triggered crawler tokens.
2. The agent chooses and justifies the sample.
3. `collect.py fetch` captures each sample page once, enforcing the method's limits:
   50 pages, 30 seconds and 5 MiB per response, 5 redirects and at least one
   second between requests to a host. It obeys robots.txt for its own `GEO-Audit`
   token, refuses private addresses and off-site redirects, and records failures
   as failed or unavailable evidence rather than dropping them.
4. `new_run.py` creates a schema 1.4.0 run.json with that evidence embedded and every
   criterion and topic marked unknown, ready for the specialist roles.

It does not run JavaScript, solve bot challenges or log in; rendering, mobile and
performance checks still need a browser or measurement tool and are recorded as
unknown until done.

Helpers:
```bash
python scripts/collect.py discover https://example.com/ /absolute/path/to/run/evidence
python scripts/collect.py fetch /absolute/path/to/run/evidence https://example.com/ https://example.com/services
python scripts/new_run.py /absolute/path/to/run/run.json --url https://example.com/ --sample https://example.com/ \
    --business-type "Services" --market "UK" --language en --sampling-rationale "Why these pages" \
    --evidence /absolute/path/to/run/evidence/fetch-evidence.json
python scripts/evidence.py /absolute/path/to/saved-page.html
python scripts/score.py /absolute/path/to/assessment.json
python scripts/run_contract.py /absolute/path/to/run.json
python scripts/geo-audit-pdf.py /absolute/path/to/run.json /absolute/path/to/report.html
python scripts/geo-audit-pdf.py /absolute/path/to/run.json /absolute/path/to/report.pdf
python scripts/geo-audit-pdf.py /absolute/path/to/run.json /absolute/path/to/evidence.html --technical
```

Read [the exact run format](docs/RUN-FORMAT.md) before producing an audit. Evidence records have checked hashes, source/time/method/status and resolvable IDs. evidence.py inventories HTML, strict JSON-LD, Microdata items and typed RDFa without establishing indexing or schema semantics; titles inside inline SVG or MathML are not mistaken for the page title. Its --record-id mode emits a captured-text record and requires --source, --collected-at and --method. Scoring uses the fixed 1.2.0 criterion set and 0/50/100 anchors; omitted checks stay unknown and N/A exclusions remain visible in coverage. All-N/A categories withhold the total. A valid run can be incomplete: inspect coverage and `warnings`, not just the exit code.

Read [full audit coverage](docs/AUDIT-DEPTH.md) and [client reporting](docs/CLIENT-REPORT.md).
Default HTML/PDF exports preserve the five deep dives, all findings, source links,
completion checks and action plan. Internal evidence codes, checksums and captured
bodies belong in the separate `--technical` export; its PDF shortens each capture
while its HTML keeps everything. Both outputs use the same validated run.
Simplifying language must not shrink the audit to a short summary. When the run's
prose is not in English, add `--content-lang` with its language tag.

Try the clearly labelled, entirely unassessed demonstration without collecting a website:
```sh
python3 scripts/run_contract.py examples/run.json
python3 scripts/geo-audit-pdf.py examples/run.json /tmp/geo-demo-report.html
```
Choose a new output path if it already exists. Explicit --overwrite permits output replacement but never input collisions. Outputs get normal file permissions from your umask. The JSON example is a template, not a completed audit.

Old criteria JSON is intentionally rejected. Old Markdown remains available through --legacy-markdown, with validated metadata and an explicit unverified-score warning. Do not relabel old scores as validated 1.2.0 results.

PDF branding uses GEO_AUDIT_AUTHOR and GEO_AUDIT_DOMAIN (hostname only). Rendering uses PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH when set, otherwise Playwright's own Chromium, and falls back to an installed system Chrome/Chromium only when that build is missing. Rendering blocks HTTP/HTTPS page resource requests and uses local fallback fonts; this is not a network-level isolation guarantee. A missing Playwright installation does not prevent --help or non-rendering validation.

## Verification
```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest tests.test_run_contract   # a single file
ruff check scripts tests
```
Regression tests cover evidence integrity, fixed scoring and omissions, run validation and provenance, the collector (against a local test server: robots rules, sitemaps, redirects, limits, private addresses and request spacing), legacy metadata, safe HTML, collisions, concurrent writes, failure cleanup and staged installation. GitHub Actions runs the suite on Python 3.10 and 3.13, the browser tests and ruff for every push and pull request.

Real browser verification additionally requires pdftotext:
```sh
GEO_RUN_RENDER_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
```
Set GEO_RENDER_ARTIFACTS to an existing writable directory to retain fixtures/PDFs in unique subdirectories for visual review. Without GEO_RUN_RENDER_TESTS, the real-browser tests are explicitly skipped, not claimed as passed.

## Limitations and interpretation
- Actual AI visibility is unmeasured unless prompts, responses, and citations are recorded.
- llms.txt is optional; training crawler blocks do not automatically reduce search readiness.
- Missing schema alone is not Critical.
- Scope, unknowns, evidence coverage, and source links must accompany recommendations.
- Compare runs only when sample, market, language, criteria, and rubric are compatible.
- Existing reports predate this rubric and should not be treated as validated by this update.
- PDF pagination still requires visual inspection for each delivered report.
- Captured content hashes prove integrity, not that a source or editorial judgment is true. Human review remains necessary.
- The rubric is a deliberately coarse sample assessment, not a universal or empirically calibrated business score. Its weights and anchor descriptions are editorial.
- The collector sees what a generic HTTP client receives, not what a verified search or AI crawler receives, and does not render JavaScript. Its private-address check cannot prevent DNS rebinding.
- There is no hardened multi-tenant browser sandbox, account system, subscription billing or production deployment in this phase.

## Credits
Built by Apostolos Bolkas. Inspired by https://github.com/zubair-trabzada/geo-seo-claude.
Research context: https://arxiv.org/abs/2311.09735. Study results are not guarantees for this rubric or an individual website.


## Changes in 1.4.0

- Evidence collection is implemented (`collect.py`) instead of being left to the agent.
- `new_run.py` creates a valid run skeleton with collected evidence embedded.
- Run schema 1.4.0 rejects findings without a capture of the pages they name,
  hypotheses or unknowns rated high or critical, duplicate affected pages,
  fragment sample URLs and "no structured data" exclusions contradicted by the
  captures. Older runs report these as warnings. Advisory warnings flag off-site
  samples, implausible capture dates and leftover placeholders.
- Comparisons ignore the order of sample URLs.
- Reports: correct singular/plural counts, `--content-lang`, abbreviation-aware
  action previews, distinguishable query-string page labels, readable file
  permissions and shortened captures in technical PDFs.
- Specialist roles have distinct descriptions and least-privilege tool lists.

### Report presentation (since 1.3.1)

Client reports lead with a decision summary and linked action plan, separate
strengths from fixes, and include missing/unknown detailed checks in verification.
Full evidence-backed findings and all five category reviews are retained. Core
scores are explained in the appendix. HTML supports keyboard navigation and
mobile reading; PDFs include page numbers, heading bookmarks and accessibility
tags. Optional local brand fonts and report preparation guidance are documented
in [the client report guide](docs/CLIENT-REPORT.md).
