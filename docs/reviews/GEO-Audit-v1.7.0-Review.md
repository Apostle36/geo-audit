# GEO Audit v1.7.0 — product audit, repairs and continuation record

**Date:** 31 October 2026
**Baseline:** `main` at `bc4f0b5e4398ba0a67e86071f8fae47c1cb9df27`, toolkit 1.6.0, clean working tree.
**Work branch:** `feat/v1.7-trust-repairs` (local; not pushed, merged or deployed).
**Scope:** code, skill and role instructions, tests, docs, ADRs, the v1.1 review, pilot and acceptance notes,
saved local audits, real local runs of the CLI and browser capture. No customer contact, paid services, account
creation or production deployment. Market and commercial analysis is kept outside this public repository.

## Verdict

GEO Audit is a dependable **assisted** audit toolkit for a careful expert operator. It is not yet a product that
an unattended analyst or a paying self-service customer can trust without supervision. Its evidence model, fixed
rubric, delivery gate and follow-up verification are stronger than anything I found published by comparable
tools. Two defects undermined that trust and are now repaired:

1. **A bot challenge or error page could silently support a "reviewed" report.** A run where two of three
   sampled pages returned HTTP 403 (bot challenge) and HTTP 404 validated with zero warnings, scored 100/100,
   passed the delivery check, received a named approval and exported a final report that never mentioned either
   failure. Collection records the response as a success, and the challenge flag lived only in a checkpoint log.
2. **One page could hang an audit indefinitely.** A page whose JavaScript blocks the main thread made browser
   capture wait forever in `page.content()`, holding the workspace lock. Playwright has no timeout for DOM reads.

Both are fixed with regression tests. Run schema 1.4.0, rubric 1.2.0, workflow configuration 1.1.0 and approval
formats are unchanged.

## Baseline (before changes)

| Check | Command | Result |
|---|---|---|
| Unit suite, Python 3.14.4 | `python -m unittest discover -s tests -v` | 233 passed, 15 skipped (render) |
| Real browser + PDF, Python 3.14.4 | `GEO_RUN_RENDER_TESTS=1 python -m unittest discover -s tests` | 233 passed, 0 skipped, 54 s |
| Unit suite, Python 3.10.20 | same | 233 passed, 15 skipped |
| Lint | `ruff check scripts tests` (ruff 0.16.8) | passed |
| Whitespace | `git diff --check` | passed |
| Dependency advisories | `pip-audit -r scripts/requirements.txt` | no known vulnerabilities (Python packages only) |

Environment: isolated `uv` virtual environments in the session scratchpad; Playwright 1.58.0 with its Chromium
145.0.7632.6 headless shell; Markdown 3.10.2; pdftotext 26.01.0; Linux. macOS and Windows were not tested.

## What exists

| Stage | Implementation | Deterministic or judgement |
|---|---|---|
| Install | `install.py` stages a package, atomically swaps it (Linux `renameat2`), keeps backups | Deterministic |
| Discovery | `collect.py discover`: robots.txt (RFC 9309), sitemaps, navigation fallback | Deterministic |
| Sampling | `audit.py sample` freezes ≤50 URLs plus a rationale | **Human/agent judgement** |
| HTTP capture | `collect.py fetch`: bounded, robots-aware, private addresses refused, raw bytes hashed | Deterministic |
| Browser capture | `browser_collect.py`: desktop/mobile DOM, viewport screenshot, lab timings, same-site requests only | Deterministic |
| Workflow | `audit.py` start/sample/resume/status/export, immutable attempt checkpoints, file lock | Deterministic |
| Assessment | Five role instructions (`.claude/agents/`), 34 topics, 10 scored criteria | **Agent/human judgement** |
| Validation | `run_contract.py`: structure, provenance, coverage, warnings | Deterministic |
| Scoring | `score.py`: rubric 1.2.0, hash-pinned, 0/50/100 anchors, totals withheld when incomplete | Deterministic |
| Delivery | `delivery.py`: blockers, named approval bound to exact bytes, exclusions, acknowledgements | **Named human attestation** |
| Reports | `geo-audit-pdf.py`, `client_report.py`: draft/final HTML/PDF, separate technical export | Deterministic |
| Follow-up | `actions.py` journal, `compare_runs.py` conservative comparison | Deterministic + **named review** |

Documented but not implemented: live AI-answer observation (sidecar guidance only), hosted service, accounts,
billing, multi-tenant isolation. Intentionally out of scope: logins, form submission, challenge bypass.

## Findings register

