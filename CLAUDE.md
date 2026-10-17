# GEO Audit — Agent & Skill Routing

## Running an Audit

**To audit any website:**
```
/geo-audit https://example.com
```

The `/geo-audit` skill orchestrates the audit using explicitly loaded bundled roles and writes validated `run.json`, HTML and PDF in a unique run directory. It can perform roles sequentially when delegation is unavailable. Read `docs/RUN-FORMAT.md`, `docs/AUDIT-DEPTH.md` and `docs/CLIENT-REPORT.md` for toolkit 1.4.0 (versions live in `scripts/version.py`). New runs use schema 1.4.0; core scoring retains immutable rubric 1.2.0; detailed review is separate. Default reports are comprehensive and client-facing; `--technical` exports raw evidence separately.

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

## PDF Generation

The audit runs `scripts/run_contract.py run.json` before `scripts/geo-audit-pdf.py run.json report.pdf`. Resolve every entry in its `warnings`. See `README.md` for setup and limitations. Five core roles assess readiness; optional platform observations are separate and no live collection integration exists. Save evidence and reports in a unique run directory.
