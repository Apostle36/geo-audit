"""Problem 2: one entity register; strengths never praise a flagged name; fixes use the source spelling."""
import unittest

from fixtures_v15 import strength, v15_run
from run_contract import audit_run, validate_run


class EntityRegister(unittest.TestCase):
    def test_valid_register_passes(self):
        validate_run(v15_run())

    def test_strength_may_not_present_a_wrong_spelling(self):
        run = v15_run()
        run['findings'][1].update(
            claim='The privacy page names the operating company, Acme Studio EOOD, which is a useful concrete fact.',
            observed="The privacy page says 'This site is operated by Acme Studio EOOD, Sofia.'",
            affected_urls=['https://example.com/privacy/'], evidence_ids=['page-4'],
            excerpts=[{'evidence_id': 'page-4', 'text': 'Acme Studio EOOD'}])
        with self.assertRaisesRegex(ValueError, 'presents .*Acme Studio EOOD.* as a strength'):
            validate_run(run)

    def test_fix_must_recommend_the_source_spelling(self):
        run = v15_run()
        run['findings'][2]['fix'] = 'Pick one spelling of the company name and use it everywhere.'
        with self.assertRaisesRegex(ValueError, 'ACME STUDIO EOOD'):
            validate_run(run)

    def test_needs_owner_entity_requires_an_owner_question(self):
        run = v15_run()
        run['owner_questions'] = []
        with self.assertRaisesRegex(ValueError, 'owner question'):
            validate_run(run)

    def test_spellings_must_be_found_in_their_evidence(self):
        run = v15_run()
        run['entities'][1]['spellings'][0]['text'] = 'Acme Studios EOOD'
        with self.assertRaisesRegex(ValueError, 'not found in evidence page-4'):
            validate_run(run)

    def test_review_mentioning_a_flagged_spelling_must_cite_its_finding(self):
        run = v15_run()
        run['review'][0].update(summary='Specific facts include the operator name Acme Studio EOOD.', finding_ids=[])
        _, warnings = audit_run(run)
        self.assertTrue(any('Acme Studio EOOD' in w and 'finding' in w for w in warnings), warnings)
        run['review'][0]['finding_ids'] = ['F3']
        _, warnings = audit_run(run)
        self.assertFalse(any('Acme Studio EOOD' in w for w in warnings), warnings)

    def test_confirmed_entities_can_appear_in_strengths(self):
        run = v15_run()
        run['entities'][1]['status'] = 'confirmed'
        run['findings'][1]['claim'] = 'The privacy page names Acme Studio EOOD as the operator.'
        run['findings'][1].update(affected_urls=['https://example.com/privacy/'], evidence_ids=['page-4'],
                                  observed="The privacy page says 'This site is operated by Acme Studio EOOD, Sofia.'",
                                  excerpts=[{'evidence_id': 'page-4', 'text': 'Acme Studio EOOD'}])
        validate_run(run)
        self.assertEqual(strength()['id'], 'F2')


class OwnerQuestions(unittest.TestCase):
    def test_duplicate_questions_fail(self):
        run = v15_run()
        duplicate = dict(run['owner_questions'][0], id='Q2',
                         question="Is your collaborator's surname spelled Smyth or Smith ?")
        run['owner_questions'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'Duplicate owner question'):
            validate_run(run)

    def test_owner_placeholder_without_question_warns(self):
        run = v15_run()
        run['findings'][2]['fix'] = ('Change the operator name on the privacy page to ACME STUDIO EOOD, '
                                     'registered since [year].')
        _, warnings = audit_run(run)
        self.assertTrue(any('owner question' in w for w in warnings), warnings)


if __name__ == '__main__':
    unittest.main()
