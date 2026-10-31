import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import capture_quality
from client_report import render_client_html
from collect import Client, fetch
from delivery import approve, readiness, validate_approval
from new_run import skeleton
from review_topics import TOPICS
from run_contract import audit_run, report_data
from test_collect_contract import serve, html, PROSE
from test_reliability import ROOT

CHALLENGE = (403, {'Content-Type': 'text/html'},
             b'<!doctype html><title>Just a moment...</title><p>Verify you are human to continue.</p>')
ROUTES = {
    '/robots.txt': (200, {'Content-Type': 'text/plain'}, b'User-agent: *\nDisallow:\n'),
    '/': html('Acme valves', PROSE),
    '/services?view=all': CHALLENGE,
    '/thin': html('Loading', '<div id="app"></div>'),
    '/hidden': (200, {'Content-Type': 'text/html', 'X-Robots-Tag': 'noindex'}, html('Hidden', PROSE)[2]),
    '/brochure': (200, {'Content-Type': 'application/pdf'}, b'%PDF-1.4 binary'),
    '/moved': (301, {'Location': 'https://elsewhere.example/'}, b''),
}


def collected(paths):
    """Real collect.py records for the fixture paths, captured from a local server."""
    with serve(ROUTES) as (base, _), tempfile.TemporaryDirectory() as directory:
        urls = [base + path for path in paths]
        evidence, _ = fetch(Client(delay=0, allow_private=True, proxies={}), urls, Path(directory))
    return urls, [item for item in evidence if item['source'] in urls]


def assessed_run(urls, records):
    """Every check assessed from the given captures, as a careless analyst might record it."""
    run = skeleton(url=urls[0], sample=urls, business_type='Industrial B2B', market='UK', language='en',
                   sampling_rationale='Homepage and service journey.', date=records[0]['collected_at'][:10],
                   evidence=records)
    ids = [item['id'] for item in records]
    for items in run['assessment']['criteria'].values():
        for item in items:
            item.update(status='assessed', value=100, evidence_ids=ids, rationale='All sampled pages meet the anchor.')
    for item in run['review']:
        item.update(status='assessed', evidence_ids=ids, summary='Reviewed across the sample.')
    run['summary'] = 'The sampled pages answer customer questions clearly.'
    run['limitations'] = ['AI visibility not measured.']
    return run


def browser_record(identifier, url, dom, viewport='desktop', **measurements):
    values = {'viewport_name': viewport, 'http_status': 200, 'blocked_requests': [],
              'content_readiness': {'status': 'unverified'}, **measurements}
    content = 'Browser observation (untrusted page content).\n' + json.dumps(values) + '\n\nRendered DOM:\n' + dom
    return {'id': identifier, 'source': url, 'collected_at': '2026-10-30T10:00:00Z',
            'method': f'browser_collect.py 1.7.0: Chromium JavaScript observation ({viewport})', 'content': content,
            'status': 'success', 'sha256': hashlib.sha256(content.encode()).hexdigest()}


class Signals(unittest.TestCase):
    def test_collector_records_yield_specific_prompts(self):
        urls, records = collected(['/', '/services?view=all', '/thin', '/hidden', '/brochure', '/moved', '/gone'])
        codes = {record['source'].split('/', 3)[3]: capture_quality.observe(record)['codes'] for record in records}
        self.assertEqual(codes[''], [])
        self.assertEqual(codes['services?view=all'], ['http_error', 'possible_challenge'])
        self.assertEqual(codes['thin'], ['thin_response'])
        self.assertEqual(codes['hidden'], ['noindex_header'])
        self.assertEqual(codes['brochure'], ['non_text_body'])
        self.assertEqual(codes['moved'], ['redirect_not_followed'])
        self.assertEqual(codes['gone'], ['http_error'])
        self.assertFalse(capture_quality.degraded(capture_quality.observe(records[3])))

    def test_browser_prompts_and_unrecognised_methods(self):
        url = 'https://example.com/'
        empty = capture_quality.observe(browser_record('b1', url, '<div id="app"></div>', http_status=500,
                                                       content_readiness={'status': 'timeout'}))
        self.assertEqual(empty['codes'], ['http_error', 'readiness_timeout', 'thin_render'])
        full = capture_quality.observe(browser_record('b2', url, '<main>' + PROSE + '</main>'))
        self.assertEqual(full['codes'], [])
        manual = {'id': 'm', 'source': url, 'collected_at': '2026-10-30T10:00:00Z', 'method': 'saved-http-response',
                  'content': 'Response: 404', 'status': 'success', 'sha256': ''}
        self.assertIsNone(capture_quality.observe(manual))