Priority: P0 critical exposure, P1 major trust/integrity/core-workflow failure, P2 material improvement, P3 polish.
Effort is listed separately from severity.

### GA-01 — P1 — Degraded captures could support approved conclusions without any warning

- **Classification:** confirmed bug (validity). **Status:** fixed.
- **Evidence:** local fixture site with `/` (200), `/services` (403 "Just a moment…", `possible_challenge` in
  `fetch-log.json`), `/gone` (404). After `audit.py start/sample/resume`, all criteria assessed at 100 citing the
  three captures. `run_contract.py` → `overall 100.0, warnings []`; `delivery.py check` → exit 0, reviewable;
  `delivery.py approve` → ready; `audit.py export --final` → report contains no "403", "404" or "challenge".
- **Cause:** a received response is `success` whatever its status; review flags never reached `run.json`
  validation or reports; validation checks references, not whether the cited capture shows the page.
- **Consequence:** an analyst or agent can deliver confident conclusions about pages it never saw. Affects every
  audit of a site with bot protection, errors, soft 404s or JavaScript-only content.
- **Repair:** `scripts/capture_quality.py` derives prompts from the collectors' own records (error response,
  unfollowed redirect, possible challenge or soft 404, non-HTML body, unmet content check, little visible text
  in the response or render, noindex). Validation adds one advisory warning per sampled page whose recorded
  conclusions cite *only* prompted captures. Thin-text prompts are ignored for header-level checks; the
  response-status topic is exempt; unknown conclusions are never flagged; `search_directives` scored 100 with
  a cited noindex is flagged. Existing delivery rules then require resolution or a named acknowledgement, which
  the final report prints. Effort: ~1 day.
- **Verification:** the same reproduction now yields two warnings and `delivery check` exit 4 until acknowledged.
  `tests/test_capture_quality.py` (15 tests) uses real `collect.py` records from a local server. Corpus check of
  all 11 saved local runs: no new warnings on the Books pilot, Plausible acceptance runs, the bolkas.com audit or
  the example; three on the Quotes JavaScript pilot, where authority/content conclusions cite only raw HTML that
  lacks the rendered quotes. That is a defensible prompt, not a false alarm.
- **Remaining uncertainty:** prompts are heuristics. A challenge served with normal-looking content, or a
  plausible but wrong judgement from a good capture, is not detected. Semantic truth still needs human review.

### GA-02 — P1 — Browser capture could hang forever

- **Classification:** confirmed bug (reliability). **Status:** fixed.
- **Evidence:** page `<script>setTimeout(()=>{while(true){}},300)</script>`; `browser_collect.capture` did not
  return within 150 s (killed by `timeout`). Step-through showed `wait_for_function` times out correctly at 3 s,
  then `page.content()` never returns.
- **Consequence:** an unattended `resume` holds the workspace lock indefinitely; a retry hangs again. A hostile
  page can stall the toolkit. For a hosted service this would be a denial-of-service vector.
- **Repair:** `capture_isolated()` runs each observation as a worker in its own process group with a 180 s hard
  deadline. On timeout or interrupt, the whole group (worker, Playwright driver, Chromium) is killed and a
  `failed`, retryable observation is saved. Request spacing is preserved across the process boundary. The CLI
  uses the worker by default (`--in-process` opts out). Effort: ~0.5 day.
- **Verification:** real-Chromium test with the busy page returns a failed observation at the deadline; unit tests
  prove a grandchild process is killed and a crashed worker becomes an explicit failure. Live Ctrl-C during a
  hung capture: exit 130, resume hint, attempt kept without `result.json`, no Chromium processes left.
- **Cost:** about +1.1 s and one extra robots.txt request per observation (measured: median 2.05 s vs 0.95 s
  per local capture). Follow-up: pass the parent's robots decision to the worker.

### GA-03 — P2 — Non-ASCII page paths failed collection

- **Classification:** confirmed bug. **Status:** fixed.
- **Evidence:** `fetch` of `http://host/услуги` → `failed: UnicodeEncodeError: ordinal not in range(128)`; the
  browser preflight used the same client, so rendered capture failed too. Raw UTF-8 `Location` headers were
  decoded as Latin-1. Relevant for Bulgarian, Greek and other non-Latin sites. IDN hostnames already worked.
- **Repair:** `request_uri()` percent-encodes non-ASCII characters, spaces and control characters on the
  request line as UTF-8, as browsers do; evidence keeps the URL as supplied. `Location` bytes are percent-encoded.
