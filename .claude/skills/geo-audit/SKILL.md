---
name: geo-audit
version: 1.0.0
author: geo-seo-claude
tags: [geo, audit, seo, ai-search, citability, eeat, schema]
description: >
  Full website GEO+SEO audit with parallel subagent delegation. Always use this
  skill when a user wants to audit a website for AI search visibility, asks
  "audit my site", "check my site for AI visibility", "how does my site perform
  on ChatGPT/Perplexity/Gemini?", "get a GEO score", "is my website optimized
  for AI search?", provides a URL and asks for a comprehensive check, or wants
  to know why their site isn't appearing in AI-generated answers. Produces a
  composite GEO Score (0-100) with prioritized action plan. Do not free-form
  a GEO audit without invoking this skill.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
  - WebFetch
  - Write
---

# GEO Audit Orchestration Skill

## Purpose

This skill performs a comprehensive Generative Engine Optimization (GEO) audit of any website. GEO is the practice of optimizing web content so that AI systems (ChatGPT, Claude, Perplexity, Gemini, etc.) can discover, understand, cite, and recommend it. This audit measures how well a site performs across all GEO dimensions and produces an actionable improvement plan.

## Key Insight

Traditional SEO optimizes for search engine rankings. GEO optimizes for AI citation and recommendation. Sites that score high on GEO metrics see 30-115% more visibility in AI-generated responses (Georgia Tech / Princeton / IIT Delhi 2024 study). The two disciplines overlap but have distinct requirements.

---

## Evidence Rule (Non-Negotiable)

Every finding in this audit **must cite its source**. Before writing any claim about a specific page, confirm you have fetched that page and extracted the exact value.

**Required evidence format per finding:**
```
Claim: [The specific assertion]
Source: [URL fetched]
Extracted value: [Exact text/tag/value found in the raw HTML]
```

**Hard prohibitions:**
- Never infer a page's meta description, H1, canonical URL, or internal links from another page or a template default.
- Never claim a value is "missing" or "duplicate" without fetching the page and extracting the actual value.
- Never extrapolate from a layout file's default props to a page that may override them.
- Never report internal links on an article page without parsing the body HTML of that specific article.
- **Never report a duplicate, missing, or conflicting schema block without counting the actual JSON-LD `<script>` tags in the raw HTML of that specific page.** A `@id` reference inside a non-Person block (e.g. `ProfilePage.mainEntity`) is not a second Person block. Count `<script type="application/ld+json">` occurrences and extract each `@type` before writing any schema finding.

**Source Code Shortcut (when codebase is available locally):**
If the audit runs inside a project directory (git repo), check for source files before fetching over HTTP. Source files are more authoritative than rendered HTML for catching config-level issues:
- Read page component files to extract `title`, `description`, H1, and canonical values.
- Read `astro.config.mjs`, `next.config.js`, `nuxt.config.ts`, or equivalent for `trailingSlash`, `baseURL`, and sitemap config.
- Compare source-defined defaults against per-page overrides — only flag a duplicate if both pages produce identical output, not if they share a fallback.

---

## Audit Workflow

### Phase 1: Discovery and Reconnaissance

**Step 1: Fetch Homepage and Detect Business Type**

1. Use WebFetch to retrieve the homepage at the provided URL.
2. Extract the following signals:
   - Page title, meta description, H1 heading
   - Navigation menu items (reveals site structure)
   - Footer content (reveals business info, location, legal pages)
   - Schema.org markup on homepage (Organization, LocalBusiness, etc.)
   - Pricing page link (SaaS indicator)
   - Product listing patterns (E-commerce indicator)
   - Blog/resource section (Publisher indicator)
   - Service pages (Agency indicator)
   - Address/phone/Google Maps embed (Local business indicator)

3. Classify the business type using these patterns:

| Business Type | Detection Signals |
|---|---|
| **SaaS** | Pricing page, "Sign up" / "Free trial" CTAs, app.domain.com subdomain, feature comparison tables, integration pages |
| **Local Business** | Physical address on homepage, Google Maps embed, "Near me" content, LocalBusiness schema, service area pages |
| **E-commerce** | Product listings, shopping cart, product schema, category pages, price displays, "Add to cart" buttons |
| **Publisher** | Blog-heavy navigation, article schema, author pages, date-based archives, RSS feeds, high content volume |
| **Agency/Services** | Case studies, portfolio, "Our Work" section, team page, client logos, service descriptions |
| **Hybrid** | Combination of above signals -- classify by dominant pattern |

