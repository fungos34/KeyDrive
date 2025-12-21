#!/usr/bin/env python3
"""
Unit tests for Remote Control Mode (CHG-20251221-042).

Tests the validation functions and state management for remote .smartdrive control.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add paths for imports
_test_dir = Path(__file__).resolve().parent
_tests_root = _test_dir.parent
_repo_root = _tests_root.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Import SSOT constants
from core.constants import ConfigKeys
from core.modes import SecurityMode


class TestValidateRemoteRoot:
    """Tests for validate_remote_root function."""

    def test_valid_remote_root(self, tmp_path):
        """Test validation of a valid remote .smartdrive structure."""
        from scripts.gui import validate_remote_root

        # Create valid .smartdrive structure
        smartdrive_dir = tmp_path / ".smartdrive"
        smartdrive_dir.mkdir()
        scripts_dir = smartdrive_dir / "scripts"
        scripts_dir.mkdir()

        # Create config.json
        config_path = smartdrive_dir / "config.json"
        config_path.write_text('{"schema_version": "2.0", "mode": "pw_only"}')

        # Create required scripts
        (scripts_dir / "mount.py").write_text("# mount script")
        (scripts_dir / "unmount.py").write_text("# unmount script")

        valid, error = validate_remote_root(tmp_path)
        assert valid is True
        assert error == ""

    def test_missing_smartdrive_dir(self, tmp_path):
        """Test validation fails when .smartdrive directory is missing."""
        from scripts.gui import validate_remote_root

        valid, error = validate_remote_root(tmp_path)
        assert valid is False
        assert ".smartdrive" in error

    def test_missing_config_json(self, tmp_path):
        """Test validation fails when config.json is missing."""
        from scripts.gui import validate_remote_root

        smartdrive_dir = tmp_path / ".smartdrive"
        smartdrive_dir.mkdir()
        scripts_dir = smartdrive_dir / "scripts"
        scripts_dir.mkdir()

        valid, error = validate_remote_root(tmp_path)
        assert valid is False
        assert "config.json" in error

    def test_missing_scripts_dir(self, tmp_path):
        """Test validation fails when scripts directory is missing."""
        from scripts.gui import validate_remote_root

        smartdrive_dir = tmp_path / ".smartdrive"
        smartdrive_dir.mkdir()
        (smartdrive_dir / "config.json").write_text('{"schema_version": "2.0"}')

        valid, error = validate_remote_root(tmp_path)
        assert valid is False
        assert "scripts" in error

    def test_missing_mount_script(self, tmp_path):
        """Test validation fails when mount.py is missing."""
        from scripts.gui import validate_remote_root

        smartdrive_dir = tmp_path / ".smartdrive"
        smartdrive_dir.mkdir()
        scripts_dir = smartdrive_dir / "scripts"
        scripts_dir.mkdir()
        (smartdrive_dir / "config.json").write_text('{"schema_version": "2.0"}')
        (scripts_dir / "unmount.py").write_text("# unmount")

        valid, error = validate_remote_root(tmp_path)
        assert valid is False
        assert "mount.py" in error

    def test_nonexistent_path(self, tmp_path):
        """Test validation fails for nonexistent path."""
        from scripts.gui import validate_remote_root

        nonexistent = tmp_path / "does_not_exist"
        valid, error = validate_remote_root(nonexistent)
        assert valid is False
        assert "does not exist" in error


class TestValidateRemoteConfig:
    """Tests for validate_remote_config function."""

    def test_valid_config(self, tmp_path):
        """Test validation of valid config.json."""
        from scripts.gui import validate_remote_config

        config_path = tmp_path / "config.json"
        config_data = {
            ConfigKeys.SCHEMA_VERSION: "2.0",
            ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
        }
        config_path.write_text(json.dumps(config_data))

        valid, config, error = validate_remote_config(config_path)
        assert valid is True
        assert config[ConfigKeys.SCHEMA_VERSION] == "2.0"
        assert config[ConfigKeys.MODE] == SecurityMode.PW_ONLY.value
        assert error == ""

    def test_missing_config_file(self, tmp_path):
        """Test validation fails for missing config file."""
        from scripts.gui import validate_remote_config

        config_path = tmp_path / "nonexistent.json"
        valid, config, error = validate_remote_config(config_path)
        assert valid is False
        assert config == {}
        assert "not found" in error

    def test_invalid_json(self, tmp_path):
        """Test validation fails for invalid JSON."""
        from scripts.gui import validate_remote_config

        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json {{{")

        valid, config, error = validate_remote_config(config_path)
        assert valid is False
        assert config == {}
        assert "Invalid JSON" in error

    def test_missing_schema_version(self, tmp_path):
        """Test validation fails when schema_version is missing."""
        from scripts.gui import validate_remote_config

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({ConfigKeys.MODE: SecurityMode.PW_ONLY.value}))

        valid, config, error = validate_remote_config(config_path)
        assert valid is False
        assert ConfigKeys.SCHEMA_VERSION in error

    def test_invalid_security_mode(self, tmp_path):
        """Test validation fails for invalid security mode."""
        from scripts.gui import validate_remote_config

        config_path = tmp_path / "config.json"
        config_data = {
            ConfigKeys.SCHEMA_VERSION: "2.0",
            ConfigKeys.MODE: "invalid_mode",
        }
        config_path.write_text(json.dumps(config_data))

        valid, config, error = validate_remote_config(config_path)
        assert valid is False
        assert "Invalid security mode" in error

    def test_all_valid_security_modes(self, tmp_path):
        """Test validation succeeds for all valid security modes."""
        from scripts.gui import validate_remote_config

        # Valid modes from core/modes.py SecurityMode enum
        valid_modes = [mode.value for mode in SecurityMode]

        for mode in valid_modes:
            config_path = tmp_path / "config.json"
            config_data = {
                ConfigKeys.SCHEMA_VERSION: "2.0",
                ConfigKeys.MODE: mode,
            }
            config_path.write_text(json.dumps(config_data))

            valid, config, error = validate_remote_config(config_path)
            assert valid is True, f"Mode {mode} should be valid but got error: {error}"


class TestResolveRemoteCredentialPaths:
    """Tests for resolve_remote_credential_paths function."""

    def test_pw_only_mode(self, tmp_path):
        """Test credential resolution for pw_only mode (no keyfiles)."""
        from scripts.gui import resolve_remote_credential_paths

        config = {ConfigKeys.MODE: SecurityMode.PW_ONLY.value}
        result = resolve_remote_credential_paths(config, tmp_path)

        assert result["keyfiles"] == []
        assert result["seed_gpg"] is None
        assert result["yubikey_slot"] is None

    def test_pw_keyfile_mode_with_keyfiles(self, tmp_path):
        """Test credential resolution with keyfile references."""
        from scripts.gui import resolve_remote_credential_paths

        # Create keys directory and keyfile
        keys_dir = tmp_path / ".smartdrive" / "keys"
        keys_dir.mkdir(parents=True)
        keyfile = keys_dir / "test.key"
        keyfile.write_text("keyfile content")

        config = {
            ConfigKeys.MODE: SecurityMode.PW_KEYFILE.value,
            ConfigKeys.KEYFILE: "test.key",  # Single keyfile, not list
        }
        result = resolve_remote_credential_paths(config, tmp_path)

        assert len(result["keyfiles"]) == 1
        assert result["keyfiles"][0] == keyfile

    def test_gpg_mode_with_seed(self, tmp_path):
        """Test credential resolution for GPG mode with seed file."""
        from scripts.gui import resolve_remote_credential_paths

        # Create keys directory and seed.gpg
        keys_dir = tmp_path / ".smartdrive" / "keys"
        keys_dir.mkdir(parents=True)
        seed_file = keys_dir / "seed.gpg"
        seed_file.write_text("encrypted seed")

        config = {ConfigKeys.MODE: SecurityMode.GPG_PW_ONLY.value}
        result = resolve_remote_credential_paths(config, tmp_path)

        assert result["seed_gpg"] == seed_file

    def test_yubikey_mode_slot(self, tmp_path):
        """Test credential resolution for GPG mode with YubiKey slot."""
        from scripts.gui import resolve_remote_credential_paths

        # Note: yubikey_slot is not in ConfigKeys yet - using raw string
        config = {
            ConfigKeys.MODE: SecurityMode.PW_GPG_KEYFILE.value,  # Mode that uses YubiKey
            "yubikey_slot": 1,  # Raw string - not in ConfigKeys
        }
        result = resolve_remote_credential_paths(config, tmp_path)

        assert result["yubikey_slot"] == 1

    def test_missing_keyfile_not_included(self, tmp_path):
        """Test that missing keyfiles are not included in result."""
        from scripts.gui import resolve_remote_credential_paths

        # Create keys directory but not the keyfile
        keys_dir = tmp_path / ".smartdrive" / "keys"
        keys_dir.mkdir(parents=True)

        config = {
            ConfigKeys.MODE: SecurityMode.PW_KEYFILE.value,
            ConfigKeys.KEYFILE: "nonexistent.key",  # Single keyfile, not list
        }
        result = resolve_remote_credential_paths(config, tmp_path)

        assert result["keyfiles"] == []


class TestAppModeEnum:
    """Tests for AppMode enum."""

    def test_local_mode_exists(self):
        """Test that LOCAL mode exists."""
        from scripts.gui import AppMode

        assert hasattr(AppMode, "LOCAL")
        assert AppMode.LOCAL is not None

    def test_remote_mode_exists(self):
        """Test that REMOTE mode exists."""
        from scripts.gui import AppMode

        assert hasattr(AppMode, "REMOTE")
        assert AppMode.REMOTE is not None

    def test_modes_are_distinct(self):
        """Test that LOCAL and REMOTE modes are distinct."""
        from scripts.gui import AppMode

        assert AppMode.LOCAL != AppMode.REMOTE


class TestRemoteMountProfile:
    """Tests for RemoteMountProfile dataclass."""

    def test_profile_creation(self, tmp_path):
        """Test creating a RemoteMountProfile."""
        from scripts.gui import RemoteMountProfile

        profile = RemoteMountProfile(
            remote_root=tmp_path,
            remote_smartdrive=tmp_path / ".smartdrive",
            remote_config_path=tmp_path / ".smartdrive" / "config.json",
            remote_config={ConfigKeys.MODE: SecurityMode.PW_ONLY.value},
            original_drive_letter="H",
        )

        assert profile.remote_root == tmp_path
        assert profile.original_drive_letter == "H"
        assert profile.remote_config[ConfigKeys.MODE] == SecurityMode.PW_ONLY.value

    def test_profile_default_credential_paths(self, tmp_path):
        """Test that credential_paths defaults to empty dict."""
        from scripts.gui import RemoteMountProfile

        profile = RemoteMountProfile(
            remote_root=tmp_path,
            remote_smartdrive=tmp_path / ".smartdrive",
            remote_config_path=tmp_path / ".smartdrive" / "config.json",
            remote_config={},
            original_drive_letter="H",
        )

        assert profile.credential_paths == {}


class TestMountWorkerConfigPath:
    """Tests for MountWorker config_path parameter."""

    def test_mount_worker_accepts_config_path(self):
        """Test that MountWorker accepts config_path parameter."""
        from scripts.gui import MountWorker

        # This should not raise an error
        worker = MountWorker(password="test", keyfiles=None, config_path=Path("/test/config.json"))
        assert worker.config_path == Path("/test/config.json")

    def test_mount_worker_config_path_default_none(self):
        """Test that MountWorker config_path defaults to None."""
        from scripts.gui import MountWorker

        worker = MountWorker(password="test")
        assert worker.config_path is None


class TestUnmountWorkerConfigPath:
    """Tests for UnmountWorker config_path parameter."""

    def test_unmount_worker_accepts_config_path(self):
        """Test that UnmountWorker accepts config_path parameter."""
        from scripts.gui import UnmountWorker

        # This should not raise an error
        worker = UnmountWorker(config_path=Path("/test/config.json"))
        assert worker.config_path == Path("/test/config.json")

    def test_unmount_worker_config_path_default_none(self):
        """Test that UnmountWorker config_path defaults to None."""
        from scripts.gui import UnmountWorker

        worker = UnmountWorker()
        assert worker.config_path is None


# Skip GUI tests if PyQt6 is not available
try:
    from PyQt6.QtWidgets import QApplication

    HAS_PYQT6 = True
except ImportError:
    HAS_PYQT6 = False


@pytest.mark.skipif(not HAS_PYQT6, reason="PyQt6 not available")
class TestRemoteBannerLabel:
    """Tests for RemoteBannerLabel widget."""

    @pytest.fixture
    def qapp(self):
        """Create QApplication for tests."""
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    def test_banner_creation(self, qapp):
        """Test that RemoteBannerLabel can be created."""
        from scripts.gui import RemoteBannerLabel

        banner = RemoteBannerLabel()
        assert banner is not None

    def test_banner_blink_state(self, qapp):
        """Test that blink state can be toggled."""
        from scripts.gui import RemoteBannerLabel

        banner = RemoteBannerLabel()
        banner.set_blink_state(True)
        assert banner._blink_state is True
        banner.set_blink_state(False)
        assert banner._blink_state is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
