# GEO Audit — Agent & Skill Routing

## Running an Audit

**To audit any website:**
```
/geo-audit https://example.com
```

The `/geo-audit` skill orchestrates the audit using explicitly loaded bundled roles and writes validated `run.json`, HTML and PDF in a unique run directory. It can perform roles sequentially when delegation is unavailable. Read `docs/RUN-FORMAT.md`, `docs/AUDIT-DEPTH.md`, `docs/CLIENT-REPORT.md`, `docs/WORKFLOW.md` and `docs/ACTIONS.md` for toolkit 1.7.0 (versions live in `scripts/version.py`). New runs use schema 1.4.0; core scoring retains immutable rubric 1.2.0; detailed review is separate. Default client exports are labelled drafts; final reports require a current named review. `--technical` exports raw evidence separately.

## Development

Run `python -m unittest discover -s tests` and `ruff check scripts tests` before committing. Keep `scripts/version.py`, the skill's `metadata.version` and the README heading in step; a test enforces it.

## Skill & Agent Map

| Component | Location | Purpose |
|---|---|---|
| `/geo-audit` skill | `.claude/skills/geo-audit/SKILL.md` | Main orchestrator — runs the full audit |
| `geo-ai-visibility` | `.claude/agents/geo-ai-visibility.md` | AI Citability analysis |
| `brand-radar` | `.claude/agents/brand-radar.md` | External Authority mapping |
| `geo-technical` | `.claude/agents/geo-technical.md` | Technical GEO infrastructure |
| `geo-content` | `.claude/agents/geo-content.md` | Content E-E-A-T quality |
| `geo-schema` | `.claude/agents/geo-schema.md` | Schema & structured data |
| `geo-platform-analysis` | `.claude/agents/geo-platform-analysis.md` | AI platform readiness |

## Collection

`scripts/collect.py discover` reads robots.txt and sitemaps; `scripts/collect.py fetch` captures the chosen sample within the method's limits; `scripts/new_run.py` creates the run skeleton with that evidence.

Use `scripts/audit.py` for guided start/sample/resume/status/export with per-page checkpoints. `--browser` at start enables desktop/mobile DOM, screenshots and local timing observations. It does not assign scores or establish field Core Web Vitals. Analysts still assess the saved run. Run `scripts/delivery.py check` and record a named approval only after reviewing the actual findings and evidence; never automatically approve on a human's behalf. Exclude unfinished checks only when an authorised scope decision supports the stated reason. Editing the run invalidates the approval. See docs/WORKFLOW.md.

## PDF Generation

The audit runs `scripts/run_contract.py run.json` before `scripts/geo-audit-pdf.py run.json report.pdf`. Resolve every entry in its `warnings`. See `README.md` for setup and limitations. Five core roles assess readiness; optional platform observations are separate and no live collection integration exists. Save evidence and reports in a unique run directory.

## Follow-up work

Use scripts/actions.py for a separate append-only action journal. Owner, estimated hours, dependencies and status never change run.json or scores. Completion means ready_to_verify; verified requires a fresh compatible follow-up and explicit named human/agent review. Declare agent reviews honestly. Use scripts/compare_runs.py or audit.py compare; absent findings remain unresolved without proof bound to the exact current bytes. --compare and --actions add client-report sections and must also be supplied when approving that final report. See docs/ACTIONS.md and ADR-002.
