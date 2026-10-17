from contextlib import contextmanager
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from test_reliability import ROOT, module
from evidence import extract, validate_registry
from run_contract import audit_run

collect = module('collect', 'collect.py')


@contextmanager
def serve(routes):
    """Serve {path: (status, headers, body)} on 127.0.0.1; unknown paths return 404.

    A callable body writes its own response (for slow streams) and declares its own length.
    """
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.requests.append((self.path, self.headers.get('User-Agent')))
            status, headers, body = routes.get(self.path, (404, {'Content-Type': 'text/html'}, b'<title>Missing</title>'))
            self.send_response(status)
            for key, value in headers.items():
                if key != 'X-Stream':
                    self.send_header(key, value)
            if 'X-Stream' not in headers and not callable(body):
                # Streamed bodies end when the HTTP/1.0 connection closes.
                self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                body(self.wfile) if callable(body) else self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The collector gave up, as intended.

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', server
    finally:
        server.shutdown()
        server.server_close()


def html(title, body='', extra=''):
    text = f'<!doctype html><html><head><title>{title}</title>{extra}</head><body>{body}</body></html>'
    return 200, {'Content-Type': 'text/html; charset=utf-8'}, text.encode()


PROSE = '<p>' + 'Useful service detail for customers. ' * 12 + '</p>'