class ConclusionWarnings(unittest.TestCase):
    def test_challenge_and_error_pages_cannot_silently_support_assessed_conclusions(self):
        urls, records = collected(['/', '/services?view=all', '/gone'])
        run = assessed_run(urls, records)
        scores, warnings = audit_run(run)
        self.assertEqual(scores['overall'], 100)  # Scores are unchanged; the warning carries the doubt.
        self.assertEqual(len(warnings), 2, warnings)
        self.assertIn(urls[1], warnings[0])
        self.assertIn('HTTP 403 response; possible bot challenge', warnings[0])
        self.assertIn('HTTP 404 response', warnings[1])
        result = readiness(run)
        self.assertFalse(result['reviewable'])
        self.assertEqual(sum('Resolve or acknowledge' in item for item in result['blockers']), 2)

    def test_unknown_conclusions_and_an_unprompted_capture_of_the_same_page_are_not_flagged(self):
        urls, records = collected(['/', '/services?view=all'])
        run = assessed_run(urls, records)
        challenge = records[1]['id']
        for items in run['assessment']['criteria'].values():
            for item in items:
                item.update(status='unknown', evidence_ids=[challenge], rationale='The services page was blocked.')
                del item['value']
        for item in run['review']:
            item.update(status='unknown', evidence_ids=[challenge])
        self.assertEqual(audit_run(run)[1], [])
        rendered = browser_record('browser-1', urls[1], '<main>' + PROSE + '</main>')
        run = assessed_run(urls, [*records, rendered])
        self.assertEqual(audit_run(run)[1], [])

    def test_header_checks_may_use_a_thin_response_but_content_checks_may_not(self):
        urls, records = collected(['/thin'])
        run = assessed_run(urls, records)
        for items in run['assessment']['criteria'].values():
            for item in items:
                item.update(status='unknown', evidence_ids=[], rationale='Not assessed.')
                del item['value']
        run['review'] = [item for item in run['review'] if item['category'] == 'technical'
                         and item['topic'] in {'responses', 'robots', 'metadata', 'security'}]
        self.assertEqual(audit_run(run)[1], [])
        content = assessed_run(urls, records)['review'][0]
        run['review'].append(content)
        warnings = audit_run(run)[1]
        self.assertEqual(len(warnings), 1)
        self.assertIn('little visible text in the HTML response', warnings[0])

    def test_response_topic_reports_errors_without_a_prompt(self):
        urls, records = collected(['/gone'])
        run = assessed_run(urls, records)
        for items in run['assessment']['criteria'].values():
            for item in items:
                item.update(status='unknown', evidence_ids=[], rationale='Not assessed.')
                del item['value']
        run['review'] = [item for item in run['review'] if item['topic'] == 'responses']
        self.assertEqual(audit_run(run)[1], [])

    def test_full_search_directive_score_contradicted_by_noindex_is_flagged(self):
        urls, records = collected(['/hidden'])
        warnings = audit_run(assessed_run(urls, records))[1]
        self.assertEqual(len(warnings), 1)
        self.assertIn('noindex response header', warnings[0])
        self.assertIn('search_directives is scored 100', warnings[0])

    def test_older_schemas_receive_the_same_advisory_warnings(self):
        urls, records = collected(['/', '/gone'])
        run = assessed_run(urls, records)
        run['schema_version'] = '1.3.0'
        self.assertTrue(any('HTTP 404 response' in warning for warning in audit_run(run)[1]))


class DeliveryAndReport(unittest.TestCase):
    def test_acknowledged_prompts_appear_in_the_final_report(self):
        urls, records = collected(['/', '/services?view=all'])
        run = assessed_run(urls, records)
        warning = audit_run(run)[1][0]
        raw = (json.dumps(run, indent=2) + '\n').encode()
        with self.assertRaisesRegex(ValueError, 'not ready'):
            approve(raw, 'Reviewer')
        approval = approve(raw, 'Reviewer', acknowledgements={warning: 'The rendered page was reviewed manually.'})
        data = report_data(run)
        data['delivery'] = validate_approval(raw, approval)
        report = render_client_html(data)
        self.assertIn('Capture quality:</strong> 1 of 2 sampled pages needs review', report)
        self.assertIn('How each page was captured', report)
        self.assertIn('HTTP 403 response; possible bot challenge', report)
        self.assertIn('The rendered page was reviewed manually.', report)
        # The challenge's own title must not label the requested page.
        self.assertIn('>services (?view=all)</a>', report)
        self.assertNotIn('Just a moment', report)

    def test_cli_acknowledges_a_warning_whose_url_contains_equals(self):
        urls, records = collected(['/', '/services?view=all'])
        run = assessed_run(urls, records)
        warning = audit_run(run)[1][0]
        self.assertIn('?view=all', warning)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.json'
            path.write_text(json.dumps(run, indent=2) + '\n')
            command = [sys.executable, str(ROOT / 'scripts/delivery.py'), 'approve', str(path), '--reviewer', 'Named']
            refused = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(refused.returncode, 2)
            accepted = subprocess.run([*command, '--acknowledge', f'{warning}=Checked the rendered page.'],
                                      capture_output=True, text=True)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            approval = json.loads((Path(directory) / 'delivery.json').read_text())
            self.assertEqual(approval['acknowledgements'], {warning: 'Checked the rendered page.'})

    def test_clean_report_does_not_claim_complete_content(self):
        urls, records = collected(['/'])
        report = render_client_html(report_data(assessed_run(urls, records)))
        self.assertIn('raised no prompts for the sampled pages; this does not confirm complete or correct content',
                      report)
        self.assertIn('<td data-label="HTTP response">HTTP 200</td>', report)


