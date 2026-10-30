import copy
import hashlib
import unittest
from test_run_contract import run_fixture
from test_reliability import pdf
from run_contract import validate_run, report_data
from review_topics import TOPICS
from evidence import extract


def detailed_run():
    run = run_fixture()
    run['schema_version'] = '1.3.0'
    run['review'] = [{'category': 'content', 'topic': 'freshness', 'status': 'assessed',
        'summary': 'The documented reporting period is visible. UNIQUE_DEEP_REVIEW',
        'affected_urls': run['metadata']['sample'][:], 'evidence_ids': ['page-1']}]
    return run


class AuditDepth(unittest.TestCase):
    def test_new_and_historical_runs_keep_core_scores(self):
        self.assertEqual(validate_run(detailed_run()), validate_run(run_fixture()))
        self.assertEqual(report_data(detailed_run())['overall_score'], 100)

    def test_detailed_review_is_not_silently_lost(self):
        html = pdf.generate_html(report_data(detailed_run()))
        self.assertIn('UNIQUE_DEEP_REVIEW', html)
        self.assertIn('href="https://example.com/"', html)
        self.assertNotIn('page-1', html)

    def test_missing_topics_and_legacy_scope_stay_visible(self):
        html = pdf.generate_html(report_data(run_fixture()))
        self.assertIn('no separate assessment recorded', html)
        self.assertIn('0 of 34', html)
        self.assertIn('not a complete health score', html)

    def test_raw_evidence_only_in_technical_export(self):
        run = detailed_run()
        record = run['assessment']['evidence'][0]
        record['content'] = 'RAW_CAPTURE_UNIQUE_MARKER'
        record['sha256'] = hashlib.sha256(record['content'].encode()).hexdigest()
        client = pdf.generate_html(report_data(run))
        technical = pdf.generate_html(report_data(run, technical=True))
        self.assertNotIn('RAW_CAPTURE_UNIQUE_MARKER', client)
        self.assertIn('RAW_CAPTURE_UNIQUE_MARKER', technical)
        self.assertIn('page-1', technical)

    def test_all_finding_details_are_preserved(self):
        run = detailed_run()
        for key in ('observed', 'claim', 'consequence', 'fix', 'acceptance', 'confidence_reason'):
            run['findings'][0][key] = f'UNIQUE_{key}_MARKER'
        html = pdf.generate_html(report_data(run))
        for key in ('observed', 'claim', 'consequence', 'fix', 'acceptance', 'confidence_reason'):
            self.assertIn(f'UNIQUE_{key}_MARKER', html)

    def test_invalid_review_contracts(self):
        for changes in ({'status': 'good'}, {'topic': 'imaginary'}, {'category': 'imaginary'},
                        {'summary': ''}, {'affected_urls': []}, {'affected_urls': ['https://other.example/']},
                        {'evidence_ids': ['missing']}, {'evidence_ids': []}):
            run = detailed_run()
            run['review'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_run(run)
        run = detailed_run()
        run['review'].append(copy.deepcopy(run['review'][0]))
        with self.assertRaises(ValueError):
            validate_run(run)

    def test_unknown_allowed_without_evidence_but_not_pass(self):
        run = detailed_run()
        run['review'][0].update(status='unknown', evidence_ids=[])
        validate_run(run)
        html = pdf.generate_html(report_data(run))
        self.assertIn('Detailed checks to complete', html)
        self.assertIn('0 of 34', html)

    def test_failed_evidence_cannot_establish_review(self):
        run = detailed_run()
        run['assessment']['criteria'] = {}
        run['findings'] = []
        run['assessment']['evidence'][0]['status'] = 'failed'
        with self.assertRaises(ValueError):
            validate_run(run)
        run['review'][0]['status'] = 'unknown'
        validate_run(run)

    def test_review_must_cover_claimed_urls(self):
        run = detailed_run()
        run['assessment']['criteria'] = {}
        run['metadata']['sample'].append('https://example.com/other')
        run['review'][0]['affected_urls'].append('https://example.com/other')
        with self.assertRaises(ValueError):
            validate_run(run)

    def test_html_inputs_remain_inert_in_new_blocks(self):
        run = detailed_run()
        run['review'][0]['summary'] = '<script>bad()</script> **fake score**'
        run['findings'][0]['claim'] = '<img src=x onerror=bad()>'
        html = pdf.generate_html(report_data(run))
        self.assertNotIn('<script>bad()', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;script&gt;bad()', html)

    def test_empty_review_is_valid_but_not_complete(self):
        run = detailed_run()
        run['review'] = []
        validate_run(run)
        self.assertIn('0 of 34', pdf.generate_html(report_data(run)))
        run['schema_version'] = '1.2.0'
        with self.assertRaises(ValueError):
            validate_run(run)

    def test_astro_and_boolean_attributes_are_not_errors(self):
        html = '<main data-astro-cid-abc inert><input disabled required><details open><script async defer></script></details></main>'
        self.assertEqual(extract(html)['errors'], [])
        self.assertTrue(extract('<script type="application/ld+json">{bad}</script>')['errors'])

    def test_complete_topic_catalog_renders_without_changing_score(self):
        run = detailed_run()
        run['review'] = [dict(category=c, topic=t, status='assessed', summary=f'Reviewed {c} {t}',
            affected_urls=run['metadata']['sample'], evidence_ids=['page-1']) for c, ts in TOPICS.items() for t in ts]
        self.assertEqual(validate_run(run)['overall'], 100)
        self.assertIn('34 of 34', pdf.generate_html(report_data(run)))

    def test_scope_is_declared_not_claimed_as_observed(self):
        html = pdf.generate_html(report_data(detailed_run()))
        self.assertIn('Declared sample: 1 page.', html)
        self.assertNotIn('Pages Analyzed', html)
        self.assertNotIn('Conclusions apply only to the listed subset', html)
        self.assertNotIn('Scope: 1 of 1', html)

    def test_full_page_inventory_is_not_repeated_per_topic(self):
        run = detailed_run()
        run['findings'] = []
        run['review'] = [dict(category=c, topic=t, status='assessed', summary=f'Reviewed {c} {t}',
            affected_urls=run['metadata']['sample'], evidence_ids=['page-1']) for c, ts in TOPICS.items() for t in ts]
        html = pdf.generate_html(report_data(run))
        # Once in the per-page capture table and once in the reviewed-page inventory, never per topic.
        self.assertEqual(html.count('href="https://example.com/"'), 2)

    def test_technical_preserves_detailed_review(self):
        html = pdf.generate_html(report_data(detailed_run(), technical=True))
        self.assertIn('UNIQUE_DEEP_REVIEW', html)
        self.assertIn('content.freshness', html)

    def test_malformed_external_source_renders_as_inert_text(self):
        run = detailed_run()
        record = copy.deepcopy(run['assessment']['evidence'][0])
        record.update(id='external', source='https://[invalid')
        run['assessment']['evidence'].append(record)
        run['findings'][0]['evidence_ids'].append('external')
        html = pdf.generate_html(report_data(run))
        self.assertIn('https://[invalid', html)
        self.assertNotIn('href="https://[invalid', html)
