#!/usr/bin/env python3
"""
Generate a branded PDF from GEO-AUDIT-REPORT.md

Converts a GEO audit markdown report to a branded A4 PDF.
Uses Playwright's native page.pdf() for text-based output with selectable
text and proper CSS page-break support (tables never split mid-page).

Usage:
  python3 scripts/geo-audit-pdf.py
  python3 scripts/geo-audit-pdf.py GEO-AUDIT-REPORT.md
  python3 scripts/geo-audit-pdf.py report.md output.pdf

Branding (optional env vars):
  GEO_AUDIT_AUTHOR   Your name  (default: "GEO Audit")
  GEO_AUDIT_DOMAIN   Your domain (default: "")

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

# Branding — override with env vars
AUTHOR = os.environ.get("GEO_AUDIT_AUTHOR", "GEO Audit")
DOMAIN = os.environ.get("GEO_AUDIT_DOMAIN", "")

try:
    from playwright.sync_api import sync_playwright
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install playwright && playwright install chromium")
    sys.exit(1)


# A4 at 96 dpi
A4_W = 794
A4_H = 1123


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def score_color(score: int) -> str:
    if score >= 75:
        return "#16A34A"
    if score >= 55:
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


def inline_md(text: str) -> str:
    """Convert inline markdown to HTML — bold, italic, code, links."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def md_to_html(text: str) -> str:  # noqa: C901
    """Convert a markdown block to HTML, handling tables, lists, headings."""
    lines = text.split("\n")
    out: list[str] = []
    in_table = False
    in_code = False
    in_ul = False
    in_ol = False
    table_header_done = False

    def close_lists() -> str:
        nonlocal in_ul, in_ol
        result = ""
        if in_ul:
            result += "</ul>"
            in_ul = False
        if in_ol:
            result += "</ol>"
            in_ol = False
        return result

    i = 0
    while i < len(lines):
        line = lines[i]

        # Code fence
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append(close_lists())
                lang = line.strip()[3:]
                out.append(f'<pre><code class="lang-{lang}">')
                in_code = True
            i += 1
            continue

        if in_code:
            out.append(escape_html(line))
            i += 1
            continue

        # Tables
        if "|" in line and line.strip().startswith("|"):
            if not in_table:
                out.append(close_lists())
                out.append("<table>")
                in_table = True
                table_header_done = False

            cells = [c.strip() for c in line.strip().strip("|").split("|")]

            if all(re.match(r"^[-:]+$", c) for c in cells if c):
                out.append("<tbody>")
                table_header_done = True
                i += 1
                continue

            if not table_header_done:
                row = "<thead><tr>" + "".join(f"<th>{inline_md(c)}</th>" for c in cells) + "</tr></thead>"
            else:
                row = "<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in cells) + "</tr>"
            out.append(row)
            i += 1
            continue
        elif in_table:
            out.append("</tbody></table>")
            in_table = False
            table_header_done = False

        stripped = line.strip()

        if line.startswith("### "):
            out.append(close_lists())
            out.append(f"<h3>{inline_md(line[4:])}</h3>")
        elif line.startswith("#### "):
            out.append(close_lists())
            out.append(f"<h4>{inline_md(line[5:])}</h4>")
        elif stripped.startswith("- [x] ") or stripped.startswith("- [X] "):
            if not in_ul:
                out.append('<ul class="checklist">')
                in_ul = True
            out.append(f'<li class="done">{inline_md(stripped[6:])}</li>')
        elif stripped.startswith("- [ ] "):
            if not in_ul:
                out.append('<ul class="checklist">')
                in_ul = True
            out.append(f'<li class="todo">{inline_md(stripped[6:])}</li>')
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline_md(stripped[2:])}</li>")
        elif re.match(r"^\d+\. ", stripped):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            content = re.sub(r"^\d+\. ", "", stripped)
            out.append(f"<li>{inline_md(content)}</li>")
        elif stripped in ("---", "***", "___"):
            out.append(close_lists())
            out.append("<hr>")
        elif stripped.startswith("> "):
            out.append(close_lists())
            out.append(f"<blockquote>{inline_md(stripped[2:])}</blockquote>")
        elif not stripped:
            out.append(close_lists())
        elif stripped:
            out.append(close_lists())
            out.append(f"<p>{inline_md(stripped)}</p>")

        i += 1

    out.append(close_lists())
    if in_table:
        out.append("</tbody></table>")
    if in_code:
        out.append("</code></pre>")

    return "\n".join(out)


