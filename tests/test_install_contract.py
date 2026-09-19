from pathlib import Path
import json
import hashlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_reliability import ROOT, module

installer = module('installer', 'install.py')


class InstallContract(unittest.TestCase):
    def test_install_upgrade_prunes_and_preserves_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'skills with spaces'
            installer.install(parent)
            destination = parent / 'geo-audit'
            (destination / 'scripts/stale.py').write_text('old custom resource')
            (destination / 'SKILL.md').write_text('customized instructions')
            result = installer.install(parent)
            self.assertFalse((destination / 'scripts/stale.py').exists())
            self.assertEqual((Path(result['backup']) / 'scripts/stale.py').read_text(), 'old custom resource')
            self.assertEqual((Path(result['backup']) / 'SKILL.md').read_text(), 'customized instructions')
            manifest = json.loads((destination / 'package-manifest.json').read_text())
            for resource in ('docs/AUDIT-DEPTH.md', 'docs/CLIENT-REPORT.md', 'scripts/client_report.py', 'scripts/review_topics.py'):
                self.assertIn(resource, manifest)
            for name, digest in manifest.items():
                self.assertEqual(hashlib.sha256((destination / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(list(parent.glob('.geo-audit-stage-*')), [])

    def test_installed_bundle_can_reinstall_elsewhere(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first', Path(directory) / 'second'
            installer.install(first)
            installer.install(second, source_root=first / 'geo-audit')
            self.assertEqual((first / 'geo-audit/scripts/score.py').read_bytes(), (second / 'geo-audit/scripts/score.py').read_bytes())

    def test_missing_source_leaves_previous_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'skills'
            installer.install(parent)
            before = (parent / 'geo-audit/SKILL.md').read_bytes()
            with self.assertRaises(ValueError):
                installer.install(parent, source_root=Path(directory) / 'missing')
            self.assertEqual((parent / 'geo-audit/SKILL.md').read_bytes(), before)

    def test_staging_and_exchange_failure_preserve_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'skills'
            installer.install(parent)
            (parent / 'geo-audit/SKILL.md').write_text('keep me')
            for target in ('shutil.copytree', 'exchange'):
                with patch.object(installer, 'exchange', side_effect=OSError('simulated')) if target == 'exchange' else patch('shutil.copytree', side_effect=OSError('simulated')):
                    with self.assertRaises(OSError):
                        installer.install(parent)
                self.assertEqual((parent / 'geo-audit/SKILL.md').read_text(), 'keep me')
                self.assertEqual(list(parent.glob('.geo-audit-stage-*')), [])

    def test_global_role_is_diagnosed_not_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'skills'
            agents = Path(directory) / 'agents'
            agents.mkdir()
            role = agents / 'geo-technical.md'
            role.write_text('legacy role')
            result = installer.install(parent)
            self.assertIn(str(role), result['different_global_roles'])
            self.assertEqual(role.read_text(), 'legacy role')

    def test_source_install_rejected(self):
        with self.assertRaises(ValueError):
            installer.install(ROOT / '.claude/skills')
