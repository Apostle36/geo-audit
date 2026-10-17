#!/usr/bin/env python3
"""
Generate branded HTML/PDF from a validated audit run JSON.

Uses Playwright's native page.pdf() for selectable text. Long tables span pages
with repeated table headers. Legacy Markdown requires explicit opt-in and its
scores are labeled unverified. See docs/RUN-FORMAT.md for the run contract.

Usage:
  python3 scripts/geo-audit-pdf.py run.json output.html
  python3 scripts/geo-audit-pdf.py run.json output.pdf
  python3 scripts/geo-audit-pdf.py report.md output.pdf --legacy-markdown

Branding (optional env vars):
  GEO_AUDIT_AUTHOR   Your name  (default: "GEO Audit")
  GEO_AUDIT_DOMAIN   Your domain (default: "")

Browser: PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH if set, otherwise Playwright's own
Chromium, otherwise an installed system Chrome/Chromium as a fallback.

  Example:
    GEO_AUDIT_AUTHOR="Jane Smith" GEO_AUDIT_DOMAIN="janesmith.com" python3 scripts/geo-audit-pdf.py

Requirements:
  pip install playwright markdown
  playwright install chromium
"""

import os
import sys
import re
from pathlib import Path
import html as html_lib
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Branding — override with env vars
AUTHOR = os.environ.get("GEO_AUDIT_AUTHOR", "GEO Audit")
DOMAIN = os.environ.get("GEO_AUDIT_DOMAIN", "")


# A4 at 96 dpi
A4_W = 794
A4_H = 1123

# A PDF of raw captures stops being readable long before the collection limits are
# reached, so each capture is shortened there. Technical HTML keeps every character.
TECHNICAL_PDF_EVIDENCE_CHARACTERS = 5000


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def score_color(score: int) -> str:
    if score >= 75:
        return "#16A34A"
    if score >= 60:
        return "#D97706"
    if score >= 40:
        return "#EA580C"
    return "#DC2626"