- **Verification:** `InternationalAndAddressBoundaries` tests (Cyrillic path, raw UTF-8 redirect, robots match);
  demo audit captured `/услуги` with HTTP 200 in HTTP, desktop and mobile.

### GA-04 — P2 — Warnings containing `=` could not be acknowledged

- **Classification:** confirmed bug (exposed by URL-bearing warnings). **Status:** fixed.
- **Evidence:** `delivery.py approve --acknowledge 'WARNING=reason'` split on the first `=`, so any warning
  naming a URL with a query (`?view=all`, `?delay=1500`) could never be acknowledged from the CLI.
- **Repair/verification:** split after the longest known warning text; CLI test with `?view=all`.

### GA-05 — P2 — Error and challenge pages mislabelled the requested page

- **Classification:** confirmed bug (report). **Status:** fixed.
- **Evidence:** labels come from captured titles, so the challenged services page appeared as "Just a moment…"
  and a 404 page as "Missing" throughout the report and action table.
- **Repair/verification:** pages whose latest HTTP capture has a failure prompt use the URL-derived label; test
  asserts `services (?view=all)` and no "Just a moment".

### GA-06 — P3 — Mobile table captions and raw review timestamp

Captions of the action table (and the new table) were squeezed to ~50–90 px at 390 px width; the final-report
byline printed a raw ISO timestamp. Both fixed; verified at 390 px and 1280 px (no horizontal overflow).

### GA-07 — P3 — NAT64 addresses of private hosts were accepted

`[64:ff9b::a9fe:a9fe]` (169.254.169.254 via the well-known NAT64 prefix) passed the private-address check on
Python 3.10 and 3.14. Embedded IPv4 is now checked; the local-use prefix is refused. Other forms tested
(decimal, hex, IPv4-mapped, 6to4, link-local, CGNAT, `0`) were already refused. **Fixed** for the local tool;
DNS rebinding remains (GA-09).

### GA-08 — P2 — Off-site assets make CDN-dependent pages look empty

- **Classification:** confirmed limitation. **Status:** now visible, not solved.
- **Evidence:** page whose content is injected by a script on another host: capture `success`, readiness
  `unverified`, headings `[]`, one blocked request. Only the site and its `www` twin are allowed, so
  `cdn.`/`static.` subdomains and third-party CDNs are blocked.
- **Now:** `thin_render` prompts appear in status, validation and the report.
- **Proposed repair:** an explicit, recorded resource-host allowlist at audit start (GET/HEAD only, public
  addresses only, never navigations), stored in a new workflow configuration version and shown in reports.
  Effort 1–2 days. Acceptance: a CDN-rendered fixture renders when its host is allowed, and blocked/allowed hosts
  are listed per capture.

### GA-09 — P1 for hosting, P3 locally — No network-level egress boundary

The address check resolves DNS separately from the connection (rebinding window). Browser subresources are
checked in Python and fetched by Playwright's Node side. Non-HTTP channels such as WebRTC are not covered by
request routing (untested hypothesis). Acceptable for an operator auditing public sites on their own machine.
**Hosted release blocker:** per-job network namespace or container with an egress proxy that resolves once,
pins the address and enforces the public-address rule; no metadata endpoint reachability; CPU/memory limits.

### GA-10 — P2 — Browser engine age

Playwright is pinned at 1.58.0 (Chromium 145, January 2026); 1.64.1 (Chromium 156) was released on 22 October
2026. The browser runs untrusted site JavaScript. `pip-audit` does not cover the bundled browser, and I did not
map specific Chromium CVEs. Recommendation: upgrade, re-run the render suite (1.64 changes hidden-iframe
visibility), and adopt a monthly update check.

### GA-11 — P2 — Platform support was undocumented

`audit.py`, `actions.py` and `install.py` import `fcntl` at module level, so Windows fails with an import
traceback. macOS lacks `renameat2`: a fresh install works, upgrades are refused without damage. Now documented in
the README; untested on both platforms. Proposed: clear startup message on Windows; `renamex_np(RENAME_SWAP)` on
macOS once a Mac test run is possible.

### GA-12 — P2 — Reworded follow-up findings can read as "resolved + new"

Finding identity is exact (category, normalised claim, page set). If a follow-up rewords a persisting issue under
a new ID, a passing review is not blocked and the comparison can show the old item resolved and a "new" one.
Proposed: flag candidate matches (same category and overlapping pages, different wording) and require explicit
reconciliation before a passing review or a "resolved" label. Effort 1–2 days.

### GA-13 — P2 — Licensing position

