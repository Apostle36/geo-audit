import builtins
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import browser_collect
from collect import Client
from evidence import validate_registry
from test_collect_contract import serve
from test_reliability import ROOT


class BrowserPolicy(unittest.TestCase):
    def test_private_addresses_offsite_and_mutations_are_blocked(self):
        policy = browser_collect.Policy(Client(), 'https://example.com/')
        self.assertIn('off-site', policy.reason('https://other.example/'))
        self.assertIn('state-changing', policy.reason('https://example.com/', method='POST'))
        self.assertIn('HTTP(S)', policy.reason('file:///etc/passwd'))
        self.assertIn('credentials', policy.reason('https://user:pass@example.com/'))
        private = browser_collect.Policy(Client(), 'http://127.0.0.1/')
        self.assertIsNotNone(private.reason('http://127.0.0.1/'))

    def test_redirect_and_request_budgets(self):
        policy = browser_collect.Policy(Client(), 'https://example.com/', max_requests=2)
        self.assertIn('redirect limit', policy.reason('https://example.com/', redirects=6))
        policy.reason('https://other.example/')
        self.assertIn('request limit', policy.reason('https://example.com/'))

    def test_only_a_blocked_main_frame_navigation_fails_the_observation(self):
        class Frame:
            def __init__(self, parent=None, available=True):
                self.parent, self.available = parent, available

            @property
            def parent_frame(self):
                if not self.available:
                    raise RuntimeError('Frame for this navigation request is not available')
                return self.parent

        def routed(frame, url='https://www.google.com/maps/embed?pb=1'):
            policy = browser_collect.Policy(Client(), 'https://example.com/')
            request = Mock(url=url, method='GET', redirected_from=None, resource_type='document', frame=frame)
            request.is_navigation_request.return_value = True
            route = Mock(request=request)
            policy.route(route)
            route.abort.assert_called_once_with()
            route.fulfill.assert_not_called()
            return policy

        main = Frame()
        embedded = routed(Frame(parent=main))
        self.assertEqual(embedded.blocked, [{'url': 'https://www.google.com/maps/embed?pb=1',
                                             'reason': 'off-site resource or navigation'}])
        self.assertIsNone(embedded.navigation_problem)
        self.assertEqual(routed(main).navigation_problem, 'off-site resource or navigation')
        # A navigation issued before its frame exists (a popup) is still treated as the page's own.
        self.assertEqual(routed(Frame(available=False)).navigation_problem, 'off-site resource or navigation')

    def test_missing_browser_is_an_explicit_unavailable_capture(self):
        original = builtins.__import__
        def unavailable(name, *args, **kwargs):
            if name == 'playwright.sync_api':
                raise ImportError('simulated missing runtime')
            return original(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'capture'
            with patch.object(browser_collect.Policy, 'reason', return_value=None), \
                    patch('builtins.__import__', side_effect=unavailable):
                result = browser_collect.capture(Client(), 'https://example.com/', output)
            self.assertEqual(result['log']['status'], 'unavailable')
            validate_registry(result['evidence'])
            self.assertTrue((output / 'result.json').is_file())
            self.assertIn('install playwright', result['evidence'][0]['content'])


class IsolatedObservation(unittest.TestCase):
    """The worker is replaced by small scripts, so no browser is needed."""

    def run_worker(self, script, deadline):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'grandchild.pid'
            command = [sys.executable, '-c', script.format(marker=str(marker))]
            client = Client(delay=0)
            with patch.object(browser_collect, 'worker_command', return_value=command):
                started = time.monotonic()
                result = browser_collect.capture_isolated(client, 'https://example.com/', Path(directory) / 'c',
                                                          identifier='b1', viewport='mobile', deadline=deadline)
                elapsed = time.monotonic() - started
            saved = json.loads((Path(directory) / 'c/result.json').read_text())
            pid = int(marker.read_text()) if marker.exists() else None
            return result, saved, elapsed, pid, client

    def test_deadline_kills_the_whole_process_group_and_records_a_failure(self):
        script = ('import pathlib, subprocess, sys, time\n'
                  "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                  "pathlib.Path(r'{marker}').write_text(str(child.pid))\ntime.sleep(60)")
        result, saved, elapsed, pid, client = self.run_worker(script, deadline=2)
        self.assertLess(elapsed, 15)
        self.assertEqual(result, saved)
        self.assertEqual(result['log']['status'], 'failed')
        self.assertIn('exceeded the 2-second observation limit', result['evidence'][0]['content'])
        self.assertTrue(result['evidence'][0]['method'].endswith('(mobile)'))
        validate_registry(result['evidence'])
        self.assertIn('example.com', client.last)
        for _ in range(50):  # The orphaned grandchild is reaped by init shortly after the kill.
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail('The worker\'s child process survived the deadline')

    def test_crashed_worker_without_a_result_is_an_explicit_failure(self):
        result, _, _, _, _ = self.run_worker("import sys; sys.exit('boom: no browser here')", deadline=30)
        self.assertEqual(result['log']['status'], 'failed')
        self.assertIn('exited with status 1: boom: no browser here', result['evidence'][0]['content'])

    def test_existing_observation_directory_is_refused_before_starting_a_worker(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(browser_collect.subprocess, 'Popen') as popen, self.assertRaises(FileExistsError):
            browser_collect.capture_isolated(Client(), 'https://example.com/', Path(directory))
        popen.assert_not_called()


@unittest.skipUnless(os.environ.get('GEO_RUN_RENDER_TESTS') == '1', 'Set GEO_RUN_RENDER_TESTS=1 for actual browser checks')
class RealBrowserCollection(unittest.TestCase):
    def test_page_that_blocks_its_main_thread_cannot_hang_the_audit(self):
        body = b'<!doctype html><title>Busy</title><h1>Hi</h1><script>setTimeout(()=>{while(true){}}, 100)</script>'
        with serve({'/': (200, {'Content-Type': 'text/html'}, body)}) as (base, _), \
                tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            result = browser_collect.capture_isolated(Client(delay=0, allow_private=True, proxies={}), base + '/',
                                                      Path(directory) / 'busy', deadline=12)
            self.assertLess(time.monotonic() - started, 30)
            self.assertEqual(result['log']['status'], 'failed')
            self.assertIn('12-second observation limit', result['evidence'][0]['content'])

    def test_isolated_observation_matches_the_in_process_result(self):
        body = b'<!doctype html><title>Plain</title><h1>Customer answer</h1>'
        with serve({'/': (200, {'Content-Type': 'text/html'}, body)}) as (base, _), \
                tempfile.TemporaryDirectory() as directory:
            result = browser_collect.capture_isolated(Client(delay=0, allow_private=True, proxies={}), base + '/',
                                                      Path(directory) / 'plain', identifier='b9', viewport='mobile')
            self.assertEqual(result['log']['status'], 'success', result)
            self.assertEqual(result['evidence'][0]['id'], 'b9')
            self.assertTrue((Path(directory) / 'plain/viewport.png').is_file())
            self.assertIn('Customer answer', (Path(directory) / 'plain/rendered.html').read_text())

    def test_javascript_dom_both_viewports_and_lab_measurements(self):
        html = b'''<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Before</title></head><body><h1>Before</h1>
            <script>document.querySelector('h1').textContent='Rendered customer answer';
            document.title='After'; fetch('/write', {method:'POST'}).catch(()=>{});</script></body></html>'''
        with serve({'/': (200, {'Content-Type': 'text/html'}, html)}) as (base, server), \
                tempfile.TemporaryDirectory() as directory:
            client = Client(delay=0, allow_private=True, proxies={})
            for viewport in browser_collect.VIEWPORTS:
                with self.subTest(viewport=viewport):
                    output = Path(directory) / viewport
                    result = browser_collect.capture(client, base + '/', output, identifier=viewport, viewport=viewport)
                    self.assertEqual(result['log']['status'], 'success', result)
                    validate_registry(result['evidence'])
                    dom = (output / 'rendered.html').read_text()
                    self.assertIn('<h1>Rendered customer answer</h1>', dom)
                    metrics = json.loads((output / 'measurements.json').read_text())
                    self.assertEqual(metrics['title'], 'After')
                    self.assertEqual(metrics['viewport'], browser_collect.VIEWPORTS[viewport])
                    self.assertEqual(metrics['requested_viewport'], browser_collect.VIEWPORTS[viewport])
                    self.assertIsNone(metrics['field_core_web_vitals'])
                    self.assertEqual(metrics['content_readiness']['status'], 'unverified')
                    self.assertFalse(metrics['interaction_tested'])
                    self.assertTrue(metrics['navigation'])
                    self.assertTrue((output / 'viewport.png').read_bytes().startswith(b'\x89PNG'))
                    self.assertTrue(any('state-changing' in x['reason'] for x in metrics['blocked_requests']))
            self.assertNotIn('/write', [path for path, _ in server.requests])

    def test_robots_and_offsite_redirects_are_preserved_as_unsuccessful(self):
        routes = {'/robots.txt': (200, {}, b'User-agent: *\nDisallow: /private\n'),
                  '/private': (200, {}, b'Must not be fetched'),
                  '/offsite': (302, {'Location': 'https://example.org/'}, b'')}
        with serve(routes) as (base, server), tempfile.TemporaryDirectory() as directory:
            client = Client(delay=0, allow_private=True, proxies={})
            private = browser_collect.capture(client, base + '/private', Path(directory) / 'private')
            self.assertEqual(private['log']['status'], 'unavailable')
            self.assertNotIn('/private', [path for path, _ in server.requests])
            redirect = browser_collect.capture(client, base + '/offsite', Path(directory) / 'offsite')
            self.assertEqual(redirect['log']['status'], 'failed')
            self.assertTrue(any('off-site' in item['reason'] for item in redirect['log']['blocked_requests']))

    def test_same_site_redirect_resolves_but_asset_redirect_never_leaves_scope(self):
        with serve({}) as (other, outside):
            offsite = other.replace('127.0.0.1', 'localhost') + '/must-not-fetch'
            routes = {'/start': (302, {'Location': '/destination'}, b''),
                      '/destination': (200, {'Content-Type': 'text/html'},
                          b'<title>Resolved</title><h1>Answer</h1><script src="/asset.js"></script>'),
                      '/asset.js': (302, {'Location': offsite}, b'')}
            with serve(routes) as (base, _), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'capture'
                result = browser_collect.capture(Client(delay=0, allow_private=True, proxies={}),
                                                   base + '/start', output)
                self.assertEqual(result['log']['status'], 'success', result)
                metrics = json.loads((output / 'measurements.json').read_text())
                self.assertEqual(metrics['final_url'], base + '/destination')
                self.assertEqual(result['evidence'][0]['source'], base + '/start')
                self.assertTrue(any('redirect blocked' in item['reason'] for item in metrics['blocked_requests']))
                self.assertEqual(outside.requests, [])

    def test_offsite_iframe_is_blocked_and_recorded_without_failing_the_page(self):
        with serve({}) as (other, outside):
            embed = other.replace('127.0.0.1', 'localhost') + '/maps/embed?pb=1'
            body = (f'<!doctype html><title>Contact</title><h1>Contact us</h1>'
                    f'<iframe src="{embed}" width="600" height="450"></iframe>').encode()
            with serve({'/contact': (200, {'Content-Type': 'text/html'}, body)}) as (base, _), \
                    tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'contact'
                result = browser_collect.capture(Client(delay=0, allow_private=True, proxies={}),
                                                 base + '/contact', output)
                self.assertEqual(result['log']['status'], 'success', result)
                metrics = json.loads((output / 'measurements.json').read_text())
                self.assertEqual(metrics['http_status'], 200)
                self.assertIn({'url': embed, 'reason': 'off-site resource or navigation'}, metrics['blocked_requests'])
                self.assertIn('<h1>Contact us</h1>', (output / 'rendered.html').read_text())
                self.assertEqual(outside.requests, [])

    def test_offsite_main_frame_navigation_by_script_still_fails(self):
        with serve({}) as (other, outside):
            away = other.replace('127.0.0.1', 'localhost') + '/away'
            body = (f'<!doctype html><title>Leaving</title><h1>Leaving</h1>'
                    f'<script>setTimeout(() => {{ location.href = "{away}"; }}, 50)</script>').encode()
            with serve({'/': (200, {'Content-Type': 'text/html'}, body)}) as (base, _), \
                    tempfile.TemporaryDirectory() as directory:
                result = browser_collect.capture(Client(delay=0, allow_private=True, proxies={}), base + '/',
                                                 Path(directory) / 'leaving')
                self.assertEqual(result['log']['status'], 'failed', result)
                self.assertIn('Navigation was blocked: off-site', result['evidence'][0]['content'])
                self.assertEqual(outside.requests, [])

    def test_new_document_redirect_after_preflight_is_blocked_before_fetching_target(self):
        with serve({}) as (other, outside):
            offsite = other.replace('127.0.0.1', 'localhost') + '/must-not-fetch'
            routes = {}
            def first_response(stream):
                stream.write(b'<h1>Preflight content</h1>')
                routes['/changing'] = (302, {'Location': offsite}, b'')
            routes['/changing'] = (200, {'Content-Type': 'text/html'}, first_response)
            with serve(routes) as (base, _), tempfile.TemporaryDirectory() as directory:
                result = browser_collect.capture(Client(delay=0, allow_private=True, proxies={}),
                    base + '/changing', Path(directory) / 'capture')
                self.assertEqual(result['log']['status'], 'failed', result)
                self.assertTrue(any('redirect blocked' in item['reason'] for item in result['log']['blocked_requests']))
                self.assertEqual(outside.requests, [])

    def test_mobile_without_viewport_tag_records_both_requested_and_actual_layout(self):
        routes = {'/': (200, {'Content-Type': 'text/html'}, b'<title>Legacy mobile layout</title><h1>Answer</h1>')}
        with serve(routes) as (base, _), tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'mobile'
            result = browser_collect.capture(Client(delay=0, allow_private=True, proxies={}), base + '/',
                                               output, viewport='mobile')
            self.assertEqual(result['log']['status'], 'success', result)
            metrics = json.loads((output / 'measurements.json').read_text())
            self.assertEqual(metrics['requested_viewport']['width'], 390)
            self.assertGreater(metrics['viewport']['width'], 390)
            self.assertIsNone(metrics['viewport_meta'])

    def test_bounded_condition_waits_for_delayed_visible_content_in_both_viewports(self):
        body = b'''<meta name="viewport" content="width=device-width"><title>Delayed</title><h1>Shell</h1>
            <div id="content"></div><script>setTimeout(()=>{
            document.querySelector('#content').innerHTML='<p class="answer">One</p><p class="answer">Two</p>';
            },800)</script>'''
        with serve({'/': (200, {'Content-Type': 'text/html'}, body)}) as (base, _), tempfile.TemporaryDirectory() as directory:
            for viewport in browser_collect.VIEWPORTS:
                output = Path(directory) / viewport
                result = browser_collect.capture(Client(delay=0, allow_private=True, proxies={}), base+'/', output,
                    viewport=viewport, settle_ms=0, ready_selector='.answer', ready_min_count=2, ready_timeout_ms=3000)
                self.assertEqual(result['log']['status'], 'success', result)
                readiness = result['log']['content_readiness']
                self.assertEqual(readiness['status'], 'met')
                self.assertEqual(readiness['matched_elements'], 2)
                self.assertGreater(readiness['elapsed_ms'], 500)
                self.assertIn('<p class="answer">Two</p>', (output/'rendered.html').read_text())

    def test_timeout_preserves_snapshot_and_does_not_count_hidden_elements(self):
        body = b'<title>Partial</title><h1>Shell</h1><p class="answer" style="display:none">Hidden</p>'
        with serve({'/': (200, {'Content-Type': 'text/html'}, body)}) as (base, _), tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'timeout'
            result = browser_collect.capture(Client(delay=0, allow_private=True, proxies={}), base+'/', output,
                settle_ms=0, ready_selector='.answer', ready_timeout_ms=100)
            self.assertEqual(result['log']['status'], 'success')
            self.assertEqual(result['log']['content_readiness']['status'], 'timeout')
            self.assertEqual(result['log']['content_readiness']['matched_elements'], 0)
            self.assertTrue((output/'viewport.png').is_file())
            self.assertTrue((output/'rendered.html').is_file())
            validate_registry(result['evidence'])

    def test_standalone_cli_returns_incomplete_for_a_saved_timeout_snapshot(self):
        routes={'/':(200,{'Content-Type':'text/html'},b'<title>Partial</title><p class="answer">One</p>')}
        with serve(routes) as (base,_), tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'capture'
            result=subprocess.run([sys.executable,str(ROOT/'scripts/browser_collect.py'),base+'/',str(output),
                '--allow-private','--ready-selector','.answer','--ready-min-count','2','--ready-timeout-ms','100',
                '--settle-ms','0'],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,4,result.stderr)
            data=json.loads(result.stdout)
            self.assertEqual(data['status'],'success')
            self.assertEqual(data['content_readiness']['status'],'timeout')
            self.assertEqual(data['content_readiness']['matched_elements'],1)
            self.assertTrue((output/'viewport.png').exists())


if __name__ == '__main__':
    unittest.main()
