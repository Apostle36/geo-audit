import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import actions
from test_delivery import complete_run, raw
from test_provenance_contract import add_page
from test_reliability import ROOT


def baseline():
    run = complete_run()
    run['metadata']['date'] = datetime.now(timezone.utc).date().isoformat()
    for record in run['assessment']['evidence']:
        record['collected_at'] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    run['findings'][0].update(severity='medium', fix='Improve the captured content.', acceptance='Fresh capture proves improvement.')
    return run


def followup(run, *, remove=True):
    run = copy.deepcopy(run)
    for record in run['assessment']['evidence']:
        record['collected_at'] = datetime.now(timezone.utc).isoformat()
    if remove:
        run['findings'] = []
    return run


def passed(store, identifier, run, **overrides):
    return actions.review(store, identifier, raw(run), **{
        'evidence_ids': [r['id'] for r in run['assessment']['evidence']],
        'result': 'passed', 'reviewer': 'Codex', 'reviewer_type': 'agent',
        'rationale': 'Synthetic acceptance review for a test fixture.', **overrides})


class Actions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / 'actions'
        self.run = baseline()
        actions.initialise(raw(self.run), self.store)

    def test_init_preserves_exact_baseline_and_cannot_overwrite(self):
        self.assertEqual((self.store / 'baseline.json').read_bytes(), raw(self.run))
        with self.assertRaises(FileExistsError):
            actions.initialise(raw(self.run), self.store)
        self.assertEqual(actions.load(self.store)['tasks']['F1']['status'], 'planned')

    def test_context_and_uncertainty_are_not_assignable_improvement_actions(self):
        run = baseline()
        run['findings'][0].update(severity='informational', kind='unknown', status='unknown')
        state = actions.initialise(raw(run), self.root / 'unknown')
        self.assertEqual(state['tasks'], {})

    def test_done_queues_review_and_never_directly_verifies(self):
        state = actions.update(self.store, 'F1', owner='<Owner>', effort_hours=2.5, status='ready_to_verify')
        task = state['tasks']['F1']
        self.assertEqual((task['owner'], task['effort_hours'], task['status']), ('<Owner>', 2.5, 'ready_to_verify'))
        self.assertIsNone(task['verification'])
        with self.assertRaisesRegex(ValueError, 'separate evidence review'):
            actions.update(self.store, 'F1', status='verified')
        self.assertEqual(actions.load(self.store)['event_count'], 1)

    def test_fresh_explicit_review_verifies_without_changing_either_run(self):
        actions.update(self.store, 'F1', status='ready_to_verify')
        current = followup(self.run)
        previous = raw(current)
        state = passed(self.store, 'F1', current)
        self.assertEqual(state['tasks']['F1']['status'], 'verified')
        self.assertEqual(state['tasks']['F1']['verification']['reviewer_type'], 'agent')
        self.assertEqual(raw(current), previous)
        self.assertEqual((self.store / 'baseline.json').read_bytes(), raw(self.run))
        self.assertEqual((self.store / 'runs' / (actions.digest(previous) + '.json')).read_bytes(), previous)

    def test_metadata_changes_keep_proof_but_reopening_invalidates_it(self):
        actions.update(self.store, 'F1', status='ready_to_verify')
        passed(self.store, 'F1', followup(self.run))
        self.assertEqual(actions.update(self.store, 'F1', owner='New owner')['tasks']['F1']['status'], 'verified')
        task = actions.update(self.store, 'F1', status='in_progress')['tasks']['F1']
        self.assertIsNone(task['verification'])
        self.assertEqual(len(list((self.store / 'events').iterdir())), 4)

    def test_review_rejects_same_run_stale_and_pre_completion_captures(self):
        early = followup(self.run)
        actions.update(self.store, 'F1', status='ready_to_verify')
        for run, pattern in ((self.run, 'different follow-up'), (early, 'fresh'), (followup(self.run), None)):
            if pattern is None:
                run['assessment']['evidence'][0]['collected_at'] = self.run['assessment']['evidence'][0]['collected_at']
                pattern = 'fresh'
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ValueError, pattern):
                passed(self.store, 'F1', run)
        self.assertEqual(actions.load(self.store)['event_count'], 1)

    def test_passing_review_rejects_remaining_issue_and_reused_id(self):
        actions.update(self.store, 'F1', status='ready_to_verify')
        for changed in (False, True):
            current = followup(self.run, remove=False)
            if changed:
                current['findings'][0]['claim'] = 'A completely different issue'
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'still contains'):
                passed(self.store, 'F1', current)

    def test_review_requires_every_page_and_matching_scope(self):
        run = baseline()
        add_page(run)
        run['findings'][0].update(affected_urls=run['metadata']['sample'][:], evidence_ids=['page-1', 'page-2'])
        other = self.root / 'two-pages'
        actions.initialise(raw(run), other)
        actions.update(other, 'F1', status='ready_to_verify')
        current = followup(run)
        with self.assertRaisesRegex(ValueError, 'every affected URL'):
            passed(other, 'F1', current, evidence_ids=['page-1'])
        current['metadata']['market'] = 'Other market'
        with self.assertRaisesRegex(ValueError, 'Incompatible'):
            passed(other, 'F1', current)

    def test_failed_and_inconclusive_reviews_never_verify(self):
        for result, expected in (('inconclusive', 'ready_to_verify'), ('failed', 'in_progress')):
            actions.update(self.store, 'F1', status='ready_to_verify')
            state = passed(self.store, 'F1', followup(self.run), result=result)
            self.assertEqual(state['tasks']['F1']['status'], expected)

    def test_dependencies_block_active_work_and_cycles(self):
        run = baseline()
        other = copy.deepcopy(run['findings'][0])
        other.update(id='F2', claim='Second issue')
        run['findings'].append(other)
        store = self.root / 'deps'
        actions.initialise(raw(run), store)
        actions.update(store, 'F2', depends_on=['F1'])
        for changes in ({'status': 'in_progress'}, {'status': 'ready_to_verify'}):
            with self.assertRaisesRegex(ValueError, 'verified dependencies'):
                actions.update(store, 'F2', **changes)
        with self.assertRaisesRegex(ValueError, 'cycle'):
            actions.update(store, 'F1', depends_on=['F2'])
        actions.update(store, 'F1', status='ready_to_verify')
        passed(store, 'F1', followup(run))
        actions.update(store, 'F2', status='in_progress')
        with self.assertRaisesRegex(ValueError, 'reopen dependents'):
            actions.update(store, 'F1', status='planned')
        with self.assertRaisesRegex(ValueError, 'Reopen'):
            actions.update(store, 'F1', depends_on=[])

    def test_bad_updates_leave_no_events(self):
        for changes in ({'owner': ''}, {'effort_hours': -1}, {'effort_hours': float('inf')},
                        {'depends_on': ['missing']}, {'depends_on': ['F1']}, {'acceptance': 'Override'}, {'status': []}, {}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                actions.update(self.store, 'F1', **changes)
        self.assertEqual(actions.load(self.store)['event_count'], 0)

    def test_journal_and_snapshot_tampering_is_detected(self):
        actions.update(self.store, 'F1', status='ready_to_verify')
        passed(self.store, 'F1', followup(self.run))
        event = self.store / 'events/000001.json'
        original = event.read_bytes()
        event.write_bytes(original.replace(b'ready_to_verify', b'in_progress'))
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            actions.load(self.store)
        event.write_bytes(original)
        capture = next((self.store / 'runs').iterdir())
        capture.write_bytes(capture.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'snapshot hash mismatch'):
            actions.load(self.store)

    def test_missing_event_baseline_edit_and_symlink_are_rejected(self):
        baseline_path = self.store / 'baseline.json'
        original = baseline_path.read_bytes()
        baseline_path.write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'baseline hash'):
            actions.load(self.store)
        baseline_path.write_bytes(original)
        actions.update(self.store, 'F1', owner='One')
        actions.update(self.store, 'F1', owner='Two')
        (self.store / 'events/000001.json').unlink()
        with self.assertRaisesRegex(ValueError, 'contiguous'):
            actions.load(self.store)
        alias = self.root / 'alias'
        alias.symlink_to(self.store)
        with self.assertRaisesRegex(ValueError, 'real action store'):
            actions.load(alias)

    def test_cli_preserves_history_and_requires_reviewer_type(self):
        command = [sys.executable, str(ROOT / 'scripts/actions.py')]
        done = subprocess.run([*command, 'update', str(self.store), 'F1', '--status', 'ready_to_verify'], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['tasks']['F1']['status'], 'ready_to_verify')
        current = self.root / 'current.json'
        current.write_bytes(raw(followup(self.run)))
        result = subprocess.run([*command, 'review', str(self.store), 'F1', '--run', str(current), '--evidence', 'page-1',
                                 '--result', 'passed', '--reviewer', 'Codex', '--rationale', 'Test'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(actions.load(self.store)['event_count'], 1)

    def test_passing_review_reports_prompted_evidence_without_refusing_it(self):
        # A deliberate 404 can be the accepted fix, so the prompt is shown rather than refused.
        from collect import METHOD, Response, describe
        actions.update(self.store, 'F1', status='ready_to_verify')
        current = followup(self.run)
        record = current['assessment']['evidence'][0]
        content = describe(record['source'], [Response(record['source'], 404, 'Not Found',
                                                       [('Content-Type', 'text/html')])], '<title>Gone</title>', [], '')
        record.update(method=METHOD, content=content, sha256=actions.digest(content.encode()))
        path = self.root / 'current.json'
        path.write_bytes(raw(current))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/actions.py'), 'review', str(self.store), 'F1',
                                 '--run', str(path), '--evidence', 'page-1', '--result', 'passed',
                                 '--reviewer', 'Named reviewer', '--reviewer-type', 'human',
                                 '--rationale', 'The retired page now returns 404 as agreed.'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['tasks']['F1']['status'], 'verified')
        self.assertEqual(output['capture_prompts'], ['https://example.com/: HTTP 404 response'])


if __name__ == '__main__':
    unittest.main()
