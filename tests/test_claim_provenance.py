"""Problem 1: factual sentences must rest on the kind of evidence they claim."""
import copy
import unittest

from fixtures_v15 import ABOUT, rehash, v15_run, with_claim_check
from run_contract import audit_run, report_data, validate_run
from test_provenance_contract import strict_run


class ExcerptContract(unittest.TestCase):
    def test_valid_fixture_passes(self):
        scores, warnings = audit_run(v15_run())
        self.assertEqual(scores['overall'], 100)
        self.assertEqual([w for w in warnings if 'search' in w.lower()], [])

    def test_on_page_claim_backed_only_by_search_log_fails(self):
        """Reproduces the 5 Nov failure: a search snippet folded into an on-page observation."""
        run = v15_run()
        run['findings'][0].update(
            observed="The about page links to a LinkedIn profile spelled 'Jane Smith'.",
            evidence_ids=['page-2', 'search-1'],
            excerpts=[{'evidence_id': 'search-1', 'text': 'Jane Smith'}])
        with self.assertRaisesRegex(ValueError, 'search-result snippet'):
            validate_run(run)

    def test_href_excerpt_must_exist_in_the_cited_capture(self):
        run = v15_run()
        run['findings'][0]['excerpts'] = [{'evidence_id': 'page-2', 'href': 'https://www.linkedin.com/in/janesmith'}]
        with self.assertRaisesRegex(ValueError, 'not found in evidence page-2'):
            validate_run(run)
        run['findings'][0]['excerpts'] = [{'evidence_id': 'page-2', 'href': 'https://studio.example/'}]
        validate_run(run)

    def test_text_excerpt_normalises_entities_and_curly_quotes(self):
        run = v15_run()
        run['findings'][0]['excerpts'] = [{'evidence_id': 'page-2', 'text': "Jane Smyth's role"}]
        validate_run(run)
        run['findings'][0]['excerpts'] = [{'evidence_id': 'page-2', 'text': 'Jane Smythe'}]
        with self.assertRaisesRegex(ValueError, 'not found in evidence page-2'):
            validate_run(run)

    def test_snippet_claims_must_say_they_come_from_search(self):
        run = v15_run()
        run['findings'][0].update(
            observed="Her profile title is 'Jane Smith'.", evidence_ids=['page-2', 'search-1'],
            excerpts=[{'evidence_id': 'page-2', 'text': 'Jane Smyth'}, {'evidence_id': 'search-1', 'text': 'Jane Smith'}])
        with self.assertRaisesRegex(ValueError, 'must say it comes from search results'):
            validate_run(run)
        run['findings'][0]['observed'] = "A search result gives her profile title as 'Jane Smith'."
        validate_run(run)

    def test_audited_site_excerpt_must_capture_an_affected_page(self):
        run = v15_run()
        run['findings'][0].update(affected_urls=[ABOUT], evidence_ids=['page-2', 'page-1'],
                                  observed="The about page says 'Acme Studio builds websites for industrial companies.'",
                                  excerpts=[{'evidence_id': 'page-1',
                                             'text': 'Acme Studio builds websites for industrial companies.'}])
        with self.assertRaisesRegex(ValueError, 'capture of a page this finding names'):
            validate_run(run)

    def test_non_unknown_findings_need_excerpts_and_titles(self):
        for changes, message in (({'excerpts': []}, 'excerpt'), ({'title': 'x' * 91}, 'title'),
                                 ({'criteria': ['imaginary']}, 'criterion')):
            run = v15_run()
            run['findings'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                validate_run(run)

    def test_source_types_are_required_and_consistent(self):
        run = v15_run()
        del run['assessment']['evidence'][0]['source_type']
        with self.assertRaisesRegex(ValueError, 'source_type'):
            validate_run(run)
        run = v15_run()
        run['assessment']['evidence'][5]['source_type'] = 'audited_site'  # the register is another host
        with self.assertRaisesRegex(ValueError, 'audited_site'):
            validate_run(run)


class LegacyProvenanceWarning(unittest.TestCase):
    def test_older_run_flags_a_term_found_only_in_search_evidence(self):
        run = strict_run()
        page = run['assessment']['evidence'][0]
        page['content'] = '<p>Our collaborator Jane Smyth runs Studio Example.</p>'
        rehash(page)
        search = copy.deepcopy(page)
        search.update(id='search-log', source='web-search-log-2026-09-10', method='WebSearch queries, dated log',
                      content='Query 1: profile title Jane Smithers, Studio Example.')
        rehash(search)
        run['assessment']['evidence'].append(search)
        run['findings'][0].update(evidence_ids=['page-1', 'search-log'],
                                  observed='The page links to a profile that spells the surname Smithers.')
        _, warnings = audit_run(run)
        self.assertTrue(any("'Smithers'" in w and 'search-result evidence' in w for w in warnings), warnings)


class ClaimCheck(unittest.TestCase):
    def test_complete_supported_check_passes(self):
        from claim_check import status
        run = with_claim_check(v15_run())
        validate_run(run)
        self.assertTrue(status(run)['complete'])
        self.assertEqual(status(run)['unsupported'], [])

    def test_unsupported_sentence_blocks_client_export(self):
        run = with_claim_check(v15_run(), verdict='unsupported')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            report_data(run)

    def test_changed_sentence_makes_the_check_stale(self):
        from claim_check import status
        from delivery import readiness
        run = with_claim_check(v15_run())
        run['findings'][0]['observed'] = "The about page names the collaborator 'Jane Smyth' twice."
        self.assertTrue(status(run)['stale'])
        self.assertTrue(any('claim check' in b.lower() for b in readiness(run)['blockers']))

    def test_search_only_verdict_needs_disclosure(self):
        from claim_check import status
        run = with_claim_check(v15_run(), verdict='search_only')
        self.assertTrue(status(run)['undisclosed'])
        with self.assertRaisesRegex(ValueError, 'search'):
            report_data(run)

    def test_draft_without_check_shows_banner(self):
        from test_reliability import pdf
        html = pdf.generate_html(report_data(v15_run()))
        self.assertIn('Claims not yet checked', html)
        self.assertNotIn('Claims not yet checked', pdf.generate_html(report_data(with_claim_check(v15_run()))))


if __name__ == '__main__':
    unittest.main()
