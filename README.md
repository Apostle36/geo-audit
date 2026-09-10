# GEO Audit
Version 1.1.0: an evidence-based editorial readiness assessment with optional measured AI visibility.

The five core roles assess citability, independent authority, content quality, technical eligibility, and structured data. A sixth optional role records actual AI responses. Readiness scores are not predictions of citations or empirically validated ranking metrics.

## Install
Python 3.10+ and a supported agent runtime are required. From this repository:
```bash
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt
.venv/bin/playwright install chromium
.venv/bin/python scripts/install.py /absolute/path/to/skills
```
The installer bundles instructions, agent role definitions, and scripts into geo-audit/. It backs up an existing installation. Agents can read bundled role definitions; automatic runtime registration is not assumed. Restart or reload the agent session after installation.

## Run
Invoke /geo-audit https://example.com. The skill stores each run under audits/<hostname>/<UTC timestamp>/ with a manifest, saved evidence, findings, and Markdown/PDF reports.

The collection workflow is orchestrator-driven: timeouts, robots rules, sampling, and evidence capture must be performed by the agent. The repository does not yet include an autonomous crawler or live platform-testing integration.

Helpers:
```bash
python scripts/evidence.py /absolute/path/to/saved-page.html
python scripts/score.py /absolute/path/to/criteria.json
python scripts/geo-audit-pdf.py /absolute/path/to/report.md /absolute/path/to/report.pdf
```

evidence.py inventories saved HTML and JSON-LD, including arrays and graphs. It does not establish indexing or validate all Schema.org semantics. score.py documents its JSON input in its module docstring; unknown criteria prevent complete scores. Criterion selection and anchors must be recorded before assessment.

PDF branding uses GEO_AUDIT_AUTHOR and GEO_AUDIT_DOMAIN (hostname only). Optional PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH selects a browser. PDF rendering blocks network requests and uses local fallback fonts; missing/invalid scores fail explicitly. An explicit Not assessed score is supported.

## Verification
```bash
.venv/bin/python -m unittest discover -s tests -v
```
Regression tests cover score handling, fenced headings, unsafe links, metadata escaping, JSON-LD arrays/graphs, malformed JSON, and incomplete scoring.

## Limitations and interpretation
- Actual AI visibility is unmeasured unless prompts, responses, and citations are recorded.
- llms.txt is optional; training crawler blocks do not automatically reduce search readiness.
- Missing schema alone is not Critical.
- Scope, unknowns, evidence coverage, and source links must accompany recommendations.
- Compare runs only when sample, market, language, criteria, and rubric are compatible.
- Existing reports predate this rubric and should not be treated as validated by this update.
- PDF pagination still requires visual inspection for each delivered report.

## Credits
Built by Apostolos Bolkas. Inspired by https://github.com/zubair-trabzada/geo-seo-claude.
Research context: https://arxiv.org/abs/2311.09735. Study results are not guarantees for this rubric or an individual website.
