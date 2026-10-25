# Toolkit 1.5.0 verification

Verified locally on 25 October 2026 with Python 3.14.4, Playwright 1.58.0,
Markdown 3.10.2 and Ruff 0.16.8. CI remains configured for Python 3.10/3.13 and
an additional real-browser job; those CI runs were not executed locally.

## Results

- `GEO_RUN_RENDER_TESTS=1 python -m unittest discover -s tests`: **178 tests passed**, no skips.
- `ruff check scripts tests`: passed.
- `git diff --check`: passed.
- The new CLI help works without optional browser dependencies installed.

The suite exercises the full CLI start/sample/resume/export sequence against a
local HTTP fixture. Repeated resume makes no additional page requests and leaves
run bytes unchanged. Interrupted attempts are retained, successful steps reused,
failed attempts explicitly retried, and analyst text preserved when evidence is
appended. Corrupt checkpoints and concurrent writers are rejected.

Delivery regressions cover unfinished drafts, unknown core checks, partial-page
topic coverage, explicit exclusions, warning qualifications, all-N/A score
withholding, exact-byte approval invalidation and protected input/approval files.
Real PDFs preserve reviewer and scope text, show draft labels when appropriate,
and retain the existing long-table and concurrent-export checks.

Real browser fixtures verify JavaScript-produced DOM, both viewport sizes,
requested versus actual layout without a viewport tag, screenshots, measured
navigation timing, blocked mutation requests, robots exclusions and off-site
redirects. Same-site redirects resolve before rendering. Asset redirects and a
document that changes its redirect after preflight cannot fetch the outside
fixture server.

## Visual inspection and limits

The first pages of both synthetic draft and final PDFs were rasterised and
visually inspected. Status labels, scope exclusions and reviewer details were
readable without clipping. This does not certify every possible report's
pagination or accessibility. Captures and PDFs in this verification are synthetic
fixtures, not completed live-site audits.

Retained local render artifacts: `/tmp/geo-audit-1.5-validation/`.
Browser observations remain scoped lab evidence. Human interpretation, factual
review and report approval are still required. Run schema 1.4.0 and rubric 1.2.0
were preserved.
