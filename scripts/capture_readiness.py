"""Bounded, explicitly configured content checks and saved browser observations."""
import time

from evidence import parse_timestamp, strict_json

DEFAULT_TIMEOUT_MS = 10000
DEFAULT_SETTLE_MS = 500

# A visible element can be below the viewport. This checks document content,
# not whether a screenshot includes it or whether the page is usable.
VISIBLE_COUNT = """cfg => [...document.querySelectorAll(cfg.selector)].filter(el => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden'
        && style.visibility !== 'collapse' && style.display !== 'none';
}).length"""
MATCH_CONDITION = 'cfg => (' + VISIBLE_COUNT + ')(cfg) >= cfg.min_count'


def settings(*, selector=None, min_count=1, timeout_ms=DEFAULT_TIMEOUT_MS, settle_ms=DEFAULT_SETTLE_MS):
    if selector is not None:
        if not isinstance(selector, str) or not selector.strip() or len(selector) > 1000:
            raise ValueError('Ready selector must be nonempty CSS, up to 1000 characters')
        selector = selector.strip()
    for value, low, high, name in ((min_count, 1, 10000, 'minimum count'),
                                   (timeout_ms, 1, 30000, 'readiness timeout'),
                                   (settle_ms, 0, 5000, 'settle time')):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{name} must be an integer between {low} and {high}')
    if selector is None and min_count != 1:
        raise ValueError('A minimum count requires --ready-selector')
    return {'selector': selector, 'min_count': min_count, 'timeout_ms': timeout_ms, 'settle_ms': settle_ms}


def add_arguments(parser):
    parser.add_argument('--ready-selector', help='CSS selector for expected visible document content; no automatic clicks')
    parser.add_argument('--ready-min-count', type=int, default=1, help='Required matching visible elements (default: 1)')
    parser.add_argument('--ready-timeout-ms', type=int, default=DEFAULT_TIMEOUT_MS, help='Bounded condition wait, 1–30000 ms')
    parser.add_argument('--settle-ms', type=int, default=DEFAULT_SETTLE_MS, help='Initial settling interval, 0–5000 ms')


def from_arguments(args):
    return settings(selector=args.ready_selector, min_count=args.ready_min_count,
                    timeout_ms=args.ready_timeout_ms, settle_ms=args.settle_ms)


def wait_for_content(page, config):
    from playwright.sync_api import TimeoutError
    config = settings(**config)
    started = time.monotonic()
    page.wait_for_timeout(config['settle_ms'])
    result = {**config, 'status': 'unverified', 'matched_elements': None,
              'reason': 'No expected-content condition configured; saving a snapshot does not establish content readiness.'}
    if config['selector'] is not None:
        try:
            page.wait_for_function(MATCH_CONDITION, arg=config, polling=100, timeout=config['timeout_ms'])
            result.update(status='met', reason='The configured visible-element condition was observed.')
        except TimeoutError:
            result.update(status='timeout', reason='The configured visible-element condition was not observed before timeout.')
        result['matched_elements'] = page.evaluate(VISIBLE_COUNT, config)
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    return result


def latest_browser_observations(run):
    """Read saved measurements only; historical captures remain in run.json.

    Absence of readiness metadata on an older capture never implies verification.
    Unknown or malformed measurement payloads are ignored, not executed.
    """
    latest = {}
    sample = set(run['metadata']['sample'])
    for index, record in enumerate(run['assessment']['evidence']):
        if (record['source'] not in sample or record['status'] != 'success'
                or not record['method'].startswith('browser_collect.py ')):
            continue
        try:
            header, separator, _ = record['content'].partition('\n\nRendered DOM:\n')
            if not separator:
                continue
            measurements = strict_json(header.split('\n', 1)[1])
            viewport = measurements.get('viewport_name')
            if not isinstance(viewport, str) or viewport not in {'desktop', 'mobile'}:
                continue
            key = (record['source'], viewport)
            order = (parse_timestamp(record['collected_at']), index)
            if key not in latest or order > latest[key][0]:
                latest[key] = (order, {'url': record['source'], 'viewport': viewport, 'measurements': measurements})
        except (ValueError, IndexError, AttributeError):
            continue
    return [item[1] for item in latest.values()]
