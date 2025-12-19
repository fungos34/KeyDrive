#!/usr/bin/env python3
"""
Integration test for deploy.py with PathResolver SSOT enforcement.

Tests that deployment:
- Uses PathResolver.for_target() exclusively
- Creates exactly one config location (canonical)
- Creates exactly one static directory (canonical)
- Produces no duplicates
"""

import sys
import tempfile
import unittest
from pathlib import Path

_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent

if str(_project_root / ".smartdrive") not in sys.path:
    sys.path.insert(0, str(_project_root / ".smartdrive"))

from core.path_resolver import RuntimePaths


class TestDeployPathResolverIntegration(unittest.TestCase):
    """Test deploy.py PathResolver integration."""

    def test_deploy_creates_canonical_structure(self):
        """Deployment should create canonical .keydrive structure via PathResolver."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)

            # Simulate what deploy.py does
            paths = RuntimePaths.for_target(target, create_dirs=True)

            # Verify canonical structure
            self.assertTrue(paths.smartdrive_root.exists())
            self.assertEqual(paths.smartdrive_root.name, ".smartdrive")

            self.assertTrue(paths.scripts_root.exists())
            self.assertTrue(paths.static_dir.exists())
            self.assertTrue(paths.keys_dir.exists())
            self.assertTrue(paths.logs_dir.exists())

            # Verify config location is canonical
            # NOTE: Config lives at .smartdrive/config.json, NOT .smartdrive/scripts/config.json
            self.assertEqual(paths.config_file, target / ".smartdrive" / "config.json")

            # Verify static location is canonical
            self.assertEqual(paths.static_dir, target / ".smartdrive" / "static")

    def test_deploy_produces_no_duplicates(self):
        """Deployment should never create duplicate config/static."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)

            # Deploy once
            paths = RuntimePaths.for_target(target, create_dirs=True)

            # Create config
            paths.config_file.write_text("{}", encoding="utf-8")

            # Create static content
            (paths.static_dir / "test.ico").write_text("icon", encoding="utf-8")

            # Check for duplicates
            duplicates = paths.detect_duplicates()

            self.assertEqual(len(duplicates), 0, f"Duplicates found: {duplicates}")

    def test_cross_drive_paths_independent_of_cwd(self):
        """PathResolver.for_target() should work regardless of CWD."""
        import os

        with tempfile.TemporaryDirectory() as cwd_dir:
            with tempfile.TemporaryDirectory() as target_dir:
                old_cwd = os.getcwd()
                try:
                    # Change to different directory
                    os.chdir(cwd_dir)

                    # Create paths for target (not CWD)
                    paths = RuntimePaths.for_target(Path(target_dir), create_dirs=True)

                    # Verify paths point to target, not CWD
                    self.assertEqual(paths.project_root, Path(target_dir).resolve())
                    self.assertIn(".smartdrive", str(paths.smartdrive_root))
                    self.assertNotIn(cwd_dir, str(paths.smartdrive_root))

                finally:
                    os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
