"""Deterministic capture-quality prompts derived from saved evidence.

A prompt means a saved capture may not show useful page content, for example an
error response, a possible bot challenge or a nearly empty render. Prompts ask a
reviewer to check; they never establish a defect, and an absent prompt never
establishes a healthy or complete page. Only records written by collect.py and
browser_collect.py are interpreted; other capture methods yield no prompts.
"""
from collect import Response, flags, visible_text
from evidence import document_title, parse_timestamp, strict_json

HTTP_METHOD = 'collect.py '
BROWSER_METHOD = 'browser_collect.py '
DOM_SEPARATOR = '\n\nRendered DOM:\n'
# Matches collect.py's thin_response threshold, applied to rendered text.
THIN_TEXT = 200

# The capture may not show the requested page at all.
FAILURE = ('http_error', 'redirect_not_followed', 'possible_challenge', 'possible_soft_404', 'non_text_body')
# The capture shows the page, but possibly without its main content.
THIN = ('thin_response', 'readiness_timeout', 'thin_render')
DEGRADED = FAILURE + THIN
# Directives describe the page rather than the capture, so they are listed but never degrade it.
DIRECTIVES = ('noindex_meta', 'noindex_header')
# Checks of the response itself: status, redirects and errors are what they report.
RESPONSE_CHECKS = {'review.technical.responses'}
# Checks drawn from response headers and markup, valid even when visible text is missing.
HTTP_LEVEL_CHECKS = {'core.technical.search_directives', 'review.technical.robots', 'review.technical.sitemaps',
                     'review.technical.metadata', 'review.technical.security', 'review.technical.urls_links',
                     'finding.technical'}


def label(code, status=None):
    return {
        'http_error': f'HTTP {status} response',
        'redirect_not_followed': f'HTTP {status} redirect not followed',
        'possible_challenge': 'possible bot challenge',
        'possible_soft_404': 'possible "not found" page returned with HTTP 200',
        'thin_response': 'little visible text in the HTML response',
        'non_text_body': 'non-HTML body; text not inspected',
        'readiness_timeout': 'expected content not observed before timeout',
        'thin_render': 'little visible text after rendering',
        'noindex_meta': 'noindex meta directive',
        'noindex_header': 'noindex response header',
    }[code]


def http_observation(record):
    """Status, prompts and directives from a collect.py record; None when the format is not recognised."""
    head, separator, body = record['content'].partition('\n\n')
    lines = head.split('\n')
    if not separator or not lines[0].startswith('Request: GET '):
        return None
    status, headers, final_seen = None, [], False
    for line in lines[1:]:
        if line.startswith('Response: '):
            code = line.split(' ', 2)[1] if line.count(' ') else ''
            status = int(code) if code.isdigit() else None
        elif line.startswith('Final URL: '):
            final_seen = True
        elif final_seen and not line.startswith('Note: '):
            key, colon, value = line.partition(': ')
            if colon:
                headers.append((key, value))
    if status is None:
        return None
    binary = body.startswith(('[Binary body omitted', '[Non-HTML body omitted', '[Binary robots.txt body'))
    response = Response(record['source'], status, '', headers, b'')
    codes = list(flags(response, None if binary else body))
    if 300 <= status < 400:
        codes.insert(0, 'redirect_not_followed')
    elif not 200 <= status < 300:
        codes.insert(0, 'http_error')
    if binary:
        codes.append('non_text_body')
    return {'kind': 'http', 'http_status': status, 'codes': codes}


def browser_observation(record):
    header, separator, dom = record['content'].partition(DOM_SEPARATOR)
    if not separator:
        return None
    try:
        measurements = strict_json(header.split('\n', 1)[1])
    except (ValueError, IndexError):
        return None
    if not isinstance(measurements, dict):
        return None
    status = measurements.get('http_status')
    status = status if type(status) is int else None
    readiness = measurements.get('content_readiness')
    readiness = readiness.get('status') if isinstance(readiness, dict) else None
    blocked = measurements.get('blocked_requests')
    codes = []
    if status is not None and not 200 <= status < 300:
        codes.append('http_error')
    if readiness == 'timeout':
        codes.append('readiness_timeout')
    if len(visible_text(dom)) < THIN_TEXT:
        codes.append('thin_render')
    viewport = measurements.get('viewport_name')
    return {'kind': 'browser', 'http_status': status, 'codes': codes,
            # A tuple, so a malformed unhashable value is rejected rather than raising.
            'viewport': viewport if viewport in ('desktop', 'mobile') else None,
            'readiness': readiness if isinstance(readiness, str) else 'not_recorded',
            'blocked_requests': len(blocked) if isinstance(blocked, list) else 0}