**Step 2: Crawl Sitemap and Internal Links**

1. Attempt to fetch `/sitemap.xml` and `/sitemap_index.xml`.
2. If sitemap exists, extract up to 50 unique page URLs prioritized by:
   - Homepage (always include)
   - Top-level navigation pages
   - High-value pages (pricing, about, contact, key service/product pages)
   - Blog posts (sample 5-10 most recent)
   - Category/landing pages
3. If no sitemap exists, crawl internal links from the homepage:
   - Extract all `<a href>` links pointing to the same domain
   - Follow up to 2 levels deep
   - Prioritize pages linked from main navigation
4. Respect `robots.txt` directives -- do not fetch disallowed paths.
5. Enforce a maximum of 50 pages and a 30-second timeout per fetch.

**Step 3: Collect Page-Level Data**

For each page in the crawl set, **fetch that page individually** and record:
- URL, title, meta description, canonical URL — extracted from the raw HTML of **that specific page**
- H1-H6 heading structure — read from the raw HTML of **that specific page**
- Word count of main content
- Schema.org types present
- Internal/external link counts — parsed from the body HTML of **that specific page**
- Images with/without alt text
- Open Graph and Twitter Card meta tags
- Response status code
- Whether the page has structured data

**Duplicate detection:** Only flag meta descriptions or titles as duplicate after extracting the actual rendered values from each page and comparing them directly. Do not assume that pages sharing a layout template will have identical output — templates typically accept per-page overrides.

**Trailing slash / canonical verification:** Fetch the page and read the `<link rel="canonical">` tag from the raw HTML. Do not infer canonical format from the site config filename or convention.

---

### Phase 2: Parallel Subagent Delegation

Delegate analysis to 4 specialized subagents. Each subagent produces structured findings. **Subagents do not produce final scores** — scores are calculated in Phase 3 from verified inputs only.

**Subagent 1: AI Citability Analysis (geo-ai-visibility)**
- Analyze content blocks for quotability by AI systems
- Score each block on: answer quality, self-containment, readability, statistical density, uniqueness
- Return: top 10 scored blocks with per-dimension breakdown, list of gaps

**Subagent 2: External Authority Inputs (brand-radar)**
- Map brand presence across: LinkedIn, YouTube, Reddit, Wikipedia, industry directories, third-party publications
- For each platform: state whether present (yes/no) and what was found — do NOT produce a score
- Return: a factual platform presence map with specific findings per platform
- Do NOT infer presence from WebFetch — use direct platform lookups and web search

**Subagent 3: Technical GEO Infrastructure (geo-technical)**
- Analyze robots.txt for AI crawler access — distinguish between (a) crawlers actually blocked (Disallow: /), (b) wildcard Allow: / already permitting all crawlers including GPTBot/ClaudeBot/PerplexityBot, and (c) named Allow: / directives that merely duplicate the wildcard and change nothing functionally. Only flag as an issue if crawlers are genuinely blocked or if the site owner may want to distinguish inference crawlers from training crawlers (CCBot, Common Crawl) — which is a content ownership decision, not a technical fix.
- Check for llms.txt presence and quality
- Verify meta tags, headers, and technical accessibility for AI systems
- Check page speed and rendering (JS-heavy sites are harder for AI crawlers)

**Subagent 4: Content E-E-A-T Quality (geo-content)**
- Evaluate Experience, Expertise, Authoritativeness, Trustworthiness signals
- Check author bios, credentials, source citations
- Assess content freshness, depth, and originality
- Verify "About" page quality and team credentials

**Subagent 5: Schema & Structured Data (geo-schema)**
- Validate all schema.org markup
- Check for GEO-critical schema types (FAQ, HowTo, Organization, Product, Article)
- Assess schema completeness and accuracy
- Identify missing schema opportunities

---

### Phase 2.5: Evidence Verification (Mandatory Before Scoring)

**Before writing ANY finding into the report — Critical, High, Medium, or Low — verify it directly from source.** Do not rely solely on WebFetch or subagent output for any claim.

WebFetch summarizes and interprets HTML — it misses JSON-LD blocks, misreports HTTP status codes, and produces unreliable findings for technical claims. This has caused audits to report schema as missing when it was present, llms.txt as absent when it returned 200, and indexing as broken when all pages were indexed.

**Mandatory verification checks (run these yourself, not via subagent):**