No `LICENSE` file; GitHub reports no licence. Public visibility alone grants no reuse rights, so the project is
currently "all rights reserved", not open source. Provenance: the initial commit (`418e719`, April 2026) added
role files 84–99% line-similar, and a skill 65% similar, to the MIT-licensed `zubair-trabzada/geo-seo-claude`.
The current files share 2–3% (0–1 long lines). Git history therefore contains MIT-derived material without the
upstream notice. This is not legal advice. **Decision needed** (see below).

### GA-14 — P3 — Prompt-injection surface

Roles are least-privilege and instructed to treat content as data. Residual risks: `brand-radar` has WebFetch, so
injected text could steer requests that carry audit data in URLs; Bash-enabled roles rely on instructions not to
execute captured content. Proposed: keep network tools out of evidence-reading roles, or have the orchestrator
mediate fetches against an allowlist.

### GA-15 — P3 — Methodology observations (no change made)

- Any site without structured data gets both schema criteria N/A, which withholds the overall score by design.
  This is honest but means the headline number is usually absent. Any change needs rubric 1.3.0 with explicit
  migration and comparison rules; 1.2.0 must stay immutable.
- Category weights remain editorial; the README states this. No sensitivity or inter-assessor consistency study
  exists; I did not run repeated agent assessments of a fixed corpus (requires model credits and a protocol).
- Report length: 10 pages for a 5-page demo, 11–13 pages for 3-page pilots. A one-page decision brief is a
  product gap.

## Historical reconciliation

| Item | Then | Now | How verified |
|---|---|---|---|
| v1.1 F01 fabricated evidence IDs | P1 | Fixed | Re-reproduced: all three cases rejected |
| F02 omitted criteria inflate scores | P1 | Fixed | Re-reproduced: overall withheld; `skip` N/A rejected |
| F03 output overwrites input | P1 | Fixed | Re-reproduced: same path and hard link both exit 2, input unchanged |
| F04 table clipping | P1 | Fixed | Render tests; demo PDF/HTML inspected with long labels |
| F05 Markdown fidelity, F06 preamble loss, F07 conflicting scores | P1/P2 | Fixed for legacy import | Regression tests pass (not re-reproduced by hand) |
| F08 malformed attributes crash | P2 | Fixed | Re-reproduced: all three complete |
| F09 duplicate titles, NaN | P2 | Fixed | Re-reproduced: titles kept separately, 2 errors |
| F10 non-atomic install | P2 | Fixed on Linux | Fresh install, upgrade with backup, reinstall from bundle |
| F11 stale global roles | P2 | Partially fixed | Collisions diagnosed; runtime role selection still instruction-based, unverified |
| F12 no end-to-end contract | P2 | Largely fixed | `run_contract.py`, schema 1.4.0, delivery gate; GA-01 was a remaining gap |
| Pilot P1 content readiness | P1 | Fixed (1.5.1) | Real-render tests run in this session |
| Pilot P2 discovery fallback | P2 | Fixed (1.5.1) | Tests |
| Pilot P3 visual coverage | P2 | Partially fixed | Layout/blocked-resource caveats exist; main-content screenshots not implemented |
| Pilot P4 operator polish | P3 | Fixed | Ctrl-C message verified live |

## Changes in this branch

| File | Change |
|---|---|
| `scripts/capture_quality.py` (new) | Capture prompts, conclusion warnings, per-page summary, review prompts |
| `scripts/run_contract.py` | Adds capture warnings to advisory warnings (all schemas) |
| `scripts/browser_collect.py` | Isolated worker with hard deadline; `--in-process` |
| `scripts/collect.py` | `request_uri`, UTF-8 `Location` handling, NAT64 check, `Client.pause` |
| `scripts/audit.py` | Status `pages` and `pages_needing_review`; uses isolated capture |
| `scripts/client_report.py` | "How each page was captured", summary line, safe labels, caption and date fixes |
| `scripts/delivery.py` | Acknowledgements containing `=` |
| `scripts/actions.py` | `capture_prompts` in review output |
| `scripts/install.py`, `scripts/version.py` | New module required; toolkit 1.7.0 |
| Tests | New `test_capture_quality.py`; additions to collector, browser, action, install tests |
| Docs | README, CLAUDE.md, SKILL.md, RUN-FORMAT, WORKFLOW, CLIENT-REPORT, ACTIONS |

**Compatibility:** all 11 saved local runs still validate. Approvals of runs that now raise a capture warning must
be renewed with an acknowledgement; no saved approvals were affected locally.

## Verification after changes