def observe(record):
    """Interpret one successful collector record, or return None when no prompt can be derived."""
    if record['status'] != 'success':
        return None
    if record['method'].startswith(HTTP_METHOD):
        return http_observation(record)
    if record['method'].startswith(BROWSER_METHOD):
        return browser_observation(record)
    return None


def degraded(observation):
    return observation is not None and any(code in DEGRADED for code in observation['codes'])


def failed(observation):
    return observation is not None and any(code in FAILURE for code in observation['codes'])


def labels(observation, codes=None):
    codes = observation['codes'] if codes is None else codes
    return [label(code, observation['http_status']) for code in codes]


def degraded_labels(observation):
    return labels(observation, [code for code in observation['codes'] if code in DEGRADED])


class Observations:
    """Interprets each record once; captures can be several megabytes."""

    def __init__(self, registry):
        self.registry, self.cache = registry, {}

    def __call__(self, identifier):
        if identifier not in self.cache:
            self.cache[identifier] = observe(self.registry[identifier])
        return self.cache[identifier]


def conclusion_uses(run):
    """(check, evidence IDs, page URLs) for every recorded conclusion that is not unknown."""
    sample = run['metadata']['sample']
    for category, items in run['assessment']['criteria'].items():
        for item in items:
            if isinstance(item, dict) and item.get('status') in {'assessed', 'not_applicable'}:
                yield f"core.{category}.{item['id']}", item['evidence_ids'], sample
    for item in run.get('review', []):
        if item['status'] != 'unknown':
            yield f"review.{item['category']}.{item['topic']}", item['evidence_ids'], item['affected_urls']
    for finding in run['findings']:
        if finding['kind'] != 'unknown':
            yield f"finding.{finding['category']}", finding['evidence_ids'], finding['affected_urls']


def relevant(observation, check):
    """Prompts that undermine this kind of conclusion; missing text does not void a header check."""
    if observation is None or check in RESPONSE_CHECKS:
        return []
    allowed = FAILURE if check in HTTP_LEVEL_CHECKS else DEGRADED
    return [code for code in observation['codes'] if code in allowed]


def conclusion_warnings(run, registry):
    """Warn when a page's recorded conclusions rest only on captures with relevant prompts.

    A conclusion that also cites an unprompted capture of the same page is not
    flagged. Deliberately reported errors still need a reviewer's acknowledgement.
    """
    observe_id = Observations(registry)
    pages = {}
    for check, ids, urls in conclusion_uses(run):
        for url in urls:
            cited = [key for key in ids if registry[key]['source'] == url and registry[key]['status'] == 'success']
            prompts = [(observe_id(key), relevant(observe_id(key), check)) for key in cited]
            if prompts and all(codes for _, codes in prompts):
                for observation, codes in prompts:
                    pages.setdefault(url, set()).update(labels(observation, codes))
    warnings = [f'Sample page {url}: assessed conclusions rely only on captures with review prompts '
                f'({"; ".join(sorted(pages[url]))}); confirm them against other evidence or mark them unknown'
                for url in run['metadata']['sample'] if url in pages]
    for item in run['assessment']['criteria'].get('technical', []):
        if isinstance(item, dict) and item.get('id') == 'search_directives' and item.get('value') == 100:
            for key in item['evidence_ids']:
                observation = observe_id(key)
                directives = [code for code in (observation or {}).get('codes', []) if code in DIRECTIVES]
                if directives and registry[key]['source'] in run['metadata']['sample']:
                    warnings.append(f'Evidence {key} has a {" and ".join(labels(observation, directives))}, '
                                    'but search_directives is scored 100; check the effective directive')
    return warnings


