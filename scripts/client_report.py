"""Client presentation of validated runs; never changes evidence or scoring."""
from datetime import date
from html import escape
import base64
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, unquote
from review_topics import TOPICS, CATEGORY_NAMES, CRITERION_NAMES
from version import TOOLKIT_VERSION
from evidence import document_title
from capture_readiness import latest_browser_observations


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


# A full stop after these words (or after initials such as "U.S.") does not end a sentence.
ABBREVIATIONS = {'e.g', 'i.e', 'etc', 'vs', 'approx', 'incl', 'esp', 'cf', 'fig', 'no', 'nos', 'dr', 'mr', 'mrs',
                 'ms', 'st', 'ltd', 'inc', 'co', 'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'sept',
                 'oct', 'nov', 'dec'}


def first_sentence(text):
    text = text.strip()
    for match in re.finditer(r'[.!?]\s+', text):
        if text[match.start()] == '.':
            before = text[:match.start()].split()
            word = before[-1].lstrip('([{"\'‘“').lower() if before else ''
            if word in ABBREVIATIONS or re.fullmatch(r'(?:[a-z]\.)*[a-z]', word):
                continue
        return text[:match.start() + 1]
    return text


def action_preview(text):
    """Prefer a complete first sentence to a cut-off instruction."""
    return excerpt(first_sentence(text), 230)


def plural(count, singular, plural_form=None):
    return f'{count} {singular if count == 1 else plural_form or singular + "s"}'


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


