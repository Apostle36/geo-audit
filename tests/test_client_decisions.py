import copy
import unittest
from unittest.mock import patch
from test_audit_depth import detailed_run
from test_reliability import pdf
from run_contract import report_data, validate_run
from client_report import report_model, check_report_integrity, font_css


class ClientDecisions(unittest.TestCase):
    def render(self, run):
        return pdf.generate_html(report_data(run))

    def test_unknown_topics_are_in_plan_even_without_unknown_findings(self):
        run=detailed_run()
        run['review'][0].update(status='unknown',summary='Reporting period needs checking.')
        output=self.render(run)
        plan=output.split('id="actions"')[1].split('<nav')[0]
        self.assertIn('href="#check-content-freshness"',plan)
        self.assertIn('Reporting period needs checking.',output)
        self.assertNotIn('No items recorded for this stage',output)

    def test_informational_observation_is_not_an_action(self):
        run=detailed_run()
        model=report_model(run)
        self.assertEqual(model['actions'],[])
        self.assertEqual(len(model['context']),1)
        self.assertIn('Captured content',self.render(run))

    def test_hypothesis_is_not_promoted_to_supported_fix(self):
        run=detailed_run()
        run['findings'][0].update(kind='hypothesis',severity='high')
        model=report_model(run)
        self.assertFalse(model['actions'])
        self.assertEqual(len(model['verification']),1)
        output=self.render(run)
        self.assertIn('Hypothesis — verify first',output)
        self.assertIn('href="#finding-1"',output)

    def test_long_fix_is_preserved_once_with_short_linked_previews(self):
        run=detailed_run()
        run['findings'][0].update(severity='high',fix='A sufficiently long recommendation '+('with exact evidence and completion detail '*20)+'FINAL_UNIQUE_FIX')
        output=self.render(run)
        self.assertEqual(output.count('FINAL_UNIQUE_FIX'),1)
        self.assertIn('…</a>',output)
        self.assertEqual(output.count('id="finding-1"'),1)

    def test_not_applicable_is_explained_but_not_unresolved(self):
        run=detailed_run()
        run['review'][0].update(status='not_applicable')
        model=report_model(run)
        self.assertNotIn('check-content-freshness',[x['anchor'] for x in model['outstanding']])
        self.assertIn('Not applicable:',self.render(run))

    def test_navigation_escapes_untrusted_ids_and_text(self):
        run=detailed_run()
        run['findings'][0].update(id='bad" onclick="alert(1)',claim='<script>bad()</script>')
        output=self.render(run)
        self.assertNotIn('onclick=',output)
        self.assertNotIn('<script>',output)
        self.assertIn('&lt;script&gt;',output)
        self.assertIn('id="finding-1"',output)

    def test_integrity_rejects_lost_detail_and_broken_link(self):
        run=detailed_run()
        output=self.render(run)
        model=report_model(run)
        with self.assertRaises(ValueError):
            check_report_integrity(output.replace('Captured content',''),run,model)
        with self.assertRaises(ValueError):
            check_report_integrity(output+'<a href="#nonexistent">go</a>',run,model)

    def test_score_scope_locale_and_input_preservation(self):
        run=detailed_run()
        before=copy.deepcopy(run)
        scores=validate_run(run)
        output=self.render(run)
        self.assertIn('10 September 2026',output)
        self.assertIn('lang="en-GB"',output)
        self.assertIn('does not score speed, mobile usability or security',output)
        self.assertEqual(run,before)
        self.assertEqual(validate_run(run),scores)

    def test_font_override_fails_clearly_when_incomplete(self):
        with patch.dict('os.environ',{'GEO_AUDIT_FONT_DIR':'/nonexistent/brand-fonts'}), \
                self.assertRaisesRegex(ValueError,'report font'):
            font_css()

    def test_every_finding_kind_and_all_topics_have_destinations(self):
        run=detailed_run()
        for i,kind in enumerate(('observation','recommendation','hypothesis','unknown')):
            f=copy.deepcopy(run['findings'][0])
            f.update(id=f'F{i+2}',kind=kind,severity='medium',status='unknown' if kind=='unknown' else 'present')
            run['findings'].append(f)
        output=self.render(run)
        check_report_integrity(output,run,report_model(run))
        for i in range(1,6):
            self.assertIn(f'id="finding-{i}"',output)

    def test_unknown_core_check_is_not_hidden_by_complete_detailed_reviews(self):
        from review_topics import TOPICS
        run=detailed_run()
        run['review']=[dict(category=c,topic=t,status='assessed',summary='Scoped observation',affected_urls=run['metadata']['sample'],evidence_ids=['page-1']) for c,topics in TOPICS.items() for t in topics]
        run['assessment']['criteria']['authority'][1].update(status='unknown')
        del run['assessment']['criteria']['authority'][1]['value']
        output=self.render(run)
        plan=output.split('id="actions"')[1].split('<nav')[0]
        self.assertIn('href="#core-check-independent_support"',plan)
        self.assertIn('id="core-check-independent_support"',output)

    def test_counts_use_correct_plurals(self):
        run=detailed_run()
        run['findings'][0].update(severity='medium')
        output=self.render(run)
        self.assertIn('1 page in the declared sample · 1 improvement action ·',output)
        self.assertIn('33 detailed checks remain unresolved',output)
        self.assertIn('Declared sample: 1 page.',output)
        self.assertNotIn('1 pages',output)

    def test_previews_do_not_stop_at_abbreviations(self):
        from client_report import action_preview
        self.assertEqual(action_preview('Add proof, e.g. named client results. Then measure.'),
                         'Add proof, e.g. named client results.')
        self.assertEqual(action_preview('Cite the U.S. study (approx. 2024) on the page! Later steps follow.'),
                         'Cite the U.S. study (approx. 2024) on the page!')
        self.assertEqual(action_preview('No full stop at all'),'No full stop at all')

    def test_query_only_pages_are_distinguishable(self):
        from client_report import page_label
        self.assertEqual(page_label('https://example.com/?p=12'),'Homepage (?p=12)')
        self.assertEqual(page_label('https://example.com/our-services/'),'our services')

    def test_content_language_marks_run_prose_only(self):
        from client_report import render_client_html
        run=detailed_run()
        run['summary']='Ελληνική περίληψη'
        run['findings'][0].update(severity='medium')
        output=render_client_html(report_data(run),content_lang='el')
        self.assertIn('<html lang="en-GB">',output)
        self.assertIn('<p lang="el">Ελληνική περίληψη</p>',output)
        self.assertIn('<h3 lang="el">Synthetic content observation</h3>',output)
        self.assertIn('<span lang="el">Captured content</span>',output)
        check_report_integrity(output,run,report_model(run))
        self.assertNotIn('lang="el"',self.render(run))
        for bad in ('el"><script>','x','english language'):
            with self.subTest(tag=bad), self.assertRaisesRegex(ValueError,'BCP 47'):
                render_client_html(report_data(run),content_lang=bad)
        with self.assertRaisesRegex(ValueError,'client reports only'):
            pdf.generate_html(report_data(run,technical=True),content_lang='el')

    def test_technical_headings_are_not_markdown(self):
        run=detailed_run()
        run['findings'][0]['id']='*F1*'
        output=pdf.generate_html(report_data(run,technical=True))
        self.assertIn('<h2>Finding *F1*</h2>',output)
        self.assertNotIn('<em>F1</em>',output)

    def test_client_retains_hostname_validation(self):
        from client_report import render_client_html
        with self.assertRaisesRegex(ValueError,'hostname'):
            render_client_html(report_data(detailed_run()),domain='https://bad.example/path')
