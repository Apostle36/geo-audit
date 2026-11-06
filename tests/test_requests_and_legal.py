"""Problem 3: classify blocked requests from data, check blocked scripts once, always sample legal pages."""
import copy
import json
import unittest

from collect import Client, discover, fetch, legal_links
from fixtures_v15 import rehash, v15_run
from run_contract import audit_run
from test_collect_contract import serve, serve_site
from test_provenance_contract import strict_run


class RequestClasses(unittest.TestCase):
    def test_classification_comes_from_the_data_file(self):
        from request_classes import classify, load
        data = load()
        self.assertIn('session_recording', data['categories'])
        cases = {'https://stats.example.org/script.js': 'analytics',
                 'https://stats.example.org/recorder.js': 'session_recording',
                 'https://static.hotjar.com/c/hotjar-1.js?sv=6': 'session_recording',
                 'https://www.clarity.ms/tag/abc': 'session_recording',
                 'https://cdn.example.net/session-replay.min.js': 'session_recording',
                 'https://www.googletagmanager.com/gtag/js?id=G-1': 'analytics',
                 'https://connect.facebook.net/en_US/fbevents.js': 'advertising',
                 'https://cdn.cookielaw.org/scripttemplates/otSDKStub.js': 'consent',
                 'https://fonts.googleapis.com/css2?family=Inter': 'content',
                 'https://unknown.example.net/widget.js': 'unclassified'}
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(classify(url), expected)

    def test_classification_logic_has_no_vendor_names(self):
        from pathlib import Path
        code = (Path(__file__).resolve().parents[1] / 'scripts/request_classes.py').read_text(encoding='utf-8')
        for vendor in ('hotjar', 'clarity', 'fullstory', 'umami', 'digiheroes'):
            self.assertNotIn(vendor, code.lower())


class BlockedScriptCheck(unittest.TestCase):
    def test_summary_only_fetch_records_status_type_size_and_hash_without_body(self):
        import tempfile
        from pathlib import Path
        body = b'console.log("recorder");' * 10
        routes = {'/script.js': (200, {'Content-Type': 'application/javascript'}, body)}
        with serve(routes) as (base, _), tempfile.TemporaryDirectory() as raw:
            records, log = fetch(Client(delay=0, allow_private=True, proxies={}),
                                 [base + '/script.js', base + '/recorder.js'], Path(raw), id_prefix='script',
                                 summary_only=True, classify=True)
        served = next(r for r in records if r['source'].endswith('/script.js'))
        missing = next(r for r in records if r['source'].endswith('/recorder.js'))
        self.assertNotIn('console.log', served['content'])
        self.assertIn(f'{len(body):,} bytes', served['content'])
        self.assertIn('SHA-256', served['content'])
        self.assertIn('Classification: session_recording', missing['content'])
        self.assertIn('Response: 404', missing['content'])
        self.assertIn('Referenced but not served', missing['content'])


