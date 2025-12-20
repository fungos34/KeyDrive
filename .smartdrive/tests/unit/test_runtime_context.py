#!/usr/bin/env python3
"""
Unit tests for RuntimeContext (core/context.py)

Tests the "run from anywhere" config path resolution.
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Add project paths for imports
# test file is at .smartdrive/tests/unit/test_runtime_context.py
_test_file = Path(__file__).resolve()
_unit_dir = _test_file.parent
_tests_dir = _unit_dir.parent
_smartdrive_dir = _tests_dir.parent  # This is .smartdrive/

if str(_smartdrive_dir) not in sys.path:
    sys.path.insert(0, str(_smartdrive_dir))

from core.constants import FileNames
from core.context import (
    RuntimeContext,
    add_config_argument,
    create_context_from_config,
    create_context_from_drive,
    get_context_from_args,
    infer_context_from_script,
)
from core.paths import Paths


class TestRuntimeContextFactories(unittest.TestCase):
    """Test RuntimeContext factory methods."""

    def setUp(self):
        """Create temp directories for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

        # Create a mock .smartdrive structure
        self.mock_drive = self.temp_path / "MockDrive"
        self.mock_smartdrive = self.mock_drive / ".smartdrive"
        self.mock_scripts = self.mock_smartdrive / "scripts"
        self.mock_config = self.mock_smartdrive / "config.json"

        self.mock_drive.mkdir(parents=True)
        self.mock_smartdrive.mkdir()
        self.mock_scripts.mkdir()
        self.mock_config.write_text('{"version": "1.0.0", "gui_lang": "en"}')

    def tearDown(self):
        """Clean up temp directories."""
        import shutil

        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass

    def test_from_config_path(self):
        """Test creating context from explicit config path."""
        ctx = RuntimeContext.from_config_path(self.mock_config)

        # Verify paths are correctly derived
        self.assertEqual(ctx.config_path, self.mock_config.resolve())
        self.assertEqual(ctx.smartdrive_dir, self.mock_smartdrive.resolve())
        self.assertEqual(ctx.drive_root, self.mock_drive.resolve())

    def test_from_drive_root(self):
        """Test creating context from drive root."""
        ctx = RuntimeContext.from_drive_root(self.mock_drive)

        # Verify paths are correctly derived
        self.assertEqual(ctx.drive_root, self.mock_drive.resolve())
        self.assertEqual(ctx.smartdrive_dir, self.mock_smartdrive.resolve())
        self.assertEqual(ctx.config_path, self.mock_config.resolve())

    def test_from_script_location_deployed(self):
        """Test inferring context from script in deployed structure."""
        # Create a mock script file in scripts/
        mock_script = self.mock_scripts / "test_script.py"
        mock_script.write_text("# test")

        ctx = RuntimeContext.from_script_location(mock_script)

        # Script is in .smartdrive/scripts/, so:
        # - smartdrive_dir = .smartdrive
        # - drive_root = parent of .smartdrive
        self.assertEqual(ctx.smartdrive_dir, self.mock_smartdrive.resolve())
        self.assertEqual(ctx.drive_root, self.mock_drive.resolve())

    def test_factory_functions(self):
        """Test convenience factory functions."""
        ctx1 = create_context_from_config(self.mock_config)
        ctx2 = create_context_from_drive(self.mock_drive)

        # Both should produce equivalent contexts
        self.assertEqual(ctx1.config_path, ctx2.config_path)
        self.assertEqual(ctx1.smartdrive_dir, ctx2.smartdrive_dir)
        self.assertEqual(ctx1.drive_root, ctx2.drive_root)