def review_prompts(identifiers, registry):
    """Readable degraded-capture prompts for the evidence behind an action review."""
    result = []
    for identifier in identifiers:
        observation = observe(registry[identifier]) if identifier in registry else None
        if degraded(observation):
            result.append(f"{registry[identifier]['source']}: {', '.join(degraded_labels(observation))}")
    return result


def latest(records, method):
    """The latest successful record, otherwise the latest attempt, for one capture method."""
    chosen = [record for record in records if record['method'].startswith(method)]
    if not chosen:
        return None
    ordered = sorted(enumerate(chosen), key=lambda pair: (pair[1]['status'] == 'success',
                                                          parse_timestamp(pair[1]['collected_at']), pair[0]))
    return ordered[-1][1]


def page_summary(sample, records):
    """Latest HTTP capture and latest rendered observation per viewport for each sample URL."""
    pages = []
    for url in sample:
        own = [record for record in records if record['source'] == url]
        http_record = latest(own, HTTP_METHOD)
        # Captures saved another way (evidence.py, older runs) exist but yield no prompts.
        other = any(record['status'] == 'success' and not record['method'].startswith((HTTP_METHOD, BROWSER_METHOD))
                    for record in own)
        http = {'state': 'other' if other else 'missing'}
        if http_record is not None:
            observation = observe(http_record)
            http = {'state': http_record['status'], 'http_status': observation and observation['http_status'],
                    'prompts': labels(observation) if observation else []}
            if observation:
                http['degraded'] = degraded(observation)
        browser = {}
        for viewport in ('desktop', 'mobile'):
            candidates = [record for record in own if record['method'].startswith(BROWSER_METHOD)
                          and record['method'].endswith(f'({viewport})')]
            record = latest(candidates, BROWSER_METHOD)
            if record is None:
                continue
            observation = observe(record)
            browser[viewport] = {'state': record['status'],
                                 'readiness': observation['readiness'] if observation else None,
                                 'prompts': labels(observation) if observation else [],
                                 'degraded': degraded(observation)}
        states = {'failed': 'collection failed', 'unavailable': 'not collected under the robots.txt or address policy',
                  'missing': 'no saved capture'}
        # Each prompt once, naming the captures that raised it.
        seen = {}
        captures = [('HTTP capture', 'HTTP', http), *((viewport, 'Rendered', item) for viewport, item in browser.items())]
        for source, prefix, item in captures:
            texts = [f"{prefix} {states[item['state']]}"] if item['state'] in states else item.get('prompts', [])
            for text in texts:
                seen.setdefault(text, []).append(source)
        sources = 1 + len(browser) if http['state'] != 'missing' else len(browser)
        prompts = [text if sources <= 1 else f'{text} ({where(found, sources)})' for text, found in seen.items()]
        attention = (http['state'] not in {'success', 'other'} or http.get('degraded', False)
                     or any(item['state'] != 'success' or item['degraded'] for item in browser.values()))
        pages.append({'url': url, 'http': http, 'browser': browser, 'prompts': prompts, 'kinds': list(seen),
                      'attention': attention, 'title_usable': not any(code in FAILURE for code in failure_codes(own)),
                      'title': page_title(own)})
    return pages


def where(found, available):
    if len(found) == available:
        return 'all captures'
    if found == ['desktop', 'mobile']:
        return 'desktop and mobile'
    return ', '.join(found)


def failure_codes(records):
    """Failure prompts in the latest successful HTTP capture, whose title may name an error page."""
    record = latest([item for item in records if item['status'] == 'success'], HTTP_METHOD)
    observation = observe(record) if record else None
    return observation['codes'] if observation else []


def page_title(records):
    """Title of the capture that names the page, or None when that capture may show an error page.

    The latest successful HTTP capture names the page, as in page_summary, so an earlier rate-limit or
    challenge page never does. Without one, the latest other successful capture with no failure prompt does.
    """
    successful = [record for record in records if record['status'] == 'success']
    record = latest(successful, HTTP_METHOD) or latest([item for item in successful if not failed(observe(item))], '')
    if record is None or failed(observe(record)):
        return None
    head, separator, dom = record['content'].partition(DOM_SEPARATOR)
    return document_title(dom if separator else head)
