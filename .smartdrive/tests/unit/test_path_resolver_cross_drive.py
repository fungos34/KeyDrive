#!/usr/bin/env python3
"""
Unit tests for PathResolver cross-drive support
Tests cross-drive setup scenarios (Drive A → Drive B)
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
_test_dir = Path(__file__).resolve().parent
_tests_dir = _test_dir.parent
_project_root = _tests_dir.parent

if str(_project_root / ".smartdrive") not in sys.path:
    sys.path.insert(0, str(_project_root / ".smartdrive"))

from core.path_resolver import RuntimePaths, SecurityError


class TestPathResolverCrossDrive(unittest.TestCase):
    """Test PathResolver cross-drive operations."""

    def test_for_target_creates_paths(self):
        """for_target() should create RuntimePaths for explicit target."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)

            paths = RuntimePaths.for_target(target, create_dirs=True)

            self.assertEqual(paths.project_root, target)
            self.assertEqual(paths.smartdrive_root, target / ".smartdrive")
            # NOTE: Config lives at .smartdrive/config.json, NOT .smartdrive/scripts/config.json
            self.assertEqual(paths.config_file, target / ".smartdrive" / "config.json")
            self.assertTrue(paths.static_dir.exists())
            self.assertTrue(paths.keys_dir.exists())

    def test_for_target_different_cwd(self):
        """for_target() should work regardless of CWD."""
        import os

        with tempfile.TemporaryDirectory() as tmpdir_a:
            with tempfile.TemporaryDirectory() as tmpdir_b:
                target_b = Path(tmpdir_b)

                # Change CWD to A
                old_cwd = os.getcwd()
                try:
                    os.chdir(tmpdir_a)

                    # Create paths for B (not CWD)
                    paths = RuntimePaths.for_target(target_b, create_dirs=True)

                    # Verify paths point to B, not A
                    self.assertEqual(paths.project_root, target_b)
                    self.assertNotEqual(paths.project_root, Path(tmpdir_a))

                finally:
                    os.chdir(old_cwd)

    def test_validate_write_enforces_authorized_roots(self):
        """validate_write_path() should reject paths outside authorized roots."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            paths = RuntimePaths.for_target(target, create_dirs=True)

            # Valid: write to config
            valid_path = paths.config_file
            self.assertEqual(paths.validate_write_path(valid_path), valid_path)

            # Invalid: write outside .smartdrive
            with self.assertRaises(SecurityError):
                paths.validate_write_path(target / "unauthorized.txt")


class TestDuplicateConsolidation(unittest.TestCase):
    """Test duplicate detection and consolidation."""

    def test_detect_duplicates_finds_config(self):
        """detect_duplicates() should find multiple config.json files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            paths = RuntimePaths.for_target(target, create_dirs=True)

            # Create canonical config at .smartdrive/config.json
            paths.config_file.write_text("{}", encoding="utf-8")

            # Create duplicate at OLD location (.smartdrive/scripts/config.json)
            dup = target / ".smartdrive" / "scripts" / "config.json"
            dup.parent.mkdir(parents=True, exist_ok=True)
            dup.write_text("{}", encoding="utf-8")

            duplicates = paths.detect_duplicates()

            self.assertIn("config.json", duplicates)
            self.assertEqual(len(duplicates["config.json"]), 2)

    def test_detect_duplicates_finds_static(self):
        """detect_duplicates() should find multiple static/ directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            paths = RuntimePaths.for_target(target, create_dirs=True)

            # Canonical static exists (created by for_target)
            self.assertTrue(paths.static_dir.exists())

            # Create duplicate
            dup = target / ".smartdrive" / "scripts" / "static"
            dup.mkdir(parents=True)

            duplicates = paths.detect_duplicates()

            self.assertIn("static/", duplicates)
            self.assertGreaterEqual(len(duplicates["static/"]), 2)


if __name__ == "__main__":
    unittest.main()
