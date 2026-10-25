from contextlib import redirect_stderr
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import audit
from capture_readiness import settings
from test_reliability import ROOT
from test_workflow import initialise, discovery, http
from test_collect_contract import serve
from collect import Client


class ReadinessWorkflow(unittest.TestCase):
    def test_options_are_bounded_before_creating_capture_artifacts(self):
        for options in ({'timeout_ms':0}, {'timeout_ms':30001}, {'min_count':False}, {'settle_ms':5001},
                        {'selector':''}, {'min_count':2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                settings(**options)

    def test_legacy_configuration_resumes_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=initialise(root)
            config['version']='1.0.0'
            del config['browser_readiness']
            (root/'workflow.json').write_bytes(audit.dump(config))
            original=(root/'workflow.json').read_bytes()
            with patch('audit.collect_discovery',side_effect=discovery):
                self.assertEqual(audit.resume(root)['stage'],'sample')
            self.assertEqual((root/'workflow.json').read_bytes(),original)

    def test_timeout_retries_with_new_attempts_while_preserving_old_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=initialise(root,browser=True)
            config['browser_readiness']=settings(selector='.answer',min_count=2,timeout_ms=1000,settle_ms=0)
            (root/'workflow.json').write_bytes(audit.dump(config))
            audit.select_sample(root,[config['url']],'Single fixture')
            calls=[]
            def browser(client,url,output,identifier,viewport,**options):
                calls.append(options)
                result=http(client,url,output,identifier)
                result['log']['content_readiness']={'status':'timeout' if len(calls)<=2 else 'met'}
                return result
            with patch('audit.collect_discovery',side_effect=discovery), patch('audit.collect_http',side_effect=http), \
                    patch('audit.browser_collect.capture',side_effect=browser):
                first=audit.resume(root)
                self.assertEqual(first['content_readiness']['timeout'],2)
                self.assertEqual(len(first['retryable_steps']),2)
                old=audit.read(root/'run.json')['assessment']['evidence']
                audit.resume(root)
                self.assertEqual(len(calls),2)
                retried=audit.resume(root,retry_failed=True)
            self.assertEqual(retried['content_readiness']['met'],2)
            self.assertEqual(retried['content_readiness']['timeout'],0)
            self.assertEqual(calls[0]['ready_selector'],'.answer')
            self.assertEqual(calls[0]['ready_min_count'],2)
            self.assertTrue(all(record in audit.read(root/'run.json')['assessment']['evidence'] for record in old))

    def test_cli_rejects_readiness_options_without_browser_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'new'
            command=[sys.executable,str(ROOT/'scripts/audit.py'),'start',str(root),'--url','https://example.com/',
                     '--business-type','Demo','--market','Test','--language','en','--ready-selector','.answer']
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('require --browser',result.stderr)
            self.assertFalse(root.exists())

    def test_navigation_seed_is_reused_by_http_collection(self):
        routes={'/':(200,{'Content-Type':'text/html'},b'<title>Home</title><a href="/about">About</a>')}
        with serve(routes) as (base,server), tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            initialise(root,url=base+'/')
            client=Client(delay=0,allow_private=True,proxies={})
            with patch('audit.collect.Client',return_value=client):
                found=audit.resume(root)
                self.assertEqual(found['candidate_count'],2)
                audit.select_sample(root,[base+'/'],'Discovery seed reuse')
                audit.resume(root)
            self.assertEqual([path for path,_ in server.requests].count('/'),1)
            step=audit.cached(root,'http-001')
            self.assertEqual(step['log']['pages'][0]['reused_from_navigation'],'discovery-a1-navigation')
            self.assertIn('<title>Home</title>',step['evidence'][0]['content'])
            self.assertTrue(step['log']['pages'][0]['raw_bytes_available'])
            raw=list((root/'evidence/http-001/attempt-000001/raw').glob('*.bin'))
            self.assertEqual(len(raw),1)
            self.assertIn(b'<title>Home</title>',raw[0].read_bytes())

    def test_discovery_seed_counts_toward_the_distinct_page_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=initialise(root)
            def discovered(output,prefix):
                result=discovery(None,config,output,prefix)
                result['log']['discovery']['navigation']={'status':'success','seed':config['url']}
                return result
            audit.checkpoint(root,'discovery',discovered)
            with self.assertRaisesRegex(ValueError,'49 other pages'):
                audit.select_sample(root,[f'https://example.com/{index}' for index in range(50)],'All other pages')
            self.assertFalse((root/'sample.json').exists())
            audit.select_sample(root,[config['url'],*[f'https://example.com/{index}' for index in range(49)]],
                                'Seed plus other pages within budget')
            self.assertEqual(len(audit.sample(root)['urls']),50)

    def test_cli_interrupt_preserves_config_and_prints_resume_guidance(self):
        with tempfile.TemporaryDirectory(prefix='audit path ') as directory:
            root=Path(directory)
            initialise(root)
            original=(root/'workflow.json').read_bytes()
            error=io.StringIO()
            with patch('sys.argv',['audit.py','resume',str(root)]), patch('audit.resume',side_effect=KeyboardInterrupt), \
                    redirect_stderr(error):
                result=audit.main()
            self.assertEqual(result,130)
            self.assertIn('Completed checkpoints are preserved',error.getvalue())
            self.assertIn('python scripts/audit.py resume',error.getvalue())
            self.assertNotIn('Traceback',error.getvalue())
            self.assertEqual((root/'workflow.json').read_bytes(),original)

    def test_unusable_fetched_seed_still_counts_toward_page_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=initialise(root)
            discovered={'log':{'discovery':{'navigation':{'used':True,'seed':config['url'],
                         'status':'unavailable','http_status':404}}}}
            with patch('audit.cached',return_value=discovered), self.assertRaisesRegex(ValueError,'49 other pages'):
                audit.select_sample(root,[f'https://example.com/{index}' for index in range(50)],'Other pages')


if __name__=='__main__':
    unittest.main()