```bash
# Schema presence — check raw HTML for JSON-LD blocks
curl -s "https://example.com/" | grep -c "application/ld+json"
curl -s "https://example.com/" | grep -o '"@type":"[^"]*"' | sort | uniq

# Schema duplication — count blocks and list @type per block to confirm no real duplicate
# A @id reference inside ProfilePage.mainEntity is NOT a second Person block
curl -s "https://example.com/about/" | grep -c "application/ld+json"
curl -s "https://example.com/about/" | grep -o '"@type":"[^"]*"'

# llms.txt — check HTTP status directly
curl -s -o /dev/null -w "%{http_code}" "https://example.com/llms.txt"

# robots.txt — get raw content
curl -s "https://example.com/robots.txt"

# Sitemap — verify actual URL from robots.txt, then fetch it
curl -s "https://example.com/sitemap-index.xml" | head -20

# Meta description — extract from raw HTML
curl -s "https://example.com/" | grep -i 'name="description"'

# Canonical — extract from raw HTML
curl -s "https://example.com/" | grep -i 'rel="canonical"'

# Title tag character count — measure the actual rendered value
curl -s "https://example.com/" | grep -o '<title>[^<]*</title>' | sed 's/<[^>]*>//g' | wc -c
```

**Rule:** Verify every finding with `curl` or by reading source files before including it in the report. This applies to all severity levels, not just Critical and High.

**If verification contradicts the subagent finding, trust `curl` and source files. Correct the finding before writing the report.**

---

### Follow the Code Path (Mandatory for Asset and Schema Value Claims)

When the codebase is available locally, any finding about a specific value — an image URL in schema, a font loading method, a title length, a meta description — requires tracing the full resolution logic in source files before writing the finding.

**Do not stop at the first file that looks relevant.** Components pass props through multiple layers. The value written in a content file's frontmatter may not be the value that ends up in the rendered output.

**Required steps before writing any finding about a specific value:**

1. Find where the value originates (content frontmatter, page component, layout, or shared component)
2. Trace every conditional and fallback — `?? fallback`, `existsSync(path)`, ternary expressions
3. Only write the finding if the final resolved value, after all fallbacks, confirms the problem

**Common failure modes this prevents:**

| Claim | What to actually check |
|---|---|
| "Schema image is an SVG" | Trace the image prop from content frontmatter → page component → layout → schema component, including any `existsSync` OG image fallback |
| "Font preconnect missing" | Check how fonts are loaded — npm package (`@fontsource`), CDN (`fonts.googleapis.com`), or `@font-face` in CSS. Preconnect is only needed for CDN fonts. |
| "Title tag is X characters" | Extract the actual rendered `<title>` from raw HTML with curl and measure it — do not count the default prop string from a layout file |
| "Duplicate schema block" | Count `<script type="application/ld+json">` tags in raw HTML — a `@id` reference inside another block's property is not a second block of that type |

---

### Phase 2.7: Delta Comparison (If Previous Audit Exists)

Before generating the report, check whether a `GEO-AUDIT-REPORT.md` already exists in the working directory. If it does:
- Extract the previous overall score and each category score
- Calculate delta (current minus previous) for each category
- Include a Δ column in the score breakdown table in the report
- Note the date of the previous audit

If no previous report exists, skip this step.

---

### Phase 3: Score Aggregation and Report Generation

#### Composite GEO Score Calculation

The overall GEO Score (0-100) is a weighted average of **five** category scores. Brand Authority and Platform Optimization are merged into a single External Authority category — they measure the same underlying signal (off-site presence) and splitting them artificially inflates precision.

**Weight rationale:**
- AI Citability (25%): The primary GEO signal — content that can't be extracted can't be cited, regardless of other factors
- External Authority (30%): The hardest gap to close and the most decisive factor for whether AI tools cite a source at all; weighted highest because a technically perfect site with no off-site presence will not be cited
- Content E-E-A-T (20%): Foundational trust signal; affects both AI citation likelihood and search ranking
- Technical GEO (15%): Table stakes — most sites pass the basics; issues here are fixable quickly
- Schema & Structured Data (10%): High leverage per hour of effort but not a primary citation driver on its own

