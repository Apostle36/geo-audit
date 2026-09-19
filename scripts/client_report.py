"""Client presentation of validated runs; never changes evidence or scoring."""
from datetime import date
from html import escape
import base64
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote
from review_topics import TOPICS, CATEGORY_NAMES, CRITERION_NAMES


def safe_link(label, url):
    try:
        parsed = urlsplit(url)
        safe = parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password
    except ValueError:
        safe = False
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' if safe else escape(label)


def render_blocks(blocks):
    """Historical block API retained for callers; input text is always escaped."""
    out = []
    for kind, value in blocks:
        if kind == 'links':
            out.append('<p class="source-links">' + ' · '.join(safe_link(label, url) for label, url in value) + '</p>')
        elif kind == 'table':
            header, rows = value
            out.append('<table><thead><tr>' + ''.join(f'<th scope="col">{escape(str(x))}</th>' for x in header) + '</tr></thead><tbody>')
            out.extend('<tr>' + ''.join(f'<td>{escape(str(x))}</td>' for x in row) + '</tr>' for row in rows)
            out.append('</tbody></table>')
        elif kind == 'list':
            out.append('<ul>' + ''.join(f'<li>{escape(x)}</li>' for x in value) + '</ul>')
        elif kind in {'p', 'h3', 'h4'}:
            out.append(f'<{kind}>' + escape(value) + f'</{kind}>')
        else:
            raise ValueError(f'Unsupported report block: {kind}')
    return '\n'.join(out)


def excerpt(text, limit=150):
    """Explicitly shortened navigation copy; the complete text stays in detail."""
    text = ' '.join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0].rstrip(' ,;:') + '…'


def action_preview(text):
    """Prefer a complete first sentence to a cut-off instruction."""
    return excerpt(re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0], 230)


def client_report_data(run, scores):
    # Data is passed through, not edited. Repeated narrative cannot safely be
    # semantically rewritten by a deterministic renderer.
    return {'client_report': True, 'run': run, 'scores': scores,
            'overall_score': scores['overall'], 'url': run['metadata']['url']}


def report_model(run, scores=None):
    """One classification drives summary, plan, details and coverage labels."""
    ranks = {n: i for i, n in enumerate(('critical', 'high', 'medium', 'low', 'informational'))}
    findings = sorted(run['findings'], key=lambda f: ranks[f['severity']])
    actions, verification, context = [], [], []
    for index, finding in enumerate(findings, 1):
        item = {'finding': finding, 'anchor': f'finding-{index}'}
        if finding['kind'] in {'unknown', 'hypothesis'} or finding['status'] == 'unknown':
            verification.append(item)
        elif finding['severity'] == 'informational' or finding['status'] == 'not_applicable':
            context.append(item)
        else:
            actions.append(item)
    recorded = {(x['category'], x['topic']): x for x in run.get('review', [])}
    outstanding, excluded = [], []
    for category, topics in TOPICS.items():
        for topic, label in topics.items():
            item = recorded.get((category, topic))
            row = {'label': label, 'anchor': f'check-{category}-{topic}', 'review': item}
            if item is None or item['status'] == 'unknown':
                outstanding.append(row)
            elif item['status'] == 'not_applicable':
                excluded.append(row)
    core_unknown = [c for c in (scores or {}).get('criteria', []) if c['status'] == 'unknown']
    return dict(core_unknown=core_unknown, actions=actions, verification=verification, context=context,
                outstanding=outstanding, excluded=excluded, recorded=recorded)


def font_css():
    """Opt-in local brand fonts. No remote loads or licensed font distribution."""
    directory = os.environ.get('GEO_AUDIT_FONT_DIR')
    if not directory:
        return ''
    root = Path(directory).expanduser()
    specs = [('AboutBeige', 'AboutBeige/AboutBeige-Regular.woff2', '400'),
             ('AboutBeige', 'AboutBeige/AboutBeige-SemiBold.woff2', '600'),
             ('Geist Mono', 'GeistMono/GeistMono-Variable.woff2', '100 900')]
    result = []
    for family, relative, weight in specs:
        path = root / relative
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f'Missing or oversized local report font: {path}')
        raw = path.read_bytes()
        if not raw.startswith(b'wOF2'):
            raise ValueError(f'Expected a WOFF2 font: {path}')
        payload = base64.b64encode(raw).decode('ascii')
        result.append(f"@font-face{{font-family:'{family}';src:url(data:font/woff2;base64,{payload}) format('woff2');font-weight:{weight};font-style:normal;font-display:swap;}}")
    return '\n'.join(result)