def score_label(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    if score >= 40:
        return "Poor"
    return "Critical"


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_to_html(text: str) -> str:
    """Parse first, then allowlist HTML so code and blockquotes retain meaning."""
    from html.parser import HTMLParser
    from urllib.parse import urlsplit
    try:
        import markdown
    except ImportError as exc:
        raise RuntimeError("Install reporting dependencies: pip install -r scripts/requirements.txt") from exc

    class SafeHTML(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.parts = []

        def handle_starttag(self, tag, attrs):
            allowed = {"p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "em", "strong", "del",
                       "ul", "ol", "li", "blockquote", "pre", "code", "table", "thead", "tbody", "tr", "th", "td", "a"}
            if tag == "img":
                self.parts.append(html_lib.escape("[Image omitted: " + (dict(attrs).get("alt") or "no description") + "]"))
                return
            if tag not in allowed:
                self.parts.append(html_lib.escape(self.get_starttag_text()))
                return
            safe = []
            for key, value in attrs:
                if tag != "a" or key not in {"href", "title"}:
                    continue
                if key == "href":
                    try:
                        parsed = urlsplit(value or "")
                        if parsed.scheme.lower() not in {"http", "https", "mailto"} and not (value or "").startswith("#"):
                            continue
                        if parsed.scheme in {"http", "https"} and not parsed.hostname:
                            continue
                    except ValueError:
                        continue
                safe.append(f' {key}="{html_lib.escape(value or "", quote=True)}"')
            self.parts.append("<" + tag + "".join(safe) + ">")

        def handle_endtag(self, tag):
            if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "em", "strong", "del", "ul", "ol", "li",
                       "blockquote", "pre", "code", "table", "thead", "tbody", "tr", "th", "td", "a"}:
                self.parts.append(f"</{tag}>")
            elif tag not in {"img", "br", "hr"}:
                self.parts.append(html_lib.escape(f"</{tag}>"))

        def handle_data(self, data):
            self.parts.append(html_lib.escape(data, quote=False))

        def handle_entityref(self, name):
            self.parts.append(f"&{name};")

        def handle_charref(self, name):
            self.parts.append(f"&#{name};")

    rendered = markdown.markdown(text, extensions=["tables", "fenced_code"])
    rendered = re.sub(r"(<li>(?:<p>)?)\[([ xX])\] ",
                      lambda m: m[1] + ("☑ " if m[2].lower() == "x" else "☐ "), rendered)
    parser = SafeHTML()
    parser.feed(rendered)
    return "".join(parser.parts)


def inline_md(text: str) -> str:
    result = md_to_html(text)
    return result[3:-4] if result.startswith("<p>") and result.endswith("</p>") else result


def parse_report(text: str) -> dict:
    """Extract metadata and section list from the markdown report."""
    if "\x00" in text:
        raise ValueError("NUL characters are not supported in Markdown reports")
    data: dict = {
        "url": "",
        "date": "",
        "business_type": "",
        "pages_analyzed": "",
        "overall_score": None,
        "score_label": "—",
        "sections": [],
        "executive_summary": "",
    }

    # Legacy Markdown is an explicit, unverified import path. Only top-level
    # declarations outside fenced/indented code are authoritative metadata.
    lines, declarations = [], []
    fence = None
    in_header = True
    labels = {"Audit Date": "date", "URL": "url", "Business Type": "business_type", "Pages Analyzed": "pages_analyzed"}
    seen = set()
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[match.end():].strip():
                fence = None
            lines.append(line)
            continue
        if fence:
            lines.append("\x00" + line if line.startswith("## ") else line)
            continue
        if line.startswith("## "):
            in_header = False
        meta = re.fullmatch(r"\*\*(Audit Date|URL|Business Type|Pages Analyzed):\*\*\s*(.*)", line)
        if meta and in_header:
            key = labels[meta[1]]
            if key in seen:
                raise ValueError(f"Duplicate metadata: {meta[1]}")
            seen.add(key)
            data[key] = meta[2].strip()
            continue
        score = re.fullmatch(r"\*\*Overall GEO Score:\s*(.*?)\*\*\s*", line)
        if score:
            declarations.append(score[1])
        elif line.startswith("**Overall GEO Score:"):
            raise ValueError("Malformed score declaration")
        else:
            lines.append(line)
    if fence:
        raise ValueError("Unclosed code fence")
    if seen != set(labels.values()):
        raise ValueError("Missing report header metadata")
    from datetime import date
    from run_contract import web_url
    web_url(data["url"])
    if date.fromisoformat(data["date"]).isoformat() != data["date"]:
        raise ValueError("Audit Date must be YYYY-MM-DD")
    if not data["business_type"] or not re.fullmatch(r"[1-9]\d*", data["pages_analyzed"]):
        raise ValueError("Business Type and a positive Pages Analyzed count are required")
    if len(declarations) != 1:
        raise ValueError("Exactly one overall score declaration is required")
    protected = "\n".join(lines)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)/100", declarations[0])
    if m:
        s = float(m.group(1))
        if not 0 <= s <= 100:
            raise ValueError("Overall score must be between 0 and 100")
        data["overall_score"] = int(s) if s.is_integer() else s
        data["score_label"] = score_label(s)
    elif declarations[0].lower() != "not assessed":
        raise ValueError("Missing or invalid overall score")
    else:
        data["score_label"] = "Not assessed"

    parts = re.split(r"^(## .+)$", protected, flags=re.MULTILINE)
    parts = [part.replace("\x00", "") for part in parts]

    data["executive_summary"] = parts[0].strip()

    current: dict | None = None
    for part in parts[1:]:
        if part.startswith("## "):
            if current:
                data["sections"].append(current)
            current = {"heading": part[3:].strip(), "content": ""}
        elif current is not None:
            current["content"] += part

    if current:
        data["sections"].append(current)
    body_text = data["executive_summary"] + "\n" + "\n".join(s["content"] for s in data["sections"])
    if not re.sub(r"(?m)^#{1,6}\s.*$", "", body_text).strip():
        raise ValueError("Report has no body content")
    data["executive_summary"] = "Legacy Markdown import: evidence and scores are not verified.\n\n" + data["executive_summary"]
    data["score_label"] = "Unverified legacy score"
    return data


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(data: dict, content_lang=None) -> str:
    if data.get("client_report"):
        from client_report import render_client_html
        return render_client_html(data, AUTHOR, DOMAIN, content_lang)
    if content_lang is not None:
        raise ValueError("--content-lang applies to client reports only")
    score = data["overall_score"]
    color = score_color(score) if score is not None else "#71717A"
    score = score if score is not None else "—"
    data = {k: html_lib.escape(v, quote=True) if isinstance(v, str) and k != "executive_summary" else v for k, v in data.items()}
    author_safe = html_lib.escape(AUTHOR, quote=True)
    domain_safe = html_lib.escape(DOMAIN, quote=True)
    url_display = data["url"].replace("https://", "").replace("http://", "").rstrip("/")
    if DOMAIN and not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", DOMAIN):
        raise ValueError("GEO_AUDIT_DOMAIN must be a hostname")
    domain_link = f'<a href="https://{domain_safe}" style="color:inherit;text-decoration:none;">{domain_safe}</a>' if DOMAIN else ""

    def body(text, format="markdown"):
        if format == 'blocks':
            from client_report import render_blocks
            return render_blocks(text)
        return '<div class="plain-text">' + html_lib.escape(text) + '</div>' if format == "plain" else md_to_html(text)

    def heading(section):
        # Structured runs supply plain headings (for example finding IDs); only legacy Markdown is parsed.
        return html_lib.escape(section["heading"]) if section.get("format") == "plain" else inline_md(section["heading"])

    sections_html = "".join(
        f'<section class="report-section">'
        f'<h2>{heading(s)}</h2>'
        f'<div class="section-body">{body(s["content"], s.get("format", "markdown"))}</div>'
        f'</section>'
        for s in data["sections"]
    )

    meta_items = [
        ("Business Type", data["business_type"]),
        (data.get('sample_label', "Pages Analyzed"), data["pages_analyzed"]),
        ("Audit Date", data["date"]),
    ]
    meta_html = "".join(
        f'<div class="cover-meta-item">'
        f'<div class="cover-meta-label">{k}</div>'
        f'<div class="cover-meta-value">{v}</div>'
        f'</div>'
        for k, v in meta_items if v
    )
    cover_score = (f'<p class="cover-note">{data["cover_note"]}</p>' if data.get('cover_note') else
        f'<div class="score-ring"><div class="score-num">{score}</div><div class="score-denom">/100</div><div class="score-label">{data["score_label"]}</div></div>')

    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GEO Audit Report — {url_display}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --text:    #18181B;
    --heading: #09090B;
    --muted:   #71717A;
    --border:  #E4E4E7;
    --surface: #F4F4F5;
    --white:   #FFFFFF;
    --score:   {color};
    --font:    'Inter', -apple-system, sans-serif;
  }}

  body {{
    font-family: var(--font);
    font-size: 14px;
    line-height: 1.65;
    color: var(--text);
    background: var(--white);
    width: {A4_W}px;
  }}

  /* ── Cover ────────────────────────────── */
  .cover {{
    width: {A4_W}px;
    min-height: {A4_H}px;
    padding: 52px 60px 44px;
    display: flex;
    flex-direction: column;
    border-bottom: 2px solid var(--heading);
  }}

  .cover-top {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 72px;
  }}

  .brand-name {{
    font-size: 14px;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: var(--heading);
  }}

  .cover-date {{
    font-size: 12px;
    color: var(--muted);
    font-weight: 500;
  }}

  .cover-eyebrow {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 14px;
  }}

  .cover-title {{
    font-size: 52px;
    font-weight: 800;
    letter-spacing: -0.05em;
    line-height: 1.0;
    color: var(--heading);
    margin-bottom: 10px;
  }}

  .cover-url {{
    font-size: 16px;
    font-weight: 500;
    color: var(--muted);
    margin-bottom: 56px;
  }}

  .score-ring {{
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 160px;
    height: 160px;
    border: 2px solid var(--score);
    border-radius: 2px;
    margin-bottom: 44px;
  }}

  .score-num {{
    font-size: 48px;
    font-weight: 800;
    letter-spacing: -0.05em;
    color: var(--score);
    line-height: 1;
  }}

  .score-denom {{
    font-size: 14px;
    font-weight: 500;
    color: var(--muted);
    margin-top: 2px;
  }}

  .score-label {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--score);
    margin-top: 8px;
  }}

  .cover-meta {{
    display: flex;
    gap: 36px;
    margin-bottom: auto;
  }}

  .cover-meta-item {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}

  .cover-meta-label {{
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--muted);
  }}

  .cover-meta-value {{
    font-size: 12px;
    font-weight: 600;
    color: var(--heading);
  }}

  .cover-footer {{
    margin-top: 56px;
    padding-top: 18px;
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}

  .cover-byline {{
    font-size: 11px;
    color: var(--muted);
  }}

  .cover-byline strong {{
    color: var(--heading);
    font-weight: 700;
  }}

  .cover-domain {{
    font-size: 13px;
    font-weight: 800;
    color: var(--heading);
    letter-spacing: -0.02em;
  }}

  /* ── Running header ───────────────────── */
  .page-header {{
    padding: 16px 60px;
    border-bottom: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}

  .header-audit {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--muted);
  }}

  .header-brand {{
    font-size: 12px;
    font-weight: 800;
    color: var(--heading);
    letter-spacing: -0.02em;
  }}

  /* ── Content ──────────────────────────── */
  .exec-block {{
    padding: 36px 60px;
  }}

  .content-wrap {{
    padding: 0 60px 56px;
  }}

  .report-section {{
    padding: 40px 0;
    border-bottom: 1px solid var(--border);
  }}

  .report-section:last-child {{
    border-bottom: none;
  }}

  /* ── Typography ───────────────────────── */
  h2 {{
    font-size: 20px;
    font-weight: 800;
    letter-spacing: -0.03em;
    color: var(--heading);
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }}

  h3 {{
    font-size: 14px;
    font-weight: 700;
    color: var(--heading);
    margin-top: 24px;
    margin-bottom: 8px;
  }}

  h4 {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    margin-top: 18px;
    margin-bottom: 6px;
  }}

  p {{
    margin-bottom: 10px;
    line-height: 1.65;
  }}

  strong {{ font-weight: 700; color: var(--heading); }}
  em {{ font-style: italic; }}
  a {{ color: var(--heading); font-weight: 600; text-decoration: underline; text-decoration-color: var(--border); }}

  code {{
    font-family: 'Courier New', monospace;
    font-size: 11.5px;
    background: var(--surface);
    padding: 1px 5px;
    border-radius: 3px;
    color: var(--heading);
  }}

  pre {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 14px;
    margin: 12px 0;
  }}

  pre code {{
    background: none;
    padding: 0;
    font-size: 10.5px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-all;
  }}

  blockquote {{
    border-left: 3px solid var(--border);
    padding: 6px 14px;
    margin: 10px 0;
    color: var(--muted);
    font-style: italic;
  }}

  hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 20px 0;
  }}

  /* ── Lists ────────────────────────────── */
  ul, ol {{
    padding-left: 18px;
    margin: 6px 0 10px;
  }}

  li {{
    margin-bottom: 4px;
    line-height: 1.55;
  }}

  ul.checklist {{
    list-style: none;
    padding-left: 0;
  }}

  ul.checklist li {{
    padding-left: 22px;
    position: relative;
    margin-bottom: 5px;
  }}

  ul.checklist li::before {{
    position: absolute;
    left: 0;
    top: 0;
    font-size: 12px;
  }}

  ul.checklist li.done {{
    color: var(--muted);
    text-decoration: line-through;
  }}

  ul.checklist li.done::before {{
    content: '✓';
    color: #16A34A;
  }}

  ul.checklist li.todo::before {{
    content: '○';
    color: var(--muted);
  }}

  /* ── Tables ───────────────────────────── */
  table {{
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 12px;
  }}

  th {{
    background: var(--surface);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    padding: 8px 10px;
    text-align: left;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
  }}

  td {{
    padding: 8px 10px;
    border-bottom: 1px solid var(--border);
    color: var(--text);
    vertical-align: top;
    line-height: 1.5;
  }}

  tr:last-child td {{ border-bottom: none; }}

  /* ── Issue blocks ─────────────────────── */
  .issue-block {{
    break-inside: avoid;
    margin-bottom: 4px;
  }}

  /* ── Print / PDF page breaks ─────────── */
  @media print {{
    @page {{ margin: 0; }}
    .cover {{ break-after: page; }}
    table {{ break-inside: auto; }}
    tr {{ break-inside: avoid; }}
    thead {{ display: table-header-group; }}
    h2 {{ break-after: avoid; }}
    h3 {{ break-after: avoid; }}
    h4 {{ break-after: avoid; }}
    pre {{ break-inside: avoid; }}
    blockquote {{ break-inside: avoid; }}
    ul, ol {{ break-inside: avoid; }}
    li {{ break-inside: avoid; }}
    p {{ break-inside: avoid; orphans: 4; widows: 4; }}
    .report-section {{ break-inside: auto; }}
    h3 + p, h4 + p {{ break-before: avoid; }}
  }}

  /* ── Footer ───────────────────────────── */
  .page-footer {{
    padding: 14px 60px;
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 8px;
  }}

  .footer-brand {{
    font-size: 12px;
    font-weight: 800;
    color: var(--heading);
    letter-spacing: -0.02em;
  }}

  .footer-note {{
    font-size: 10px;
    color: var(--muted);
  }}
  th, td, a, p, .cover-url, .plain-text {{ overflow-wrap: anywhere; word-break: break-word; }}
  .plain-text, pre, pre code {{ white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }}
  .plain-text {{ margin: 12px 0; }}
  .cover-note {{ max-width: 540px; font-size: 20px; margin-bottom: 40px; }}
  .source-links {{ font-size: 11px; line-height: 1.6; }}
  h4 {{ font-size: 14px; margin: 18px 0 6px; break-after: avoid; text-transform: none; letter-spacing: normal; line-height: 1.5; }}
  .cover-meta-item:last-child {{ min-width: 95px; }}
  @media screen and (max-width: 794px) {{
    body {{ width: 100%; }}
    .cover {{ width: 100%; min-height: auto; padding: 32px 24px; }}
    .cover-top {{ margin-bottom: 36px; }}
    .cover-title {{ font-size: 40px; }}
    .cover-meta {{ flex-wrap: wrap; gap: 20px; }}
    .content-wrap, .exec-block, .page-header, .page-footer {{ width: auto; max-width: 100%; margin-left: 0; margin-right: 0; padding-left: 24px; padding-right: 24px; }}
    table {{ table-layout: fixed; width: 100%; }}
  }}
  @media print {{
    pre, blockquote, ul, ol, p {{ break-inside: auto; }}
  }}
