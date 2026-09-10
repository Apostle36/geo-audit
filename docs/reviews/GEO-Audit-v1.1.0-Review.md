# GEO Audit v1.1.0 — release-readiness audit

**Verdict: Not ready for unattended client delivery.** Suitable for supervised experimentation with manual review.

**Date:** 2026-09-10
**Repository:** /home/leo/apps/geo-audit-repo
**Baseline/local/remote main:** 013feacbaf5cb063682f15aa0713a4a595e75613
**Scope:** Skill instructions, six role definitions, all four Python helpers, dependencies, installer, tests, installed copies, and actual synthetic PDF outputs. No production website audit or live AI-visibility measurement was performed.

The previous reliability upgrade corrected several misleading recommendations and added useful tests. This independent audit nevertheless reproduced failures outside those tests. The highest-impact problems are incomplete evidence validation, unconstrained scoring criteria, destructive output-path handling, clipped PDF tables, and content corruption.

No source or installed files were modified. Git remained clean before and after testing. All installation experiments and destructive-path reproductions used isolated temporary files.

## Baseline and installation state

- Local main and GitHub main match the requested baseline exactly.
- Both /home/leo/.agents/skills/geo-audit and /home/leo/.claude/skills/geo-audit match all 12 current canonical files: skill, six roles, and five script/dependency files.
- Neither installed package contains unexpected active files outside backups and bytecode caches.
- Each package contains one prior SKILL.md under .backups.
- A separate global Claude role at /home/leo/.claude/agents/geo-technical.md still contains legacy instructions, including the crawler error at line 60. This is distinct from the synchronized bundled copy.
- Runtime agent-selection behavior was not exercised in a fresh Claude session. The stale file is confirmed; whether a particular invocation selects it remains unverified.
- Do not equate backup presence with duplicate skill registration. Current upstream Codex discovery explicitly skips hidden directories; installed runtime parity and Claude discovery were not proved. See [Codex host discovery](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/loader/host.rs) and [discovery implementation](https://github.com/openai/codex/blob/main/codex-rs/ext/skills/src/loader/discovery.rs).

## Verification summary

- Existing suite: **11/11 passed**, using PYTHONDONTWRITEBYTECODE=1.
- Independent matrix: **84 recorded cases**, including expected rejections and observations, not 84 passing assertions.
- Additional checks: two concurrent actual renders, actual input/output collision, malformed JSON CLI behavior, dependency failure, and final repository status.
- Environment: Python 3.14; Playwright 1.58.0; Markdown 3.10.2; HeadlessChrome 153.
- Short PDF: 2 pages. Long PDF: 7 pages. Both rendered successfully. The earlier sandbox launch failure did not recur in this audit.
- Inspected short pages 1–2 and long pages 3 and 7 visually. Extracted text from both PDFs. Verified an https://example.com/ link annotation on short page 2.
- Short PDF preserves Unicode and score metadata but corrupts code text and blockquotes.
- Long PDF clips the second table column. None of its 100 “meaningful evidence” cell texts appear in extracted text.
- Concurrent renders to distinct outputs both succeeded. Simulated browser-failure cleanup removed temporary HTML and preserved input.

## Prioritized findings

Severity is based on demonstrated impact, not exploitability alone. P1 means fix before unattended/client release; P2 means important reliability or maintainability work.

### F01 — P1: scores accept fabricated or malformed evidence references

**Status:** Confirmed by execution.
**Location:** scripts/score.py:40.

**Reproduction:** Supply otherwise valid criteria in all five categories with evidence_ids set to "fiction", [null], or ["does-not-exist"]. Each returns overall 80 and coverage 1.0.

**Expected:** Evidence IDs are a nonempty list of nonempty strings resolving to recorded evidence, with successful collection or appropriate observation provenance.
**Actual:** Only truthiness is checked; no manifest or evidence registry is loaded.

**Impact:** A complete-looking score can be produced without verifiable evidence. “Coverage” describes submitted values, not verified audit coverage.

**Fix:** Validate input against a schema, load the evidence registry, resolve each ID, and verify provenance/status. Separate submitted, assessed, and verified coverage.

**Acceptance:** All three reproductions fail with actionable validation errors; a valid registry-backed fixture passes and reports its evidence coverage.

### F02 — P1: scoring completeness can be inflated by omitting criteria

**Status:** Confirmed mechanism; the probability of accidental inflation is an inference.
**Locations:** scripts/score.py:21, scripts/score.py:28, .claude/skills/geo-audit/SKILL.md:45.

**Reproduction:** Submit one 100-point criterion per category. Result is 100 overall and full coverage. Add a difficult criterion as not_applicable with reason "skip": result and coverage remain unchanged.

**Expected:** Coverage and applicability are evaluated against a declared, versioned criterion set.
**Actual:** The calculator sees only supplied criteria and never checks the manifest. The skill tells the agent to invent anchors before analysis but ships no canonical anchors.

**Impact:** Different agents can produce incomparable scores under the same rubric version. Helpful legacy depth/freshness/topical-coverage checklists were removed without a systematic replacement.

**Fix:** Ship business/page-type criterion profiles with anchors, load the selected profile, detect missing criteria, retain N/A counts and rationales, and define aggregation across pages. Keep editorial flexibility explicit and versioned.

**Acceptance:** Omitting a required criterion makes coverage incomplete; changing applicability requires a profile-supported reason; identical inputs and profiles produce identical category calculations.

### F03 — P1: PDF output can overwrite the source Markdown

**Status:** Confirmed with a real browser render in a temporary directory.
**Locations:** scripts/geo-audit-pdf.py:766 and scripts/geo-audit-pdf.py:792.

**Reproduction:** Invoke the renderer with the same temporary .md file as input and output. Exit code is 0; the file begins with %PDF-1.4 afterward.

**Expected:** Reject equal input/output paths and equivalent symlink/hardlink targets before rendering.
**Actual:** The source is read and subsequently overwritten with PDF bytes.

**Impact:** User error or an agent-generated path mistake destroys the source report. Existing unrelated output files are also overwritten without an explicit overwrite option.

**Fix:** Resolve and compare paths/inodes, require --overwrite for existing outputs, and write atomically through a temporary file beside the destination.

**Acceptance:** Same-file, symlink, and hardlink collisions are rejected without changing input; existing-output refusal is the default; interrupted writes preserve the prior output.

### F04 — P1: long table cells push findings outside the PDF page

**Status:** Confirmed by rendered image and PDF text.
**Locations:** scripts/geo-audit-pdf.py:587, scripts/geo-audit-pdf.py:607.

**Reproduction:** Render the supplied long.md fixture containing 100 two-column rows with long unbroken URLs. Long-page3.png and long-page7.png show only the URL column; finding text is outside the page. Extracted text contains zero “meaningful evidence” cells.

**Expected:** Every column stays within the printable area and remains readable.
**Actual:** Automatic table sizing and missing long-token wrapping create horizontal overflow and reduced apparent text size.

**Fix:** Use bounded/fixed table layout, explicit column widths where needed, overflow-wrap:anywhere, and suitable page margins. Permit long tables to span pages with repeated headers rather than claiming every table remains intact.

**Acceptance:** All 100 finding markers survive PDF text extraction and visual inspection; no element exceeds the page width; repeated table headers remain readable.

### F05 — P1: Markdown preprocessing changes code and quote content

**Status:** Confirmed in HTML and actual PDF text.
**Location:** scripts/geo-audit-pdf.py:123.

**Reproduction:** A fenced HTML example containing <div>x & y</div> produces HTML containing &amp;lt;div&amp;gt; and the PDF visibly prints &lt;div&gt;x &amp; y&lt;/div&gt;. A Markdown blockquote becomes a paragraph beginning with a literal >.

**Expected:** Code displays the original characters, and blockquotes retain their structure.
**Actual:** Escaping the entire source before Markdown parsing interferes with parser semantics. Checklist syntax is also left as literal [ ]/[x] because no task-list extension is configured.

**Impact:** Technical fixes copied from a client report can be wrong. Quoted source evidence is visually misrepresented.

**Fix:** Parse Markdown without blanket pre-escaping, then sanitize the generated HTML using an allowlist. Preserve code semantics and intentionally support or document checklists.

**Acceptance:** Extracted PDF code equals the source example exactly; quotes become blockquotes; task states render predictably; unsafe HTML/link fixtures remain inert.

### F06 — P1: introductory content is silently discarded

**Status:** Confirmed parser behavior.
**Location:** scripts/geo-audit-pdf.py:194.

**Reproduction:** Put IMPORTANT CONCLUSION before the first level-two heading, or provide a valid scored report without any level-two headings. Neither the introductory text nor the conclusion is retained in parsed sections/executive_summary.

**Expected:** Preserve report prose or reject a document that does not meet an explicit schema.
**Actual:** All pre-section content is assumed to be redundant metadata and discarded.

**Impact:** A valid-looking PDF may omit its executive conclusion, limitations, or evidence context.

**Fix:** Use a defined metadata block and parse body content independently; retain the preamble or require an explicit executive-summary section with validation.

**Acceptance:** A unique preamble marker survives HTML and PDF extraction. A contentless report fails preflight rather than producing a cover-only deliverable.

### F07 — P2: contradictory scores and invalid metadata are accepted

**Status:** Confirmed.
**Locations:** scripts/geo-audit-pdf.py:151 and scripts/geo-audit-pdf.py:178.

**Reproduction:** Two declarations of 50 and 90 select 50 silently. “Not assessed” followed by 50 selects 50. An unclosed code fence containing 99 becomes the report score. Metadata after line 20 disappears; URL "not-a-url", date "yesterday", and pages -5 are accepted.

**Expected:** One authoritative score, fence-aware parsing, validated metadata, and consistency with calculated results.
**Actual:** First-match regex and positional metadata heuristics permit conflicting or nonsensical report identities.

**Fix:** Consume validated structured report data; if Markdown remains an input format, use its syntax tree and reject missing/ambiguous metadata and scores. Bind the display to score.py output.

**Acceptance:** Contradictory scores, unclosed-example-only scores, invalid URLs/dates/counts, and missing required metadata fail clearly; legitimate longer headers parse correctly.

### F08 — P2: malformed HTML attributes crash evidence extraction

**Status:** Confirmed.
**Locations:** scripts/evidence.py:21, scripts/evidence.py:23, scripts/evidence.py:25.

**Reproduction:** Each of <meta name>, <link rel>, and <script type></script> raises AttributeError because HTMLParser represents a valueless attribute as None.

**Expected:** Continue extraction and report a malformed-attribute diagnostic.
**Actual:** The whole extraction aborts.

**Impact:** A minor malformed tag can prevent evidence collection for the rest of a page.

**Fix:** Normalize nullable attribute values and isolate extraction errors with element context.

**Acceptance:** All three fixtures complete; valid metadata/schema later in the same document remains captured, with explicit diagnostics.

### F09 — P2: extraction obscures duplicate titles and accepts nonstandard JSON

**Status:** Confirmed.
**Locations:** scripts/evidence.py:31 and scripts/evidence.py:42.

**Reproduction:** Two titles become "Alpha & βOther", a value that never existed as a title. Duplicate JSON keys silently keep the last value. NaN is accepted without error.

**Expected:** Preserve individual observations and diagnose strict JSON problems.
**Actual:** Title provenance is lost; Python's permissive JSON defaults can make malformed input appear valid.

**Fix:** Return titles as a list with positions; add duplicate-key warnings and reject nonstandard constants. Preserve raw blocks and distinguish syntax errors from semantic checks.

**Acceptance:** Duplicate titles remain individually identifiable, duplicate keys are flagged, and NaN/Infinity fail strict JSON validation.

**Related documented limitations:** Microdata/RDFa, conflicting @id entities, empty pages, JavaScript shells, and challenges do not receive semantic diagnoses. This is not a violation of the helper's documented inventory scope, but its JSON should expose “not checked” capabilities to prevent misuse.

### F10 — P2: installation is non-atomic and preserves stale active resources

**Status:** Confirmed in isolated installs.
**Locations:** scripts/install.py:21–25 (main copy operations begin at line 21).

**Reproduction:** Reinstall after adding scripts/stale.py: stale.py remains active. In an isolated source copy with scripts unavailable, installation fails after writing SKILL.md and agents; the destination is partially populated.

**Expected:** Validate all source resources, assemble a complete package, then replace the active package while backing up the prior version.
**Actual:** Direct incremental copying leaves mixtures of old/new files and a discoverable partial skill on failure.

**Fix:** Stage in a sibling temporary directory, validate contents, back up the prior install outside discovery, and switch atomically. Preserve user overrides through an explicit mechanism.

**Acceptance:** Missing-resource/interrupted-install tests leave the prior version intact; obsolete shipped files are removed; backups retain customizations; fresh paths with spaces continue working.

**Additional packaging defect:** The bundled install.py assumes repository layout and cannot reinstall from the installed bundle. Either support both layouts or omit that helper and clearly document source-only installation.

### F11 — P2: legacy global agent definitions can conflict with bundled roles

**Status:** File mismatch confirmed; runtime selection consequence unverified.
**Locations:** scripts/install.py:23; .claude/skills/geo-audit/SKILL.md:26; /home/leo/.claude/agents/geo-technical.md:60.

**Reproduction:** Compare the synchronized bundled technical role against the global Claude role. The global file still labels GPTBot/ClaudeBot as inference crawlers.

**Expected:** Delegation reliably uses the versioned role supplied with the skill.
**Actual:** The installer copies roles inside the skill but does not reconcile same-named global agents. The orchestrator names roles without explicitly instructing the runtime to read and pass their bundled contents.

**Impact:** An invocation may reintroduce obsolete guidance depending on runtime resolution and active definitions.

**Fix:** Make bundled-role loading explicit, namespace/version identifiers, and provide a collision diagnostic. Do not silently replace user-customized global agents.

**Acceptance:** A fresh-session delegation trace identifies the bundled version/hash even when a stale global role of the same name exists.

### F12 — P2: no machine-enforced end-to-end audit contract

**Status:** Confirmed architectural limitation, already partly documented.
**Locations:** .claude/skills/geo-audit/SKILL.md:15–23, line 45, line 61; README.md:19.

**Reproduction/evidence:** The repo contains an HTML inventory helper, score helper, installer, and renderer. There is no collector, manifest/finding JSON schema, evidence-link validator, sample comparability checker, or report validator. The finding status vocabulary differs from the scorer's assessed/unknown/not_applicable vocabulary without a specified mapping.

**Expected:** Before delivery, validate artifacts, provenance, coverage, score inputs, and consistency.
**Actual:** These obligations are natural-language instructions. Redirect count and response-size bounds are requested without concrete values or implementation.

**Impact:** A skilled human/agent can follow the process, but the package cannot establish that a “complete” audit actually followed it.

**Fix:** Add a validate-run command, versioned schemas, criterion profiles, evidence registry, and a documented transformation from findings to criteria. Add bounded collection or explicit command templates and final checks.

**Acceptance:** A run with missing raw evidence, unresolved IDs, incompatible deltas, or inconsistent report score cannot pass release validation.

## Lower-priority observations

- Malformed Markdown URL [x](https://[invalid) crashes the sanitizer via urlsplit. Catch errors and render inert text.
- Markdown images are silently discarded, including alt text. Keep an explicit omitted-image note or support trusted local assets.
- The “running header” and footer are ordinary flow elements, so they do not repeat on every page. This was confirmed on long pages 3 and 7.
- Empty executive-summary spacing adds unnecessary whitespace.
- requirements.txt:1 uses open-ended dependency lower bounds; no lockfile or supported-version matrix exists. Reproducibility was tested only on the stated environment.
- Missing Markdown causes --help to raise an unhandled import error. Move help/preflight before optional imports and produce actionable diagnostics.
- Invalid scoring data structures raise implementation exceptions (AttributeError/KeyError/TypeError), and unknown criterion fields are silently accepted. Prefer a strict schema and structured CLI errors.
- Removing legacy scoring/coverage detail improved factual restraint but also removed useful freshness, topical coverage, and page-type guidance. Restore reviewed reference checklists, not unsupported platform folklore.

## Methodology verification against primary sources

These are checks of the current instructions, not new visibility guarantees.

| Topic | Assessment |
|---|---|
| OpenAI crawler roles | Current v1.1.0 distinction is correct: GPTBot training, OAI-SearchBot search, ChatGPT-User user-triggered. [Official crawler documentation](https://developers.openai.com/api/docs/bots). |
| Google AI features | Optional treatment of llms.txt and no universal special-schema requirement are supported. Google requires eligibility/indexing/snippet access, not a special AI file. [Google AI features](https://developers.google.com/search/docs/appearance/ai-features). |
| Robots semantics | Effective group/path handling is directionally correct, but needs tests for specific groups, merging matching groups, longest path, ties, status failures, and origin boundaries. [Google robots specification](https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec). |
| Anthropic | Training, search, and user actions also differ. The skill delegates checking these without shipping provider coverage. [Anthropic crawler documentation](https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler). Search-indexed official text was available; opening the full page timed out. |
| Perplexity | PerplexityBot supports search, not foundation-model training; Perplexity-User is user-triggered and generally ignores robots rules. Do not generalize one provider's user-fetch semantics to all providers. [Official crawler documentation](https://docs.perplexity.ai/docs/resources/perplexity-crawlers). |
| Schema | Multiple types and flexible vocabulary are legitimate; inventory is not feature eligibility or semantic validation. [Schema.org data model](https://schema.org/docs/datamodel.html). |
| LCP | “Never lazy-load the likely LCP image” is supported; static observations cannot substitute for measurement. [web.dev LCP guidance](https://web.dev/articles/optimize-lcp). |
| Authorship and expertise | Authorship should fit reader expectations. E-E-A-T is not itself a specific ranking factor or a Google numeric score. [Helpful-content guidance](https://developers.google.com/search/docs/fundamentals/creating-helpful-content). |
| Authority weights | 30% authority and other weights remain editorial judgments. No evidence in the package validates them as predictors. The current disclaimer is appropriate; criterion profiles and repeatability are still missing. |

Primary sources checked on 2026-09-10.

## Security and operational review

- **Confirmed destructive behavior:** F03, requiring a caller to supply a colliding output path. This is accidental overwrite risk, not a demonstrated remote exploit.
- **Tested protections:** Raw script markup stays escaped; javascript: and file: link schemes lose their link target; quote injection remains inside an escaped href and does not create an event attribute.
- **Availability failures:** Malformed HTML attributes and malformed IPv6 link syntax crash parsing. These are realistic untrusted-input failures; no remote code execution was demonstrated.
- **Networking:** Renderer registers HTTP/HTTPS abort routes before navigation. PDF annotations still contain intended external hyperlinks. It also retains Google Fonts preconnect/stylesheet tags, so a claim of zero browser-level egress was not verified by packet capture. Remove unnecessary external tags for a genuinely offline design.
- **Local reads:** No demonstrated path from report markup to arbitrary local-file reading. Explicit CLI paths remain caller-controlled.
- **Shell injection:** Python helpers do not interpolate website data into shell commands. Agent-written collection commands are outside these helpers and need safe argument handling.
- **Fetching limits and prompt injection:** Prompt defenses exist, but no autonomous collector or adversarial full-agent run was tested. Do not claim enforced SSRF protection, redirect limits, or prompt-injection immunity.
- **Privacy:** No audit reports are tracked. Default audits/ output is ignored. Arbitrarily named reports or evidence saved elsewhere could still be committed; no secret scanner was found.
- **Concurrency:** Distinct-output concurrent PDF generation passed; unique temporary directories work. Same-destination concurrent writes remain unprotected. Failure cleanup was verified with a mocked browser exception.

## What remains unverified

- Fresh-session Codex/Claude role discovery and exact installed-version hidden-directory behavior.
- Full site collection against robots, redirects, bot challenges, and mixed encodings. Fixtures exercised extraction only.
- API-assisted AI-visibility testing and repeatability across live platforms.
- Network-level egress, browser exploit resistance, and adversarial agent execution.
- All supported Python/Markdown/Playwright versions.
- Every page of every possible PDF; representative pages and text were inspected.
- A complete audit rerun using a relocated repository. Installed helper preflight succeeded from /tmp, and resource copies are self-contained, but bundled installer layout is broken as described.
- Pixel-perfect results with branded fonts or other operating systems.

## Strengths to preserve

- Clear separation of readiness from observed visibility.
- Explicit unknowns and no automatic penalties for training opt-outs or llms.txt.
- Source links, evidence IDs, scope, and comparability requirements.
- JSON-LD array/graph inventory, raw block retention, and hashing.
- Finite score bounds, rejection of booleans/strings, duplicate criterion-ID checks.
- Backup creation and resource bundling.
- Unique PDF temporary directories, cleanup on failure, and basic link protections.
- Useful 11-test regression baseline and candid README limitations.

## Implementation plan

### Immediate: before client delivery

1. Reject output/input collisions and protect existing outputs (F03).
2. Fix long-table width and Markdown fidelity; preserve report prose (F04–F06).
3. Require real evidence IDs and validate score/report metadata (F01, F07).
4. Normalize HTML attributes and preserve duplicate metadata (F08–F09).
5. Ensure delegation uses versioned bundled roles (F11).

Acceptance gate: existing tests plus all reproduced failures; short/long PDF text integrity and visual checks; real same-file refusal; no fabricated-evidence score.

### Next release

1. Add canonical criterion profiles, JSON schemas, manifest/evidence validation, and end-to-end validate-run (F02, F12).
2. Make installation atomic and prune obsolete shipped resources (F10).
3. Restore reviewed page-type/freshness/topical-coverage references.
4. Add precise dependency/preflight handling, version locks, and CI.
5. Correct repeating headers/footers and accessibility/task-list behavior.

### Longer term

1. Implement bounded evidence collection with provider-aware robots tests and preserved HTTP provenance.
2. Add repeatable measured-visibility experiments with recorded platform context.
3. Build benchmark sites and assess inter-run/inter-reviewer consistency.
4. Calibrate or retire composite weights based on measured usefulness rather than claims of predictive certainty.

## Evidence package

The accompanying ZIP contains the two synthetic reports and PDFs, extracted long-report text, representative screenshots, rendering logs, JSON case results, and reproduction scripts. Scripts use the audited local repository path; change that path when reproducing elsewhere. Temporary installation copies are excluded.

The test case records include expected errors, confirmed defects, and scope observations. They must not be interpreted as a pass/fail count without the explanations in this report.
