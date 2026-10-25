from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import os
from unittest.mock import patch

import audit
import capture_readiness
from collect import Client, now, record
from delivery import approve
from evidence import strict_json
from test_collect_contract import serve_site, serve
from test_delivery import complete_run
from test_reliability import ROOT


def initialise(root, *, browser=False, url='https://example.com/'):
    config = {'version': audit.WORKFLOW_VERSION, 'url': url, 'business_type': 'Services', 'market': 'UK',
              'language': 'en', 'date': datetime.now(timezone.utc).date().isoformat(),
              'browser': browser, 'allow_private': False, 'browser_readiness': capture_readiness.settings()}
    (root / 'workflow.json').write_bytes(audit.dump(config))
    return config


def discovery(client, config, output, prefix):
    output.mkdir()
    return {'evidence': [record(prefix, config['url'], now(), 'Discovery fixture', 'success')],
            'log': {'status': 'success', 'discovery': {'candidates': [{'loc': config['url']}]}}}


def http(client, url, output, prefix):
    output.mkdir()
    return {'evidence': [record(prefix, url, now(), 'Page fixture', 'success')], 'log': {'status': 'success'}}


class Workflow(unittest.TestCase):
    def test_discover_select_resume_then_repeat_without_network_or_rewrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialise(root)
            with patch('audit.collect_discovery', side_effect=discovery) as discover, \
                    patch('audit.collect_http', side_effect=http) as fetch:
                result = audit.resume(root)
                self.assertEqual(result['stage'], 'sample')
                self.assertFalse((root / 'run.json').exists())
                audit.select_sample(root, ['https://example.com/'], 'Homepage fixture')
                self.assertEqual(audit.resume(root)['stage'], 'review')
                original = (root / 'run.json').read_bytes()
                audit.resume(root)
                self.assertEqual(discover.call_count, 1)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(original, (root / 'run.json').read_bytes())

    def test_interruption_reuses_finished_pages_and_retains_partial_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialise(root)
            urls = ['https://example.com/', 'https://example.com/service']
            audit.select_sample(root, urls, 'Main journey')
            def interrupted(client, url, output, prefix):
                if url.endswith('/service'):
                    output.mkdir()
                    (output / 'partial.bin').write_bytes(b'partial observation')
                    raise KeyboardInterrupt()
                return http(client, url, output, prefix)
            with patch('audit.collect_discovery', side_effect=discovery), \
                    patch('audit.collect_http', side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                audit.resume(root)
            self.assertFalse((root / 'run.json').exists())
            self.assertEqual(audit.status(root)['steps'][-1]['status'], 'pending')
            with patch('audit.collect_http', side_effect=http) as fetch:
                audit.resume(root)
                self.assertEqual(fetch.call_count, 1)
            self.assertTrue((root / 'evidence/http-002/attempt-000001/partial.bin').exists())
            self.assertTrue((root / 'evidence/http-002/attempt-000002/result.json').exists())

    def test_explicit_retry_preserves_analysis_and_prior_failed_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialise(root)
            audit.select_sample(root, ['https://example.com/'], 'Homepage fixture')
            def unavailable(client, url, output, prefix):
                result = http(client, url, output, prefix)
                result['evidence'][0]['status'] = 'failed'
                result['log']['status'] = 'failed'
                return result
            with patch('audit.collect_discovery', side_effect=discovery), \
                    patch('audit.collect_http', side_effect=unavailable):
                first = audit.resume(root)
            self.assertIn('http-001', first['retryable_steps'])
            run = audit.read(root / 'run.json')
            run['summary'] = 'Analyst work must survive a retry.'
            (root / 'run.json').write_bytes(audit.dump(run))
            with patch('audit.collect_http', side_effect=http) as fetch:
                audit.resume(root)
                self.assertEqual(fetch.call_count, 0)
                result = audit.resume(root, retry_failed=True)
                self.assertEqual(fetch.call_count, 1)
            updated = audit.read(root / 'run.json')
            self.assertEqual(updated['summary'], run['summary'])
            self.assertTrue(set(item['id'] for item in run['assessment']['evidence']).issubset(
                item['id'] for item in updated['assessment']['evidence']))
            self.assertEqual(result['retryable_steps'], [])
            self.assertEqual(len(audit.attempts(root, 'http-001')), 2)

    def test_corrupt_checkpoint_is_reported_instead_of_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialise(root)
            with patch('audit.collect_discovery', side_effect=discovery):
                audit.resume(root)
            path = root / 'evidence/discovery/attempt-000001/result.json'
            result = audit.read(path)
            result['evidence'][0]['content'] = 'Changed after capture'
            path.write_bytes(audit.dump(result))
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                audit.resume(root)

    def test_browser_steps_are_opt_in_and_checkpointed_per_viewport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialise(root, browser=True)
            audit.select_sample(root, ['https://example.com/'], 'Homepage fixture')
            def browser(client, url, output, identifier, viewport, **options):
                return http(client, url, output, identifier)
            with patch('audit.collect_discovery', side_effect=discovery), patch('audit.collect_http', side_effect=http), \
                    patch('audit.browser_collect.capture', side_effect=browser) as capture:
                result = audit.resume(root)
                audit.resume(root)
                self.assertEqual(capture.call_count, 2)
            self.assertEqual(len(result['steps']), 4)

    def test_frozen_sample_and_metadata_cannot_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialise(root)
            audit.select_sample(root, ['https://example.com/'], 'Homepage fixture')
            with patch('audit.collect_discovery', side_effect=discovery), patch('audit.collect_http', side_effect=http):
                audit.resume(root)
            with self.assertRaises(ValueError):
                audit.select_sample(root, ['https://example.com/other'], 'Changed scope')
            run = audit.read(root / 'run.json')
            run['metadata']['market'] = 'Other market'
            (root / 'run.json').write_bytes(audit.dump(run))
            with patch('audit.collect.Client') as client, self.assertRaisesRegex(ValueError, 'metadata diverged'):
                audit.resume(root)
            client.assert_not_called()

    def test_read_only_status_marks_changed_approval_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = initialise(root)
            audit.select_sample(root, ['https://example.com/'], 'Homepage fixture')
            with patch('audit.collect_discovery', side_effect=discovery), patch('audit.collect_http', side_effect=http):
                audit.resume(root)
            run = complete_run()
            run['metadata'].update({key: config[key] for key in ('url', 'business_type', 'market', 'language', 'date')})
            run['metadata']['sampling_rationale'] = 'Homepage fixture'
            run['assessment']['evidence'] += audit.read(root / 'run.json')['assessment']['evidence']
            source = root / 'run.json'
            source.write_bytes(audit.dump(run))
            (root / 'delivery.json').write_bytes(audit.dump(approve(source.read_bytes(), 'Reviewer')))
            self.assertEqual(audit.status(root)['stage'], 'ready')
            source.write_bytes(source.read_bytes() + b' ')
            self.assertEqual(audit.status(root)['approval']['state'], 'stale')

    def test_concurrent_writer_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with audit.lock(root), self.assertRaisesRegex(ValueError, 'Another command'):
                with audit.lock(root):
                    self.fail('Second writer acquired the lock')

    def test_reviewed_export_cannot_skip_a_new_unembedded_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = initialise(root)
            audit.select_sample(root, ['https://example.com/'], 'Homepage fixture')
            with patch('audit.collect_discovery', side_effect=discovery), patch('audit.collect_http', side_effect=http):
                audit.resume(root)
            run = complete_run()
            run['metadata'].update({key: config[key] for key in ('url', 'business_type', 'market', 'language', 'date')})
            run['metadata']['sampling_rationale'] = 'Homepage fixture'
            run['assessment']['evidence'] += audit.read(root / 'run.json')['assessment']['evidence']
            source = root / 'run.json'
            source.write_bytes(audit.dump(run))
            (root / 'delivery.json').write_bytes(audit.dump(approve(source.read_bytes(), 'Reviewer')))
            next_attempt = root / 'evidence/http-001/attempt-000002'
            checkpoint = http(None, config['url'], next_attempt, 'http-001-a2')
            (next_attempt / 'result.json').write_bytes(audit.dump(checkpoint))
            progress = audit.status(root)
            self.assertEqual(progress['stage'], 'collection')
            self.assertIn('http-001', progress['unsynced_steps'])
            with self.assertRaisesRegex(ValueError, 'Finish collection'):
                audit.export(root, root / 'final.html', final=True)
            audit.resume(root)
            self.assertEqual(audit.status(root)['approval']['state'], 'stale')
            self.assertEqual(audit.read(source)['summary'], run['summary'])

    def test_cli_start_refuses_nonempty_directory_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'keep.txt'
            original.write_text('Preserve me')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/audit.py'), 'start', str(root),
                '--url', 'https://example.com/', '--business-type', 'Services', '--market', 'UK', '--language', 'en'],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(original.read_text(), 'Preserve me')

    def test_local_http_workflow_integration(self):
        with serve_site() as (base, _), tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialise(root, url=base + '/')
            audit.select_sample(root, [base + '/', base + '/missing'], 'Homepage and observed error fixture')
            client = Client(delay=0, allow_private=True, proxies={})
            with patch('audit.collect.Client', return_value=client):
                result = audit.resume(root)
                captures = (root / 'run.json').read_bytes()
                audit.resume(root)
            self.assertEqual(result['stage'], 'review')
            run = strict_json(captures.decode())
            self.assertIn('Response: 404', run['assessment']['evidence'][-1]['content'])
            self.assertEqual(captures, (root / 'run.json').read_bytes())
            audit.export(root, root / 'draft.html')
            self.assertIn('DRAFT — review required', (root / 'draft.html').read_text())


