import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import actions
from client_report import render_client_html
from delivery import approve, validate_approval
from report_context import prepare
from run_contract import report_data
from test_actions import baseline, followup, passed
from test_delivery import raw
from test_reliability import ROOT, pdf


class TrackingReports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store, self.previous, self.current = self.root / 'actions', self.root / 'previous.json', self.root / 'current.json'
        self.before = baseline()
        self.previous.write_bytes(raw(self.before))
        actions.initialise(self.previous.read_bytes(), self.store)
        actions.update(self.store, 'F1', owner='<script>Owner</script>', effort_hours=1.5, status='ready_to_verify')
        self.after = followup(self.before)
        self.current.write_bytes(raw(self.after))
        passed(self.store, 'F1', self.after, rationale='<Review> accepted the synthetic check.')

    def context(self):
        return prepare(self.current.read_bytes(), previous=self.previous, actions=self.store)

    def test_escaped_tracking_comparison_and_full_acceptance_are_visible(self):
        context, _ = self.context()
        html = render_client_html({**report_data(self.after), **context})
        for value in ('What changed', 'Action tracking', '1 resolved', '1.5 hours', 'Verified',
                      self.before['findings'][0]['acceptance'], '&lt;script&gt;Owner&lt;/script&gt;',
                      '&lt;Review&gt;', '(agent)', 'DRAFT — review required'):
            self.assertIn(value, html)
        self.assertNotIn('<script>Owner', html)
        self.assertNotIn('page-1', html)
        self.assertNotIn('run_sha256', html)
        self.assertIn('href="#what-changed"', html)
        self.assertIn('href="#action-tracking"', html)

    def test_old_approval_cannot_authorise_new_sections_and_context_cannot_be_dropped(self):
        current = self.current.read_bytes()
        old = approve(current, 'Synthetic reviewer')
        _, attachments = self.context()
        with self.assertRaisesRegex(ValueError, 'attachments changed'):
            validate_approval(current, old, attachments=attachments)
        approval = approve(current, 'Synthetic reviewer', attachments=attachments)
        self.assertEqual(approval['version'], '1.1.0')
        self.assertEqual(validate_approval(current, approval, attachments=attachments)['state'], 'ready')
        with self.assertRaisesRegex(ValueError, 'attachments changed'):
            validate_approval(current, approval)

    def test_assignment_edit_and_previous_reformat_invalidate_context_review(self):
        _, attachments = self.context()
        current = self.current.read_bytes()
        approval = approve(current, 'Synthetic reviewer', attachments=attachments)
        actions.update(self.store, 'F1', owner='Another owner')
        _, changed = self.context()
        with self.assertRaisesRegex(ValueError, 'attachments changed'):
            validate_approval(current, approval, attachments=changed)
        self.previous.write_bytes(self.previous.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'different baseline'):
            self.context()

    def test_draft_export_preserves_sources_and_rejects_aliases(self):
        output = self.root / 'report.html'
        before = self.previous.read_bytes(), self.current.read_bytes()
        pdf.export_report(self.current, output, previous_path=self.previous, actions_path=self.store)
        self.assertIn('What changed', output.read_text())
        self.assertEqual((self.previous.read_bytes(), self.current.read_bytes()), before)
        alias = self.root / 'hardlink.json'
        alias.hardlink_to(self.store / 'manifest.json')
        for target in (self.previous, self.store / 'report.html', alias):
            # All output formats must be valid to reach alias protection.
            if target.suffix == '.json':
                target = target.with_suffix('.html')
                target.hardlink_to(self.previous if 'previous' in target.name else self.store / 'manifest.json')
            with self.subTest(target=target), self.assertRaises(ValueError):
                pdf.export_report(self.current, target, overwrite=True, previous_path=self.previous, actions_path=self.store)

    def test_context_final_export_requires_review_of_that_context(self):
        _, attachments = self.context()
        approval = self.root / 'approval.json'
        approval.write_bytes(raw(approve(self.current.read_bytes(), 'Synthetic reviewer', attachments=attachments)))
        target = self.root / 'reviewed.html'
        pdf.export_report(self.current, target, final=True, approval_path=approval,
                          previous_path=self.previous, actions_path=self.store)
        self.assertIn('Reviewed final report', target.read_text())
        with self.assertRaisesRegex(ValueError, 'attachments changed'):
            pdf.export_report(self.current, self.root / 'missing-context.html', final=True, approval_path=approval)

    def test_wrong_store_and_incompatible_export_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'different baseline'):
            prepare(self.current.read_bytes(), actions=self.store)
        self.after['metadata']['market'] = 'Other market'
        self.current.write_bytes(raw(self.after))
        with self.assertRaisesRegex(ValueError, 'Incompatible audit comparison'):
            pdf.export_report(self.current, self.root / 'bad.html', previous_path=self.previous)
        self.assertFalse((self.root / 'bad.html').exists())

    def test_other_snapshot_verification_is_qualified(self):
        context, _ = prepare(self.previous.read_bytes(), actions=self.store)
        html = render_client_html({**report_data(self.before), **context})
        self.assertIn('not verified for this report', html)

    def test_cli_context_approval_and_parallel_updates(self):
        command = [sys.executable, str(ROOT / 'scripts/delivery.py'), 'approve', str(self.current),
                   '--reviewer', 'Synthetic reviewer', '--compare', str(self.previous), '--actions', str(self.store)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root / 'delivery.json').read_text())['version'], '1.1.0')
        command = [sys.executable, str(ROOT / 'scripts/actions.py'), 'update', str(self.store), 'F1', '--owner']
        processes = [subprocess.Popen([*command, owner], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for owner in ('Owner A', 'Owner B')]
        for process in processes:
            _, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(actions.load(self.store)['event_count'], 4)


if __name__ == '__main__':
    unittest.main()