def render_client_html(data, author='GEO Audit', domain=''):
    if domain and not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', domain):
        raise ValueError('GEO_AUDIT_DOMAIN must be a hostname')
    run, scores = data['run'], data['scores']
    meta = run['metadata']; model = report_model(run, scores)
    registry = {x['id']: x for x in run['assessment']['evidence']}
    sample = set(meta['sample'])
    e = escape
    readable_date = date.fromisoformat(meta['date']).strftime('%d %B %Y').lstrip('0')
    def p(text, cls=''):
        return f'<p{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{e(text)}</p>'
    def jump(label, anchor):
        # Anchors are generated by this module, never taken from report text.
        return f'<a href="#{anchor}">{e(label)}</a>'
    def label(url):
        try:
            parsed = urlsplit(url)
            path = unquote(parsed.path.strip('/')).replace('-', ' ').replace('_', ' ')
            return path or 'Homepage'
        except ValueError:
            return url
    def page_scope(urls):
        if set(urls) == sample:
            return p('Applies to the declared sample.', 'scope')
        return '<p class="scope">Pages: ' + '; '.join(safe_link(label(u), u) for u in urls) + '.</p>'
    def sources(ids):
        urls = list(dict.fromkeys(registry[i]['source'] for i in ids if registry[i]['source'].startswith(('http://', 'https://')) and registry[i]['source'] not in sample))
        if not urls:
            return ''
        return '<p class="sources">Sources: ' + ' · '.join(safe_link(excerpt(url, 90), url) for url in urls) + '</p>'
    def finding(item):
        f = item['finding']; anchor = item['anchor']
        kind = {'observation': 'Observed', 'recommendation': 'Recommendation', 'hypothesis': 'Hypothesis — verify first', 'unknown': 'Unresolved'}[f['kind']]
        parts = [f'<article class="finding" id="{anchor}">', p(f"{kind} · {f['severity'].capitalize()} priority", 'eyebrow'), f'<h3>{e(f["claim"])}</h3>', page_scope(f['affected_urls'])]
        for key, title in [('observed', 'Evidence'), ('consequence', 'Why it matters'), ('fix', 'Recommended action'), ('acceptance', 'Completion check'), ('confidence_reason', 'Confidence and limits')]:
            parts.append(f'<p><strong>{title}.</strong> {e(f[key])}</p>')
        parts += [sources(f['evidence_ids']), '</article>']
        return '\n'.join(parts)
    actions = model['actions']
    assessed = sum(x['status'] == 'assessed' for x in run.get('review', []))
    total = sum(len(t) for t in TOPICS.values())
    unresolved_count = len(model['outstanding'])
    parts = ['<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
             f'<meta name="geo-client-report" content="1.3.1"><title>GEO Audit Report — {e(urlsplit(meta["url"]).netloc)}</title><style>',
             CLIENT_CSS, font_css(), '</style></head><body>',
             '<a class="skip" href="#actions">Skip to action plan</a><main id="report">',
             '<section class="decision" id="summary">',
             p(f'GEO Audit · {readable_date}', 'eyebrow'), '<h1>Website readiness review</h1>',
             p(meta['url'], 'site'), p(f'Prepared by {author}' + (f' · {domain}' if domain else ''), 'byline'),
             '<h2>The decision summary</h2>', p(run['summary']), '<h3>Start here</h3>']
    if actions:
        parts.append('<ol class="priorities">' + ''.join('<li>' + jump(action_preview(x['finding']['fix']), x['anchor']) + '</li>' for x in actions[:3]) + '</ol>')
    else:
        parts.append(p('No supported improvement actions were recorded. This does not establish a clean bill of health.'))
    parts += ['<div class="coverage">', p(f"{len(meta['sample'])} pages in the declared sample · {len(actions)} improvement actions · {assessed} of {total} detailed topics assessed."),
              p(f'{unresolved_count} detailed checks remain unresolved or unrecorded. Counts describe review coverage, not website quality.'), '</div>',
              p('AI visibility not measured by this report. These findings concern website readiness; they do not predict citations, traffic or revenue.', 'limit'),
              p('Overall core score withheld: at least one required area is incomplete.' if scores['overall'] is None else 'Core scores and their precise scope are provided in the methodology appendix.', 'limit'), '</section>',
              '<section class="decision" id="actions"><h2>Prioritised action plan</h2>',
              p('Short action previews link to the full evidence and completion checks. Order follows recorded severity. Effort and ownership need scoping; the saved audit contains no estimates.', 'intro')]
    if actions:
        parts += ['<table class="actions"><caption>Supported improvements</caption><thead><tr><th scope="col">Priority</th><th scope="col">Action and evidence</th><th scope="col">Affected pages</th></tr></thead><tbody>']
        for x in actions:
            f=x['finding']; scope='Declared sample' if set(f['affected_urls']) == sample else '; '.join(label(u) for u in f['affected_urls'])
            parts.append(f'<tr><td data-label="Priority">{e(f["severity"].capitalize())}</td><td data-label="Action">{jump(action_preview(f["fix"]),x["anchor"])}</td><td data-label="Pages">{e(excerpt(scope,100))}</td></tr>')
        parts.append('</tbody></table>')
    else: parts.append(p('No supported improvement actions were recorded.'))
    parts += ['<h3>Verify before changing</h3>']
    pending_core=[jump('Core check: '+CRITERION_NAMES[c['id']], 'core-check-'+c['id']) for c in model['core_unknown']]
    pending=pending_core+[jump(excerpt(x['finding']['claim'],100),x['anchor']) for x in model['verification']]+[jump(x['label'],x['anchor']) for x in model['outstanding']]
    parts.append('<ul class="verification-index">'+''.join(f'<li>{x}</li>' for x in pending)+'</ul>' if pending else p('No unresolved findings or detailed checks recorded.'))
    parts += ['</section><nav id="contents" aria-label="Report contents"><h2>In this report</h2><ul>']
    contents=[('Findings and evidence','findings')]+[(v,'category-'+k) for k,v in CATEGORY_NAMES.items()]+[('Outstanding checks and limitations','outstanding'),('Scope and scoring method','method')]
    parts+=['<li>'+jump(t,a)+'</li>' for t,a in contents]
    parts+=['</ul></nav><section id="findings"><h2>Findings and evidence</h2>']
    if actions:parts += [finding(x) for x in actions]
    else:parts.append(p('No supported improvement findings recorded.'))
    if model['context']:
        parts.append('<h3>Context and strengths to preserve</h3>')
        parts += [finding(x) for x in model['context']]
    parts.append('</section>')
    for category, topics in TOPICS.items():
        parts.append(f'<section id="category-{category}"><h2>{e(CATEGORY_NAMES[category])}</h2>')
        items=[(t,label,model['recorded'].get((category,t))) for t,label in topics.items()]
        any_assessed=False
        for topic,title,item in items:
            if item and item['status']=='assessed':
                any_assessed=True
                parts += ['<div class="review-topic">',f'<h3>{e(title)}</h3>',p(item['summary'])]
                if set(item['affected_urls'])!=sample:parts.append(page_scope(item['affected_urls']))
                parts += [sources(item['evidence_ids']),'</div>']
        if not any_assessed:
            parts.append(p('No separate detailed topic assessment is available for this area. Core checks, if recorded, are explained in the methodology appendix.'))
        count=sum(1 for _,_,x in items if x is None or x['status']=='unknown')
        if count:parts.append('<p class="scope">'+jump(f'{count} unresolved or unrecorded checks in this area','outstanding')+'</p>')
        parts.append('</section>')
    parts += ['<section id="outstanding"><h2>Outstanding checks and limitations</h2>',p('These are evidence gaps or hypotheses, not confirmed defects. Resolve them before drawing a stronger conclusion.')]
    parts += [finding(x) for x in model['verification']]
    for c in model['core_unknown']:
        parts += [f'<article class="pending" id="core-check-{c["id"]}"><h3>{e(CRITERION_NAMES[c["id"]])}</h3>',p(c.get('rationale','No core assessment supplied.')),sources(c.get('evidence_ids',[])),'</article>']
    parts.append('<h3>Detailed checks to complete</h3>')
    for x in model['outstanding']+model['excluded']:
        item=x['review']; text='no separate assessment recorded.' if item is None else item['summary']
        if item and item['status']=='not_applicable':text='Not applicable: '+text
        parts += [f'<article class="pending" id="{x["anchor"]}"><h4>{e(x["label"])}</h4>',p(text)]
        if item:parts += [page_scope(item['affected_urls']),sources(item['evidence_ids'])]
        parts.append('</article>')
    parts += ['<h3>Limits of this run</h3><ul>']+[f'<li>{e(x)}</li>' for x in run['limitations']]+['</ul></section>']
    parts += ['<section id="method"><h2>Scope and scoring method</h2>',
              p(f"Declared sample: {len(meta['sample'])} pages. Audit date: {readable_date}. Business: {meta['business_type']}. Market: {meta['market']}. Language: {meta['language']}."),p(meta['sampling_rationale']),
              p(f'Detailed review topics with a recorded assessment: {assessed} of {total}. Some topics cover only a subset of pages; this is not whole-site completeness.'),
              '<h3>Core readiness overview — not a complete health score</h3>',
              p('Each criterion uses a coarse editorial anchor: 0 means none, 50 some, and 100 all applicable reviewed pages meet it. Category scores average two criteria. An unknown required criterion withholds its category score and the overall score. These values are not probabilities or measurements of AI visibility.'),
              '<table><caption>Core scores and exactly what they cover</caption><thead><tr><th scope="col">Area / score</th><th scope="col">Scored checks</th></tr></thead><tbody>']
    for category,row in scores['categories'].items():
        criteria=[x for x in scores['criteria'] if x['category']==category]
        score='Incomplete' if row['score'] is None else f'{row["score"]:g}/100'
        desc='; '.join(CRITERION_NAMES[x['id']] for x in criteria)
        if category=='technical':desc+=' (does not score speed, mobile usability or security)'
        parts.append(f'<tr><td>{e(CATEGORY_NAMES[category])}<br><strong>{score}</strong></td><td>{e(desc)}</td></tr>')
    parts += ['</tbody></table>',p('Overall core score is withheld because one or more required areas are incomplete.' if scores['overall'] is None else f'Overall core score: {scores["overall"]:g}/100.'),
              p(f'Core scoring methodology: {scores["rubric_version"]}. Evidence, collection dates and integrity checks remain in the saved run. Raw captures are available through a separate technical export. Links in this report point to live sources that may have changed since collection.')]
    # Core explanations remain accessible even when detailed reviews exist.
    parts.append(p('Detailed criterion rationales are available in the HTML report and saved run.', 'print-only'))
    parts.append('<details><summary>How the core criteria were assessed</summary>')
    for c in scores['criteria']:
        if c['status']=='unknown':continue
        parts += [f'<h4>{e(CRITERION_NAMES[c["id"]])}</h4>',p(c.get('rationale','No assessment supplied.'))]
    parts += ['</details><h3>Reviewed pages</h3><ol class="sample">']
    parts += [f'<li>{safe_link(u,u)}</li>' for u in meta['sample']]
    parts += ['</ol></section></main><footer>',p(f'{author} · GEO Audit · {readable_date}'),'</footer></body></html>']
    html='\n'.join(parts)
    check_report_integrity(html,run,model)
    return html