| Category | Weight | What It Measures | Score Confidence |
|---|---|---|---|
| **AI Citability** | 25% | How quotable/extractable content is for AI systems | Medium — structured rubric, subjective judgment |
| **External Authority** | 30% | Off-site brand presence, third-party mentions, entity signals | Medium — platform lookups, hard to fully enumerate |
| **Content E-E-A-T** | 20% | Experience, Expertise, Authoritativeness, Trustworthiness | Medium — structured rubric, subjective judgment |
| **Technical GEO** | 15% | AI crawler access, llms.txt, rendering, speed | High — curl-verified binary facts |
| **Schema & Structured Data** | 10% | Schema.org markup quality and completeness | High — curl-verified binary facts |

**Formula:**
```
GEO_Score = (Citability * 0.25) + (ExternalAuthority * 0.30) + (EEAT * 0.20) + (Technical * 0.15) + (Schema * 0.10)
```

**External Authority score derivation (do not let brand-radar self-score):**
Calculate from the platform presence map using this rubric:

| Signal | Points |
|---|---|
| Active LinkedIn profile with content | 10 |
| Listed in ≥1 industry directory (Clutch, TechBehemoths, G2, etc.) | 15 |
| ≥1 third-party publication mention or byline | 20 |
| YouTube channel with ≥3 videos | 10 |
| Active Reddit presence or mentions | 10 |
| Wikipedia or Wikidata entry (only if legitimately notable) | 15 |
| ≥3 verified client reviews on third-party platforms | 10 |
| Podcast appearance or press coverage | 10 |

Max: 100. Score what is verified present. Do not add points for signals that were not confirmed.

#### Score Interpretation

| Score Range | Rating | Interpretation |
|---|---|---|
| 90-100 | Excellent | Top-tier GEO optimization; site is highly likely to be cited by AI |
| 75-89 | Good | Strong GEO foundation with room for improvement |
| 60-74 | Fair | Moderate GEO presence; significant optimization opportunities exist |
| 40-59 | Poor | Weak GEO signals; AI systems may struggle to cite or recommend |
| 0-39 | Critical | Minimal GEO optimization; site is largely invisible to AI systems |

---

## Issue Severity Classification

Every issue found during the audit is classified by severity:

### Critical (Fix Immediately)
- All AI crawlers blocked in robots.txt
- No indexable content (JavaScript-rendered only with no SSR)
- Domain-level noindex directive
- Site returns 5xx errors on key pages
- Complete absence of any structured data
- Brand not recognized as an entity by any AI system

### High (Fix Within 1 Week)
- Key AI crawlers (GPTBot, ClaudeBot, PerplexityBot) explicitly blocked via Disallow: /
- No llms.txt file present
- Zero question-answering content blocks on key pages
- Missing Organization or LocalBusiness schema
- No author attribution on content pages
- All content behind login/paywall with no preview

### Medium (Fix Within 1 Month)
- Partial AI crawler blocking (some allowed, some blocked)
- llms.txt exists but is incomplete or malformed
- Content blocks average under 50 citability score
- Missing FAQ schema on pages with FAQ content
- Thin author bios without credentials
- No third-party directory listings or external mentions

### Low (Optimize When Possible)
- Minor schema validation errors
- Some images missing alt text
- Content freshness issues on non-critical pages
- Missing Open Graph tags
- Suboptimal heading hierarchy on some pages
- LinkedIn company page exists but is incomplete

---

## Output Format

Generate a file called `GEO-AUDIT-REPORT.md` with the following structure:

