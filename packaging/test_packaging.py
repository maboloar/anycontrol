"""Installer regression checks; no network or system-package mutations."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('bootstrap', Path(__file__).with_name('bootstrap.py'))
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

class InstallerTests(unittest.TestCase):
    def test_missing_or_modified_asset_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'model').write_bytes(b'verified')
            manifest = {'files': {'model': bootstrap.digest(root/'model')}}
            self.assertEqual(bootstrap.verify_files(root, manifest), [])
            (root/'model').write_bytes(b'broken')
            self.assertEqual(bootstrap.verify_files(root, manifest), ['model'])
            (root/'model').unlink()
            self.assertEqual(bootstrap.verify_files(root, manifest), ['model'])

    def test_lock_parser_checks_every_package_without_hash_lines(self):
        versions = bootstrap.expected_versions(Path(__file__).with_name('requirements-macos-arm64.lock'))
        self.assertEqual(versions['torch'], '2.14.0')
        self.assertEqual(versions['websockets'], '17.1')
        self.assertEqual(len(versions), 68)
        self.assertEqual(versions['pyobjc-framework-vision'], '12.2.2')

    def test_missing_runtime_requests_installation(self):
        ok, reason = bootstrap.probe(Path('/nonexistent-anycontrol-test/python'), {}, {})
        self.assertFalse(ok)
        self.assertIn('없음', reason)

    def test_unavailable_existing_server_is_not_reused(self):
        self.assertFalse(bootstrap.existing_server(0, '1.0.0'))

if __name__ == '__main__': unittest.main()