LANGUAGE_TAG = re.compile(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*')


def render_client_html(data, author='GEO Audit', domain='', content_lang=None):
    """content_lang is a BCP 47 tag for run-written prose when it differs from the English template."""
    if domain and not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', domain):
        raise ValueError('GEO_AUDIT_DOMAIN must be a hostname')
    if content_lang is not None and not LANGUAGE_TAG.fullmatch(content_lang):
        raise ValueError('Content language must be a BCP 47 tag such as el or pt-BR')
    report = _ClientReport(data['run'], data['scores'], author, domain, content_lang)
    report.delivery = data.get('delivery', {'state': 'draft'})
    html = '\n'.join(report.parts())
    check_report_integrity(html, report.run, report.model)
    return html


def paragraph(text, cls=''):
    attribute = f' class="{cls}"' if cls else ''
    return f'<p{attribute}>{escape(text)}</p>'


def jump(label, anchor, attributes=''):
    # Anchors are generated by this module, never taken from report text.
    return f'<a href="#{anchor}"{attributes}>{escape(label)}</a>'


def page_label(url, title=None):
    try:
        parsed = urlsplit(url)
        segments = [unquote(part) for part in parsed.path.strip('/').split('/') if part]
        if segments and segments[-1].lower() in {'index.html', 'index.htm'}:
            segments.pop()
        path = segments[-1] if segments else ''
        if path.isdigit() and len(segments) > 1:
            path = ' '.join(segments[-2:])
        path = re.sub(r'\.html?$', '', path, flags=re.I)
        path = re.sub(r'_\d+$', '', path).replace('-', ' ').replace('_', ' ')
        title = ' '.join(title.split()).split(' | ', 1)[0] if isinstance(title, str) else ''
        query = f' (?{unquote(parsed.query)})' if parsed.query else ''
        return (excerpt(title, 90) if title and parsed.path.strip('/') else path or 'Homepage') + query
    except ValueError:
        return url


def delivery_check_label(key):
    group, category, check = key.split('.')
    label = CRITERION_NAMES[check] if group == 'core' else TOPICS[category][check]
    return f'{CATEGORY_NAMES[category]}: {label}'


class _ClientReport:
    """Client HTML for one validated run. Every run-supplied string is escaped."""

    def __init__(self, run, scores, author, domain, content_lang=None):
        self.run, self.scores = run, scores
        self.author, self.domain = author, domain
        # Marks run-written prose so assistive technology reads it in its own language.
        self.lang = f' lang="{content_lang}"' if content_lang else ''
        self.meta = run['metadata']
        self.model = report_model(run, scores)
        self.registry = {x['id']: x for x in run['assessment']['evidence']}
        self.sample = set(self.meta['sample'])
        self.readable_date = date.fromisoformat(self.meta['date']).strftime('%d %B %Y').lstrip('0')
        self.assessed = sum(x['status'] == 'assessed' for x in run.get('review', []))
        self.total = sum(len(t) for t in TOPICS.values())
        titles = {}
        for record in run['assessment']['evidence']:
            if record['source'] in self.sample and record['source'] not in titles and record['status'] == 'success':
                dom = record['content'].partition('\n\nRendered DOM:\n')
                titles[record['source']] = document_title(dom[2] if dom[1] else dom[0])
        self.labels = {url: page_label(url, titles.get(url)) for url in self.sample}
        labels = list(self.labels.values())
        self.labels = {url: label + (' · ' + page_label(url) if labels.count(label) > 1 else '')
                       for url, label in self.labels.items()}
        self.browser_observations = latest_browser_observations(run)

    def parts(self):
        return (self.head() + self.decision_summary() + self.action_plan() + self.contents()
                + self.findings() + self.category_reviews() + self.collection_conditions()
                + self.outstanding() + self.method())

    # Shared fragments

    def prose(self, text):
        """Escaped run-written text, tagged with its language when that was supplied."""
        return f'<span{self.lang}>{escape(text)}</span>' if self.lang else escape(text)

    def prose_paragraph(self, text, prefix=''):
        if prefix:
            return f'<p>{escape(prefix)}{self.prose(text)}</p>'
        return f'<p{self.lang}>{escape(text)}</p>'

    def readable_warning(self, warning):
        for identifier, record in sorted(self.registry.items(), key=lambda pair: -len(pair[0])):
            warning = re.sub(r'\b[Ee]vidence ' + re.escape(identifier) + r'(?=\s|[,;:]|$)',
                             lambda _match, source=record['source']: 'Saved capture of ' + source, warning)
        for finding in self.run['findings']:
            warning = warning.replace('Finding ' + finding['id'] + ' ', finding['claim'] + ': ')
        for identifier, label in CRITERION_NAMES.items():
            warning = warning.replace(identifier, label)
        return warning.replace('no_structured_data_in_sample', 'no structured information in the sample')

    def page_scope(self, urls):
        if set(urls) == self.sample:
            return paragraph('Applies to the declared sample.', 'scope')
        return '<p class="scope">Pages: ' + '; '.join(safe_link(self.labels[u], u) for u in urls) + '.</p>'

    def sources(self, ids):
        external = []
        for identifier in ids:
            source = self.registry[identifier]['source']
            if source.startswith(('http://', 'https://')) and source not in self.sample and source not in external:
                external.append(source)
        if not external:
            return ''
        return '<p class="sources">Sources: ' + ' · '.join(safe_link(excerpt(url, 90), url) for url in external) + '</p>'

    def finding(self, item):
        f, anchor = item['finding'], item['anchor']
        kind = {'observation': 'Observed', 'recommendation': 'Recommendation',
                'hypothesis': 'Hypothesis — verify first', 'unknown': 'Unresolved'}[f['kind']]
        parts = [f'<article class="finding" id="{anchor}">',
                 paragraph(f"{kind} · {f['severity'].capitalize()} priority", 'eyebrow'),
                 f'<h3{self.lang}>{escape(f["claim"])}</h3>',
                 self.page_scope(f['affected_urls'])]
        for key, title in [('observed', 'Evidence'), ('consequence', 'Why it matters'), ('fix', 'Recommended action'),
                           ('acceptance', 'Completion check'), ('confidence_reason', 'Confidence and limits')]:
            parts.append(f'<p><strong>{title}.</strong> {self.prose(f[key])}</p>')
        parts += [self.sources(f['evidence_ids']), '</article>']
        return '\n'.join(parts)

    # Sections, in reading order

    def head(self):
        host = escape(urlsplit(self.meta['url']).netloc)
        return ['<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width, initial-scale=1">',
                f'<meta name="geo-client-report" content="{TOOLKIT_VERSION}"><title>GEO Audit Report — {host}</title><style>',
                CLIENT_CSS, '.delivery-state{border:2px solid currentColor;padding:10px 14px;font-weight:700}',
                font_css(), '</style>',
                f'<meta name="geo-delivery-state" content="{self.delivery["state"]}"></head><body>',
                '<a class="skip" href="#actions">Skip to action plan</a><main id="report">']

    def decision_summary(self):
        actions = self.model['actions']
        byline = f'Prepared by {self.author}' + (f' · {self.domain}' if self.domain else '')
        parts = ['<section class="decision" id="summary">',
                 paragraph('Reviewed final report' if self.delivery['state'] == 'ready'
                           else 'DRAFT — review required before delivery', 'delivery-state'),
                 paragraph(f'GEO Audit · {self.readable_date}', 'eyebrow'),
                 '<h1>Website readiness review</h1>',
                 paragraph(self.meta['url'], 'site'),
                 paragraph(byline, 'byline'),
                 '<h2>The decision summary</h2>',
                 self.prose_paragraph(self.run['summary']),
                 '<h3>Start here</h3>']
        if actions:
            parts.append('<ol class="priorities">' + ''.join(
                '<li>' + jump(action_preview(x['finding']['fix']), x['anchor'], self.lang) + '</li>'
                for x in actions[:3]) + '</ol>')
        else:
            parts.append(paragraph('No supported improvement actions were recorded. '
                                   'This does not establish a clean bill of health.'))
        if self.scores['overall'] is None:
            score_note = 'Overall core score withheld: at least one required area is incomplete.'
        else:
            score_note = 'Core scores and their precise scope are provided in the methodology appendix.'
        parts += ['<div class="coverage">',
                  paragraph(f"{plural(len(self.meta['sample']), 'page')} in the declared sample · "
                            f"{plural(len(actions), 'improvement action')} · "
                            f"{self.assessed} of {self.total} detailed topics assessed."),
                  paragraph(f"{plural(len(self.model['outstanding']), 'detailed check')} "
                            f"{'remains' if len(self.model['outstanding']) == 1 else 'remain'} unresolved or "
                            'unrecorded. Counts describe review coverage, not website quality.'),
                  '</div>',
                  paragraph('AI visibility not measured by this report. These findings concern website readiness; '
                            'they do not predict citations, traffic or revenue.', 'limit'),
                  paragraph(score_note, 'limit'),
                  '</section>']
        if self.delivery['state'] == 'ready':
            details = [paragraph(f"Reviewed by {self.delivery['reviewer']} · {self.delivery['reviewed_at']}")]
            if self.delivery['exclusions']:
                details.append('<h3>Agreed scope exclusions</h3><ul>' + ''.join(
                    f'<li>{escape(delivery_check_label(key))}: {escape(reason)}</li>'
                    for key, reason in self.delivery['exclusions'].items())
                               + '</ul>')
            if self.delivery['acknowledgements']:
                details.append('<h3>Review qualifications</h3><ul>' + ''.join(
                    f'<li>{escape(self.readable_warning(warning))}: {escape(reason)}</li>'
                    for warning, reason in self.delivery['acknowledgements'].items()) + '</ul>')
            parts[-1:-1] = details
        return parts

    def action_plan(self):
        actions = self.model['actions']
        parts = ['<section class="decision" id="actions"><h2>Prioritised action plan</h2>',
                 paragraph('Short action previews link to the full evidence and completion checks. Order follows '
                           'recorded severity. Effort and ownership need scoping; the saved audit contains no '
                           'estimates.', 'intro')]
        if actions:
            parts.append('<table class="actions"><caption>Supported improvements</caption><thead><tr>'
                         '<th scope="col">Priority</th><th scope="col">Action and evidence</th>'
                         '<th scope="col">Affected pages</th></tr></thead><tbody>')
            for x in actions:
                f = x['finding']
                if set(f['affected_urls']) == self.sample:
                    scope = 'Declared sample'
                else:
                    scope = '; '.join(self.labels[u] for u in f['affected_urls'])
                parts.append(f'<tr><td data-label="Priority">{escape(f["severity"].capitalize())}</td>'
                             f'<td data-label="Action">{jump(action_preview(f["fix"]), x["anchor"], self.lang)}</td>'
                             f'<td data-label="Pages">{escape(excerpt(scope, 100))}</td></tr>')
            parts.append('</tbody></table>')
        else:
            parts.append(paragraph('No supported improvement actions were recorded.'))
        parts.append('<h3>Verify before changing</h3>')
        pending = [jump('Core check: ' + CRITERION_NAMES[c['id']], 'core-check-' + c['id'])
                   for c in self.model['core_unknown']]
        pending += [jump(excerpt(x['finding']['claim'], 100), x['anchor'], self.lang)
                    for x in self.model['verification']]
        pending += [jump(x['label'], x['anchor']) for x in self.model['outstanding']]
        if pending:
            parts.append('<ul class="verification-index">' + ''.join(f'<li>{x}</li>' for x in pending) + '</ul>')
        else:
            parts.append(paragraph('No unresolved findings or detailed checks recorded.'))
        parts.append('</section>')
        return parts

    def contents(self):
        entries = [('Findings and evidence', 'findings')]
        entries += [(name, 'category-' + key) for key, name in CATEGORY_NAMES.items()]
        entries += [('Outstanding checks and limitations', 'outstanding'), ('Scope and scoring method', 'method')]
        if self.browser_observations:
            entries.insert(-2, ('Browser capture conditions', 'capture-conditions'))
        return (['<nav id="contents" aria-label="Report contents"><h2>In this report</h2><ul>']
                + ['<li>' + jump(title, anchor) + '</li>' for title, anchor in entries]
                + ['</ul></nav>'])

    def findings(self):
        parts = ['<section id="findings"><h2>Findings and evidence</h2>']
        if self.model['actions']:
            parts += [self.finding(x) for x in self.model['actions']]
        else:
            parts.append(paragraph('No supported improvement findings recorded.'))
        if self.model['context']:
            parts.append('<h3>Context and strengths to preserve</h3>')
            parts += [self.finding(x) for x in self.model['context']]
        parts.append('</section>')
        return parts

    def category_reviews(self):
        parts = []
        for category, topics in TOPICS.items():
            parts.append(f'<section id="category-{category}"><h2>{escape(CATEGORY_NAMES[category])}</h2>')
            items = [(title, self.model['recorded'].get((category, topic))) for topic, title in topics.items()]
            assessed = [(title, item) for title, item in items if item and item['status'] == 'assessed']
            for title, item in assessed:
                parts += ['<div class="review-topic">', f'<h3>{escape(title)}</h3>',
                          self.prose_paragraph(item['summary'])]
                if set(item['affected_urls']) != self.sample:
                    parts.append(self.page_scope(item['affected_urls']))
                parts += [self.sources(item['evidence_ids']), '</div>']
            if not assessed:
                parts.append(paragraph('No separate detailed topic assessment is available for this area. Core '
                                       'checks, if recorded, are explained in the methodology appendix.'))
            unresolved = sum(1 for _, item in items if item is None or item['status'] == 'unknown')
            if unresolved:
                parts.append('<p class="scope">'
                             + jump(f"{plural(unresolved, 'unresolved or unrecorded check')} in this area",
                                    'outstanding')
                             + '</p>')
            parts.append('</section>')
        return parts

    def outstanding(self):
        parts = ['<section id="outstanding"><h2>Outstanding checks and limitations</h2>',
                 paragraph('These are evidence gaps or hypotheses, not confirmed defects. Resolve them before '
                           'drawing a stronger conclusion.')]
        parts += [self.finding(x) for x in self.model['verification']]
        for c in self.model['core_unknown']:
            parts += [f'<article class="pending" id="core-check-{c["id"]}">'
                      f'<h3>{escape(CRITERION_NAMES[c["id"]])}</h3>',
                      self.prose_paragraph(c['rationale']) if 'rationale' in c
                      else paragraph('No core assessment supplied.'),
                      self.sources(c.get('evidence_ids', [])),
                      '</article>']
        parts.append('<h3>Detailed checks to complete</h3>')
        for x in self.model['outstanding'] + self.model['excluded']:
            item = x['review']
            if item is None:
                text = paragraph('no separate assessment recorded.')
            elif item['status'] == 'not_applicable':
                text = self.prose_paragraph(item['summary'], prefix='Not applicable: ')
            else:
                text = self.prose_paragraph(item['summary'])
            parts += [f'<article class="pending" id="{x["anchor"]}"><h4>{escape(x["label"])}</h4>', text]
            if item:
                parts += [self.page_scope(item['affected_urls']), self.sources(item['evidence_ids'])]
            parts.append('</article>')
        parts.append('<h3>Limits of this run</h3><ul>')
        parts += [f'<li{self.lang}>{escape(x)}</li>' for x in self.run['limitations']]
        parts.append('</ul></section>')
        return parts

    def collection_conditions(self):
        if not self.browser_observations:
            return []
        counts = dict.fromkeys(('met', 'unverified', 'timeout', 'not_recorded'), 0)
        caveats = {}
        for observation in self.browser_observations:
            values, viewport = observation['measurements'], observation['viewport']
            condition = values.get('content_readiness')
            state = condition.get('status') if isinstance(condition, dict) else 'not_recorded'
            state = state if isinstance(state, str) and state in counts else 'not_recorded'
            counts[state] += 1
            messages = []
            if state == 'timeout':
                messages.append('The expected-content condition timed out; this snapshot may be incomplete.')
            requested, actual = values.get('requested_viewport', {}), values.get('viewport', {})
            if viewport == 'mobile':
                requested_width = requested.get('width') if isinstance(requested, dict) else None
                actual_width = actual.get('width') if isinstance(actual, dict) else None
                if (type(requested_width) in (int, float) and type(actual_width) in (int, float)
                        and actual_width > requested_width):
                    messages.append(f'Layout width {actual_width:g} px for a {requested_width:g} px requested viewport; '
                                    'no overflow does not establish mobile usability.')
                if values.get('viewport_meta') is None:
                    messages.append('No viewport declaration was recorded.')
            blocked = values.get('blocked_requests')
            if isinstance(blocked, list) and blocked:
                hosts = set()
                for request in blocked[:150]:
                    try:
                        host = urlsplit(request.get('url', '')).hostname if isinstance(request, dict) else None
                        if host:
                            hosts.add(host)
                    except ValueError:
                        pass
                messages.append(f'{plural(len(blocked), "resource request")} blocked'
                                + (f' ({", ".join(sorted(hosts)[:5])})' if hosts else '')
                                + '; rendering fidelity needs review.')
            if messages:
                caveats.setdefault(observation['url'], []).append(viewport.capitalize() + ': ' + ' '.join(messages))
        parts = ['<section id="capture-conditions"><h2>Browser capture conditions</h2>',
                 paragraph(f"Latest saved observations by page and viewport: {counts['met']} configured content "
                           f"checks met; {counts['timeout']} timed out; "
                           f"{counts['unverified'] + counts['not_recorded']} unverified or not recorded."),
                 paragraph('Saving a snapshot establishes collection, not complete content. A met condition confirms '
                           'only the chosen document elements at that moment. These observations do not establish '
                           'site health, usability or accessibility.', 'limit')]
        for url, messages in caveats.items():
            parts += ['<div class="capture-condition">', f'<h3>{safe_link(self.labels[url], url)}</h3>',
                      '<ul>' + ''.join(f'<li>{escape(message)}</li>' for message in messages) + '</ul></div>']
        parts.append('</section>')
        return parts

    def method(self):
        meta, scores = self.meta, self.scores
        parts = ['<section id="method"><h2>Scope and scoring method</h2>',
                 paragraph(f"Declared sample: {plural(len(meta['sample']), 'page')}. Audit date: {self.readable_date}. "
                           f"Business: {meta['business_type']}. Market: {meta['market']}. "
                           f"Language: {meta['language']}."),
                 self.prose_paragraph(meta['sampling_rationale']),
                 paragraph(f'Detailed review topics with a recorded assessment: {self.assessed} of {self.total}. '
                           'Some topics cover only a subset of pages; this is not whole-site completeness.'),
                 '<h3>Core readiness overview — not a complete health score</h3>',
                 paragraph('Each criterion uses a coarse editorial anchor: 0 means none, 50 some, and 100 all '
                           'applicable reviewed pages meet it. Category scores average two criteria. An unknown '
                           'required criterion withholds its category score and the overall score. These values '
                           'are not probabilities or measurements of AI visibility.'),
                 '<table><caption>Core scores and exactly what they cover</caption><thead><tr>'
                 '<th scope="col">Area / score</th><th scope="col">Scored checks</th></tr></thead><tbody>']
        for category, row in scores['categories'].items():
            score = 'Incomplete' if row['score'] is None else f'{row["score"]:g}/100'
            checks = '; '.join(CRITERION_NAMES[x['id']] for x in scores['criteria'] if x['category'] == category)
            if category == 'technical':
                checks += ' (does not score speed, mobile usability or security)'
            parts.append(f'<tr><td>{escape(CATEGORY_NAMES[category])}<br><strong>{score}</strong></td>'
                         f'<td>{escape(checks)}</td></tr>')
        if scores['overall'] is None:
            overall = 'Overall core score is withheld because one or more required areas are incomplete.'
        else:
            overall = f'Overall core score: {scores["overall"]:g}/100.'
        parts += ['</tbody></table>',
                  paragraph(overall),
                  paragraph(f'Core scoring methodology: {scores["rubric_version"]}. Evidence, collection dates and '
                            'integrity checks remain in the saved run. Raw captures are available through a '
                            'separate technical export. Links in this report point to live sources that may have '
                            'changed since collection.'),
                  # Core explanations remain accessible even when detailed reviews exist.
                  paragraph('Detailed criterion rationales are available in the HTML report and saved run.',
                            'print-only'),
                  '<details><summary>How the core criteria were assessed</summary>']
        for c in scores['criteria']:
            if c['status'] != 'unknown':
                parts += [f'<h4>{escape(CRITERION_NAMES[c["id"]])}</h4>', self.prose_paragraph(c['rationale'])]
        parts.append('</details><div class="reviewed-pages"><h3>Reviewed pages</h3><ol class="sample">')
        parts += [f'<li>{safe_link(u, u)}</li>' for u in meta['sample']]
        parts += ['</ol></div></section></main><footer>',
                  paragraph(f'{self.author} · GEO Audit · {self.readable_date}'),
                  '</footer></body></html>']
        return parts


def check_report_integrity(html, run, model):
    """Fail export if navigation or material findings disappear during changes."""
    anchors = re.findall(r'\bid="([^"]+)"', html)
    if len(anchors) != len(set(anchors)):
        raise ValueError('Duplicate report navigation target')
    for target in re.findall(r'href="#([^"]+)"', html):
        if target not in anchors:
            raise ValueError(f'Missing report navigation target: {target}')
    for finding in run['findings']:
        for key in ('claim', 'observed', 'consequence', 'fix', 'acceptance', 'confidence_reason'):
            if escape(finding[key]) not in html:
                raise ValueError(f'Report lost finding detail: {key}')
    for x in model['outstanding']:
        if f'id="{x["anchor"]}"' not in html:
            raise ValueError('Report lost an unresolved check')


CLIENT_CSS = """
:root{--text:#1A1A18;--muted:#464644;--label:#6F6F68;--border:#CECECA;--surface:#FAFAF8;--secondary:#F4F4F0}
*{box-sizing:border-box}html{scroll-behavior:auto}body{margin:0;background:var(--surface);color:var(--text);font:15px/1.6 Inter,system-ui,sans-serif}main,footer{max-width:940px;margin:auto;padding:0 48px}section,nav{padding:32px 0;border-bottom:1px solid var(--border)}h1,h2,h3{font-family:AboutBeige,Georgia,serif;font-weight:600;line-height:1.2;letter-spacing:-.025em}h1{font-size:48px;margin:16px 0}h2{font-size:30px;margin:0 0 20px}h3{font-size:21px;margin:24px 0 12px}h4{font-size:16px;margin:20px 0 8px}p{margin:10px 0}a{color:inherit;text-underline-offset:3px;overflow-wrap:anywhere}a:hover{color:var(--muted)}a:focus-visible,summary:focus-visible{outline:2px solid var(--text);outline-offset:4px}.eyebrow,.byline,caption{font-family:'Geist Mono',monospace;font-size:12px;color:var(--label)}.eyebrow{letter-spacing:.1em}.site{font-size:20px}.byline{margin-bottom:28px}.scope,.sources,.intro,.limit{font-size:13px;color:var(--muted)}.coverage{border-left:3px solid var(--text);padding:4px 16px;margin:24px 0;background:var(--secondary)}.priorities{padding-left:22px}.priorities li{padding:4px 0}.finding{padding:24px 0;border-bottom:1px solid var(--border)}.finding:last-child{border:0}.finding h3{margin-top:8px}.finding .eyebrow{margin-bottom:4px}.finding strong{font-weight:650}.pending{margin:20px 0}.sources{font-size:12px}table{border-collapse:collapse;width:100%;table-layout:fixed;margin:16px 0;font-size:13px}caption{text-align:left;margin-bottom:8px}th,td{text-align:left;padding:12px 10px;vertical-align:top;border-bottom:1px solid var(--border);overflow-wrap:anywhere}th{background:var(--secondary);font-size:12px}tr{break-inside:avoid}.actions th:nth-child(1){width:14%}.actions th:nth-child(2){width:58%}.actions th:nth-child(3){width:28%}ul,ol{padding-left:22px}li{margin:6px 0}.verification-index{columns:2;column-gap:28px;font-size:13px}nav ul{columns:2;font-size:14px}.sample{font-size:13px}.skip{position:absolute;left:16px;top:-100px;padding:12px;background:white}.skip:focus{top:8px}footer{padding-top:20px;padding-bottom:20px;font-size:12px}.print-only{display:none}details{margin:24px 0}summary{cursor:pointer;font-weight:600}p,li{overflow-wrap:anywhere}
@media(max-width:600px){main,footer{padding-left:24px;padding-right:24px}h1{font-size:36px}h2{font-size:28px}.verification-index,nav ul{columns:1}.actions thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}.actions,.actions tbody,.actions tr,.actions td{display:block}.actions tr{border-bottom:1px solid var(--border);padding:12px 0}.actions td{border:0;padding:4px 0}.actions td::before{content:attr(data-label) ': ';font-weight:650}}
@media print{@page{size:A4;margin:15mm 16mm 18mm}body{background:white;font-size:10.5pt;line-height:1.45}main,footer{max-width:none;padding:0}section,nav{padding:22px 0}h1{font-size:30pt}h2{font-size:20pt}h3{font-size:14pt}h4{font-size:11pt}h1,h2,h3,h4,caption{break-after:avoid;break-inside:avoid}p,li{widows:3;orphans:3}a{text-decoration:none}a[href^='#']{text-decoration:underline}.decision{break-after:page}.decision h2{margin-top:14px}.decision .intro,.decision .limit,.decision .scope{font-size:9.5pt}.actions{font-size:9pt}.actions th,.actions td{padding:8px}.finding{padding:16px 0;break-inside:auto}.finding .eyebrow,.finding .scope{break-after:avoid}.finding p{break-inside:avoid}.review-topic{break-inside:auto}.review-topic h3{break-after:avoid}.pending{break-inside:avoid}thead{display:table-header-group}nav{break-after:avoid}nav ul{font-size:10pt}.scope,.sources,.limit{font-size:9pt}.eyebrow,.byline,caption{font-size:9pt}.skip,footer,details{display:none}.print-only{display:block;font-size:9pt;color:var(--muted)}details:not([open])>*:not(summary){display:none}.verification-index{font-size:9pt}.coverage{margin:16px 0}li{margin:4px 0}}
"""

# Compact methodology without shrinking the substantive findings or losing URLs.
CLIENT_CSS += """
@media print{#method{padding:16px 0}#method p{margin:6px 0;break-inside:avoid}#method table{margin:10px 0;font-size:9pt}#method th,#method td{padding:7px 8px}#method h3{margin:16px 0 10px}#method .sample li{margin:3px 0}.reviewed-pages,.capture-condition{break-inside:avoid}}
"""