```markdown
# GEO Audit Report: [Site Name]

**Audit Date:** [Date]
**URL:** [URL]
**Business Type:** [Detected Type]
**Pages Analyzed:** [Count]

---

## Executive Summary

**Overall GEO Score: [X]/100 ([Rating])**

[2-3 sentence summary of the site's GEO health, biggest strengths, and most critical gaps.]

### Score Breakdown

| Category | Score | Δ vs Last Audit | Confidence | Weight | Weighted Score |
|---|---|---|---|---|---|
| AI Citability | [X]/100 | [+X / -X / —] | Medium | 25% | [X] |
| External Authority | [X]/100 | [+X / -X / —] | Medium | 30% | [X] |
| Content E-E-A-T | [X]/100 | [+X / -X / —] | Medium | 20% | [X] |
| Technical GEO | [X]/100 | [+X / -X / —] | High | 15% | [X] |
| Schema & Structured Data | [X]/100 | [+X / -X / —] | High | 10% | [X] |
| **Overall GEO Score** | | | | | **[X]/100** |

_Previous audit: [date] — [X]/100. If no previous audit, show — in Δ column._

---

## Critical Issues (Fix Immediately)

[List each critical issue with specific page URLs and recommended fix]

## High Priority Issues

[List each high-priority issue with details]

## Medium Priority Issues

[List each medium-priority issue]

## Low Priority Issues

[List each low-priority issue]

---

## Category Deep Dives

### AI Citability ([X]/100) — Confidence: Medium
[Detailed findings, top scoring blocks, gaps, rewrite suggestions]

### External Authority ([X]/100) — Confidence: Medium
[Platform presence map per platform (LinkedIn / YouTube / Reddit / directories / press), score derivation showing which signals were present and points awarded]

### Content E-E-A-T ([X]/100) — Confidence: Medium
[Author quality, source citations, freshness, depth, per-dimension breakdown]

### Technical GEO ([X]/100) — Confidence: High
[Crawler access, llms.txt, rendering, headers — all curl-verified]

### Schema & Structured Data ([X]/100) — Confidence: High
[Schema types found per page (curl-verified), validation results, missing opportunities]

---

## Quick Wins (Implement This Week)

1. [Specific, actionable quick win with expected impact]
2. [Another quick win]
3. [Another quick win]
4. [Another quick win]
5. [Another quick win]

## 30-Day Action Plan

### Week 1: [Theme]
- [ ] Action item 1
- [ ] Action item 2

### Week 2: [Theme]
- [ ] Action item 1
- [ ] Action item 2

### Week 3: [Theme]
- [ ] Action item 1
- [ ] Action item 2

### Week 4: [Theme]
- [ ] Action item 1
- [ ] Action item 2

---

## Appendix: Pages Analyzed

| URL | Title | GEO Issues |
|---|---|---|
| [url] | [title] | [issue count] |
```

---

## Phase 4: PDF Generation (run after writing GEO-AUDIT-REPORT.md)

After saving `GEO-AUDIT-REPORT.md`, generate a branded PDF automatically:

```bash
python3 scripts/geo-audit-pdf.py GEO-AUDIT-REPORT.md
```

This produces `GEO-AUDIT-REPORT.pdf` alongside the markdown file — an A4 report with a cover page, running header, score display, and footer on every page. Branding can be customized via `GEO_AUDIT_AUTHOR` and `GEO_AUDIT_DOMAIN` environment variables.

**If the script is not found**, it lives at `marketing-team/scripts/geo-audit-pdf.py`. Run from the `marketing-team/` directory.

**Dependencies** (install once if missing):
```bash
pip install playwright pillow && playwright install chromium
```

The PDF is a client-deliverable version of the report. Do not modify it manually — always regenerate from the markdown source.

---

## Quality Gates

- **Page Limit:** Never crawl more than 50 pages per audit. Prioritize high-value pages.
- **Timeout:** 30-second maximum per page fetch. Skip pages that exceed this.
- **Robots.txt:** Always check and respect robots.txt before crawling. Note any AI-specific directives.
- **Rate Limiting:** Wait at least 1 second between page fetches to avoid overloading the server.
- **Error Handling:** Log failed fetches but continue the audit. Report fetch failures in the appendix.
- **Content Type:** Only analyze HTML pages. Skip PDFs, images, and other binary content.
- **Deduplication:** Canonicalize URLs before crawling. Skip duplicate content (e.g., HTTP vs HTTPS, www vs non-www, trailing slashes).

---

## Business-Type-Specific Audit Adjustments

### SaaS Sites
- Extra weight on: Feature comparison tables (high citability), integration pages, documentation quality
- Check for: API documentation structure, changelog pages, knowledge base organization
- Key schema: SoftwareApplication, FAQPage, HowTo

### Local Businesses
- Extra weight on: NAP consistency, Google Business Profile signals, local schema
- Check for: Service area pages, location-specific content, review markup
- Key schema: LocalBusiness, GeoCoordinates, OpeningHoursSpecification

### E-commerce Sites
- Extra weight on: Product descriptions (citability), comparison content, buying guides
- Check for: Product schema completeness, review aggregation, FAQ sections on product pages
- Key schema: Product, AggregateRating, Offer, BreadcrumbList

### Publishers
- Extra weight on: Article quality, author credentials, source citation practices
- Check for: Article schema, author pages, publication date freshness, original research
- Key schema: Article, NewsArticle, Person (author), ClaimReview

### Agency/Services
- Extra weight on: Case studies (citability), expertise demonstration, thought leadership
- Check for: Portfolio schema, team credentials, industry-specific expertise signals
- Key schema: Organization, Service, Person (team), Review