@unittest.skipUnless(os.environ.get('GEO_RUN_RENDER_TESTS') == '1', 'Set GEO_RUN_RENDER_TESTS=1 for actual browser checks')
class RealWorkflowCLI(unittest.TestCase):
    def test_configured_readiness_is_recorded_and_reused_by_the_cli(self):
        body=b'''<meta name="viewport" content="width=device-width"><title>Delayed</title><h1>Shell</h1>
            <div id="content"></div><script>setTimeout(()=>{document.querySelector('#content').innerHTML=
            '<p class="answer">One</p><p class="answer">Two</p>';},800)</script>'''
        with serve({'/':(200,{'Content-Type':'text/html'},body)}) as (base,server), tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'audit'
            command=[sys.executable,str(ROOT/'scripts/audit.py')]
            start=subprocess.run([*command,'start',str(root),'--url',base+'/',
                '--business-type','Demo','--market','Test','--language','en','--browser','--allow-private',
                '--sample',base+'/','--sampling-rationale','Delayed content fixture','--ready-selector','.answer',
                '--ready-min-count','2','--ready-timeout-ms','3000','--settle-ms','0'],
                capture_output=True,text=True,timeout=60)
            self.assertEqual(start.returncode,0,start.stderr)
            self.assertEqual(strict_json(start.stdout)['content_readiness']['met'],2)
            self.assertEqual(audit.configuration(root)['browser_readiness']['selector'],'.answer')
            count=len(server.requests)
            repeat=subprocess.run([*command,'resume',str(root)],capture_output=True,text=True,timeout=30)
            self.assertEqual(repeat.returncode,0,repeat.stderr)
            self.assertEqual(len(server.requests),count)
            self.assertEqual(strict_json(repeat.stdout)['content_readiness']['met'],2)

    def test_start_sample_collect_resume_and_draft_export(self):
        with serve_site() as (base, server), tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'audit'
            command = [sys.executable, str(ROOT / 'scripts/audit.py')]
            def run(*args):
                result = subprocess.run([*command, *map(str, args)], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                return audit.strict_json(result.stdout)
            started = run('start', root, '--url', base + '/', '--business-type', 'Synthetic fixture',
                          '--market', 'UK', '--language', 'en', '--browser', '--allow-private')
            self.assertEqual(started['stage'], 'sample')
            selected = run('sample', root, '--sample', base + '/', '--sampling-rationale', 'Homepage fixture')
            self.assertEqual(selected['stage'], 'collection')
            collected = run('resume', root)
            self.assertEqual(collected['stage'], 'review')
            self.assertEqual(collected['retryable_steps'], [])
            original = (root / 'run.json').read_bytes()
            requests = len(server.requests)
            run('resume', root)
            self.assertEqual((root / 'run.json').read_bytes(), original)
            self.assertEqual(len(server.requests), requests)
            self.assertEqual(len(list((root / 'evidence').glob('browser-*/attempt-*/viewport.png'))), 2)
            exported = run('export', root, root / 'draft.html')
            self.assertEqual(exported['state'], 'draft')
            self.assertIn('DRAFT — review required', (root / 'draft.html').read_text())
            rejected = subprocess.run([*command, 'export', str(root), str(root / 'final.html'), '--final'],
                                      capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertFalse((root / 'final.html').exists())


if __name__ == '__main__':
    unittest.main()
