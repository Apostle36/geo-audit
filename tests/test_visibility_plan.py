"""Problem 8: a buyer question set and recording template when AI visibility was not measured."""
import unittest

from fixtures_v15 import v15_run
from run_contract import audit_run


class VisibilityPlan(unittest.TestCase):
    def test_draft_expands_inputs_into_15_to_20_questions(self):
        from visibility import draft_questions
        questions = draft_questions(['B2B websites'], ['industrial manufacturers'], 'the EU', 'Example Studio')
        self.assertTrue(15 <= len(questions) <= 20, len(questions))
        self.assertTrue(any('Example Studio' in q for q in questions))
        self.assertTrue(any('industrial manufacturers' in q and 'Example Studio' not in q for q in questions))
        self.assertEqual(len(questions), len(set(questions)))
        many = draft_questions(['websites', 'automation', 'analytics'], ['factories', 'logistics firms'], 'the EU')
        self.assertEqual(len(many), 20)

    def test_too_few_inputs_are_refused(self):
        from visibility import draft_questions
        with self.assertRaisesRegex(ValueError, 'fewer than 15'):
            draft_questions(['websites'], ['factories'], 'the EU')

    def test_drafted_plan_validates_in_a_run(self):
        from visibility import draft_questions
        run = v15_run()
        run['visibility']['questions'] = draft_questions(['websites'], ['factories'], 'the EU', 'Acme Studio')
        audit_run(run)


if __name__ == '__main__':
    unittest.main()
