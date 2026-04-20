# GEO Audit for Claude Code

A full **Generative Engine Optimization (GEO)** audit system built for [Claude Code](https://claude.ai/code). Run one command and get a scored report with actionable fixes — in markdown and PDF.

GEO is the practice of optimizing web content so AI systems (ChatGPT, Perplexity, Claude, Gemini) can discover, understand, cite, and recommend it. A [2024 study by Georgia Tech, Princeton, and IIT Delhi](https://arxiv.org/abs/2311.09735) found that sites with strong GEO signals saw 30–115% more visibility in AI-generated responses.

---

## What It Does

Run `/geo-audit https://example.com` and the system:

1. Crawls the site (sitemap, key pages, raw HTML via curl)
2. Spawns 4 specialized subagents in parallel — citability, authority, E-E-A-T, technical
3. Verifies every finding with `curl` before writing it (no hallucinated schema findings)
4. Scores across 5 weighted categories
5. Writes `GEO-AUDIT-REPORT.md` with prioritized issues and a 30-day action plan
6. Generates `GEO-AUDIT-REPORT.pdf` — selectable text, no broken page splits on tables

**Example output: [50/100 audit of Studio Enthusiasm](https://studio-enthusiasm.com)**

---

## Scoring Model

| Category | Weight | What It Measures |
|---|---|---|
| External Authority | 30% | Off-site brand presence, third-party mentions, entity signals |
| AI Citability | 25% | How quotable/extractable content is for AI systems |
| Content E-E-A-T | 20% | Experience, Expertise, Authoritativeness, Trustworthiness |
| Technical GEO | 15% | AI crawler access, llms.txt, rendering, canonicals |
| Schema & Structured Data | 10% | Schema.org markup quality and completeness |

---

## Installation

### Prerequisites

- [Claude Code](https://claude.ai/code) CLI installed
- Python 3.9+
- Playwright (for PDF generation)

### 1. Clone the repo

```bash
git clone https://github.com/Apostle36/geo-audit.git
cd geo-audit
```

### 2. Install the skill and agents into Claude Code

Copy the skill and agents to your Claude Code global config directory:

```bash
# Create directories if they don't exist
mkdir -p ~/.claude/skills/geo-audit
mkdir -p ~/.claude/agents

# Copy the skill
cp .claude/skills/geo-audit/SKILL.md ~/.claude/skills/geo-audit/SKILL.md

# Copy the agents
cp .claude/agents/*.md ~/.claude/agents/
```

### 3. Install PDF generation dependencies

```bash
pip install -r scripts/requirements.txt
playwright install chromium
```

### 4. Copy the PDF script somewhere on your PATH (optional)

The audit skill expects `scripts/geo-audit-pdf.py` to exist relative to the working directory where you run the audit. Copy it to your project or run audits from this repo's root.

---

## Usage

Open Claude Code in any directory and run:

```
/geo-audit https://example.com
```

The audit writes two files in the current directory:
- `GEO-AUDIT-REPORT.md` — full scored report with issues by severity
- `GEO-AUDIT-REPORT.pdf` — formatted PDF, same content, selectable text

### Running from this repo

```bash
cd /path/to/geo-audit
claude  # opens Claude Code
# then in Claude Code:
/geo-audit https://yoursite.com
```

---

## Report Structure

```
GEO Audit Report: [Site Name]
├── Executive Summary (overall score + breakdown table)
├── Critical Issues      — fix immediately
├── High Priority Issues — fix within 1 week
├── Medium Priority      — fix within 1 month
├── Low Priority         — optimize when possible
├── Category Deep Dives
│   ├── AI Citability    — scored content blocks, gaps, rewrite suggestions
│   ├── External Authority — platform presence map, score derivation
│   ├── Content E-E-A-T  — per-dimension breakdown
│   ├── Technical GEO    — curl-verified binary facts
│   └── Schema & Structured Data — JSON-LD templates included
├── Quick Wins (implement this week)
├── 30-Day Action Plan
└── Appendix: Pages Analyzed
```

---

## How the Evidence Rule Works

Every finding in the report cites its source with the exact extracted value. The audit uses `curl` directly for all technical checks — never WebFetch, which misses JSON-LD blocks and misreports HTTP status codes.

```bash
# Examples of verification commands the audit runs
curl -s "https://example.com/" | grep -c "application/ld+json"
curl -s -o /dev/null -w "%{http_code}" "https://example.com/llms.txt"
curl -s "https://example.com/robots.txt"
curl -s "https://example.com/" | grep -i 'rel="canonical"'
```

If a subagent finds schema missing but curl finds it present, curl wins. Claims are only written after verification.

---

## Agents

| Agent | Role |
|---|---|
| `geo-ai-visibility` | Scores content blocks for AI quotability across 5 dimensions |
| `brand-radar` | Maps brand presence on LinkedIn, directories, publications, YouTube, Reddit |
| `geo-technical` | Checks robots.txt, llms.txt, canonicals, hreflang, rendering, speed |
| `geo-content` | Evaluates E-E-A-T signals, author attribution, content depth, freshness |
| `geo-schema` | Detects and validates JSON-LD, generates missing schema templates |
| `geo-platform-analysis` | Scores readiness for Google AI Overviews, ChatGPT, Perplexity, Gemini, Bing |

---

## PDF Generation

The PDF script (`scripts/geo-audit-pdf.py`) uses Playwright's native `page.pdf()` to produce vector PDFs with:
- Selectable, copyable text
- No broken tables across page breaks (`break-inside: avoid` via `@media print`)
- Branded cover page with score and URL

Dependencies: `playwright`, `markdown`. Run `playwright install chromium` once after installing.

---

## License

MIT — use freely, attribution appreciated.

---

## Credits

Built by [Apostolos Bolkas](https://bolkas.com) — B2B marketing consultant and automation specialist.

Research basis: ["GEO: Generative Engine Optimization"](https://arxiv.org/abs/2311.09735) — Aggarwal et al., 2024 (Georgia Tech / Princeton / IIT Delhi).
