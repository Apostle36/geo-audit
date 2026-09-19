# GEO Audit
Version 1.3.1: comprehensive website readiness review with readable reports and separately preserved evidence. This is a local agent-assisted toolkit, not a SaaS or live AI-visibility tracker.

The audit covers 34 detailed topics across five areas, with business-specific
guidance, page-level findings, strengths, missing checks and an action plan.
The ten scored core criteria remain on immutable rubric 1.2.0 for continuity;
they do not replace the detailed analysis or establish complete website health.
New runs use schema 1.3.0 with detailed review records. Existing 1.2.0 runs still
render, with missing detail labeled rather than fabricated.

The five core roles assess citability, independent authority, content quality, technical eligibility, and structured data. A sixth optional role can guide separately recorded AI observations; no live-platform collection integration exists. Readiness scores are not predictions of citations or empirically validated ranking metrics.

## Install
Python 3.10+ and a supported agent runtime are required. From this repository:
```bash
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
.venv/bin/playwright install chromium
.venv/bin/python scripts/install.py /absolute/path/to/skills
```
The installer bundles instructions, role definitions, scripts, rubric and format documentation into geo-audit/. It stages a complete package and preserves prior customizations in .backups/. Obsolete active files are removed from the new package, but remain in the backup. Atomic upgrades require Linux renameat2; unsupported systems fail without changing the prior install. Global role conflicts are reported, never overwritten. The orchestrator must explicitly read the bundled role files. Restart/reload the agent session after installing. This source update does not automatically update existing global installations.

## Run
Invoke /geo-audit https://example.com with the updated skill installed. Each run uses a unique audits/<hostname>/<UTC timestamp>/ directory. Its authoritative artifact is run.json, embedding metadata, captured evidence, findings and assessment. Reports derive from that validated data.

The collection workflow is orchestrator-driven: timeouts, robots rules, sampling, and evidence capture must be performed by the agent. The repository does not yet include an autonomous crawler or live platform-testing integration.

Helpers:
```bash
python scripts/evidence.py /absolute/path/to/saved-page.html
python scripts/score.py /absolute/path/to/assessment.json
python scripts/run_contract.py /absolute/path/to/run.json
python scripts/geo-audit-pdf.py /absolute/path/to/run.json /absolute/path/to/report.html
python scripts/geo-audit-pdf.py /absolute/path/to/run.json /absolute/path/to/report.pdf
python scripts/geo-audit-pdf.py /absolute/path/to/run.json /absolute/path/to/evidence.html --technical
```

Read [the exact run format](docs/RUN-FORMAT.md) before producing an audit. Evidence records have checked hashes, source/time/method/status and resolvable IDs. evidence.py inventories HTML and strict JSON-LD without establishing indexing or schema semantics. Its --record-id mode emits a captured-text record. Scoring uses the fixed 1.2.0 criterion set and 0/50/100 anchors; omitted checks stay unknown and N/A exclusions remain visible in coverage. All-N/A categories withhold the total. A valid run can be incomplete: inspect coverage, not just the exit code.

Read [full audit coverage](docs/AUDIT-DEPTH.md) and [client reporting](docs/CLIENT-REPORT.md).
Default HTML/PDF exports preserve the five deep dives, all findings, source links,
completion checks and action plan. Internal evidence codes, checksums and captured
bodies belong in the separate `--technical` export. Both outputs use the same
validated run. Simplifying language must not shrink the audit to a short summary.

Try the clearly labeled, entirely unassessed demonstration without collecting a website:
```sh
python3 scripts/run_contract.py examples/run.json
python3 scripts/geo-audit-pdf.py examples/run.json /tmp/geo-demo-report.html
```
Choose a new output path if it already exists. Explicit --overwrite permits output replacement but never input collisions. The JSON example is a template, not a completed audit.

Old criteria JSON is intentionally rejected. Old Markdown remains available through --legacy-markdown, with validated metadata and an explicit unverified-score warning. Do not relabel old scores as validated 1.2.0 results.

PDF branding uses GEO_AUDIT_AUTHOR and GEO_AUDIT_DOMAIN (hostname only). Optional PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH selects a browser. Rendering blocks HTTP/HTTPS page resource requests and uses local fallback fonts; this is not a network-level isolation guarantee. A missing Playwright installation does not prevent --help or non-rendering validation.

## Verification
```bash
.venv/bin/python -m unittest discover -s tests -v
```
Regression tests cover evidence integrity, fixed scoring and omissions, run validation, legacy metadata, safe HTML, collisions, concurrent writes, failure cleanup and staged installation.

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
- There is no hardened multi-tenant browser sandbox, automated crawler, account system, subscription billing or production deployment in this phase.

## Credits
Built by Apostolos Bolkas. Inspired by https://github.com/zubair-trabzada/geo-seo-claude.
Research context: https://arxiv.org/abs/2311.09735. Study results are not guarantees for this rubric or an individual website.


### Report presentation 1.3.1

Client reports now lead with a decision summary and linked action plan, separate
strengths from fixes, and include missing/unknown detailed checks in verification.
Full evidence-backed findings and all five category reviews are retained. Core
scores are explained in the appendix; the 1.2.0 rubric and 1.3.0 run schema are
unchanged. HTML supports keyboard navigation and mobile reading; PDFs include
page numbers, heading bookmarks and accessibility tags. Optional local brand
fonts and report preparation guidance are documented in
[the client report guide](docs/CLIENT-REPORT.md).