</style>
</head>
<body>

<!-- Cover -->
<div class="cover">
  <div class="cover-top">
    <span class="brand-name">{domain_link}</span>
    <span class="cover-date">{data['date']}</span>
  </div>

  <div class="cover-eyebrow">Generative Engine Optimization</div>
  <div class="cover-title">GEO Audit<br>Report</div>
  <div class="cover-url">{data['url']}</div>

  {cover_score}

  <div class="cover-meta">{meta_html}</div>

  <div class="cover-footer">
    <div class="cover-byline">
      Prepared by <strong>{author_safe}</strong>{f" &middot; {domain_link}" if DOMAIN else ""}
    </div>
  </div>
</div>

<!-- Running header -->
<div class="page-header">
  <span class="header-audit">GEO Audit &middot; {url_display}</span>
  <span class="header-brand">{domain_safe}</span>
</div>

<!-- Executive Summary -->
<div class="exec-block">
{body(data['executive_summary'], data.get('summary_format', 'markdown'))}
</div>

<!-- All sections -->
<div class="content-wrap">
{sections_html}
</div>

<!-- Footer -->
<div class="page-footer">
  <span class="footer-brand">{domain_link}</span>
  <span class="footer-note">
    {author_safe}{" &middot; " if DOMAIN else ""}{domain_link} &middot; GEO Audit Report
  </span>