class PageSummary(unittest.TestCase):
    def test_latest_success_wins_and_failures_stay_visible(self):
        urls, records = collected(['/', '/gone'])
        failed = copy.deepcopy(records[0])
        failed.update(id='retry', status='failed', content='Collection failed: timeout',
                      collected_at='2099-01-01T00:00:00Z')
        failed['sha256'] = hashlib.sha256(failed['content'].encode()).hexdigest()
        pages = capture_quality.page_summary(urls, [*records, failed])
        self.assertEqual(pages[0]['http']['state'], 'success')
        self.assertFalse(pages[0]['attention'])
        self.assertTrue(pages[1]['attention'])
        missing = capture_quality.page_summary(['https://example.com/x'], [])
        self.assertEqual(missing[0]['prompts'], ['HTTP no saved capture'])
        only_failed = capture_quality.page_summary([urls[0]], [failed])
        self.assertEqual(only_failed[0]['prompts'], ['HTTP collection failed'])
        manual = {**records[0], 'method': 'saved-http-response'}  # For example evidence.py --record-id.
        other = capture_quality.page_summary([urls[0]], [manual])[0]
        self.assertEqual((other['http']['state'], other['prompts'], other['attention']), ('other', [], False))

    def test_prompts_are_grouped_by_the_captures_that_raised_them(self):
        urls, records = collected(['/services?view=all'])
        rendered = [browser_record(f'b-{viewport}', urls[0], '<p>Verify you are human.</p>', viewport, http_status=403)
                    for viewport in ('desktop', 'mobile')]
        page = capture_quality.page_summary(urls, [*records, *rendered])[0]
        self.assertEqual(page['prompts'], ['HTTP 403 response (all captures)', 'possible bot challenge (HTTP capture)',
                                           'little visible text after rendering (desktop and mobile)'])
        self.assertFalse(page['title_usable'])

    def test_label_comes_from_the_recapture_not_an_earlier_rate_limit_page(self):
        routes = {'/robots.txt': ROUTES['/robots.txt'],
                  '/product': (429, {'Content-Type': 'text/html', 'Retry-After': '60'},
                               b'<!doctype html><title>Too many requests</title><h1>Too many requests</h1>')}
        with serve(routes) as (base, _), tempfile.TemporaryDirectory() as directory:
            client, url = Client(delay=0, allow_private=True, proxies={}), base + '/product'
            first, _ = fetch(client, [url], Path(directory))
            routes['/product'] = html('Pumpkin cube candle | Shop', PROSE)
            retry, _ = fetch(client, [url], Path(directory), id_prefix='retry')
        records = [item for item in [*first, *retry] if item['source'] == url]
        self.assertEqual([capture_quality.observe(item)['http_status'] for item in records], [429, 200])
        page = capture_quality.page_summary([url], records)[0]
        self.assertEqual((page['title_usable'], page['title']), (True, 'Pumpkin cube candle | Shop'))
        report = render_client_html(report_data(assessed_run([url], records)))
        self.assertIn(f'<td data-label="Page"><a href="{url}">Pumpkin cube candle</a></td>', report)
        self.assertNotIn('Too many requests', report)

    def test_label_skips_failed_captures_without_an_http_capture(self):
        url = 'https://example.com/contact'
        limited = browser_record('b-limited', url, '<title>Too many requests</title>', http_status=429)
        normal = browser_record('b-normal', url, '<title>Contact us</title>' + PROSE, viewport='mobile')
        self.assertEqual(capture_quality.page_summary([url], [normal, limited])[0]['title'], 'Contact us')
        self.assertIsNone(capture_quality.page_summary([url], [limited])[0]['title'])

    def test_workflow_status_names_pages_that_saved_only_an_error(self):
        from unittest.mock import patch
        import audit
        from test_collect_contract import serve_site
        from test_workflow import initialise
        with serve_site() as (base, _), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialise(root, url=base + '/')
            audit.select_sample(root, [base + '/', base + '/missing'], 'Homepage and an observed error')
            with patch('audit.collect.Client', return_value=Client(delay=0, allow_private=True, proxies={})):
                result = audit.resume(root)
        self.assertEqual([step['status'] for step in result['steps']], ['success'] * 3)  # Responses were saved.
        self.assertEqual(result['pages_needing_review'], 1)
        self.assertEqual(result['pages'][1], {'url': base + '/missing', 'http_status': 404, 'needs_review': True,
                                              'prompts': ['HTTP 404 response']})
        self.assertTrue(result['next'].startswith('1 sampled page(s) have capture prompts'))

    def test_all_topics_are_still_covered(self):
        # The new table is additive: the 34 topics and their order are unchanged.
        self.assertEqual(sum(len(topics) for topics in TOPICS.values()), 34)


if __name__ == '__main__':
    unittest.main()
