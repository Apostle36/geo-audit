import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_audit_depth import detailed_run
from test_reliability import ROOT
from run_contract import audit_run, comparable, report_data, validate_run, PLACEHOLDER


def strict_run():
    run = detailed_run()
    run['schema_version'] = '1.4.0'
    return run


def add_page(run, url='https://example.com/b', content='Second page'):
    record = copy.deepcopy(run['assessment']['evidence'][0])
    record.update(id='page-2', source=url, content=content, sha256=hashlib.sha256(content.encode()).hexdigest())
    run['assessment']['evidence'].append(record)
    run['metadata']['sample'].append(url)
    for items in run['assessment']['criteria'].values():
        for item in items:
            item['evidence_ids'] = ['page-1', 'page-2']
    run['review'][0].update(affected_urls=run['metadata']['sample'][:], evidence_ids=['page-1', 'page-2'])
    return run


def set_content(record, content):
    record.update(content=content, sha256=hashlib.sha256(content.encode()).hexdigest())


def schema_not_applicable(run):
    for item in run['assessment']['criteria']['schema']:
        item.update(status='not_applicable', reason='no_structured_data_in_sample')
        del item['value']
    return run


def finding_on_wrong_page(run):
    add_page(run)
    run['findings'][0].update(affected_urls=['https://example.com/b'], evidence_ids=['page-1'])


def hypothesis_rated_high(run):
    run['findings'][0].update(kind='hypothesis', severity='high')


def unknown_rated_critical(run):
    run['findings'][0].update(kind='unknown', status='unknown', severity='critical')


def duplicate_affected_url(run):
    run['findings'][0]['affected_urls'] *= 2


def fragment_sample(run):
    add_page(run, url='https://example.com/#top')


def structured_data_marked_absent(run):
    schema_not_applicable(run)
    set_content(run['assessment']['evidence'][0], '<div itemscope itemtype="https://schema.org/Organization"></div>')


ISSUES = (finding_on_wrong_page, hypothesis_rated_high, unknown_rated_critical, duplicate_affected_url,
          fragment_sample, structured_data_marked_absent)


class ProvenanceContract(unittest.TestCase):
    def test_strict_fixture_is_clean(self):
        scores, warnings = audit_run(strict_run())
        self.assertEqual(scores['overall'], 100)
        self.assertEqual(warnings, [])

    def test_strict_schema_rejects_and_legacy_schemas_warn(self):
        for issue in ISSUES:
            run = strict_run()
            issue(run)
            with self.subTest(issue=issue.__name__, schema='1.4.0'), self.assertRaises(ValueError):
                validate_run(run)
            for legacy in ('1.3.0', '1.2.0'):
                old = copy.deepcopy(run)
                old['schema_version'] = legacy
                if legacy == '1.2.0':
                    del old['review']
                with self.subTest(issue=issue.__name__, schema=legacy):
                    _, warnings = audit_run(old)
                    self.assertTrue(any('schema 1.4.0 rejects it' in warning for warning in warnings), warnings)

    def test_finding_evidence_must_capture_each_affected_page(self):
        run = add_page(strict_run())
        run['findings'][0].update(affected_urls=['https://example.com/b'], evidence_ids=['page-1'])
        with self.assertRaisesRegex(ValueError, 'cites no capture.*example.com/b'):
            validate_run(run)
        run['findings'][0]['evidence_ids'] = ['page-2']
        validate_run(run)
        # Unknown findings may rest on failed or partial collection.
        run['findings'][0].update(kind='unknown', status='unknown', evidence_ids=['page-1'])
        validate_run(run)

    def test_true_absence_of_structured_data_remains_not_applicable(self):
        run = schema_not_applicable(strict_run())
        set_content(run['assessment']['evidence'][0], '<html><head><meta property="og:title" content="x"></head></html>')
        self.assertIsNone(validate_run(run)['categories']['schema']['score'])
        set_content(run['assessment']['evidence'][0], '<script type="application/ld+json">{"@type":"Thing"}</script>')
        with self.assertRaisesRegex(ValueError, 'JSON-LD'):
            validate_run(run)

    def test_advisory_warnings_do_not_reject(self):
        run = strict_run()
        run['summary'] = f'{PLACEHOLDER} Replace with the reviewed conclusion.'
        record = copy.deepcopy(run['assessment']['evidence'][0])
        record.update(id='future', source='https://example.com/press', collected_at='2099-01-01T00:00:00Z')
        stale = dict(record, id='stale', collected_at='2025-01-01T00:00:00Z')
        late = dict(record, id='late', collected_at='2026-09-20T00:00:00Z')
        run['assessment']['evidence'] += [record, stale, late]
        scores, warnings = audit_run(run)
        self.assertEqual(scores['overall'], 100)
        text = '\n'.join(warnings)
        for expected in ('future', 'more than 180 days', 'after the audit date', 'skeleton placeholder'):
            self.assertIn(expected, text)

    def test_off_site_sample_is_flagged_but_subdomains_are_not(self):
        run = add_page(strict_run(), url='https://blog.example.com/post')
        self.assertEqual(audit_run(run)[1], [])
        run = add_page(strict_run(), url='https://unrelated.example.org/')
        self.assertIn('outside the audited site', '\n'.join(audit_run(run)[1]))

    def test_sample_order_does_not_break_comparison(self):
        a = add_page(strict_run())
        b = copy.deepcopy(a)
        b['metadata']['sample'].reverse()
        self.assertTrue(comparable(a, b)['comparable'])
        self.assertIn('sample', comparable(a, strict_run())['differences'])

    def test_cli_reports_warnings(self):
        run = strict_run()
        run['limitations'].append(f'{PLACEHOLDER} Add limitations.')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.json'
            path.write_text(json.dumps(run))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_contract.py'), str(path)],
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('skeleton placeholder', json.loads(result.stdout)['warnings'][0])

    def test_technical_export_can_shorten_captures_visibly(self):
        run = strict_run()
        set_content(run['assessment']['evidence'][0], 'A' * 50 + 'TAIL_MARKER')
        full = str(report_data(run, technical=True))
        short = str(report_data(run, technical=True, evidence_limit=20))
        self.assertIn('TAIL_MARKER', full)
        self.assertNotIn('TAIL_MARKER', short)
        self.assertIn('first 20 of 61 characters', short)

    def test_technical_export_lists_validation_warnings(self):
        run = strict_run()
        run['schema_version'] = '1.3.0'
        hypothesis_rated_high(run)
        sections = report_data(run, technical=True)['sections']
        self.assertEqual(sections[1]['heading'], 'Validation warnings')


if __name__ == '__main__':
    unittest.main()