class TestRuntimeContextPaths(unittest.TestCase):
    """Test RuntimeContext derived path properties."""

    def setUp(self):
        """Create temp directories."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

        self.mock_drive = self.temp_path / "TestDrive"
        self.mock_smartdrive = self.mock_drive / ".smartdrive"
        self.mock_config = self.mock_smartdrive / "config.json"

        self.mock_drive.mkdir(parents=True)
        self.mock_smartdrive.mkdir()
        self.mock_config.write_text("{}")

    def tearDown(self):
        import shutil

        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass

    def test_derived_paths(self):
        """Test that derived paths are computed correctly."""
        ctx = RuntimeContext.from_config_path(self.mock_config)

        # Check derived paths
        self.assertEqual(ctx.scripts_dir, self.mock_smartdrive / "scripts")
        self.assertEqual(ctx.keys_dir, self.mock_smartdrive / "keys")
        self.assertEqual(ctx.logs_dir, self.mock_smartdrive / "logs")
        self.assertEqual(ctx.integrity_dir, self.mock_smartdrive / "integrity")
        self.assertEqual(ctx.recovery_dir, self.mock_smartdrive / "recovery")

    def test_script_path(self):
        """Test script_path() helper."""
        ctx = RuntimeContext.from_config_path(self.mock_config)

        mount_path = ctx.script_path("mount.py")
        self.assertEqual(mount_path, ctx.scripts_dir / "mount.py")

    def test_subprocess_args(self):
        """Test get_subprocess_args() helper."""
        ctx = RuntimeContext.from_config_path(self.mock_config)

        args = ctx.get_subprocess_args()
        self.assertEqual(args, ["--config", str(ctx.config_path)])


class TestRuntimeContextConfig(unittest.TestCase):
    """Test RuntimeContext config loading."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)

        self.mock_drive = self.temp_path / "ConfigDrive"
        self.mock_smartdrive = self.mock_drive / ".smartdrive"
        self.mock_config = self.mock_smartdrive / "config.json"

        self.mock_drive.mkdir(parents=True)
        self.mock_smartdrive.mkdir()

    def tearDown(self):
        import shutil

        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass

    def test_config_exists(self):
        """Test config_exists() method."""
        self.mock_config.write_text("{}")
        ctx = RuntimeContext.from_config_path(self.mock_config)

        self.assertTrue(ctx.config_exists())

        # Remove config and check again
        self.mock_config.unlink()
        self.assertFalse(ctx.config_exists())

    def test_load_config(self):
        """Test load_config() method."""
        config_data = {"version": "2.0.0", "gui_lang": "de", "mode": "yubikey"}

        import json

        self.mock_config.write_text(json.dumps(config_data))
        ctx = RuntimeContext.from_config_path(self.mock_config)

        loaded = ctx.load_config()
        self.assertEqual(loaded["version"], "2.0.0")
        self.assertEqual(loaded["gui_lang"], "de")
        self.assertEqual(loaded["mode"], "yubikey")

    def test_load_config_caching(self):
        """Test that config is cached."""
        self.mock_config.write_text('{"version": "1.0"}')
        ctx = RuntimeContext.from_config_path(self.mock_config)

        # Load config
        config1 = ctx.load_config()

        # Modify file on disk
        self.mock_config.write_text('{"version": "2.0"}')

        # Cached version should be returned
        config2 = ctx.load_config()
        self.assertEqual(config2["version"], "1.0")

        # Force reload
        config3 = ctx.load_config(force_reload=True)
        self.assertEqual(config3["version"], "2.0")


class TestRuntimeContextValidation(unittest.TestCase):
    """Test RuntimeContext validation."""

    def test_requires_absolute_paths(self):
        """Test that relative paths raise ValueError."""
        from core.paths import Paths

        with self.assertRaises(ValueError):
            RuntimeContext(
                drive_root=Path("relative/path"),
                smartdrive_dir=Path("C:\\") / "absolute" / Paths.SMARTDRIVE_DIR_NAME,
                config_path=Path("C:\\") / "absolute" / Paths.SMARTDRIVE_DIR_NAME / FileNames.CONFIG_JSON,
            )

    def test_all_paths_must_be_absolute(self):
        """Test that all paths must be absolute."""
        temp_dir = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(ValueError):
                RuntimeContext(
                    drive_root=temp_dir,
                    smartdrive_dir=Path(".smartdrive"),  # Relative
                    config_path=temp_dir / ".smartdrive" / "config.json",
                )
        finally:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)


class TestArgumentParsing(unittest.TestCase):
    """Test argparse integration helpers."""

    def test_add_config_argument(self):
        """Test that add_config_argument adds the --config option."""
        import argparse

        parser = argparse.ArgumentParser()
        add_config_argument(parser)

        # Should not raise
        args = parser.parse_args(["--config", "/path/to/config.json"])
        self.assertEqual(args.config, Path("/path/to/config.json"))

        # Short form
        args = parser.parse_args(["-c", "/another/path.json"])
        self.assertEqual(args.config, Path("/another/path.json"))


if __name__ == "__main__":
    unittest.main()