def site(base):
    urlset = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
              + ''.join(f'<url><loc>{url}</loc><lastmod>2026-09-01</lastmod></url>'
                        for url in (f'{base}/', f'{base}/a', f'{base}/private/x', 'https://other.example/out'))
              + '</urlset>')
    index = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
             f'<sitemap><loc>{base}/pages.xml.gz</loc></sitemap><sitemap><loc>{base}/evil.xml</loc></sitemap>'
             '</sitemapindex>')
    robots = (f'User-agent: *\nDisallow: /private\nAllow: /private/open\n\nUser-agent: GPTBot\nDisallow: /\n\n'
              f'Sitemap: {base}/index.xml\n')
    return {
        '/robots.txt': (200, {'Content-Type': 'text/plain'}, robots.encode()),
        '/index.xml': (200, {'Content-Type': 'application/xml'}, index.encode()),
        '/pages.xml.gz': (200, {'Content-Type': 'application/gzip'}, gzip.compress(urlset.encode())),
        '/evil.xml': (200, {'Content-Type': 'application/xml'},
                      b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><urlset>&a;</urlset>'),
        '/': html('Home', PROSE, '<script type="application/ld+json">{"@type":"Organization"}</script>'),
        '/a': (200, {'Content-Type': 'text/html', 'Set-Cookie': 'session=SECRET123; Path=/; Secure; HttpOnly'},
               f'<title>Services</title>{PROSE}'.encode()),
        '/redirect': (301, {'Location': '/a'}, b''),
        '/offsite': (302, {'Location': 'https://other.example/'}, b''),
        '/loop1': (302, {'Location': '/loop2'}, b''),
        '/loop2': (302, {'Location': '/loop1'}, b''),
        '/big': (200, {'Content-Type': 'text/html'}, b'x' * 5000),
        '/streamed-big': (200, {'Content-Type': 'text/html', 'X-Stream': '1'}, b'x' * 5000),
        '/soft404': html('Page not found'),
        '/noindex': html('Hidden', PROSE, '<meta name="robots" content="noindex, follow">'),
        '/binary': (200, {'Content-Type': 'application/pdf'}, b'%PDF-1.7 binary'),
        # Shape of a real Fastly interstitial served with HTTP 200 (seen on a live smoke test).
        '/challenge': html('Client Challenge', '<noscript><span>JavaScript is disabled in your browser.</span><p>Please '
                           'enable JavaScript to proceed.</p></noscript><div id="loading-error">' + 'A required part of '
                           'this site could not load. ' * 8 + '</div><script src="/_fs-ch-1T1/script.js"></script>'),
        '/blocked': (403, {'Content-Type': 'text/html'}, b'<title>Attention Required! | Cloudflare</title>'),
        '/latin': (200, {'Content-Type': 'text/html; charset=iso-8859-1'}, '<title>Café</title>'.encode('latin-1')),
    }


def client(**options):
    return collect.Client(**{'delay': 0, 'allow_private': True, 'proxies': {}, 'max_bytes': 4000, **options})


class RobotsRules(unittest.TestCase):
    def robots(self, text):
        return collect.Robots('https://example.com/robots.txt', 'parsed', text)

    def allowed(self, robots, url, token='GEO-Audit'):
        return robots.decision(token, 'https://example.com' + url)['allowed']

    def test_longest_match_and_allow_on_tie(self):
        robots = self.robots('User-agent: *\nDisallow: /private\nAllow: /private/open\nAllow: /tie\nDisallow: /tie\n')
        self.assertFalse(self.allowed(robots, '/private/x'))
        self.assertTrue(self.allowed(robots, '/private/open/page'))
        self.assertTrue(self.allowed(robots, '/tie'))
        self.assertTrue(self.allowed(robots, '/public'))
        self.assertEqual(robots.decision('x', 'https://example.com/private/x')['rule'], 'Disallow: /private')

    def test_wildcards_and_end_anchor(self):
        robots = self.robots('User-agent: *\nDisallow: /*.pdf$\nDisallow: /search*q=\n')
        self.assertFalse(self.allowed(robots, '/files/a.pdf'))
        self.assertTrue(self.allowed(robots, '/files/a.pdf?download=1'))
        self.assertFalse(self.allowed(robots, '/search?page=2&q=shoes'))

    def test_specific_group_replaces_star_and_same_agent_groups_merge(self):
        robots = self.robots('User-agent: *\nDisallow: /a\n\nUser-agent: Googlebot/2.1\nDisallow: /b\n\n'
                             'User-agent: googlebot\nDisallow: /c\n')
        self.assertTrue(self.allowed(robots, '/a', 'Googlebot'))
        self.assertFalse(self.allowed(robots, '/b', 'GOOGLEBOT'))
        self.assertFalse(self.allowed(robots, '/c', 'Googlebot'))
        self.assertFalse(self.allowed(robots, '/a', 'Bingbot'))

    def test_consecutive_agents_share_a_group_until_a_rule(self):
        robots = self.robots('User-agent: A\nUser-agent: B\nDisallow: /x\nUser-agent: C\nDisallow: /y\n')
        self.assertEqual([group['agents'] for group in robots.groups], [['a', 'b'], ['c']])
        self.assertFalse(self.allowed(robots, '/x', 'B'))
        self.assertTrue(self.allowed(robots, '/x', 'C'))

    def test_empty_disallow_comments_and_robots_file(self):
        robots = self.robots('# comment\nUser-agent: * # everyone\nDisallow:\nDisallow: /robots\n')
        self.assertTrue(self.allowed(robots, '/anything'))
        self.assertTrue(self.allowed(robots, '/robots.txt'))
        self.assertFalse(self.allowed(robots, '/robots-archive'))

    def test_percent_encoding_is_normalised(self):
        robots = self.robots('User-agent: *\nDisallow: /caf%C3%A9\nDisallow: /%7Euser\n')
        self.assertFalse(self.allowed(robots, '/café/menu'))
        self.assertFalse(self.allowed(robots, '/~user/page'))

    def test_unavailable_allows_and_unreachable_disallows(self):
        self.assertTrue(collect.Robots('u', 'unavailable', detail='HTTP 404').decision('x', 'https://e.com/a')['allowed'])
        self.assertFalse(collect.Robots('u', 'unreachable', detail='HTTP 503').decision('x', 'https://e.com/a')['allowed'])

    def test_crawl_delay_is_capped(self):
        self.assertEqual(self.robots('User-agent: *\nCrawl-delay: 4\n').crawl_delay('GEO-Audit'), 4)
        self.assertEqual(self.robots('User-agent: *\nCrawl-delay: 900\n').crawl_delay('GEO-Audit'), 30)

    def test_robots_ids_never_collide_between_hosts(self):
        self.assertNotEqual(collect.robots_id('page', 'https://a-b.com/'), collect.robots_id('page', 'https://a.b.com/'))
        self.assertEqual(collect.robots_id('discovery', 'https://www.example.com/x'), 'discovery-robots-www.example.com')

    def test_non_finite_crawl_delays_are_ignored(self):
        for value in ('inf', 'nan', '1e999', '-3'):
            with self.subTest(value=value):
                robots = self.robots(f'User-agent: *\nCrawl-delay: {value}\nDisallow: /x\n')
                self.assertEqual(robots.crawl_delay('GEO-Audit'), 0)
                json.dumps(robots.summary(), allow_nan=False)

    def test_noindex_flags_read_whole_directives(self):
        def flags(headers=(), meta=''):
            response = collect.Response('https://example.com/', 200, 'OK', list(headers))
            return collect.flags(response, f'<html><head><title>T</title>{meta}</head><body>{PROSE}</body></html>')
        self.assertEqual(flags([('X-Robots-Tag', 'max-image-preview:none')]), [])
        self.assertEqual(flags(meta='<meta name="robots" content="index, follow, max-image-preview:none">'), [])
        self.assertEqual(flags([('X-Robots-Tag', 'noarchive'), ('X-Robots-Tag', 'noindex')]), ['noindex_header'])
        self.assertEqual(flags([('X-Robots-Tag', 'googlebot: noindex, nofollow')]), ['noindex_header'])
        self.assertEqual(flags(meta='<meta name="ROBOTS" content="NONE">'), ['noindex_meta'])
        self.assertEqual(flags(meta='<meta name="description" content="noindex">'), [])

    def test_healthy_cloudflare_pages_are_not_challenges(self):
        response = collect.Response('https://example.com/', 200, 'OK', [])
        page = (f'<html><head><title>Home</title></head><body>{PROSE}<script>window.__CF$cv$params={{r:"1"}};'
                's.src="/cdn-cgi/challenge-platform/scripts/jsd/main.js";</script></body></html>')
        self.assertEqual(collect.flags(response, page), [])
        challenge = '<title>Just a moment...</title><script>window._cf_chl_opt={cZone:"x"}</script>'
        self.assertEqual(collect.flags(collect.Response('u', 403, 'Forbidden', []), challenge), ['possible_challenge'])

    def test_url_checks(self):
        self.assertEqual(collect.check_urls(['https://example.com/']), [])
        for urls in ([], ['https://example.com/#top'], ['ftp://example.com/'], ['https://example.com/'] * 2,
                     [f'https://example.com/{i}' for i in range(51)]):
            with self.subTest(urls=urls[:2]):
                self.assertTrue(collect.check_urls(urls))


class Collection(unittest.TestCase):
    def test_discovery_reads_robots_and_sitemaps(self):
        with serve_site() as (base, _):
            summary, evidence = collect.discover(client(), base + '/')
        validate_registry(evidence)
        self.assertEqual(summary['robots']['state'], 'parsed')
        self.assertEqual([item['loc'] for item in summary['candidates']], [f'{base}/', f'{base}/a', f'{base}/private/x'])
        self.assertEqual(summary['out_of_scope'], 1)
        errors = {item['url'].rsplit('/', 1)[-1]: item.get('error') for item in summary['sitemaps']}
        self.assertIn('DTD', errors['evil.xml'])
        self.assertIsNone(errors['pages.xml.gz'])
        self.assertFalse(summary['agents']['GPTBot']['homepage']['allowed'])
        self.assertEqual(summary['agents']['GPTBot']['disallowed_candidates'], 3)
        self.assertTrue(summary['agents']['Googlebot']['homepage']['allowed'])
        self.assertEqual(summary['agents']['Googlebot']['disallowed_candidates'], 1)
        self.assertEqual(len({record['id'] for record in evidence}), len(evidence))

    def test_fetch_records_every_outcome_honestly(self):
        paths = ['/', '/redirect', '/offsite', '/loop1', '/big', '/streamed-big', '/missing', '/soft404', '/noindex',
                 '/private/x', '/binary', '/latin', '/challenge', '/blocked']
        with serve_site() as (base, server), tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / 'raw'
            raw.mkdir()
            evidence, log = collect.fetch(client(), [base + path for path in paths], raw)
            raw_files = sorted(p.name for p in raw.iterdir())
            requested = [path for path, _ in server.requests]
            agents = {agent for _, agent in server.requests}
        validate_registry(evidence)
        pages = {entry['url'][len(base):]: entry for entry in log['pages']}
        records = {record['source'][len(base):]: record for record in evidence}
        self.assertEqual(evidence[0]['id'], 'page-robots-http-' + base.split('//')[1])
        self.assertEqual(requested.count('/robots.txt'), 1)
        self.assertNotIn('/private/x', requested)
        self.assertEqual(agents, {collect.USER_AGENT})
        self.assertEqual(pages['/']['status'], 'success')
        self.assertTrue(extract(records['/']['content'])['jsonld'])
        self.assertEqual(pages['/redirect']['final_url'], base + '/a')
        self.assertNotIn('SECRET123', records['/redirect']['content'])
        self.assertIn('Set-Cookie: session=[value redacted by collect.py]; Path=/; Secure; HttpOnly',
                      records['/redirect']['content'])
        self.assertIn(f'Redirect: 301 {base}/redirect -> {base}/a', records['/redirect']['content'])
        self.assertIn('outside the collection scope', records['/offsite']['content'])
        self.assertIn('Redirect limit', records['/loop1']['content'])
        self.assertEqual(pages['/big']['status'], 'failed')
        self.assertIn('declared size', records['/big']['content'])
        self.assertEqual(pages['/streamed-big']['status'], 'failed')
        self.assertIn('exceeds the 4,000-byte limit', records['/streamed-big']['content'])
        self.assertEqual((pages['/missing']['status'], pages['/missing']['http_status']), ('success', 404))
        self.assertIn('possible_soft_404', pages['/soft404']['flags'])
        self.assertIn('thin_response', pages['/soft404']['flags'])
        self.assertIn('noindex_meta', pages['/noindex']['flags'])
        self.assertEqual(pages['/challenge']['flags'], ['possible_challenge'])
        self.assertEqual(pages['/blocked']['flags'], ['possible_challenge'])
        self.assertEqual(pages['/']['flags'], [])
        self.assertEqual(pages['/private/x']['status'], 'unavailable')
        self.assertIn('Disallow: /private', records['/private/x']['content'])
        self.assertIn('Binary body omitted', records['/binary']['content'])
        self.assertIn('Café', records['/latin']['content'])
        self.assertIn(pages['/binary']['body_sha256'] + '.bin', raw_files)
        self.assertFalse(pages['/']['robots_reported']['GPTBot']['allowed'])

    def test_private_addresses_are_refused_by_default(self):
        with serve_site() as (base, server), tempfile.TemporaryDirectory() as directory:
            evidence, log = collect.fetch(client(allow_private=False), [base + '/'], Path(directory))
            self.assertEqual(server.requests, [])
        self.assertEqual(log['pages'][0]['status'], 'unavailable')
        self.assertIn('non-public address', evidence[-1]['content'])

    def test_robots_server_error_blocks_and_missing_robots_allows(self):
        for status, expected in ((503, 'unavailable'), (404, 'success')):
            routes = dict(site('http://unused'))
            routes['/robots.txt'] = (status, {'Content-Type': 'text/plain'}, b'')
            with self.subTest(status=status), serve(routes) as (base, _), tempfile.TemporaryDirectory() as directory:
                _, log = collect.fetch(client(), [base + '/a'], Path(directory))
                self.assertEqual(log['pages'][0]['status'], expected)

    def test_robots_byte_order_mark_does_not_hide_rules(self):
        routes = dict(site('http://unused'))
        routes['/robots.txt'] = (200, {'Content-Type': 'text/plain'}, b'\xef\xbb\xbfUser-agent: *\r\nDisallow: /private\r\n')
        with serve(routes) as (base, server), tempfile.TemporaryDirectory() as directory:
            _, log = collect.fetch(client(), [base + '/private/x'], Path(directory))
            self.assertNotIn('/private/x', [path for path, _ in server.requests])
        self.assertEqual(log['pages'][0]['status'], 'unavailable')

    def test_slow_drip_cannot_outlast_the_deadline(self):
        import time
        def drip(stream):
            for _ in range(60):
                stream.write(b'x')
                stream.flush()
                time.sleep(0.1)
        routes = {'/robots.txt': (404, {}, b''), '/slow': (200, {'Content-Type': 'text/html', 'Content-Length': '1000'}, drip)}
        with serve(routes) as (base, _), tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            _, log = collect.fetch(client(timeout=1), [base + '/slow'], Path(directory))
            elapsed = time.monotonic() - started
        self.assertEqual(log['pages'][0]['status'], 'failed')
        self.assertIn('exceeded 1 seconds', log['pages'][0]['notes'][0])
        self.assertLess(elapsed, 3)

    def test_hostile_charset_and_unexpected_errors_stay_per_page(self):
        routes = dict(site('http://unused'))
        routes['/escape'] = (200, {'Content-Type': 'text/html; charset=unicode_escape'}, b'<title>\\ud800</title>')
        with serve(routes) as (base, _), tempfile.TemporaryDirectory() as directory:
            evidence, log = collect.fetch(client(), [base + '/escape', base + '/a'], Path(directory))
            validate_registry(evidence)
            self.assertEqual([page['status'] for page in log['pages']], ['success', 'success'])
            self.assertIn('Unusable charset unicode_escape', evidence[1]['content'])
            original = collect.capture_page
            def explode(client_, identifier, url, raw_dir):
                if url.endswith('/escape'):
                    raise RuntimeError('simulated parser failure')
                return original(client_, identifier, url, raw_dir)
            collect.capture_page = explode
            try:
                evidence, log = collect.fetch(client(), [base + '/escape', base + '/a'], Path(directory))
            finally:
                collect.capture_page = original
        self.assertEqual([page['status'] for page in log['pages']], ['failed', 'success'])
        self.assertIn('simulated parser failure', evidence[1]['content'])

    def test_sitemap_problems_are_recorded_not_fatal(self):
        routes = dict(site('http://unused'))
        routes['/robots.txt'] = (200, {}, b'User-agent: *\nDisallow: /private\nSitemap: /broken.xml.gz\nSitemap: /moved.xml\n')
        routes['/broken.xml.gz'] = (200, {'Content-Type': 'application/gzip'}, gzip.compress(b'<urlset>' * 200)[:40])
        routes['/moved.xml'] = (301, {'Location': '/private/sitemap.xml'}, b'')
        routes['/private/sitemap.xml'] = (200, {}, b'<urlset><url><loc>http://x/</loc></url></urlset>')
        with serve(routes) as (base, server):
            # The relative Sitemap lines also check resolution against robots.txt.
            summary, evidence = collect.discover(client(), base + '/')
            requested = [path for path, _ in server.requests]
        validate_registry(evidence)
        errors = {item['url'][len(base):]: item.get('error', '') for item in summary['sitemaps']}
        self.assertIn('EOFError', errors['/broken.xml.gz'])
        self.assertIn('disallowed by robots.txt', errors['/moved.xml'])
        self.assertNotIn('/private/sitemap.xml', requested)

    def test_requests_to_a_host_are_spaced(self):
        moments, waits = [0.0], []
        def clock():
            return moments[0]
        def sleep(seconds):
            waits.append(seconds)
            moments[0] += seconds
        with serve_site() as (base, _), tempfile.TemporaryDirectory() as directory:
            collect.fetch(client(delay=1.5, clock=clock, sleep=sleep), [base + '/', base + '/a'], Path(directory))
        self.assertEqual(waits, [1.5, 1.5])

    def test_collected_evidence_builds_a_valid_run(self):
        new_run = module('new_run', 'new_run.py')
        with serve_site() as (base, _), tempfile.TemporaryDirectory() as directory:
            evidence, _ = collect.fetch(client(), [base + '/', base + '/a'], Path(directory))
        run = new_run.skeleton(url=base + '/', sample=[base + '/', base + '/a'], business_type='Test', market='Test',
                               language='en', sampling_rationale='Test sample', date=evidence[0]['collected_at'][:10],
                               evidence=evidence)
        scores, warnings = audit_run(run)
        self.assertIsNone(scores['overall'])
        self.assertEqual(scores['coverage'], 0)
        self.assertEqual(len(run['review']), 34)
        self.assertTrue(any('skeleton placeholder' in warning for warning in warnings))


@contextmanager
def serve_site():
    # The sitemap must name the server's own address, so routes are built after binding.
    routes = {}
    with serve(routes) as (base, server):
        routes.update(site(base))
        yield base, server


class CommandLine(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts' / args[0]), *map(str, args[1:])],
                              capture_output=True, text=True, check=False)

    def test_discover_fetch_and_new_run(self):
        with serve_site() as (base, _), tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'evidence'
            found = self.run_script('collect.py', 'discover', base + '/', out, '--allow-private', '--agent', 'GPTBot')
            self.assertEqual(found.returncode, 0, found.stderr)
            self.assertEqual(json.loads(found.stdout)['candidates'], 3)
            fetched = self.run_script('collect.py', 'fetch', out, base + '/', '--allow-private')
            self.assertEqual(fetched.returncode, 0, fetched.stderr)
            self.assertEqual(json.loads(fetched.stdout)['success'], 1)
            again = self.run_script('collect.py', 'fetch', out, base + '/', '--allow-private')
            self.assertEqual(again.returncode, 2)
            self.assertIn('already exists', again.stderr)
            self.assertNotIn('Traceback', again.stderr)
            second = Path(directory) / 'second-batch'
            fetched = self.run_script('collect.py', 'fetch', second, base + '/redirect', '--allow-private',
                                      '--id-prefix', 'extra')
            self.assertEqual(fetched.returncode, 0, fetched.stderr)
            run_path = Path(directory) / 'run.json'
            # The documented workflow merges discovery and every fetch batch.
            created = self.run_script('new_run.py', run_path, '--url', base + '/', '--sample', base + '/',
                                      '--sample', base + '/a', '--business-type', 'Test', '--market', 'Test',
                                      '--language', 'en', '--sampling-rationale', 'Test',
                                      '--evidence', out / 'fetch-evidence.json',
                                      '--evidence', out / 'discovery-evidence.json',
                                      '--evidence', second / 'fetch-evidence.json')
            self.assertEqual(created.returncode, 0, created.stderr)
            self.assertIn(f'No successful capture yet for sample URL {base}/a', created.stdout)
            checked = self.run_script('run_contract.py', run_path)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            duplicate = self.run_script('new_run.py', Path(directory) / 'other.json', '--url', base + '/',
                                        '--sample', base + '/', '--business-type', 'T', '--market', 'T',
                                        '--language', 'en', '--sampling-rationale', 'T',
                                        '--evidence', out / 'fetch-evidence.json', '--evidence', out / 'fetch-evidence.json')
            self.assertEqual(duplicate.returncode, 2)
            self.assertIn('appears in both', duplicate.stderr)

    def test_invalid_inputs_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'never-created'
            for args in (('fetch', out, 'https://example.com/#x'), ('fetch', out), ('discover', 'not-a-url', out),
                         ('fetch', out, 'https://example.com/', '--delay', '0.1')):
                with self.subTest(args=args[:3]):
                    result = self.run_script('collect.py', *args)
                    self.assertEqual(result.returncode, 2)
                    self.assertNotIn('Traceback', result.stderr)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