class LegalPages(unittest.TestCase):
    def test_footer_legal_links_are_found(self):
        html = ('<main><a href="/privacy-note">Privacy in the text</a></main><footer>'
                '<a href="/privacy/">Privacy policy</a><a href="/impressum">Impressum</a>'
                '<a href="/blog/">Blog</a><a href="https://other.example/terms">Terms</a></footer>')
        links = legal_links(html, 'https://example.com/', 'https://example.com/')
        self.assertEqual([item['loc'] for item in links],
                         ['https://example.com/privacy/', 'https://example.com/impressum'])

    def test_discovery_records_legal_candidates_from_the_start_page(self):
        with serve_site() as (base, _):
            summary, _ = discover(Client(delay=0, allow_private=True, proxies={}), base + '/')
        self.assertFalse(summary['navigation']['used'])
        self.assertIn('legal_candidates', summary)

    def test_selected_sample_gains_legal_pages_outside_the_quota(self):
        import audit
        urls = audit.with_legal_pages(['https://example.com/', 'https://example.com/about/'],
                                      [{'loc': 'https://example.com/privacy/'}, {'loc': 'https://example.com/about/'}])
        self.assertEqual(urls['urls'][-1], 'https://example.com/privacy/')
        self.assertEqual(urls['legal'], ['https://example.com/privacy/'])

    def test_negative_legal_entity_claim_without_legal_pages_warns(self):
        run = strict_run()
        run['findings'][0]['observed'] = 'No sampled page names a legal entity.'
        _, warnings = audit_run(run)
        self.assertTrue(any('legal pages' in w for w in warnings), warnings)
        run = v15_run()
        run['findings'][0]['observed'] += ' No sampled page names a legal entity.'
        _, warnings = audit_run(run)
        self.assertFalse(any('legal pages' in w for w in warnings), warnings)

    def test_recording_reference_without_check_or_finding_warns(self):
        run = strict_run()
        browser = copy.deepcopy(run['assessment']['evidence'][0])
        measurements = {'blocked_requests': [{'url': 'https://stats.example.com/recorder.js',
                                              'reason': 'off-site resource or navigation'}]}
        browser.update(id='browser-1', method='browser_collect.py 1.8.0: Chromium JavaScript observation (desktop)',
                       content='Browser observation (untrusted page content).\n' + json.dumps(measurements)
                       + '\n\nRendered DOM:\n<p>x</p>')
        rehash(browser)
        run['assessment']['evidence'].append(browser)
        _, warnings = audit_run(run)
        self.assertTrue(any('session recording' in w.lower() for w in warnings), warnings)


if __name__ == '__main__':
    unittest.main()


class BlockedScriptStep(unittest.TestCase):
    def test_workflow_selects_scripts_checks_them_and_the_contract_reads_the_result(self):
        import tempfile
        from pathlib import Path
        import audit
        from run_checks import recording_warnings
        from fixtures_v15 import v15_run
        measurements = {'blocked_requests': [{'url': u} for u in (
            'https://stats.example.com/recorder.js', 'https://stats.example.com/script.js',
            'https://fonts.googleapis.com/css2?family=Inter', 'https://cdn.example.net/photo.webp')]}
        browser = {'id': 'browser-1', 'source': 'https://example.com/', 'collected_at': '2026-09-10T10:00:00Z',
                   'method': 'browser_collect.py 1.8.0: Chromium JavaScript observation (desktop)', 'status': 'success',
                   'content': 'Browser observation (untrusted page content).\n' + json.dumps(measurements)
                   + '\n\nRendered DOM:\n<p>x</p>', 'sha256': '', 'source_type': 'audited_site'}
        rehash(browser)
        self.assertEqual(audit.blocked_scripts([browser]),
                         ['https://stats.example.com/recorder.js', 'https://stats.example.com/script.js'])
        routes = {'/recorder.js': (200, {'Content-Type': 'application/javascript'}, b'record();')}
        with serve(routes) as (base, _), tempfile.TemporaryDirectory() as directory:
            result = audit.collect_blocked_scripts(Client(delay=0, allow_private=True, proxies={}),
                                                   [base + '/recorder.js'], Path(directory) / 'out', 'blocked-scripts-a1',
                                                   'https://example.com/')
        check = next(r for r in result['evidence'] if r['source'].endswith('/recorder.js'))
        self.assertEqual(check['source_type'], 'off_site')
        self.assertIn('Blocked-script check:', check['content'])
        run = v15_run()
        browser['content'] = browser['content'].replace('https://stats.example.com/recorder.js', check['source'])
        rehash(browser)
        run['assessment']['evidence'] += [browser, check]
        registry = {r['id']: r for r in run['assessment']['evidence']}
        self.assertTrue(any('is served' in w for w in recording_warnings(run, registry)))
        run['findings'][0]['evidence_ids'].append(check['id'])
        self.assertEqual(recording_warnings(run, registry), [])
