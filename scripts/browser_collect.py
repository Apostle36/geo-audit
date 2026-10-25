"""Opt-in desktop/mobile observations, without scoring or field performance claims.

Fresh browser contexts execute public site JavaScript. Only GET/HEAD requests
to the audited host or its www variant are allowed; private addresses, off-site
navigations, popups, downloads, service workers and WebSockets are blocked.
Robots rules apply to navigations. Asset requests use normal browser cadence.
This local tool is not a hardened sandbox; DNS rebinding is still a limitation.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from browser_runtime import launch_chromium
import capture_readiness
from collect import (Client, MAX_BYTES, MAX_REDIRECTS, REDIRECTS, TOKEN, USER_AGENT, allowed_for,
                     check_urls, follow, host_twins, now, record)
from safe_io import write_new
from version import TOOLKIT_VERSION

VIEWPORTS = {'desktop': {'width': 1440, 'height': 900}, 'mobile': {'width': 390, 'height': 844}}
METHOD = f'browser_collect.py {TOOLKIT_VERSION}: Chromium JavaScript observation'
LIMITATIONS = [
    'Viewport screenshots and DOM snapshots are observations, not a complete accessibility review.',
    'Navigation and paint timings are a single local lab observation; field Core Web Vitals and INP are not measured.',
    'Off-site assets, service workers, WebSockets, popups and non-GET/HEAD requests are blocked; rendering may differ.',
    'HTTP redirects are resolved before rendering; any further resource redirect is blocked and recorded.',
    'Generic browser access does not establish verified search or AI crawler access.',
]

MEASURE = """() => ({
    title: document.title,
    final_url: location.href,
    viewport: {width: innerWidth, height: innerHeight},
    viewport_meta: document.querySelector('meta[name="viewport"]')?.content ?? null,
    horizontal_overflow: document.documentElement.scrollWidth > innerWidth,
    headings: [...document.querySelectorAll('h1,h2,h3')].map(n => ({level:n.tagName, text:n.textContent})).slice(0,200),
    navigation: performance.getEntriesByType('navigation').map(n => ({
      responseStart:n.responseStart, responseEnd:n.responseEnd,
      domContentLoadedEventEnd:n.domContentLoadedEventEnd, loadEventEnd:n.loadEventEnd, duration:n.duration})),
    paints: performance.getEntriesByType('paint').map(n => ({name:n.name, startTime:n.startTime})),
    field_core_web_vitals: null, interaction_tested: false
})"""


class Policy:
    def __init__(self, client, url, max_requests=150):
        self.client, self.hosts = client, host_twins(url)
        self.blocked, self.requests, self.max_requests = [], 0, max_requests
        self.navigation_problem = None

    def block(self, url, reason, navigation=False):
        if len(self.blocked) < 150:
            self.blocked.append({'url': url, 'reason': reason})
        if navigation:
            self.navigation_problem = reason

    def reason(self, url, method='GET', navigation=False, redirects=0):
        self.requests += 1
        parts = urlsplit(url)
        if self.requests > self.max_requests:
            return 'request limit reached'
        if parts.scheme not in {'http', 'https'} or parts.username or parts.password:
            return 'only public HTTP(S) resources without credentials are allowed'
        if method not in {'GET', 'HEAD'}:
            return 'state-changing requests are blocked'
        if (parts.hostname or '').lower() not in self.hosts:
            return 'off-site resource or navigation'
        if redirects > MAX_REDIRECTS:
            return 'redirect limit reached'
        problem = self.client.refusal(url)
        if problem:
            return problem
        if navigation and not self.client.robots(url)[0].decision(TOKEN, url)['allowed']:
            return f'navigation disallowed by robots.txt for {TOKEN}'
        return None

    def route(self, route):
        request = route.request
        previous, redirects = request.redirected_from, 0
        while previous is not None:
            redirects += 1
            previous = previous.redirected_from
        reason = self.reason(request.url, request.method, request.is_navigation_request(), redirects)
        response = None
        if not reason:
            try:
                # continue_ can follow redirects without invoking routing again.
                # Fetch exactly one response, and never hand a redirect to Chromium.
                response = route.fetch(max_redirects=0, timeout=10000)
                if response.status in REDIRECTS and response.headers.get('location'):
                    reason = 'Further HTTP redirect blocked; resolve the URL in the HTTP collection first.'
                elif request.resource_type == 'document' and response.headers.get('content-disposition', '').lower().startswith('attachment'):
                    reason = 'document download blocked'
            except Exception as exc:
                reason = f'Resource request failed: {type(exc).__name__}: {exc}'
        if reason:
            self.block(request.url, reason, request.is_navigation_request())
            route.abort()
        else:
            route.fulfill(response=response)


def capture(client, url, output, *, identifier='browser-01', viewport='desktop', settle_ms=500,
            ready_selector=None, ready_min_count=1, ready_timeout_ms=10000):
    if check_urls([url]):
        raise ValueError('; '.join(check_urls([url])))
    if viewport not in VIEWPORTS:
        raise ValueError('Use desktop or mobile')
    readiness_config = capture_readiness.settings(selector=ready_selector, min_count=ready_min_count,
                                                  timeout_ms=ready_timeout_ms, settle_ms=settle_ms)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    log = {'url': url, 'viewport': viewport, 'limitations': list(LIMITATIONS)}
    policy = Policy(client, url)
    problem = policy.reason(url, navigation=True)
    status, content = 'unavailable', f'Browser observation unavailable: {problem}'
    if not problem:
        try:
            from playwright.sync_api import sync_playwright
            chain, notes, error = follow(client, url, host_twins(url), allowed_for(client))
            if error:
                raise ValueError(f'HTTP preflight failed: {error}')
            if chain[-1].location:
                target = chain[-1].location
                reason = policy.reason(target, navigation=True) or '; '.join(notes)
                policy.block(target, reason, navigation=True)
                raise ValueError(f'HTTP redirect could not be resolved: {reason}')
            navigation_url = chain[-1].url
            log['http_preflight'] = [{'url': hop.url, 'status': hop.status, 'location': hop.location} for hop in chain]
            with sync_playwright() as runtime:
                browser = launch_chromium(runtime)
                try:
                    context = browser.new_context(viewport=VIEWPORTS[viewport], is_mobile=viewport == 'mobile',
                                                  user_agent=USER_AGENT, service_workers='block', accept_downloads=False)
                    context.route('**/*', policy.route)
                    context.route_web_socket('**/*', lambda websocket: websocket.close())
                    page = context.new_page()
                    context.on('page', lambda opened: opened.close() if opened != page else None)
                    page.set_default_timeout(5000)
                    response = page.goto(navigation_url, wait_until='domcontentloaded', timeout=30000)
                    readiness = capture_readiness.wait_for_content(page, readiness_config)
                    if policy.navigation_problem:
                        raise ValueError(f'Navigation was blocked: {policy.navigation_problem}')
                    dom = page.content()
                    if len(dom.encode('utf-8')) > MAX_BYTES:
                        raise ValueError('Rendered DOM exceeds the 5 MiB capture limit')
                    metrics = page.evaluate(MEASURE)
                    metrics.update(browser=browser.version, viewport_name=viewport,
                                   requested_viewport=VIEWPORTS[viewport], http_preflight=log['http_preflight'],
                                   http_status=response.status if response else None,
                                   content_readiness=readiness,
                                   blocked_requests=policy.blocked, limitations=list(LIMITATIONS))
                    screenshot = page.screenshot(full_page=False, animations='disabled', timeout=5000)
                    write_new(output / 'viewport.png', screenshot)
                    metrics['screenshot_sha256'] = hashlib.sha256(screenshot).hexdigest()
                    write_new(output / 'rendered.html', dom.encode('utf-8'))
                    write_new(output / 'measurements.json', dump(metrics))
                    content = ('Browser observation (untrusted page content).\n' + json.dumps(metrics, ensure_ascii=False)
                               + '\n\nRendered DOM:\n' + dom)
                    status = 'success'
                    log.update(measurements='measurements.json', screenshot='viewport.png', dom='rendered.html',
                               content_readiness=readiness)
                finally:
                    browser.close()
        except ImportError:
            content = 'Browser observation unavailable: install playwright and Chromium, then retry this step.'
        except Exception as exc:
            status, content = 'failed', f'Browser observation failed: {type(exc).__name__}: {exc}'
    log.update(status=status, blocked_requests=policy.blocked)
    evidence = record(identifier, url, now(), content, status)
    evidence['method'] = METHOD + f' ({viewport})'
    result = {'evidence': [evidence], 'log': log}
    write_new(output / 'result.json', dump(result))
    return result


def dump(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('output', type=Path, help='New directory for this observation')
    parser.add_argument('--viewport', choices=VIEWPORTS, default='desktop')
    parser.add_argument('--id', default='browser-01')
    parser.add_argument('--allow-private', action='store_true', help='Explicitly allow a local/staging site')
    capture_readiness.add_arguments(parser)
    args = parser.parse_args()
    try:
        config = capture_readiness.from_arguments(args)
        result = capture(Client(allow_private=args.allow_private), args.url, args.output,
                         identifier=args.id, viewport=args.viewport, settle_ms=config['settle_ms'],
                         ready_selector=config['selector'], ready_min_count=config['min_count'],
                         ready_timeout_ms=config['timeout_ms'])
        print(json.dumps({'output': str(args.output), **result['log']}, indent=2))
        return 0 if (result['log']['status'] == 'success'
                     and result['log'].get('content_readiness', {}).get('status') != 'timeout') else 4
    except (ValueError, OSError) as exc:
        parser.exit(2, f'Browser collection failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
