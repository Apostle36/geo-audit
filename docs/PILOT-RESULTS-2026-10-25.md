# Live pilot audits — 25 October 2026

The conventional-site pilot preserved its sampled content. The JavaScript pilot
exposed a confirmed content-readiness gap: the default browser capture completed
before delayed content appeared. Interruption recovery and checkpoint reuse
worked on both sites. The next development priority is bounded content readiness
before relying on unattended JavaScript audits.

## Sites and scope

The pilots used two live public testing sites identified by their
[operator](https://toscrape.com/), rather than local fixtures or client data:

- [Books to Scrape](https://books.toscrape.com/): catalogue homepage, travel
  category and a book-detail template. The operator identifies it as a fictional
  catalogue that does not require JavaScript.
- [Quotes to Scrape](https://quotes.toscrape.com/js/): first and second JavaScript
  pages, plus its documented delayed variant with `?delay=1500`.

These are useful live integration pilots, not evidence of readiness across all
production sites. Books' prices and ratings are explicitly fictional. No
accounts, forms, basket/checkout operations, site changes or bot bypasses were
used. Claims about indexing, real merchant reputation, quote authenticity and
AI visibility remain outside scope.

## Measured results

| Check | Conventional: Books | JavaScript: Quotes |
|---|---:|---:|
| Sample URLs | 3 | 3 |
| HTTP pages captured | 3/3 | 3/3 |
| Default browser captures completed | 6/6 | 6/6 |
| Default screenshots saved | 6/6 | 6/6 |
| Pages with expected content in both default viewports | 3/3 | 2/3 |
| Completed checkpoints preserved through interruption | 3/3 | 3/3 |
| Incomplete mobile attempt retained | Yes | Yes |
| First mobile step resumed into attempt 2 | Yes | Yes |
| Repeated resume changed run/checkpoint bytes | No | No |
| New captures on repeated resume | 0 | 0 |
| Sitemap candidates | 0 | 0 |
| Collection sequence, including interruption/recovery | 26.139 s | 23.431 s |
| Repeated resume | 0.113 s | 0.097 s |
| Initial PDF export | 1.190 s | 1.189 s |

The two collection sequences ran concurrently; their times must not be added
as elapsed time. The collection numbers exclude initial site selection, analyst
assessment, operator-source capture, report review and the later diagnostic.

The three conventional templates retained 20 homepage product cards, 11 category
cards and the selected detail's title, description, identifier, availability and
information table in raw and rendered evidence. The JavaScript responses contain
script data but no rendered quotation cards. The first two rendered pages
contain 10 cards per viewport; the delayed page contains none in its original
500 ms observations despite being recorded as successful.

A separate diagnostic at the same delayed URL used a 2200 ms settling interval.
Both desktop and mobile then contained 10 cards. Those two additional captures
took 9.435 seconds together, including preflight/navigation. Original incomplete
captures remain intact. This confirms a capture-timing limitation; it does not
show that the website lacks content, and it does not fix the default collector.

## Interruption and recovery

The retained controller launched the actual CLI unchanged. It sent SIGINT
during the first mobile capture, after discovery, the first HTTP capture and
the first desktop capture were committed. Both interrupted processes exited
with the signal. The incomplete mobile directory remained available.

Resume reused all three completed checkpoints with identical SHA-256 values and
created a second mobile attempt, then completed the remaining pages. A second
resume left run bytes and completed checkpoint hashes unchanged and created no
new attempts. This tests a real interrupted process rather than fabricated
checkpoint files. The interrupt log includes a Python traceback; clearer
interruption/resume guidance would improve operator experience.

## Review effort

Five specialist roles reviewed both saved corpora. Their reported wall-clock
windows were 50 seconds for authority, 82 for technical, 37 for schema, 42 for
citability and 28 for content. These total 239 agent-seconds and overlap within
a 208-second specialist-review window. Some include evidence waiting or contract
reading and exclude response composition; they are observations, not a clean
labor benchmark or an estimate of human review time.

The orchestrator additionally inspected all 14 saved page screenshots, integrated
68 detailed topic records, checked all material report fields against extracted
PDF text, and inspected representative report pages and mobile HTML. Human
review time was not measured and no human approval was fabricated.

Manual judgment remained necessary to select all six sample URLs, notice the
delayed empty capture, run the diagnostic, distinguish demo data from real
claims, assess the appropriate exclusions and order equal-severity actions.
This pilot therefore validates a useful assisted workflow, not an autonomous
completed audit.

## Report usefulness and checks

Both runs validate with zero warnings and no remaining skeleton placeholders.
Every one of the 34 topics per site is recorded explicitly:

| Topic disposition | Books | Quotes |
|---|---:|---:|
| Assessed | 18 | 17 |
| Not applicable to this sandbox pilot | 12 | 12 |
| Unknown with stated limitations | 4 | 5 |

The fixed rubric remains unchanged. Six of ten core criteria are assessed, two
are unknown and two are N/A in each run. Both overall scores are withheld.
These counts describe review coverage; they are not website-quality grades.
The full-sample JavaScript conclusions depend on the explicitly identified
supplemental observations, while the baseline comparison retains the 2/3 result.

The reports lead with a decision summary and action plan on pages 1–2. They
retain all findings, completion checks, confidence explanations, 68 topic
summaries and limitations. Automated text checks found no missing material
fields, placeholders or raw internal evidence IDs in the client PDFs. Both HTML
reports fit a 390 px screen without horizontal overflow. Both reject an
unapproved final export before creating a file. The exports remain labelled
drafts, consistent with their scope and unknowns.

The conventional PDF is 11 pages and the JavaScript PDF 12. They preserve the
comprehensive audit but are long for these small demonstration samples. A short
pilot comparison is useful alongside them. The JavaScript PDF's final page has
only 16 extracted words, primarily reviewed-page links and its footer; tighten
appendix pagination to avoid a nearly empty final page. Long URL-derived page
labels also wrap awkwardly in the action table.

Initial equal-severity ordering placed discovery ahead of the delayed-content
problem. The JavaScript findings were editorially reordered and re-exported
into `reports/revision-2/`. The original run and reports were retained. This
reinforces the need for reviewed prioritisation beyond severity alone.

## Improvements supported by the pilots

1. **P1 — content readiness:** expose bounded readiness/wait configuration and
   report successful navigation separately from observed main-content arrival.
   The delayed URL must produce 10 cards per viewport or an explicit unresolved
   readiness result. A global longer sleep alone is insufficient as a general
   solution.
2. **P2 — discovery fallback:** offer bounded same-site navigation candidates
   when robots/sitemap discovery returns none, retaining explicit sampling.
3. **P2 — visual coverage:** surface requested versus actual mobile layout,
   missing viewport declarations and blocked dependencies; support bounded
   main-content screenshots when navigation occupies the initial viewport.
4. **P3 — report and operator polish:** reduce appendix pagination waste, improve
   page labels and same-severity ordering, and replace interruption tracebacks
   with concise resume guidance.

Quotes requests a 390 px mobile viewport but uses a 980 px layout with no
viewport declaration; `horizontal_overflow=false` is not a mobile usability pass.
Its Google Fonts stylesheet is blocked in every default browser capture.
Books has no blocked resources, but its mobile homepage/category screenshots
show the long menu while products remain below the image in the full DOM.

No production code was changed during these pilots. Findings and supplementary
captures are preserved for the next implementation decision.

## Deliverables and reproducibility

- [Conventional report PDF](../audits/books.toscrape.com/20261025T203414Z-pilot/reports/pilot-report.pdf)
  and [HTML](../audits/books.toscrape.com/20261025T203414Z-pilot/reports/pilot-report.html).
- [JavaScript report PDF, revision 2](../audits/quotes.toscrape.com/20261025T203414Z-pilot/reports/revision-2/pilot-report.pdf)
  and [HTML](../audits/quotes.toscrape.com/20261025T203414Z-pilot/reports/revision-2/pilot-report.html).
- [Collection comparison JSON](../audits/pilots/20261025T203414Z/collection-analysis.json),
  [Books timing/interruption log](../audits/pilots/20261025T203414Z/conventional-metrics.json),
  [Quotes timing/interruption log](../audits/pilots/20261025T203414Z/javascript-metrics.json)
  and [delayed diagnostic](../audits/pilots/20261025T203414Z/delayed-diagnostic.json).

Raw responses, immutable checkpoints, screenshot digests, original collected
runs, assessed runs, role hashes, readable reports and separate technical
evidence exports remain in the two audit directories. The one-off controller,
diagnostic, analysis, integration and rendering scripts are retained in
`audits/pilots/20261025T203414Z/`. Audit artifacts are intentionally Git-ignored;
this summary is the durable repository note.
