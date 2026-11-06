"""Problem 4: counts are computed from the sitemap, and free-text counts must agree with them."""
import copy
import unittest

from fixtures_v15 import SAMPLE, SITEMAP_URLS, sitemap_record, v15_run
from run_contract import audit_run, validate_run
from test_provenance_contract import strict_run


class SampleGroups(unittest.TestCase):
    def test_section_index_page_is_not_counted_as_an_item(self):
        from sample_groups import group_urls
        groups = {g['section']: g for g in group_urls(SITEMAP_URLS)}
        templates = groups['/resources/templates/']
        self.assertEqual((templates['label'], templates['items'], templates['hub']), ('templates', 8, True))

    def test_sitemap_urls_are_read_from_saved_evidence(self):
        from sample_groups import sitemap_urls
        self.assertEqual(sitemap_urls([sitemap_record()]), SITEMAP_URLS)

    def test_wrong_count_fails_new_runs(self):
        run = v15_run()
        run['metadata']['sampling_rationale'] = 'Homepage, about, the case study, privacy and none of nine templates.'
        validate_run(run)  # "none of" is not a count
        run['metadata']['sampling_rationale'] = 'Homepage, about, the case study, privacy and 0 of 9 templates.'
        with self.assertRaisesRegex(ValueError, '0 of 9 templates.*8 templates'):
            validate_run(run)
        run['metadata']['sampling_rationale'] = 'Homepage, about, one of one work pages and 0 of 8 templates.'
        validate_run(run)

    def test_number_words_and_limitations_are_checked(self):
        run = v15_run()
        run['limitations'] = ['The sample covers 4 of the 16 sitemap URLs.']
        with self.assertRaisesRegex(ValueError, '4 of the 16 sitemap URLs.*15'):
            validate_run(run)
        run['limitations'] = ['The sample covers four of the fifteen sitemap URLs.']
        validate_run(run)

    def test_wrong_count_warns_on_older_runs(self):
        run = strict_run()
        run['assessment']['evidence'].append(copy.deepcopy(sitemap_record()))
        del run['assessment']['evidence'][-1]['source_type']
        run['metadata']['sampling_rationale'] = 'Homepage plus one of nine templates.'
        _, warnings = audit_run(run)
        self.assertTrue(any('one of nine templates' in w and '8 templates' in w for w in warnings), warnings)

    def test_generated_composition_passes_its_own_check(self):
        from sample_groups import composition_sentence
        sentence = composition_sentence(SITEMAP_URLS, SAMPLE, legal=['https://example.com/privacy/'])
        self.assertIn('4 of 15 sitemap URLs', sentence)
        self.assertIn('0 of 8 templates', sentence)
        run = v15_run()
        run['metadata']['sampling_rationale'] += ' ' + sentence
        validate_run(run)


if __name__ == '__main__':
    unittest.main()
