# GEO Audit — Agent & Skill Routing

## Running an Audit

**To audit any website:**
```
/geo-audit https://example.com
```

The `/geo-audit` skill orchestrates the audit using explicitly loaded bundled roles and writes validated `run.json`, HTML and PDF in a unique run directory. It can perform roles sequentially when delegation is unavailable. Read `docs/RUN-FORMAT.md`, `docs/AUDIT-DEPTH.md` and `docs/CLIENT-REPORT.md` for toolkit 1.3.0. Core scoring retains immutable rubric 1.2.0; detailed review is separate. Default reports are comprehensive and client-facing; `--technical` exports raw evidence separately.

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

## PDF Generation

The audit runs `scripts/run_contract.py run.json` before `scripts/geo-audit-pdf.py run.json report.pdf`. See `README.md` for setup and limitations. Five core roles assess readiness; optional platform observations are separate and no live collection integration exists. Save evidence and reports in a unique run directory.
