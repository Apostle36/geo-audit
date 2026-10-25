# Comprehensive client report

The audience is a business owner. A short executive summary must lead into a
full audit, not replace it. Preserve substantive findings, caveats, page-specific
examples and the work plan. Do not expose JSON keys, evidence IDs or checksums
in the main report. Link to readable source URLs; keep raw captures in the
separate `--technical` export and authoritative run data.

Since 1.5.1, browser capture conditions distinguish saved snapshots from met,
unverified or timed-out expected-content checks. The latest saved observation
per page/viewport is summarised, with mobile layout and blocked-resource caveats;
earlier captures stay in technical evidence. This never assigns readiness points
or authenticates page claims. Labels use captured document titles and concise
URL fallbacks while retaining query distinctions. Compact print spacing in the
method appendix reduces pagination waste without dropping findings or sources.

List the complete sampled-page inventory once in the appendix. Do not repeat it
under every observation. Full-sample observations inherit the report scope;
partial observations name only the relevant pages in natural language. Keep
unknown/omitted topics in one outstanding-work section, not repeated empty
subsections throughout the deep dives. Detailed findings must contain analysis,
not just a checklist status. The summary must not replace substantive detail.

## Required content

1. Executive summary: what was reviewed, main conclusion, first actions, limits.
2. Priorities and core score overview with clear interpretation and unknowns.
   The ten core scores are not full technical health or AI recommendation odds.
3. Five category deep dives: what works, detailed topic coverage, findings,
   affected pages, relevant sources, why it matters, fix and completion check.
4. A prioritized action plan. Give practical order; suggest owners/effort only
   when supported. Do not invent commercial terms or promise traffic/revenue.
5. Outstanding checks and scope. Missing evidence must not masquerade as a
   confirmed defect. Do not hide incomplete analysis behind a short summary.
6. Method and reviewed pages. Optional measured AI observations are a separate
   deliverable; do not imply they occurred because the audit covered readiness.

## Writing

Write findings in plain text in the run. Use complete business-facing sentences
for `observed`, `claim`, `consequence`, `fix`, `acceptance`, `confidence_reason`
and review `summary`. Translate technical terms when first needed, for example
"the sitemap (the list of pages supplied to search engines)". Retain exact
technical detail where actionable; make it understandable, not invisible.

Promote actionable issues from review summaries into `findings` with fix and
acceptance fields so they enter the prioritized plan. Do not leave a material
recommendation buried only in a topic summary. Unknown detailed topics are also
listed in outstanding work; they are not automatically proven problems.

Show page comparisons, named sources, examples or proposed corrections when
collected. Do not fabricate them merely to fill the template. Mark proposed copy
as a draft, with facts and commercial details requiring approval when needed.
Citation URLs identify live pages; the run retains what was actually captured
at the recorded time, since live pages can change.

## Export

Client exports default to a visible draft label, repeated in PDF footers. Final
exports require `--final` and a named approval of the exact run contents. Use
`delivery.py check` to list unfinished work, then `delivery.py approve` after
review. Explicit scope exclusions and warning qualifications appear in the
report. Editing run.json invalidates approval. See [the workflow guide](WORKFLOW.md)
for review, renewal and export commands. Legacy and technical exports cannot be
labelled final client reports.

```sh
python3 scripts/run_contract.py /absolute/path/run.json
python3 scripts/geo-audit-pdf.py /absolute/path/run.json /absolute/path/report.html
python3 scripts/geo-audit-pdf.py /absolute/path/run.json /absolute/path/report.pdf
python3 scripts/geo-audit-pdf.py /absolute/path/run.json /absolute/path/evidence.html --technical
python3 scripts/geo-audit-pdf.py /absolute/path/run.json /absolute/path/report-el.pdf --content-lang el
```

