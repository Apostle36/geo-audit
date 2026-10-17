# Comprehensive audit coverage

Read this with the orchestrator before a full audit. The ten immutable scored
criteria are a small comparable core, **not the audit checklist**. Complete the
detailed review for the five areas below, using the bundled role procedures.
Topic IDs live in `scripts/review_topics.py`; record their observations in the
run's `review` list (schema 1.4.0). A topic can be assessed, unknown or not applicable.
Explain unknowns and exclusions; do not label a skipped check as healthy.

## Discovery and sampling

1. Establish the business, audience, language and intended market from visible
   content. Label inferences. Ask only when an ambiguity materially changes scope.
2. Read robots and its sitemap references; expand indexes. `scripts/collect.py
   discover` does both and lists candidate pages. Select representative
   templates and priority journeys, not only the homepage. Record omitted pages
   and sample rationale. Keep utilities such as confirmations out of the scored
   public sample, but record diagnostic checks separately.
3. Capture responses once with `scripts/collect.py fetch` and share them. Its
   flags for possible soft 404s, challenges and noindex directives are prompts
   to verify. Supplement with rendered observations
   when visibility, links, navigation or interactions cannot be established from
   the response. If browser access is unavailable, record the exact unknown.
4. Inventory existing reports before comparisons. Matching names or domains alone
   do not make results comparable. Preserve original records and rubric versions.

## Business-specific focus

| Business | Pages and customer questions to include | Evidence and checks |
|---|---|---|
| Services / agency | Services, process, pricing, proof, team, contact | Deliverables, exclusions, support, named responsibility, case baselines and attribution |
| SaaS | Product, pricing, onboarding, documentation, integrations | Feature accuracy, plan limits, trials, support, supported integrations; do not create accounts without permission |
| Local business | Location, service area, hours, booking, contact | Consistent name/address/phone, relevant listings, actual location/service scope, applicable LocalBusiness properties |
| Ecommerce | Category, product, delivery, returns, trust | Price/stock parity, variants/canonicals, shipping and returns, applicable Product/Offer requirements; no checkout |
| Publisher | Article, author, category, editorial policy | Byline accountability, sourcing, dates, corrections, topic coverage and article relationships |
| Hybrid | Dominant business plus materially distinct journeys | State which checks apply to each template rather than imposing all checks everywhere |

## Five deep dives

- **Citability:** inspect representative answer passages, self-contained meaning,
  definitions, evidence, headings and tables. Compare stronger/weaker pages with
  specific excerpts and a proposed rewrite where useful. Never invent a top-five
  ranking or quote-length threshold. An optional llms.txt check is not a gate.
- **Authority:** map relevant profiles/directories, publications/bylines, reviews,
  communities/video/events and existing entity records. Preserve query/date/source
  scope, match the entity, distinguish owned, partner and independent material,
  and separate underlying client outcomes from consultant attribution.
- **Content:** check customer completeness, first-hand experience, expertise,
  sourcing, readability/headings, topical coverage and freshness. Record examples,
  measurement periods and material omissions. Do not infer AI authorship from
  writing style or demand long content where a short answer is sufficient.
- **Technical:** check responses, effective robots, sitemap/indexing intentions,
  metadata/canonicals, rendering, mobile/basic accessibility, measured performance,
  HTTPS/security and URLs/internal links. Explain when browser, Search Console,
  field data or a lab run is required; static observations do not substitute.
- **Structured information:** inventory encodings, parse, check semantics,
  entity IDs, visible parity, applicable feature requirements and page-specific
  corrections. `@id` references are not duplicate entities. Generate examples
  only from verified facts; validate JSON and label remaining placeholders.

Each role must return the detailed topics, not just two numbers. Observations
must identify the reviewed URLs, source records, result, limitation and concrete
next step when needed. Include both strengths and problems. Do not pad findings
with low-value recommendations to meet a length or count target.

## Evidence verification before delivery

- Match every material claim to the actual saved source. A valid reference or
  checksum does not establish that the source supports the interpretation.
- Check code paths only when local source is in scope: follow asset fallbacks,
  font-loading CSS and schema inputs through to the deployed response. Never
  diagnose a missing font preconnect for locally hosted fonts.
- Distinguish response errors from site absence; distinguish generic-client
  access from verified crawler access. Don't infer indexing from a 200 response.
- Verify volatile platform claims against official documentation. Report what
  was accessed and when; do not reuse old percentages or platform citation shares.
- Duplicate sources and syndicated claims are not multiple independent proofs.
- Prioritize by demonstrated consequence and scope, not an assumed ranking gain.

## What is intentionally not restored from older instructions

Automatic points for a Reddit account, three videos or Wikipedia presence;
predicted citation likelihood from an editorial score; AI-authorship detection
from prose style; universally mandatory llms.txt/speakable markup; inferred field
performance from framework tags. Restore the diagnostic subjects, not those
unsupported conclusions. Training permission is separate from search access.

## Detailed coverage versus scoring

Use `schema_version: "1.4.0"` with `review` for new comprehensive audits. Keep
`assessment.rubric_version: "1.2.0"`; never edit or silently replace that rubric.
An omitted detailed topic displays as not recorded. An unknown topic displays
as needs checking. The report must not advertise a complete audit when important
topics remain unknown. A scoped review is useful when labeled as such.

The core score is a continuity measure only. New scored criteria would need a
separate versioned rubric and an explicit migration; this repair does not invent
one or convert historical results.
