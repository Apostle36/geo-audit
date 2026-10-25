import json
import unittest

from capture_readiness import latest_browser_observations
from client_report import page_label, render_client_html
from collect import record
from run_contract import audit_run, report_data
from evidence import document_title
from test_delivery import complete_run


def browser_record(identifier, url, viewport_name, state='unverified', *, collected_at='2026-10-25T20:00:00Z', **extra):
    metrics={'viewport_name':viewport_name,'requested_viewport':{'width':390 if viewport_name=='mobile' else 1440},
             'viewport':{'width':390 if viewport_name=='mobile' else 1440},'viewport_meta':'width=device-width',
             'blocked_requests':[],'content_readiness':{'status':state},**extra}
    item=record(identifier,url,collected_at,
                'Browser observation (untrusted page content).\n'+json.dumps(metrics)+'\n\nRendered DOM:\n<title>Saved</title>',
                'success')
    item['method']='browser_collect.py 1.5.1: Chromium JavaScript observation'
    return item


class CaptureReporting(unittest.TestCase):
    def test_latest_viewport_observation_replaces_stale_timeout_for_display_only(self):
        run=complete_run()
        url=run['metadata']['sample'][0]
        old=browser_record('browser-old',url,'desktop','timeout')
        new=browser_record('browser-new',url,'desktop','met',collected_at='2026-10-25T20:01:00Z')
        run['assessment']['evidence'] += [old,new]
        observations=latest_browser_observations(run)
        self.assertEqual(len(observations),1)
        self.assertEqual(observations[0]['measurements']['content_readiness']['status'],'met')
        html=render_client_html(report_data(run))
        self.assertIn('1 configured content checks met; 0 timed out',html)
        self.assertEqual(run['assessment']['evidence'][-2:], [old,new])

    def test_old_capture_without_readiness_remains_unverified(self):
        run=complete_run()
        item=browser_record('browser-old',run['metadata']['url'],'desktop')
        text=item['content'].replace(', "content_readiness": {"status": "unverified"}', '')
        old=record(item['id'],item['source'],item['collected_at'],text,'success')
        old['method']=item['method']
        run['assessment']['evidence'].append(old)
        html=render_client_html(report_data(run))
        self.assertIn('1 unverified or not recorded',html)

    def test_timeout_mobile_scaling_and_blocked_resources_are_visible_and_escaped(self):
        run=complete_run()
        run['assessment']['evidence'].append(browser_record('browser-mobile',run['metadata']['url'],'mobile','timeout',
            viewport={'width':980},viewport_meta=None,
            blocked_requests=[{'url':'https://fonts.example/style.css','reason':'<script>untrusted</script>'}]))
        html=render_client_html(report_data(run))
        self.assertIn('1 timed out',html)
        self.assertIn('Layout width 980 px for a 390 px requested viewport',html)
        self.assertIn('No viewport declaration was recorded',html)
        self.assertIn('fonts.example',html)
        self.assertNotIn('<script>untrusted</script>',html)
        self.assertIn('id="capture-conditions"',html)
        self.assertIn('href="#capture-conditions"',html)

    def test_readable_titles_keep_query_and_pagination_variants_distinct(self):
        self.assertEqual(page_label('https://example.com/catalogue/category/books/travel_2/index.html'),'travel')
        self.assertEqual(page_label('https://example.com/catalogue/long-product_1000/index.html','A useful title | Site'),
                         'A useful title')
        self.assertEqual(page_label('https://example.com/js/page/2/'),'page 2')
        self.assertEqual(page_label('https://example.com/js-delayed/?delay=1500'),'js delayed (?delay=1500)')

    def test_capture_measurements_do_not_award_scores(self):
        run=complete_run()
        before=audit_run(run)[0]
        run['assessment']['evidence'].append(browser_record('browser-verified',run['metadata']['url'],'desktop','met'))
        after=audit_run(run)[0]
        self.assertEqual(before,after)
        self.assertIn('chosen document elements',render_client_html(report_data(run)))

    def test_title_labels_do_not_parse_unrelated_schema_or_inline_graphic_titles(self):
        body='<svg><title>Graphic</title></svg><title>Useful page</title><script type="application/ld+json">'
        body += '['*2000+'0'+']'*2000+'</script>'
        self.assertEqual(document_title(body),'Useful page')
        headers='Request: GET https://example.com/\nX-Diagnostic: <title>Header</title>\n\n'
        self.assertEqual(document_title(headers+body),'Useful page')

    def test_malformed_measurement_values_do_not_crash_client_rendering(self):
        run=complete_run()
        run['assessment']['evidence'].append(browser_record('browser-unknown',run['metadata']['url'],'desktop',[]))
        run['assessment']['evidence'].append(browser_record('browser-invalid',run['metadata']['url'],[]))
        self.assertIn('1 unverified or not recorded',render_client_html(report_data(run)))


if __name__=='__main__':
    unittest.main()
