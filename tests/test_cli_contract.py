import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_reliability import ROOT
from test_run_contract import run_fixture


class CliContract(unittest.TestCase):
    def command(self, script, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts' / script), *map(str, args)], capture_output=True, text=True)

    def test_invalid_json_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            for content in ('{"a":1,"a":2}', '{"x":NaN}', '[]', '{broken}'):
                path.write_text(content)
                for script in ('score.py', 'run_contract.py'):
                    result = self.command(script, path)
                    self.assertEqual(result.returncode, 2)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertIn('Invalid', result.stderr)

    def test_example_valid_but_unassessed(self):
        result = self.command('run_contract.py', ROOT / 'examples/run.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        scores = json.loads(result.stdout)['scores']
        self.assertIsNone(scores['overall'])
        self.assertEqual(scores['coverage'], 0)

    def test_comparison_returns_distinct_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'a.json', Path(directory) / 'b.json'
            run = run_fixture()
            a.write_text(json.dumps(run))
            run['metadata']['market'] = 'Different'
            b.write_text(json.dumps(run))
            result = self.command('run_contract.py', a, '--compare', b)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertFalse(json.loads(result.stdout)['comparison']['comparable'])

    def test_evidence_record_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.txt'
            path.write_text('Synthetic capture', encoding='utf-8')
            result = self.command('evidence.py', path, '--record-id', 'test', '--source', 'https://example.com/',
                                  '--collected-at', '2026-09-10T10:00:00Z', '--method', 'fixture')
            self.assertEqual(result.returncode, 0, result.stderr)
            from evidence import validate_registry
            self.assertIn('test', validate_registry([json.loads(result.stdout)]))
            result = self.command('evidence.py', path, '--record-id', 'test')
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('Traceback', result.stderr)
            self.assertIn('--record-id requires --source, --collected-at and --method', result.stderr)

    def test_report_json_cli_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'report.html'
            result = self.command('geo-audit-pdf.py', ROOT / 'examples/run.json', output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Demonstration template', output.read_text())
            result = self.command('geo-audit-pdf.py', Path(directory) / 'missing.json', output, '--overwrite')
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('Traceback', result.stderr)
