import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import actions
from compare_runs import compare
from test_actions import baseline, followup, passed
from test_delivery import raw
from test_reliability import ROOT


class Comparison(unittest.TestCase):
    def test_new_recurring_unresolved_and_id_renaming(self):
        before = baseline()
        current = followup(before, remove=False)
        current['findings'][0].update(id='RENAMED', claim='  SYNTHETIC content observation! ')
        new = copy.deepcopy(current['findings'][0])
        new.update(id='NEW', claim='New synthetic observation')
        current['findings'].append(new)
        result = compare(raw(current), raw(before))
        self.assertEqual(result['counts'], {'new': 1, 'recurring': 1, 'resolved': 0, 'unresolved': 0})
        result = compare(raw(followup(before)), raw(before))
        self.assertEqual(result['counts']['unresolved'], 1)
        self.assertEqual(result['counts']['resolved'], 0)

    def test_uncertainty_and_wording_changes_are_unresolved(self):
        before = baseline()
        for changes in ({'kind': 'unknown', 'status': 'unknown', 'severity': 'informational'},
                        {'claim': 'Changed wording with same ID'}):
            current = followup(before, remove=False)
            current['findings'][0].update(changes)
            result = compare(raw(current), raw(before))
            self.assertEqual(result['counts']['resolved'], 0)
            self.assertGreaterEqual(result['counts']['unresolved'], 1)

    def test_duplicate_identity_is_not_recurring_or_resolved(self):
        before = baseline()
        duplicate = copy.deepcopy(before['findings'][0])
        duplicate['id'] = 'DUPLICATE'
        before['findings'].append(duplicate)
        result = compare(raw(followup(before, remove=False)), raw(before))
        self.assertEqual(result['counts']['recurring'], 0)
        self.assertEqual(result['counts']['resolved'], 0)
        self.assertEqual(result['counts']['unresolved'], 2)

    def test_only_exact_reviewed_followup_is_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'actions'
            before = baseline()
            actions.initialise(raw(before), store)
            actions.update(store, 'F1', status='ready_to_verify')
            current = followup(before)
            passed(store, 'F1', current)
            state = actions.load(store)
            result = compare(raw(current), raw(before), action_state=state)
            self.assertEqual(result['counts']['resolved'], 1)
            self.assertEqual(result['groups']['resolved'][0]['verification']['reviewer_type'], 'agent')
            result = compare(raw(current) + b' ', raw(before), action_state=state)
            self.assertEqual(result['counts']['resolved'], 0)
            self.assertEqual(result['counts']['unresolved'], 1)

    def test_reopening_revokes_resolution_and_wrong_baseline_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'actions'
            before = baseline()
            actions.initialise(raw(before), store)
            actions.update(store, 'F1', status='ready_to_verify')
            current = followup(before)
            passed(store, 'F1', current)
            state = actions.update(store, 'F1', status='in_progress')
            self.assertEqual(compare(raw(current), raw(before), action_state=state)['counts']['resolved'], 0)
            with self.assertRaisesRegex(ValueError, 'exact previous run'):
                compare(raw(current), raw(before) + b' ', action_state=state)

    def test_incompatible_scope_has_no_change_counts_or_score_deltas(self):
        before = baseline()
        for key, value in (('market', 'Other'), ('sampling_rationale', 'Other rationale'), ('sample', ['https://example.com/'])):
            current = followup(before)
            if key == 'sample':
                current['assessment']['criteria']['schema'][0].update(status='not_applicable', reason='no_structured_data_in_sample')
                del current['assessment']['criteria']['schema'][0]['value']
            else:
                current['metadata'][key] = value
            result = compare(raw(current), raw(before))
            self.assertFalse(result['comparable'])
            self.assertNotIn('counts', result)
            self.assertNotIn('scores', result)

    def test_incomplete_scores_remain_none(self):
        before = baseline()
        criterion = before['assessment']['criteria']['content'][0]
        criterion.update(status='unknown')
        del criterion['value']
        current = followup(before)
        result = compare(raw(current), raw(before))
        self.assertEqual(result['scores']['overall'], {'previous': None, 'current': None, 'change': None})
        self.assertIsNone(result['scores']['categories']['content']['change'])

    def test_cli_incompatible_exit_and_input_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, current = baseline(), baseline()
            current['metadata']['market'] = 'Other'
            old, new = root / 'old.json', root / 'new.json'
            old.write_bytes(raw(before))
            new.write_bytes(raw(current))
            command = [sys.executable, str(ROOT / 'scripts/compare_runs.py'), str(old), str(new)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertFalse(json.loads(result.stdout)['comparable'])
            result = subprocess.run([*command, '--output', str(old)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(old.read_bytes(), raw(before))


if __name__ == '__main__':
    unittest.main()