Default exports are comprehensive client reports, not four-page summaries.
Technical HTML preserves all criteria, IDs, hashes, validation warnings and
captured content. Technical PDF shortens each capture to its first 5,000
characters with a visible note, because raw captures of a full sample run to
hundreds of pages; the complete text stays in run.json and technical HTML. Both
validate the same run and neither invents missing work. Legacy Markdown still
requires `--legacy-markdown`; it is not upgraded to verified data.

Review actual desktop/mobile HTML and representative PDF pages. Check links,
wrapping, tables, page breaks, all findings and any long examples. A passing
unit test is not sufficient proof of visual or analytical quality. Keep prior
reports when regenerating; new evidence belongs in a new run.


## Report language

Template labels are British English. When the run's prose (summary, findings,
review summaries, rationales, limitations) is written in another language, pass
its BCP 47 tag with `--content-lang`, for example `el` or `pt-BR`. That prose is
then marked with the language so screen readers pronounce it correctly; the
labels stay `en-GB`. The option applies to client reports only.

## Presentation (since 1.3.1)

The default export now leads with a decision summary and a compact action plan.
For a typical short summary and eight actions, these occupy the first two PDF
pages; longer inputs flow to further pages without being hidden or discarded.
Full findings follow in priority order, ahead of the five category reviews.
The run schema and the immutable scoring rubric 1.2.0 are unaffected by presentation.

Action previews use the first sentence of the saved fix (up to 230 characters,
with an ellipsis when shortened) and link to the complete finding. Full stops in
common abbreviations such as "e.g." and initials such as "U.S." do not end the
sentence. Write a
concise first sentence when preparing future runs. The renderer does not use a
model to rewrite or invent audit conclusions. Full finding fields and review
summaries remain available; semantic repetition already in the input needs
editorial review, not automated deletion.

Informational and not-applicable findings are kept under context and strengths,
not counted as improvement actions. Hypotheses and unknown findings go into
verification, together with unknown and omitted detailed review topics. Topics
that genuinely do not apply are explained separately from unresolved checks.
The run has no effort or owner fields, so the report states these need scoping
rather than creating unsupported estimates. All internal navigation targets and
material finding fields are checked before export.

Scores appear with their exact criterion scope in the methodology appendix.
HTML includes an expandable explanation of the individual criterion rationales;
PDF readers are directed to HTML or the saved run for that extra explanation.
All substantive findings, category reviews and unknowns remain in the PDF.

HTML uses semantic headings, landmarks, scoped table headings, a skip link,
visible keyboard focus and a responsive action table. PDF export requests tags
and heading bookmarks and adds page numbers. These are accessibility features,
not a claim of PDF/UA or WCAG conformance; inspect reading order with assistive
technology when a certified accessible deliverable is required.

The report uses British English template labels, dates such as 19 September
2026, warm monochrome colours, and a serif fallback for display typography.
Local AboutBeige and Geist Mono fonts can be embedded at export time:

```sh
GEO_AUDIT_FONT_DIR=/absolute/path/to/fonts \
GEO_AUDIT_AUTHOR='Your name' GEO_AUDIT_DOMAIN=example.com \
python3 scripts/geo-audit-pdf.py /absolute/path/run.json /absolute/path/new-report.pdf
```

The fonts directory must contain `AboutBeige/AboutBeige-Regular.woff2`,
`AboutBeige/AboutBeige-SemiBold.woff2`, and
`GeistMono/GeistMono-Variable.woff2`. No fonts are downloaded or distributed with
the toolkit. Only supply fonts you are permitted to use. Outputs embed the local
fonts so the report remains portable. Regenerate HTML and PDF with the same
settings and preserve earlier reports for comparison.

## Action tracking and comparisons

Toolkit 1.6 adds separate owner/effort/dependency/status journals, fresh-evidence acceptance reviews, and compatible follow-up comparisons. Supply `--compare /path/previous/run.json --actions /path/previous/actions` to include the “What changed” and action-tracking sections. The same context must be supplied to delivery review and final export. Missing findings are unresolved unless a passing review binds the exact follow-up bytes. See [ACTIONS.md](ACTIONS.md) for the commands, lifecycle and local integrity limits.
