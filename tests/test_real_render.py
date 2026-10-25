"""Opt-in browser checks: GEO_RUN_RENDER_TESTS=1 python -m unittest discover -s tests.

Requires Playwright/Chromium and pdftotext. GEO_RENDER_ARTIFACTS optionally keeps
artifacts in a unique subdirectory for visual review; otherwise temp cleanup.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_reliability import pdf, legacy
from test_run_contract import run_fixture


@unittest.skipUnless(os.environ.get('GEO_RUN_RENDER_TESTS') == '1', 'Set GEO_RUN_RENDER_TESTS=1 for actual browser checks')
class RealRender(unittest.TestCase):
    def setUp(self):
        root = os.environ.get('GEO_RENDER_ARTIFACTS')
        if root:
            Path(root).mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix='geo-render-check-', dir=root))
        if not root:
            self.addCleanup(shutil.rmtree, self.directory)
        else:
            print(f'Visual review artifacts: {self.directory}', flush=True)

    def text(self, path):
        result = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True, check=True)
        return result.stdout

    def test_short_fidelity_and_long_table(self):
        short = self.directory / 'short.md'
        short.write_text(legacy('IMPORTANT CONCLUSION\n\n## Evidence\n```html\n<div>x & y</div>\n```\n\n> Quoted evidence\n\n- [ ] Pending\n- [x] Done\n\nUnicode: café Ελληνικά'), encoding='utf-8')
        short_pdf = self.directory / 'short.pdf'
        pdf.export_report(short, short_pdf, legacy_markdown=True)
        text = self.text(short_pdf)
        for marker in ('IMPORTANT CONCLUSION', '<div>x & y</div>', 'Quoted evidence', 'café', 'Ελληνικά'):
            self.assertIn(marker, text)
        rows = ['| URL | Finding |', '| --- | --- |']
        for index in range(100):
            rows.append(f'| https://example.com/{"long" * 60}/{index} | ROW_{index:03d}_FINDING |')
        long = self.directory / 'long.md'
        long.write_text(legacy('LONG CONCLUSION\n\n## Findings\n' + '\n'.join(rows)), encoding='utf-8')
        long_pdf, long_html = self.directory / 'long.pdf', self.directory / 'long.html'
        pdf.export_report(long, long_html, legacy_markdown=True)
        pdf.export_report(long, long_pdf, legacy_markdown=True)
        text = self.text(long_pdf)
        for index in range(100):
            self.assertIn(f'ROW_{index:03d}_FINDING', text)
        (self.directory / 'long-extracted.txt').write_text(text, encoding='utf-8')
        # Verify browser layout, not merely the presence of CSS declarations.
        from playwright.sync_api import sync_playwright
        with sync_playwright() as runtime:
            browser = pdf.launch_chromium(runtime)
            page = browser.new_page(viewport={'width': pdf.A4_W, 'height': pdf.A4_H})
            page.goto(long_html.as_uri())
            overflows = page.locator('table, th, td').evaluate_all('(nodes) => nodes.map(n => n.getBoundingClientRect()).filter(r => r.right > 795 || r.left < -1).map(r => ({left:r.left,right:r.right}))')
            self.assertEqual(overflows, [])
            browser.close()

    def test_structured_and_concurrent_real_exports(self):
        source = self.directory / 'run.json'
        source.write_text(json.dumps(run_fixture()), encoding='utf-8')
        outputs = [self.directory / f'structured-{index}.pdf' for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda output: pdf.export_report(source, output), outputs))
        for output in outputs:
            text = self.text(output)
            for marker in ('Synthetic test conclusion', 'Captured content', 'AI visibility not measured'):
                self.assertIn(marker, text)
            self.assertNotIn('page-1', text)
            self.assertTrue(output.read_bytes().startswith(b'%PDF-'))
        technical = self.directory / 'technical.pdf'
        pdf.export_report(source, technical, technical=True)
        self.assertIn('page-1', self.text(technical))

    def test_action_tracking_and_verified_comparison_pdf(self):
        from actions import initialise, update
        from test_actions import baseline, followup, passed
        from test_delivery import raw
        before = baseline()
        previous, current, store = self.directory / 'previous.json', self.directory / 'current.json', self.directory / 'actions'
        previous.write_bytes(raw(before))
        initialise(previous.read_bytes(), store)
        update(store, 'F1', owner='Synthetic owner', effort_hours=2.5, status='ready_to_verify')
        after = followup(before)
        current.write_bytes(raw(after))
        passed(store, 'F1', after)
        output = self.directory / 'comparison.pdf'
        pdf.export_report(current, output, previous_path=previous, actions_path=store)
        text = self.text(output)
        for marker in ('What changed', '1 resolved', 'Action tracking', 'Synthetic owner', '2.5 hours',
                       before['findings'][0]['acceptance'], 'Codex (agent)', 'DRAFT'):
            self.assertIn(marker, text)
        self.assertNotIn('page-1', text)
        self.assertEqual(previous.read_bytes(), raw(before))
        self.assertEqual(current.read_bytes(), raw(after))

    def test_draft_and_reviewed_final_pdf_states(self):
        from delivery import approve
        from test_delivery import complete_run
        source = self.directory / 'run.json'
        run = complete_run()
        run['review'] = [item for item in run['review'] if (item['category'], item['topic']) != ('technical', 'performance')]
        source.write_text(json.dumps(run))
        approval = approve(source.read_bytes(), 'Synthetic test reviewer',
                           exclusions={'review.technical.performance': 'Field-data access excluded in this test scope.'})
        (self.directory / 'delivery.json').write_text(json.dumps(approval))
        draft, final = self.directory / 'draft.pdf', self.directory / 'final.pdf'
        pdf.export_report(source, draft)
        pdf.export_report(source, final, final=True)
        draft_text, final_text = self.text(draft), self.text(final)
        self.assertIn('DRAFT', draft_text)
        self.assertNotIn('DRAFT', final_text)
        self.assertIn('Reviewed final report', final_text)
        self.assertIn('Synthetic test reviewer', final_text)
        self.assertIn('Field-data access excluded', ' '.join(final_text.split()))
        self.assertIn('Synthetic test conclusion', final_text)
        final_html = self.directory / 'final.html'
        pdf.export_report(source, final_html, final=True)

    def test_detailed_client_mobile_and_pdf_fidelity(self):
        from test_audit_depth import detailed_run
        from playwright.sync_api import sync_playwright
        source = self.directory / 'detailed.json'
        source.write_text(json.dumps(detailed_run()))
        html, target = self.directory / 'detailed.html', self.directory / 'detailed.pdf'
        pdf.export_report(source, html)
        pdf.export_report(source, target)
        self.assertIn('UNIQUE_DEEP_REVIEW', self.text(target))
        self.assertNotIn('page-1', self.text(target))
        with sync_playwright() as runtime:
            browser = pdf.launch_chromium(runtime)
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            page.goto(html.as_uri())
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
            self.assertGreater(page.locator('a[href="https://example.com/"]').count(), 0)
            browser.close()