def check_report_integrity(html, run, model):
    """Fail export if navigation or material findings disappear during changes."""
    anchors=re.findall(r'\bid="([^"]+)"',html)
    if len(anchors)!=len(set(anchors)):
        raise ValueError('Duplicate report navigation target')
    for target in re.findall(r'href="#([^"]+)"',html):
        if target not in anchors:raise ValueError(f'Missing report navigation target: {target}')
    for finding in run['findings']:
        for key in ('claim','observed','consequence','fix','acceptance','confidence_reason'):
            if escape(finding[key]) not in html:
                raise ValueError(f'Report lost finding detail: {key}')
    for x in model['outstanding']:
        if f'id="{x["anchor"]}"' not in html:raise ValueError('Report lost an unresolved check')


CLIENT_CSS = """
:root{--text:#1A1A18;--muted:#464644;--label:#6F6F68;--border:#CECECA;--surface:#FAFAF8;--secondary:#F4F4F0}
*{box-sizing:border-box}html{scroll-behavior:auto}body{margin:0;background:var(--surface);color:var(--text);font:15px/1.6 Inter,system-ui,sans-serif}main,footer{max-width:940px;margin:auto;padding:0 48px}section,nav{padding:32px 0;border-bottom:1px solid var(--border)}h1,h2,h3{font-family:AboutBeige,Georgia,serif;font-weight:600;line-height:1.2;letter-spacing:-.025em}h1{font-size:48px;margin:16px 0}h2{font-size:30px;margin:0 0 20px}h3{font-size:21px;margin:24px 0 12px}h4{font-size:16px;margin:20px 0 8px}p{margin:10px 0}a{color:inherit;text-underline-offset:3px;overflow-wrap:anywhere}a:hover{color:var(--muted)}a:focus-visible,summary:focus-visible{outline:2px solid var(--text);outline-offset:4px}.eyebrow,.byline,caption{font-family:'Geist Mono',monospace;font-size:12px;color:var(--label)}.eyebrow{letter-spacing:.1em}.site{font-size:20px}.byline{margin-bottom:28px}.scope,.sources,.intro,.limit{font-size:13px;color:var(--muted)}.coverage{border-left:3px solid var(--text);padding:4px 16px;margin:24px 0;background:var(--secondary)}.priorities{padding-left:22px}.priorities li{padding:4px 0}.finding{padding:24px 0;border-bottom:1px solid var(--border)}.finding:last-child{border:0}.finding h3{margin-top:8px}.finding .eyebrow{margin-bottom:4px}.finding strong{font-weight:650}.pending{margin:20px 0}.sources{font-size:12px}table{border-collapse:collapse;width:100%;table-layout:fixed;margin:16px 0;font-size:13px}caption{text-align:left;margin-bottom:8px}th,td{text-align:left;padding:12px 10px;vertical-align:top;border-bottom:1px solid var(--border);overflow-wrap:anywhere}th{background:var(--secondary);font-size:12px}tr{break-inside:avoid}.actions th:nth-child(1){width:14%}.actions th:nth-child(2){width:58%}.actions th:nth-child(3){width:28%}ul,ol{padding-left:22px}li{margin:6px 0}.verification-index{columns:2;column-gap:28px;font-size:13px}nav ul{columns:2;font-size:14px}.sample{font-size:13px}.skip{position:absolute;left:16px;top:-100px;padding:12px;background:white}.skip:focus{top:8px}footer{padding-top:20px;padding-bottom:20px;font-size:12px}.print-only{display:none}details{margin:24px 0}summary{cursor:pointer;font-weight:600}p,li{overflow-wrap:anywhere}
@media(max-width:600px){main,footer{padding-left:24px;padding-right:24px}h1{font-size:36px}h2{font-size:28px}.verification-index,nav ul{columns:1}.actions thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.actions,.actions tbody,.actions tr,.actions td{display:block}.actions tr{border-bottom:1px solid var(--border);padding:12px 0}.actions td{border:0;padding:4px 0}.actions td::before{content:attr(data-label) ': ';font-weight:650}}
@media print{@page{size:A4;margin:15mm 16mm 18mm}body{background:white;font-size:10.5pt;line-height:1.45}main,footer{max-width:none;padding:0}section,nav{padding:22px 0}h1{font-size:30pt}h2{font-size:20pt}h3{font-size:14pt}h4{font-size:11pt}h1,h2,h3,h4,caption{break-after:avoid;break-inside:avoid}p,li{widows:3;orphans:3}a{text-decoration:none}a[href^='#']{text-decoration:underline}.decision{break-after:page}.decision h2{margin-top:14px}.decision .intro,.decision .limit,.decision .scope{font-size:9.5pt}.actions{font-size:9pt}.actions th,.actions td{padding:8px}.finding{padding:16px 0;break-inside:auto}.finding .eyebrow,.finding .scope{break-after:avoid}.finding p{break-inside:avoid}.review-topic{break-inside:auto}.review-topic h3{break-after:avoid}.pending{break-inside:avoid}thead{display:table-header-group}nav{break-after:avoid}nav ul{font-size:10pt}.scope,.sources,.limit{font-size:9pt}.eyebrow,.byline,caption{font-size:9pt}.skip,footer,details{display:none}.print-only{display:block;font-size:9pt;color:var(--muted)}details:not([open])>*:not(summary){display:none}.verification-index{font-size:9pt}.coverage{margin:16px 0}li{margin:4px 0}}
"""
