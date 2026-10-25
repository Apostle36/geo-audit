# Guided local audit workflow

Toolkit 1.5.1 provides a resumable CLI, optional browser evidence and reviewed final
exports. Run schema 1.4.0 and immutable score rubric 1.2.0 are unchanged. Existing
helper commands and historical runs remain supported.

## Start and choose pages

Use the Python environment from README.md. The directory must be new or empty:

```sh
python scripts/audit.py start /absolute/path/new-audit \
  --url https://example.com/ --business-type Services --market UK --language en --browser
python scripts/audit.py sample /absolute/path/new-audit \
  --sample https://example.com/ --sample https://example.com/services \
  --sampling-rationale 'Homepage and primary service journey.'
python scripts/audit.py resume /absolute/path/new-audit
python scripts/audit.py status /absolute/path/new-audit
```

Start discovers robots rules and sitemap pages, then pauses for selection.
If sitemaps yield no candidates, one starting page supplies up to 100 suggested
same-site navigation URLs. These destinations are not fetched. Address, robots,
scheme and port restrictions apply; assets and credential-bearing URLs are
excluded. `collect.py discover --no-navigation-fallback` retains sitemap-only
discovery. The workflow reuses the starting response if selected, including its
checked original bytes. With a captured discovery seed, include it in a
50-page sample or select at most 49 other pages to keep the distinct-page budget.
Select representative templates and customer journeys. You can supply
`--sample` (repeatable) and `--sampling-rationale` to start instead, when already
justified. Samples accept up to 50 URLs on the audited host or its www variant.
Scope freezes in sample.json; use a new audit to change it. Metadata and options
are preserved in workflow.json. `--browser` is opt-in at start; without it only
HTTP evidence is collected. `--allow-private` explicitly permits local/staging
addresses and is off by default. No logins or accounts are created.

## Resume and retry

Discovery, each HTTP page and each browser viewport have immutable attempt
directories under evidence/. result.json is published after the artifacts and
marks completion. Resume reuses completed steps, including explicit failures.
An interrupted attempt without result.json is retained and attempted again.
Successful pages are reused. A workspace lock rejects concurrent writers.
Status lists progress, retryable steps, delivery blockers and the next action.
Progress goes to stderr; final stdout is JSON.

```sh
python scripts/audit.py resume /absolute/path/new-audit --retry-failed
```

Explicit retry collects failed/unavailable steps into fresh attempts. New
evidence is appended to an existing run; earlier evidence, findings, review text
and scores are retained. References are not silently redirected to new captures.
Review conclusions after a retry. Changed runs require a new approval. Corrupt
checkpoints raise errors rather than being silently discarded.

Configured content timeouts are retryable even when the snapshot itself was
saved successfully. A status/read/resume does not automatically retry them.
Ctrl-C exits 130 with a quoted resume command and preserves completed checkpoints.

## Browser observations

Configure readiness at start when the expected document content is known:

```sh
python scripts/audit.py start /absolute/path/quotes-audit \
  --url 'https://quotes.toscrape.com/js-delayed/?delay=1500' \
  --business-type 'Public demo' --market Test --language en --browser \
  --ready-selector .quote --ready-min-count 10 --ready-timeout-ms 5000
```

`--ready-selector` is a CSS selector in the top-level document. `--ready-min-count`
defaults to 1. Only elements with visible layout boxes count; elements below the
viewport can count, and this does not establish screenshot coverage, usability
or complete page content. The timeout is 1–30000 ms and defaults to 10000 ms.
`--settle-ms` is an initial 0–5000 ms interval, default 500, before condition polling.
No clicks are performed. Conditions are immutable for this audit; choose a new
audit to change them. Workflow configuration 1.1.0 stores these settings; old
1.0.0 configurations retain the prior settling interval and unverified readiness.

The saved `content_readiness` is `met`, `unverified` or `timeout`. Without a
configured condition, content readiness is always unverified. A met condition
means only that the chosen elements were observed. On timeout, the collector
still saves the current DOM, screenshot and measurements as a successful
observation of that partial state; the separate readiness value records the
unmet condition. Standalone browser collection and workflow start/resume/status
exit 4 when a configured condition times out. Retry explicitly with
`resume --retry-failed`; earlier observations and analyst text are preserved.

