import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from client_report import render_client_html
from delivery import approve, check_keys, readiness, validate_approval
from new_run import skeleton
from review_topics import TOPICS
from run_contract import report_data, audit_run
from test_provenance_contract import strict_run, add_page
from test_reliability import ROOT, pdf


def complete_run():
    run = strict_run()
    run['review'] = [{'category': category, 'topic': topic, 'status': 'assessed',
                     'summary': f'Synthetic review of {category}: {topic}.',
                     'affected_urls': run['metadata']['sample'][:], 'evidence_ids': ['page-1']}
                    for category, topics in TOPICS.items() for topic in topics]
    return run


def raw(run):
    return (json.dumps(run, ensure_ascii=False, indent=2) + '\n').encode()


class Delivery(unittest.TestCase):
    def test_skeleton_is_a_valid_but_undeliverable_draft(self):
        run = skeleton(url='https://example.com/', sample=['https://example.com/'], business_type='Services',
                       market='UK', language='en', sampling_rationale='Homepage fixture', date='2026-10-25')
        audit_run(run)
        result = readiness(run)
        self.assertFalse(result['reviewable'])
        self.assertTrue(any('placeholder' in text for text in result['blockers']))
        with self.assertRaisesRegex(ValueError, 'not ready'):
            approve(raw(run), 'Reviewer')
        html = render_client_html(report_data(run))
        self.assertIn('DRAFT — review required', html)
        self.assertIn('content="draft"', html)

    def test_complete_run_requires_an_explicit_reviewer(self):
        run = complete_run()
        self.assertTrue(readiness(run)['reviewable'])
        with self.assertRaisesRegex(ValueError, 'reviewer'):
            approve(raw(run), ' ')
        approval = approve(raw(run), 'A Reviewer')
        self.assertEqual(validate_approval(raw(run), approval)['state'], 'ready')

    def test_edit_or_reformat_invalidates_review(self):
        source = raw(complete_run())
        approval = approve(source, 'Reviewer')
        for edited in (source + b' ', source.replace(b'Synthetic', b'Changed')):
            with self.subTest(edited=edited[:30]), self.assertRaisesRegex(ValueError, 'changed after review'):
                validate_approval(edited, approval)

    def test_scope_exclusions_are_named_and_visible(self):
        run = complete_run()
        run['review'] = [item for item in run['review'] if (item['category'], item['topic']) != ('technical', 'performance')]
        self.assertFalse(readiness(run)['reviewable'])
        exclusion = {'review.technical.performance': 'Field data access was outside the agreed scope.'}
        approval = approve(raw(run), '<Reviewer>', exclusions=exclusion)
        data = report_data(run)
        data['delivery'] = validate_approval(raw(run), approval)
        html = render_client_html(data)
        self.assertIn('Reviewed final report', html)
        self.assertIn('Agreed scope exclusions', html)
        self.assertIn('Field data access was outside', html)
        self.assertNotIn('review.technical.performance', html)
        self.assertIn('&lt;Reviewer&gt;', html)
        self.assertNotIn('DRAFT —', html)

    def test_unknown_core_and_partial_page_reviews_block_delivery(self):
        run = complete_run()
        criterion = run['assessment']['criteria']['content'][0]
        criterion['status'] = 'unknown'
        del criterion['value']
        self.assertIn('Unfinished check: core.content.customer_completeness', readiness(run)['blockers'])
        run = complete_run()
        add_page(run)
        self.assertTrue(any('only part of the sample' in text for text in readiness(run)['blockers']))

    def test_all_na_category_does_not_require_an_invented_total(self):
        run = complete_run()
        for criterion in run['assessment']['criteria']['schema']:
            criterion.update(status='not_applicable', reason='no_structured_data_in_sample')
            del criterion['value']
        self.assertIsNone(audit_run(run)[0]['overall'])
        self.assertTrue(readiness(run)['reviewable'])

    def test_empty_or_unknown_exclusion_rejected_and_cannot_exclude_everything(self):
        run = complete_run()
        for exclusions in ({'review.unknown.x': 'Out of scope'}, {'review.technical.mobile': ''}):
            with self.subTest(exclusions=exclusions), self.assertRaises(ValueError):
                readiness(run, exclusions=exclusions)
        exclusions = dict.fromkeys(check_keys(audit_run(run)[0]), 'Outside scope')
        self.assertFalse(readiness(run, exclusions=exclusions)['reviewable'])

    def test_warning_needs_an_explanation_and_placeholders_cannot_be_waived(self):
        run = complete_run()
        item = run['assessment']['evidence'][0]
        item['collected_at'] = '2020-01-01T00:00:00Z'
        warning = audit_run(run)[1][0]
        self.assertFalse(readiness(run)['reviewable'])
        self.assertTrue(readiness(run, acknowledgements={warning: 'Historical snapshot explicitly requested.'})['reviewable'])
        data = report_data(run)
        approval = approve(raw(run), 'Reviewer', acknowledgements={warning: 'Historical snapshot explicitly requested.'})
        data['delivery'] = validate_approval(raw(run), approval)
        html = render_client_html(data)
        self.assertIn('Historical snapshot explicitly requested.', html)
        self.assertNotIn('Evidence page-1', html)
        run['summary'] = '[skeleton placeholder]'
        warnings = dict.fromkeys(audit_run(run)[1], 'Acknowledged')
        self.assertFalse(readiness(run, acknowledgements=warnings)['reviewable'])

    def test_malformed_or_future_approval_is_rejected(self):
        source = raw(complete_run())
        for key, value in (('reviewed_at', '2099-01-01T00:00:00Z'), ('version', 'unknown'),
                           ('reviewer', None), ('exclusions', [])):
            approval = approve(source, 'Reviewer')
            approval[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_approval(source, approval)

    def test_final_export_checks_approval_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, approval_path = root / 'run.json', root / 'delivery.json'
            source.write_bytes(raw(complete_run()))
            approval_path.write_text(json.dumps(approve(source.read_bytes(), 'Reviewer')))
            target = root / 'final.html'
            pdf.export_report(source, target, final=True)
            self.assertIn('Reviewed final report', target.read_text())
            original = approval_path.read_bytes()
            with self.assertRaises(ValueError):
                pdf.export_report(source, approval_path, final=True, overwrite=True)
            self.assertEqual(approval_path.read_bytes(), original)
            source.write_bytes(source.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'changed after review'):
                pdf.export_report(source, root / 'stale.html', final=True)
            self.assertFalse((root / 'stale.html').exists())

    def test_final_export_cannot_use_legacy_or_technical_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'run.json'
            source.write_bytes(raw(complete_run()))
            for options in ({'legacy_markdown': True}, {'technical': True}):
                with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'client reports only'):
                    pdf.export_report(source, root / 'out.html', final=True, **options)

    def test_cli_draft_exit_and_non_overwriting_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'run.json'
            source.write_bytes(raw(strict_run()))
            command = [sys.executable, str(ROOT / 'scripts/delivery.py')]
            result = subprocess.run([*command, 'check', str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 4, result.stderr)
            self.assertEqual(json.loads(result.stdout)['state'], 'draft')
            source.write_bytes(raw(complete_run()))
            args = [*command, 'approve', str(source), '--reviewer', 'Reviewer']
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            previous = (root / 'delivery.json').read_bytes()
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual((root / 'delivery.json').read_bytes(), previous)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), json.loads(previous)['run_sha256'])


if __name__ == '__main__':
    unittest.main()
