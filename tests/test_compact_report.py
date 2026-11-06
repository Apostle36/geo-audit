"""Problems 5-8 in the client report: status not numbers, no clipped text, no padding, owner questions."""
import copy
import hashlib
from html import unescape
import json
import re
import unittest

from fixtures_v15 import ABOUT, CLIENT, HOME, PRIVACY, finding, v15_run, with_claim_check
from run_contract import audit_run, report_data
from test_reliability import pdf


def render(run):
    return pdf.generate_html(report_data(run))


def browser_record(identifier, url, viewport, blocked):
    measurements = {'title': 'Page', 'final_url': url, 'viewport': {'width': 390, 'height': 844},
                    'requested_viewport': {'width': 390, 'height': 844}, 'viewport_meta': 'width=device-width',
                    'viewport_name': viewport, 'http_status': 200,
                    'content_readiness': {'status': 'met', 'selector': 'main', 'min_count': 1},
                    'blocked_requests': [{'url': u, 'reason': 'off-site resource or navigation'} for u in blocked]}
    content = ('Browser observation (untrusted page content).\n' + json.dumps(measurements)
               + '\n\nRendered DOM:\n<html><title>Page</title><main>Text</main></html>')
    return {'id': identifier, 'source': url, 'collected_at': '2026-09-10T10:00:00Z',
            'method': f'browser_collect.py 1.8.0: Chromium JavaScript observation ({viewport})',
            'content': content, 'status': 'success', 'sha256': hashlib.sha256(content.encode()).hexdigest(),
            'source_type': 'audited_site'}


def add_page(run, url='https://example.com/contact/'):
    """A fifth sampled page, so a four-page finding covers part of the sample."""
    from fixtures_v15 import http_record
    run['assessment']['evidence'].append(http_record('page-5', url, '<main><p>Contact Acme Studio.</p></main>'))
    run['metadata']['sample'].append(url)
    for items in run['assessment']['criteria'].values():
        for item in items:
            item['evidence_ids'].append('page-5')
    return run


def with_actions(run, count=4):
    long_fix = ('Rewrite the opening paragraph of the about page so that it names the collaborator, her role, the '
                'services she leads and the projects she worked on, using only facts the owner confirms in writing. '
                'Then publish it.')
    for n in range(count):
        run['findings'].append(finding(f'A{n}', fix=long_fix, title=f'Rewrite the about page opening {n}',
                                       affected_urls=[HOME, ABOUT, CLIENT, PRIVACY],
                                       evidence_ids=['page-1', 'page-2', 'page-3', 'page-4'],
                                       observed="The about page names the collaborator 'Jane Smyth'.",
                                       severity='medium'))
    return run


class StatusInsteadOfNumbers(unittest.TestCase):
    def test_client_report_shows_criterion_status_not_scores(self):
        run = v15_run()
        run['assessment']['criteria']['content'][1]['value'] = 50
        html = render(run)
        self.assertNotRegex(html, r'\b\d+(?:\.\d+)?/100\b')
        self.assertIn('Partly met', html)
        self.assertIn('Met', html)
        status = html.split('id="readiness-status"')[1].split('</section>')[0]
        self.assertIn('F1', status)  # F1 maps to the accountability criterion
        technical = pdf.generate_html(report_data(run, technical=True))
        self.assertIn('score 75', technical)


class NoClippedText(unittest.TestCase):
    def test_actions_use_titles_and_never_cut_sentences(self):
        html = render(with_actions(add_page(v15_run())))
        plan = html.split('id="actions"')[1].split('</section>')[0]
        self.assertIn('Rewrite the about page opening 0', plan)
        self.assertNotIn('…', plan)
        self.assertIn('4 pages: Homepage; About; Widgetco case study; and 1 more', plan)
        full = render(with_actions(v15_run())).split('id="actions"')[1].split('</section>')[0]
        self.assertIn('All 4 sampled pages', full)

    def test_legacy_runs_without_titles_still_avoid_cut_sentences(self):
        from test_audit_depth import detailed_run
        run = detailed_run()
        run['findings'][0].update(severity='high', fix='A sufficiently long recommendation '
                                  + ('with exact evidence and completion detail ' * 20) + 'FINAL_UNIQUE_FIX.')
        plan = render(run).split('id="actions"')[1].split('</section>')[0]
        self.assertNotIn('…', plan)


