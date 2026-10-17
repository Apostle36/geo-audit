# Validated run formats 1.2.0, 1.3.0 and 1.4.0

Toolkit 1.4.0 writes new audits in **run schema 1.4.0**. Runs in schemas 1.2.0
and 1.3.0 remain accepted without modification. The **score rubric stays 1.2.0
and its pinned hash is unchanged**. A client report is the default; add
`--technical` to export raw captures and internal criteria separately.

## Schema 1.4.0: strict provenance (current)

Schema 1.4.0 has exactly the fields of 1.3.0, including the `review` list
described below. It additionally rejects these evidence-linkage problems:

- A finding that is not `unknown` must cite a successful capture of **every**
  URL in its `affected_urls` (the capture's `source` is that exact URL). An
  unknown finding may still rest on failed or partial collection.
- A `hypothesis` or `unknown` finding cannot be `critical` or `high`: those
  severities require a verified problem.
- A finding lists each affected URL once.
- Sample URLs contain no `#fragment`; a fragment never reaches the server, so
  `/` and `/#top` are the same page.
- `no_structured_data_in_sample` is refused when a cited sample capture contains
  JSON-LD, a Microdata item or a typed RDFa resource (`typeof`/`vocab`).
  Property-only RDFa such as Open Graph tags does not count.

For 1.2.0 and 1.3.0 runs the same problems are reported in `warnings` instead,
so historical runs keep validating. Every schema also receives advisory
warnings, never rejections, for:

- a sample URL outside the audited site (subdomains of the origin are fine);
- evidence collected in the future, after the audit date, or more than 180 days
  before it;
- any field still containing the `[skeleton placeholder]` text from new_run.py.

`run_contract.py` prints `{"valid": true, "warnings": [...], "scores": {...}}`.
Treat every warning as work to resolve or explain before delivery. The
technical export lists them under "Validation warnings".

## Detailed review (schemas 1.3.0 and 1.4.0)

New comprehensive audits use the required top-level `review` list. Every other
field below is unchanged, including `assessment.rubric_version: "1.2.0"`. Each
review entry has exactly:

```json
{"category":"technical","topic":"mobile","status":"unknown",
 "summary":"Mobile layout and keyboard interaction were not tested; browser access was unavailable.",
 "affected_urls":["https://example.com/"],"evidence_ids":[]}
```

Category/topic pairs must come from `scripts/review_topics.py` and be unique.
Statuses are `assessed`, `unknown`, `not_applicable`; summary must explain the
result or limitation in plain English. URLs must be a nonempty unique subset of
the sample. Assessed/N/A entries need successful evidence for each affected URL.
Unknown entries may have no evidence or failed collection evidence. Record the
actual reviewed subset, never imply sample-wide work from a one-page check.
If a topic is only partly observed, use `unknown` when that missing observation
prevents a conclusion; describe observed and unobserved subsets in the summary.
Otherwise scope an assessed record to its observed URLs and clearly state the
remaining scope. One topic's assessment is not automatically sample-wide.

Omitted topics remain visibly not recorded; unknown is not a failure and
assessed is not synonymous with healthy. Detailed review coverage is separate
from core scoring and never adds invented points. An empty review is valid but
incomplete, not a full audit. Evidence references establish integrity, not truth.
For comprehensive methodology read AUDIT-DEPTH.md and CLIENT-REPORT.md.

The exact 1.2.0 contract below is retained for existing runs. Adding `review` to
a 1.2.0 run is rejected: use 1.4.0 explicitly and preserve the original file.

The authoritative artifact is `run.json`. It embeds captured text, so evidence
cannot silently disappear when a report is moved. This is a local, manually
collected readiness workflow, not an autonomous crawler or visibility tracker.

## Commands

Run from the repository (or installed bundle):

```sh
python3 scripts/collect.py discover https://example.com/ /absolute/path/to/run/evidence
python3 scripts/collect.py fetch /absolute/path/to/run/evidence https://example.com/ https://example.com/services
python3 scripts/new_run.py /absolute/path/to/run/run.json --url https://example.com/ \
    --sample https://example.com/ --sample https://example.com/services \
    --business-type "Services / agency" --market "UK" --language en \
    --sampling-rationale "Homepage plus the main service template." \
    --evidence /absolute/path/to/run/evidence/fetch-evidence.json
python3 scripts/run_contract.py /absolute/path/to/run.json
python3 scripts/run_contract.py /absolute/path/to/new.json --compare /absolute/path/to/old.json
python3 scripts/geo-audit-pdf.py /absolute/path/to/run.json /absolute/path/to/report.html
python3 scripts/geo-audit-pdf.py /absolute/path/to/run.json /absolute/path/to/report.pdf
```

Validation exits 0 for a valid run **even if incomplete**, 2 for invalid input,
and 3 for an incompatible comparison. Inspect `scores.coverage`, category counts
and `overall`; valid does not mean fully assessed, true or ready for delivery.
The PDF requires Playwright/Chromium; Markdown is required for HTML formatting.
Use `--overwrite` only to explicitly replace an existing output. Input aliases,
hard links and symlink outputs are rejected. Concurrent non-overwrite exports
have one winner. Explicit concurrent overwrites are atomic, last writer wins.

## Exact top-level fields

- `schema_version`: `"1.4.0"` for new runs; `"1.3.0"` and `"1.2.0"` remain readable.
  Schemas 1.3.0 and 1.4.0 also require `review`.
- `metadata`: `url` (HTTP/S), `date` (YYYY-MM-DD), `business_type`, `market`,
  `language`, `sample` (1–50 unique HTTP/S page URLs, no fragments in 1.4.0),
  `sampling_rationale`.
  All text is nonempty. These are declared scope, not proof of collection.
- `assessment`: the envelope described below.
- `summary`: nonempty plain text, not Markdown or HTML.
- `limitations`: nonempty list of nonempty plain-text limitations.
- `findings`: list of finding records; can be empty when no findings are known.

Unknown fields are rejected. Pages analyzed is derived from the sample. The
displayed score is computed; a supplied `overall_score` is rejected.

## Assessment

Exact fields: `rubric_version` (`"1.2.0"`), `evidence` (record list), `criteria`
(object mapping any of the five rubric categories to criterion lists).
For scoring alone, save this envelope and run `python3 scripts/score.py file.json`.
The run validator additionally enforces evidence coverage of the declared sample.

Evidence records have exactly these fields:

```json
{
  "id": "page-1",
  "source": "https://example.com/",
  "collected_at": "2026-09-10T10:00:00Z",
  "method": "saved-http-response",
  "content": "Captured text or a collection failure diagnostic",
  "status": "success",
  "sha256": "SHA-256 hexadecimal digest of the UTF-8 content string"
}
```

This block illustrates fields, not a valid capture. Hash the exact UTF-8 content,
including whitespace. `collected_at` is an RFC 3339 timestamp with a timezone,
such as `2026-09-10T10:00:00Z` or `2026-09-10T12:00:00.5+02:00`; seconds and
fractions are optional, and parsing is the same on every supported Python. Status is `success`, `failed` or `unavailable`. For a
successful HTTP capture, include response status/headers and relevant body in
content; for an error, record the error. Source can identify a non-URL artifact.
Save original bytes separately if needed: the content hash is not a hash of
undecoded original bytes. Hashes establish integrity, not factual authenticity.

### Records written by collect.py

Each page record's `content` reads, in order: the request line and user agent,
one `Redirect:` line per hop, the final `Response:` status, `Final URL:`, every
response header (cookie values are redacted; cookie names and attributes such
as `Secure` and `HttpOnly` remain), any `Note:` lines (for example a redirect that was not
followed), a blank line, then the decoded body. Binary bodies are replaced by a
line naming their type, size and SHA-256. `source` is always the requested
sample URL, so a redirected page still covers its sample entry.

- `success`: a response was received, whatever its HTTP status. A 404 or an
  unfollowed off-site redirect is a successful observation of that response.
- `failed`: a request was attempted but produced no usable response (network
  error, timeout, or a body over the size limit).
- `unavailable`: the collector chose not to request it (disallowed by robots.txt
  for its own token, or a private address).

Robots captures use IDs such as `robots-www-example-com`; sitemap captures use
`sitemap-01` onwards. The raw body of every page is saved as
`evidence/raw/<sha256>.bin`, and `fetch-log.json` records redirects, decoding,
the robots decision for each reported crawler token and review flags
(`possible_soft_404`, `possible_challenge`, `thin_response`, `noindex_meta`,
`noindex_header`). Flags are heuristics for a reviewer, not findings.

Every assessed/N/A criterion must resolve successful evidence references for
**every sample URL**, using the exact URL as the evidence source. Additional
external-source references are allowed. If an applicable sample page is not
observed, mark the criterion unknown. A referenced page does not prove that its
content supports the criterion: a reviewer still checks relevance and truth.

## Fixed rules and coverage

Read `scripts/rubrics/1.2.0.json` before assessment. It defines stable criterion
IDs, evidence expectations, anchors, aggregation and allowed N/A reasons. Do
not edit a released rubric in place: create a new version and retain old files.
The calculator includes its rubric version and content hash in output/reports.
Archive the run and generated output together for historical reproducibility.
Legacy 1.1.0 results remain historical and cannot be validated as 1.2.0.

Assessed criterion fields:

```json
{"id":"direct_answers","status":"assessed","value":50,
 "rationale":"Identify the reviewed pages, customer questions and exceptions.",
 "evidence_ids":["page-1"]}
```

- Values must be 0, 50 or 100: none, some or all applicable reviewed sample units
  meet the stated anchor. These are coarse editorial anchors, not measured odds.
- Unknown: omit `value`, keep `rationale`, and use successful/error evidence IDs
  or `[]` when no capture exists. Omitted criteria also become unknown.
- N/A: omit `value`, add `reason`. Only schema criteria permit
  `no_structured_data_in_sample`, backed by successful sample observations.
  In schema 1.4.0 those observations must not contain structured data.
  Absence of markup is not itself a defect. No arbitrary `skip` exclusion exists.
- `coverage` is assessed / all expected criteria, including excluded criteria.
  `applicable_coverage` separately excludes allowed N/A criteria.
- Category scores are withheld if any applicable check is unknown. All-N/A
  categories have no score. Overall is withheld unless all categories have scores;
  weights are never silently redistributed. Category weights remain editorial.

## Findings and assessment mapping

Exact fields: `id`, `category`, `kind`, `status`, `affected_urls`, `evidence_ids`,
`observed`, `claim`, `consequence`, `fix`, `acceptance`, `severity`,
`confidence_reason`. All text fields are nonempty; IDs are unique. Affected URLs
must belong to the sample and, in schema 1.4.0, appear once each and be covered
by a cited capture unless the finding is unknown. Evidence references must be a
nonempty unique list.

- `kind`: observation, hypothesis, recommendation or unknown.
- `status`: present, absent, not_applicable or unknown.
- Unknown kind/status must occur together; only unknown findings may cite failed
  collection as their sole evidence. Describe a failure as unknown, never absent.
- `severity`: critical, high, medium, low or informational. In schema 1.4.0,
  hypothesis and unknown findings are medium, low or informational.

Findings explain evidence; they do not automatically award points. A reviewer
assesses the fixed rubric across the entire sample, writes the criterion
rationale, and supplies evidence references. Hypotheses and recommendations
must not be treated as direct observations supporting a score. The validator
checks structure/provenance, not whether an editorial claim is logically true.

## Legacy Markdown

Old reports are not silently promoted to validated runs. Explicit import:

```sh
python3 scripts/geo-audit-pdf.py old.md legacy.pdf --legacy-markdown
```

The header before the first `##` requires exactly one each of `**Audit Date:**`,
`**URL:**`, `**Business Type:**`, `**Pages Analyzed:**`. The document requires one
standalone `**Overall GEO Score: 50/100**` or `**Overall GEO Score: Not assessed**`
outside fenced code, plus actual body content. Conflicts and unclosed fences fail.
Metadata may appear after 20 lines. Preamble prose is preserved. Imported scores
are visibly marked unverified. Raw unsafe HTML is inert; images become alt-text
omission notes; task-list markers become checkbox characters. Review pagination.

## Limits

No live platform measurement, factual proof, causal attribution or guarantee of
indexing/citation is supplied. collect.py is a bounded single-threaded HTTP
collector: it does not run JavaScript, solve bot challenges, log in or verify
what a named crawler receives, and its private-address check cannot prevent DNS
rebinding. Sitemaps above 5 MiB (50 MiB decompressed) are not read. Matching
comparison scope is necessary, not sufficient for causal inference. Missing
inputs stay explicit. Keep captures free of secrets and personal information;
reports embed evidence content. Installed global role collisions are diagnosed,
not modified; the orchestrator must read the exact bundled role files.