def parse_report(text: str) -> dict:
    """Extract metadata and section list from the markdown report."""
    data: dict = {
        "url": "",
        "date": "",
        "business_type": "",
        "pages_analyzed": "",
        "overall_score": 0,
        "score_label": "—",
        "sections": [],
        "executive_summary": "",
    }

    # Only scan the first 20 lines for header metadata —
    # later sections also contain **URL:** lines (per-issue URLs) which
    # would otherwise overwrite the report-level URL.
    for line in text.split("\n")[:20]:
        if line.startswith("**Audit Date:**"):
            data["date"] = line.split("**Audit Date:**")[1].strip()
        elif line.startswith("**URL:**"):
            data["url"] = line.split("**URL:**")[1].strip()
        elif line.startswith("**Business Type:**"):
            data["business_type"] = line.split("**Business Type:**")[1].strip()
        elif line.startswith("**Pages Analyzed:**"):
            data["pages_analyzed"] = line.split("**Pages Analyzed:**")[1].strip()

    m = re.search(r"\*\*Overall GEO Score:\s*(\d+)/100", text)
    if m:
        s = int(m.group(1))
        data["overall_score"] = s
        data["score_label"] = score_label(s)

    # Split into ## sections
    parts = re.split(r"^(## .+)$", text, flags=re.MULTILINE)

    data["executive_summary"] = parts[0] if parts else ""

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

    return data


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def generate_html(data: dict) -> str:
    score = data["overall_score"]
    color = score_color(score)
    url_display = data["url"].replace("https://", "").replace("http://", "").rstrip("/")

    sections_html = "".join(
        f'<section class="report-section">'
        f'<h2>{inline_md(s["heading"])}</h2>'
        f'<div class="section-body">{md_to_html(s["content"])}</div>'
        f'</section>'
        for s in data["sections"]
    )

    meta_items = [
        ("Business Type", data["business_type"]),
        ("Pages Analyzed", data["pages_analyzed"]),
        ("Audit Date", data["date"]),
    ]
    meta_html = "".join(
        f'<div class="cover-meta-item">'
        f'<div class="cover-meta-label">{k}</div>'
        f'<div class="cover-meta-value">{v}</div>'
        f'</div>'
        for k, v in meta_items if v
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>GEO Audit Report — {url_display}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
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

  /* ── Print / PDF page breaks ─────────── */
  @media print {{
    @page {{ margin: 0; }}
    .cover {{ break-after: page; }}
    table {{ break-inside: avoid; }}
    tr {{ break-inside: avoid; }}
    thead {{ display: table-header-group; }}
    h2 {{ break-after: avoid; }}
    h3 {{ break-after: avoid; }}
    h4 {{ break-after: avoid; }}
    pre {{ break-inside: avoid; }}
    blockquote {{ break-inside: avoid; }}
    ul, ol {{ break-inside: avoid; }}
    .report-section {{ break-inside: auto; }}
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
</style>
</head>
<body>

<!-- Cover -->
<div class="cover">
  <div class="cover-top">
    <span class="brand-name">{DOMAIN}</span>
    <span class="cover-date">{data['date']}</span>
  </div>

  <div class="cover-eyebrow">Generative Engine Optimization</div>
  <div class="cover-title">GEO Audit<br>Report</div>
  <div class="cover-url">{data['url']}</div>

  <div class="score-ring">
    <div class="score-num">{score}</div>
    <div class="score-denom">/100</div>
    <div class="score-label">{data['score_label']}</div>
  </div>

  <div class="cover-meta">{meta_html}</div>

  <div class="cover-footer">
    <div class="cover-byline">
      Prepared by <strong>{AUTHOR}</strong>{f" &middot; {DOMAIN}" if DOMAIN else ""}
    </div>
  </div>
</div>

<!-- Running header -->
<div class="page-header">
  <span class="header-audit">GEO Audit &middot; {url_display}</span>
  <span class="header-brand">{DOMAIN}</span>
</div>

<!-- Executive Summary -->
<div class="exec-block">
{md_to_html(data['executive_summary'])}
</div>

<!-- All sections -->
<div class="content-wrap">
{sections_html}
</div>

<!-- Footer -->
<div class="page-footer">
  <span class="footer-brand">{DOMAIN}</span>
  <span class="footer-note">
    {AUTHOR}{" &middot; " if DOMAIN else ""}{DOMAIN} &middot; GEO Audit Report
  </span>
</div>

</body>
</html>"""


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------

def render_to_pdf(html_path: Path) -> bytes:
    """Render the HTML to a text-based A4 PDF using Playwright's native export."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_viewport_size({"width": A4_W, "height": A4_H})
        page.goto(f"file://{html_path}")
        page.wait_for_load_state("networkidle")
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        browser.close()
    return pdf_bytes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]

    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    report_path = Path(args[0]) if args else Path("GEO-AUDIT-REPORT.md")
    output_path = Path(args[1]) if len(args) > 1 else report_path.with_suffix(".pdf")

    if not report_path.exists():
        print(f"Report not found: {report_path}")
        sys.exit(1)

    print(f"Reading {report_path}...")
    md = report_path.read_text(encoding="utf-8")

    print("Parsing...")
    data = parse_report(md)
    print(f"  Score: {data['overall_score']}/100 ({data['score_label']})")
    print(f"  URL:   {data['url']}")
    print(f"  Sections: {len(data['sections'])}")

    print("Generating HTML...")
    html = generate_html(data)

    tmp = report_path.parent / "_geo_audit_render.html"
    tmp.write_text(html, encoding="utf-8")

    print("Rendering...")
    pdf_bytes = render_to_pdf(tmp.resolve())
    tmp.unlink(missing_ok=True)

    print(f"Saving {output_path}...")
    output_path.write_bytes(pdf_bytes)

    print(f"\nDone: {output_path}")


if __name__ == "__main__":
    main()