| Check | Result |
|---|---|
| `GEO_RUN_RENDER_TESTS=1 python -m unittest discover -s tests` (3.14.4) | 257 passed, 0 skipped, 85 s (was 54 s; worker start-up and a 12 s deadline test) |
| `python -m unittest discover -s tests` (3.10.20) | 257 passed, 17 skipped (render) |
| `ruff check scripts tests` | passed |
| `git diff --check` | passed |
| Live demo audit (local fixtures, browser on) | 5 pages incl. Cyrillic path, 403 challenge, CDN-dependent shell, 404; status, approval with acknowledgements, final HTML/PDF |
| Visual inspection | PDF pages 1 and 8; HTML at 390 px (no overflow, stacked table) and 1280 px |
| Resource use (demo, 5 pages × HTTP + 2 viewports + exports) | 38.6 s wall, 9.3 CPU-s, 122 MB peak RSS; ~2.7 KB per screenshot (fixtures) |
| Real audit storage (bolkas.com, 13 pages, 27 browser captures) | 63 MB directory, 13.8 MB `run.json` |

## Acceptance matrix

| Area | Evidence | Status |
|---|---|---|
| Installation | Linux fresh/upgrade/bundle reinstall; backups keep customisations | Pass on Linux; macOS/Windows untested (documented) |
| Collection | Static, delayed-JS, timeout, blocked-asset fixtures; prompts for incomplete content | Pass |
| Network safety | Address-form tests incl. NAT64; redirect scope tests | Pass locally; hosted boundary not built (GA-09) |
| Recovery | Checkpoint/interrupt tests; live Ctrl-C during hung capture; deadline kill test | Pass |
| Validity | Fabricated refs, omitted criteria and degraded-capture conclusions caught | Pass for structure and capture quality; semantic truth unverified |
| Follow-up | Absence never resolves; stale approvals fail; prompts shown on resolved items | Pass; reworded findings gap (GA-12) |
| Rendering | Real HTML/PDF with Cyrillic, long URLs, many states | Pass (representative pages inspected) |
| Compatibility | 11 historical runs; schema/rubric/workflow/approval versions unchanged | Pass |
| UX | Status page summary; report section; links; mobile layout | Pass for automated checks; no WCAG audit or user test |
| Cost/operations | Measured demo and real-audit numbers above | Measured on fixtures; real sites heavier |

## Readiness by stage

| Stage | Passed | Blockers | Evidence still needed |
|---|---|---|---|
| Internal professional use (you operate it) | All gates above | None | Upgrade Playwright (GA-10) |
| Paid assisted pilot (you deliver reviewed audits) | Same | Licence/attribution decision (GA-13); written data-handling note for clients | One real B2B audit with measured review hours |
| Public self-service service | None of the hosting gates | GA-09 isolation, auth, tenancy, quotas, queue, storage/deletion, secrets, abuse prevention, privacy and legal review, billing | Demand evidence first |

## Remaining work, ranked

1. GA-10 Playwright/Chromium upgrade and update policy (0.5 day).
2. GA-08 recorded resource-host allowlist (1–2 days).
3. GA-12 candidate-match reconciliation for follow-ups (1–2 days).
4. One-page decision brief export (1–2 days).
5. Pass robots decision to the browser worker (0.5 day).
6. GA-11 Windows message and macOS exchange (0.5–1 day, needs a Mac).
7. GA-14 role network separation (0.5 day plus a runtime test).

## Decisions needed from the maintainer

1. **Licence.** Recommendation: Apache-2.0 for the core, with a `NOTICE` that reproduces the geo-seo-claude MIT
   copyright and permission notice, because history contains derived files. Alternative if hosted competitors are
   a concern: AGPL-3.0. Source-available licences (BSL, FSL, Elastic) would stop the project being "open source".
   Get qualified advice before relicensing.
2. **Branch.** Review this branch, then authorise a push and draft PR (nothing has been pushed).
3. **Commercial route.** See the separate local product plan (not committed to this public repository).

## Continuation record

- Branch: `feat/v1.7-trust-repairs`, based on `bc4f0b5`. See `git log` for the commit.
- Reproduce verification:

```bash
python -m unittest discover -s tests -v
GEO_RUN_RENDER_TESTS=1 python -m unittest discover -s tests -v
ruff check scripts tests
git diff --check
```

- Next commands after approval: `git push -u origin feat/v1.7-trust-repairs`, then open a draft PR.
- Not verified: macOS/Windows, real production sites with bot protection, Chromium CVE exposure, WCAG manual
  review, inter-assessor consistency, human review time.
