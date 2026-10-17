from pathlib import Path
import json
import hashlib
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

    def test_old_backups_are_pruned_and_version_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'skills'
            for index in range(5):
                if index:
                    (parent / 'geo-audit/SKILL.md').write_text(f'customisation {index}')
                result = installer.install(parent, keep_backups=2)
            backups = sorted((parent / 'geo-audit/.backups').iterdir())
            self.assertEqual(len(backups), 2)
            self.assertEqual(result['pruned_backups'], 1)
            self.assertEqual((backups[-1] / 'SKILL.md').read_text(), 'customisation 4')
            version = (ROOT / 'scripts/version.py').read_text().split('TOOLKIT_VERSION = "')[1].split('"')[0]
            self.assertEqual(result['version'], version)
            for script in ('collect.py', 'new_run.py', 'version.py'):
                self.assertTrue((parent / 'geo-audit/scripts' / script).is_file())
            with self.assertRaises(ValueError):
                installer.install(parent, keep_backups=0)

    def test_source_install_rejected(self):
        with self.assertRaises(ValueError):
            installer.install(ROOT / '.claude/skills')