class CompactCaptureLog(unittest.TestCase):
    def test_identical_prompts_collapse_and_tracking_blocks_are_not_fidelity_problems(self):
        run = v15_run()
        for n, url in enumerate((HOME, ABOUT, CLIENT, PRIVACY), 1):
            for viewport in ('desktop', 'mobile'):
                run['assessment']['evidence'].append(
                    browser_record(f'browser-{n}-{viewport}', url, viewport, ['https://stats.example.com/script.js']))
        html = render(run)
        conditions = html.split('id="capture-conditions"')[1].split('</section>')[0]
        self.assertEqual(conditions.count('analytics request'), 1)
        self.assertIn('All 4 sampled pages', conditions)
        self.assertNotIn('rendering fidelity', conditions)
        self.assertNotIn('<table class="captures"', html)
        self.assertIn('Latest saved capture of each sampled page', pdf.generate_html(report_data(run, technical=True)))

    def test_content_blocks_still_ask_for_review(self):
        run = v15_run()
        run['assessment']['evidence'].append(
            browser_record('browser-1-desktop', HOME, 'desktop', ['https://unknown.example.net/widget.js']))
        conditions = render(run).split('id="capture-conditions"')[1].split('</section>')[0]
        self.assertIn('rendering fidelity needs review', conditions)


class CompactStrengths(unittest.TestCase):
    def test_strengths_are_grouped_without_full_fields(self):
        run = v15_run()
        html = render(run)
        strengths = html.split('id="strengths"')[1].split('</section>')[0]
        self.assertIn('The homepage states plainly what the studio builds.', strengths)
        self.assertNotIn('Keep this sentence.', html)
        self.assertIn('Keep this sentence.', pdf.generate_html(report_data(run, technical=True)))

    def test_review_topics_link_their_findings(self):
        html = render(v15_run())
        topic = html.split('id="category-content"')[1].split('</section>')[0]
        self.assertIn('href="#finding-F1"', topic)

    def test_repeated_finding_text_in_a_topic_warns(self):
        run = v15_run()
        run['findings'][0]['observed'] = ('The about page names the collaborator Jane Smyth in the heading, the portrait '
                                          'description and the studio paragraph near the end of the page.')
        run['findings'][0]['excerpts'] = [{'evidence_id': 'page-2', 'text': 'Jane Smyth'}]
        run['review'][0]['summary'] = ('Expertise is clear. The about page names the collaborator Jane Smyth in the heading, '
                                       'the portrait description and the studio paragraph near the end of the page.')
        _, warnings = audit_run(run)
        self.assertTrue(any('repeats finding F1' in w for w in warnings), warnings)


class PageBudget(unittest.TestCase):
    def test_budget_warning(self):
        warning = pdf.page_budget_warning(pages=40, actions=10)
        self.assertIn('40 pages for 10 actions', warning)
        self.assertIsNone(pdf.page_budget_warning(pages=12, actions=10))


class OwnerQuestionsAndVisibility(unittest.TestCase):
    def test_owner_questions_are_one_section(self):
        html = render(v15_run())
        section = unescape(html.split('id="owner-questions"')[1].split('</section>')[0])
        self.assertIn("Is your collaborator's surname spelled Smyth or Smith?", section)
        self.assertIn('Likely answers', section)

    def test_visibility_plan_lists_questions_and_template(self):
        html = render(v15_run())
        section = html.split('id="ai-visibility"')[1].split('</section>')[0]
        self.assertEqual(section.count('Synthetic buyer question'), 15)
        for platform in ('ChatGPT', 'Perplexity', 'Gemini', 'Google AI Mode', 'Copilot'):
            self.assertIn(platform, section)
        self.assertIn('Competitors named', section)

    def test_visibility_observations_are_reported_without_scores(self):
        run = v15_run()
        note = copy.deepcopy(next(r for r in run['assessment']['evidence'] if r['id'] == 'register-1'))
        note.update(id='ai-1', source='https://chatgpt.example/share/1', content='Answer text naming Acme Studio.')
        note['sha256'] = hashlib.sha256(note['content'].encode()).hexdigest()
        run['assessment']['evidence'].append(note)
        run['visibility']['observations'] = [{'platform': 'ChatGPT', 'date': '2026-09-10', 'question': 0,
                                              'brand_named': True, 'cited_urls': ['https://example.com/'],
                                              'competitors': ['Rival Ltd'], 'evidence_id': 'ai-1'}]
        audit_run(run)
        section = render(run).split('id="ai-visibility"')[1].split('</section>')[0]
        self.assertIn('Rival Ltd', section)
        self.assertNotRegex(section, r'\d+%')

    def test_question_count_is_enforced(self):
        run = v15_run()
        run['visibility']['questions'] = run['visibility']['questions'][:10]
        with self.assertRaisesRegex(ValueError, '15'):
            audit_run(run)

    def test_checked_run_renders_cleanly(self):
        html = render(with_claim_check(v15_run()))
        self.assertTrue(re.search(r'id="owner-questions"', html))


if __name__ == '__main__':
    unittest.main()