Each URL gets separate desktop (1440×900) and mobile (390×844) fresh Chromium
contexts. Successful observations save rendered.html, viewport.png,
measurements.json and result.json. Measurements record navigation/paint timings
in milliseconds, horizontal overflow, headings, viewport, browser version,
blocked requests, screenshot digest and limitations. The evidence record embeds
the DOM and measurements; screenshots stay beside it. Missing browser support
is an explicit unsuccessful step, retryable after setup. Standalone use:

```sh
python scripts/browser_collect.py https://example.com/ /absolute/path/new-capture \
  --viewport mobile --id browser-mobile
```

Navigations obey robots for GEO-Audit; assets use normal browser cadence. Only
GET/HEAD HTTP(S) requests to the audited host or its www variant are allowed.
Private addresses, off-site resources, service workers, downloads, popups,
WebSockets and other request methods are blocked. Observations have a 30-second
navigation timeout, a 150-request budget and a 5 MiB DOM limit. Screenshots show
the viewport rather than an unbounded full page. External fonts/CDNs and
service-worker apps can render differently; restrictions are recorded. This is
a local tool with a DNS-rebinding limitation, not a hardened browser service.
The bounded HTTP collector resolves same-site redirects before browser navigation.
Further HTTP resource redirects are blocked before following, including those
from scripts and assets. This can leave an incomplete render and is recorded.
Requested viewport and actual layout viewport are both preserved; pages without
a mobile viewport declaration can use a wider layout.

Browser observations do not establish indexing, verified crawler access,
complete accessibility, field Core Web Vitals or INP. Mobile emulation is not
physical-device testing. There are no automatic clicks or challenge bypasses,
invented findings or assigned scores.

Client reports summarise the latest browser observation for each sampled URL and
viewport. They distinguish met content conditions from unverified/timeout states
and flag wider-than-requested mobile layouts, missing viewport declarations and
blocked resources. Older captures are never retroactively labelled verified.
Full capture history remains in the run and technical export. Page labels use
saved titles where available, shorter URL fallbacks, and distinguishable queries.

## Analyse and preview

Collection creates run.json with unknown criteria/topics. The analyst examines
captures, writes findings and applies the unchanged rubric. Resume preserves
that work. Existing agent role instructions remain applicable.

```sh
python scripts/audit.py export /absolute/path/new-audit /absolute/path/draft.html
python scripts/delivery.py check /absolute/path/new-audit/run.json
```

Client exports have a visible DRAFT label, also repeated in PDF footers.
Structural validation still accepts drafts. Delivery checking exits 4 for
outstanding work, 2 for invalid input and 0 for a reviewable scope. Checking does
not create an approval.

## Review and deliver

A named reviewer must actually inspect findings, evidence and scope:

```sh
python scripts/delivery.py approve /absolute/path/new-audit/run.json --reviewer 'Reviewer name'
python scripts/audit.py export /absolute/path/new-audit /absolute/path/final.html --final
python scripts/audit.py export /absolute/path/new-audit /absolute/path/final.pdf --final
```

Approval requires no placeholders. Every nonexcluded core and detailed check
must be assessed or legitimately N/A; detailed checks must cover the sample.
At least one substantive assessed check must remain. An all-N/A category may
still withhold the total; inventing scores is never required. Clearly labelled
hypotheses may remain as verification work. For an agreed limited scope:

```sh
python scripts/delivery.py approve /absolute/path/run.json --reviewer 'Reviewer name' \
  --exclude 'review.technical.performance=Field data access was outside the agreed scope.'
```

Keys are `core.<category>.<criterion>` and `review.<category>.<topic>`; checking
lists unfinished keys. `--acknowledge 'EXACT WARNING=reason'` records a specific
qualification for an appropriate warning. Placeholders cannot be waived. Final
reports show exclusions in readable language and include warning qualifications.
Exclusions never rewrite evidence, scoring or the report's recorded unknowns.

delivery.json records the reviewer, review time, scope, qualifications and exact
run-byte SHA-256. It is a local attestation, not authentication or proof of truth.
Any edit or reformat invalidates approval. Earlier approvals are never replaced:
create a new file with `--output /absolute/path/delivery-2.json`, then select it
with `--approval` on export, status or delivery checking. Final export fails
before writing if approval is missing, stale or invalid. `--final` applies only
to structured client reports; technical and legacy exports keep their purpose.

The original exporter also supports `--final` and `--approval`. Choose new output
paths or explicitly use `--overwrite`; run and approval aliases are protected.