</div>

</body>
</html>"""


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

SYSTEM_BROWSERS = ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser")


def launch_chromium(playwright):
    """Explicit executable first, then Playwright's tested Chromium, then a system browser.

    Playwright pins the Chromium build it is tested against, so a system browser is
    used only when that build is not installed.
    """
    import shutil
    from playwright.sync_api import Error
    options = {"args": ["--disable-dev-shm-usage"]}
    explicit = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
    if explicit:
        return playwright.chromium.launch(executable_path=explicit, **options)
    try:
        return playwright.chromium.launch(**options)
    except Error as exc:
        if "Executable doesn't exist" not in str(exc):
            raise
        for candidate in SYSTEM_BROWSERS:
            if shutil.which(candidate):
                print(f"Playwright's Chromium is not installed; using {candidate}", file=sys.stderr)
                return playwright.chromium.launch(executable_path=candidate, **options)
        raise


def render_to_pdf(html_path: Path) -> bytes:
    """Render the HTML to a text-based A4 PDF using Playwright's native export."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Install playwright and run: playwright install chromium") from exc

    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page()
        page.set_viewport_size({"width": A4_W, "height": A4_H})
        page.route("http://**/*", lambda route: route.abort())
        page.route("https://**/*", lambda route: route.abort())
        page.goto(html_path.as_uri())
        page.wait_for_load_state("networkidle")
        client = page.locator('meta[name="geo-client-report"]').count() > 0
        options = dict(format="A4", print_background=True, tagged=True, outline=True)
        if client:
            options.update(prefer_css_page_size=True, display_header_footer=True,
                header_template='<span></span>',
                footer_template='<div style="width:100%;text-align:center;font:9px sans-serif;color:#464644">GEO Audit · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
        else:
            options['margin'] = {"top": "0", "right": "0", "bottom": "0", "left": "0"}
        pdf_bytes = page.pdf(**options)
        browser.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def export_report(report_path, output_path, *, overwrite=False, legacy_markdown=False, technical=False,
                  content_lang=None):
    from evidence import strict_json
    from run_contract import report_data
    from safe_io import check_output, atomic_write
    report_path, output_path = Path(report_path), Path(output_path)
    check_output(report_path, output_path, overwrite)
    if output_path.suffix.lower() not in {".html", ".pdf"}:
        raise ValueError("Output must end in .html or .pdf")
    text = report_path.read_text(encoding="utf-8")
    if technical and legacy_markdown:
        raise ValueError('--technical requires a validated JSON run')
    pdf = output_path.suffix.lower() == ".pdf"
    if legacy_markdown:
        data = parse_report(text)
    else:
        limit = TECHNICAL_PDF_EVIDENCE_CHARACTERS if technical and pdf else None
        data = report_data(strict_json(text), technical=technical, evidence_limit=limit)
    html = generate_html(data, content_lang)
    if output_path.suffix.lower() == ".html":
        atomic_write(report_path, output_path, html.encode("utf-8"), overwrite)
        return
    with tempfile.TemporaryDirectory(prefix="geo-audit-render-") as temp_dir:
        tmp = Path(temp_dir) / "report.html"
        tmp.write_text(html, encoding="utf-8")
        pdf_bytes = render_to_pdf(tmp.resolve())
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Renderer did not return a PDF")
    atomic_write(report_path, output_path, pdf_bytes, overwrite)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Render a validated run JSON to HTML or PDF.")
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace an existing output, never the input")
    parser.add_argument("--legacy-markdown", action="store_true", help="Import unverified legacy Markdown with a visible warning")
    parser.add_argument('--technical', action='store_true', help='Export internal criteria and captured evidence instead of the client report (PDF shortens each capture; HTML keeps it whole)')
    parser.add_argument('--content-lang', help='BCP 47 language of the run-written prose, such as el, when it is not English')
    args = parser.parse_args()
    try:
        export_report(args.report, args.output, overwrite=args.overwrite, legacy_markdown=args.legacy_markdown,
                      technical=args.technical, content_lang=args.content_lang)
    except Exception as exc:
        parser.exit(2, f"Report failed: {exc}\n")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
