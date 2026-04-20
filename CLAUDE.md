# GEO Audit — Agent & Skill Routing

## Running an Audit

**To audit any website:**
```
/geo-audit https://example.com
```

The `/geo-audit` skill orchestrates the full audit automatically. It spawns subagents in parallel and writes `GEO-AUDIT-REPORT.md` and `GEO-AUDIT-REPORT.pdf` in the working directory.

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

The audit automatically runs `scripts/geo-audit-pdf.py` after writing the markdown report. See `scripts/README.md` for setup instructions.
