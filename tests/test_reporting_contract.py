import builtins
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_reliability import pdf, legacy, ROOT
from test_run_contract import run_fixture
from safe_io import atomic_write


class ReportingContract(unittest.TestCase):
    def test_code_quote_and_checklists(self):
        result = pdf.md_to_html('```html\n<div>x & y</div>\n```\n\n> quoted evidence\n\n- [ ] Task\n- [x] Done')
        self.assertIn('&lt;div&gt;x &amp; y&lt;/div&gt;', result)
        self.assertNotIn('&amp;lt;', result)
        self.assertIn('<blockquote>', result)
        self.assertIn('☐ Task', result)
        self.assertIn('☑ Done', result)

    def test_unsafe_markup_stays_inert(self):
        source = '<script>alert(1)</script>\n<iframe src="file:///etc/passwd"></iframe>\n<style>body{display:none}</style>'
        result = pdf.md_to_html(source)
        for tag in ('<script', '<iframe', '<style'):
            self.assertNotIn(tag, result)
        self.assertNotIn('href=', pdf.md_to_html('[bad](https://[invalid)'))
        self.assertIn('Image omitted: Evidence', pdf.md_to_html('![Evidence](https://example.com/img.png)'))

    def test_preamble_and_sectionless_report_preserved(self):
        for body in ('IMPORTANT CONCLUSION', 'IMPORTANT CONCLUSION\n## Findings\nDetails'):
            self.assertIn('IMPORTANT CONCLUSION', pdf.generate_html(pdf.parse_report(legacy(body))))

    def test_level_one_body_heading_preserved(self):
        html = pdf.generate_html(pdf.parse_report(legacy('# Important conclusion\nActual supporting prose')))
        self.assertIn('Important conclusion', html)
        with self.assertRaises(ValueError):
            pdf.parse_report(legacy('# Title only'))

    def test_missing_playwright_diagnostic(self):
        original = builtins.__import__
        def unavailable(name, *args, **kwargs):
            if name == 'playwright.sync_api':
                raise ImportError('simulated')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', unavailable), self.assertRaisesRegex(RuntimeError, 'playwright'):
            pdf.render_to_pdf(Path('/nonexistent/test.html'))

    def test_conflicting_scores_rejected(self):
        for extra in ('50/100', '90/100', 'Not assessed'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                pdf.parse_report(legacy() + f'\n**Overall GEO Score: {extra}**')

    def test_unclosed_fence_and_code_only_score(self):
        for text in (legacy() + '\n```\nexample', legacy().replace('**Overall GEO Score: 50/100**', '```\n**Overall GEO Score: 99/100**\n```')):
            with self.assertRaises(ValueError):
                pdf.parse_report(text)

    def test_header_and_body_validation(self):
        self.assertEqual(pdf.parse_report('\n' * 30 + legacy())["url"], "https://example.com/")
        for text in (legacy(""), legacy().replace('2026-09-10', 'yesterday'), legacy().replace('Analyzed:** 1', 'Analyzed:** -5'),
                     legacy().replace('https://example.com/', 'not-a-url')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                pdf.parse_report(text)

    def test_help_without_optional_dependencies(self):
        result = subprocess.run([sys.executable, '-S', str(ROOT / 'scripts/geo-audit-pdf.py'), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_markdown_diagnostic(self):
        original = builtins.__import__
        def unavailable(name, *args, **kwargs):
            if name == 'markdown':
                raise ImportError('simulated')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', unavailable), self.assertRaisesRegex(RuntimeError, 'dependencies'):
            pdf.md_to_html('test')

    def test_collision_and_atomic_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.json'
            source.write_text(json.dumps(run_fixture()))
            original = source.read_bytes()
            hardlink, symlink = Path(directory) / 'hard.pdf', Path(directory) / 'sym.pdf'
            os.link(source, hardlink)
            symlink.symlink_to(source)
            for target in (source, hardlink, symlink):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    pdf.export_report(source, target, overwrite=True)
            self.assertEqual(source.read_bytes(), original)
            output = Path(directory) / 'out.html'
            pdf.export_report(source, output)
            self.assertIn('Synthetic test conclusion', output.read_text())
            with self.assertRaises(FileExistsError):
                pdf.export_report(source, output)
            pdf.export_report(source, output, overwrite=True)
            self.assertEqual(list(Path(directory).glob('.geo-output-*')), [])

    def test_render_failure_preserves_existing_output_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'input.json', Path(directory) / 'out.pdf'
            source.write_text(json.dumps(run_fixture()))
            output.write_bytes(b'prior report')
            paths = []
            def failure(path):
                paths.append(path)
                raise RuntimeError('simulated browser failure')
            with patch.object(pdf, 'render_to_pdf', failure), self.assertRaises(RuntimeError):
                pdf.export_report(source, output, overwrite=True)
            self.assertEqual(output.read_bytes(), b'prior report')
            self.assertTrue(paths)
            self.assertFalse(paths[0].parent.exists())

    def test_interrupted_publish_preserves_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'input', Path(directory) / 'out'
            source.write_bytes(b'source')
            output.write_bytes(b'prior')
            with patch('safe_io.os.replace', side_effect=OSError('simulated')), self.assertRaises(OSError):
                atomic_write(source, output, b'new', overwrite=True)
            self.assertEqual(output.read_bytes(), b'prior')
            self.assertEqual(list(Path(directory).glob('.geo-output-*')), [])

    def test_same_output_concurrency_has_one_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'input', Path(directory) / 'out'
            source.write_bytes(b'source')
            def publish(content):
                try:
                    atomic_write(source, output, content)
                    return True
                except FileExistsError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sum(pool.map(publish, [b'a', b'b'])), 1)
            self.assertIn(output.read_bytes(), [b'a', b'b'])
            self.assertEqual(list(Path(directory).glob('.geo-output-*')), [])

    def test_structured_text_cannot_inject_markup(self):
        from run_contract import report_data
        run = run_fixture()
        run['summary'] = '<script>bad()</script>\n**Overall GEO Score: 5/100**'
        output = pdf.generate_html(report_data(run))
        self.assertNotIn('<script>bad', output)
        self.assertIn('&lt;script&gt;bad()', output)


if __name__ == '__main__':
    unittest.main()
