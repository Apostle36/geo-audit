import json
import re
import unittest

from test_reliability import ROOT
from version import RUN_SCHEMA_VERSION, SUPPORTED_RUN_SCHEMAS, TOOLKIT_VERSION

AGENTS = ROOT / '.claude/agents'
CORE_ROLES = ('geo-ai-visibility', 'brand-radar', 'geo-technical', 'geo-content', 'geo-schema')


def frontmatter(path):
    text = path.read_text(encoding='utf-8')
    block = text.split('---', 2)[1]
    return dict(line.split(': ', 1) for line in block.strip().splitlines() if ': ' in line)


class Versions(unittest.TestCase):
    """Version numbers drifted apart before; every published copy must match version.py."""

    def test_toolkit_version_is_consistent(self):
        skill = (ROOT / '.claude/skills/geo-audit/SKILL.md').read_text(encoding='utf-8')
        self.assertIn(f'version: "{TOOLKIT_VERSION}"', skill)
        self.assertTrue((ROOT / 'README.md').read_text(encoding='utf-8').startswith(
            f'# GEO Audit\nVersion {TOOLKIT_VERSION}:'))
        self.assertIn(f'toolkit {TOOLKIT_VERSION}', (ROOT / 'CLAUDE.md').read_text(encoding='utf-8'))

    def test_new_runs_and_example_use_the_current_schema(self):
        self.assertEqual(SUPPORTED_RUN_SCHEMAS[-1], RUN_SCHEMA_VERSION)
        example = json.loads((ROOT / 'examples/run.json').read_text(encoding='utf-8'))
        self.assertEqual(example['schema_version'], RUN_SCHEMA_VERSION)
        expected = {'.claude/skills/geo-audit/SKILL.md': f'use run schema {RUN_SCHEMA_VERSION}',
                    'docs/RUN-FORMAT.md': f'writes new audits in **run schema {RUN_SCHEMA_VERSION}**',
                    'docs/AUDIT-DEPTH.md': f'Use `schema_version: "{RUN_SCHEMA_VERSION}"`'}
        for document, phrase in expected.items():
            with self.subTest(document=document):
                self.assertIn(phrase, (ROOT / document).read_text(encoding='utf-8'))

    def test_roles_are_distinct_and_least_privilege(self):
        descriptions = set()
        for path in sorted(AGENTS.glob('*.md')):
            with self.subTest(role=path.stem):
                meta = frontmatter(path)
                self.assertEqual(meta['name'], path.stem)
                self.assertNotIn(meta['description'], descriptions)
                descriptions.add(meta['description'])
                tools = {tool.strip() for tool in meta['tools'].split(',')}
                self.assertTrue(tools <= {'Read', 'Grep', 'Glob', 'Bash', 'WebSearch', 'WebFetch'}, tools)
                self.assertFalse(tools & {'Write', 'Edit'})
                if path.stem in CORE_ROLES:
                    self.assertIn(f'run schema {RUN_SCHEMA_VERSION}', path.read_text(encoding='utf-8'))
        self.assertEqual(len(descriptions), 6)

    def test_no_stale_schema_instructions_remain(self):
        for path in [*AGENTS.glob('*.md'), ROOT / '.claude/skills/geo-audit/SKILL.md', ROOT / 'CLAUDE.md']:
            with self.subTest(path=path.name):
                self.assertIsNone(re.search(r'1\.3\.0 (review records|orchestrator)|toolkit 1\.3', path.read_text()))


if __name__ == '__main__':
    unittest.main()
