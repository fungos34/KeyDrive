"""
Unit tests for mount input normalization and validation.

Tests the SSOT boundary function normalize_mount_inputs() which prevents
NoneType crashes and validates required fields per security mode.
"""

import sys
import unittest.mock
from pathlib import Path

import pytest

# Add .smartdrive to path for imports
_test_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_test_root / ".smartdrive"))

from core.constants import ConfigKeys, FileNames
from core.modes import SecurityMode
from core.paths import Paths

from scripts.mount import normalize_mount_inputs


class TestNormalizeMountInputs:
    """Test mount input normalization and validation."""

    def test_none_password_in_pw_mode_raises(self):
        """None password in PW mode should raise controlled error, not crash."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk1\\Partition2",
                ConfigKeys.MOUNT_LETTER: "V",
            },
        }

        with pytest.raises(ValueError, match="Password is required"):
            normalize_mount_inputs(config, password=None)

    def test_empty_password_in_pw_mode_raises(self):
        """Empty/whitespace password should raise controlled error."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk1\\Partition2",
                ConfigKeys.MOUNT_LETTER: "V",
            },
        }

        with pytest.raises(ValueError, match="Password is required"):
            normalize_mount_inputs(config, password="   ")

    def test_none_keyfile_in_keyfile_mode_raises(self):
        """None keyfile path in PW+keyfile mode should raise controlled error."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_KEYFILE.value,
            ConfigKeys.ENCRYPTED_KEYFILE: None,  # Explicitly None
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk1\\Partition2",
                ConfigKeys.MOUNT_LETTER: "V",
            },
        }

        with pytest.raises(ValueError, match="Keyfile is required"):
            normalize_mount_inputs(config, password="test123")

    def test_none_volume_path_raises(self):
        """None volume path should raise controlled error on current platform."""
        import platform

        system = platform.system().lower()

        if system == "windows":
            config = {
                ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
                ConfigKeys.WINDOWS: {ConfigKeys.VOLUME_PATH: None, ConfigKeys.MOUNT_LETTER: "V"},  # Explicitly None
            }
        else:
            config = {
                ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
                ConfigKeys.UNIX: {
                    ConfigKeys.VOLUME_PATH: None,  # Explicitly None
                    ConfigKeys.MOUNT_POINT: "~/veradrive",
                },
            }

        with pytest.raises(ValueError, match="volume_path is required"):
            normalize_mount_inputs(config, password="test123")

    def test_whitespace_only_input_normalized(self):
        """Whitespace-only input should be normalized to empty string."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "  \\Device\\Harddisk1\\Partition2  ",
                ConfigKeys.MOUNT_LETTER: "  v  ",
                ConfigKeys.VERACRYPT_PATH: "   ",  # Whitespace only
            },
        }

        result = normalize_mount_inputs(config, password="test123")

        assert result[ConfigKeys.WINDOWS][ConfigKeys.VOLUME_PATH] == "\\Device\\Harddisk1\\Partition2"
        assert result[ConfigKeys.WINDOWS][ConfigKeys.MOUNT_LETTER] == "V"
        assert result[ConfigKeys.WINDOWS][ConfigKeys.VERACRYPT_PATH] == ""

    def test_none_config_sections_handled(self):
        """None config sections should be normalized to empty dicts, then fail validation."""
        import platform

        system = platform.system().lower()

        if system == "windows":
            config = {
                ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
                ConfigKeys.WINDOWS: None,  # Section is None
            }
        else:
            config = {ConfigKeys.MODE: SecurityMode.PW_ONLY.value, ConfigKeys.UNIX: None}

        # Should not crash, but will fail validation due to missing volume_path
        with pytest.raises(ValueError, match="volume_path is required"):
            normalize_mount_inputs(config, password="test123")

    def test_valid_pw_only_mode(self):
        """Valid PW-only mode should normalize successfully."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk1\\Partition2",
                ConfigKeys.MOUNT_LETTER: "v",
            },
        }

        result = normalize_mount_inputs(config, password="test123")

        assert result["mode"] == SecurityMode.PW_ONLY.value
        assert result["password"] == "test123"
        assert result[ConfigKeys.WINDOWS][ConfigKeys.VOLUME_PATH] == "\\Device\\Harddisk1\\Partition2"
        assert result[ConfigKeys.WINDOWS][ConfigKeys.MOUNT_LETTER] == "V"  # Uppercased

    def test_valid_pw_keyfile_mode(self):
        """Valid PW+keyfile mode should normalize successfully."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_KEYFILE.value,
            ConfigKeys.ENCRYPTED_KEYFILE: FileNames.KEYFILE_PLAIN,
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk1\\Partition2",
                ConfigKeys.MOUNT_LETTER: "V",
            },
        }

        result = normalize_mount_inputs(config, password="test123")

        assert result["mode"] == SecurityMode.PW_KEYFILE.value
        assert result["password"] == "test123"
        assert result[ConfigKeys.KEYFILE] == "keyfile.vc"

    def test_gpg_pw_only_mode_no_password_required(self):
        """GPG password-only mode should not require password parameter."""
        config = {
            ConfigKeys.MODE: SecurityMode.GPG_PW_ONLY.value,
            ConfigKeys.SEED_GPG_PATH: "seed.gpg",
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk1\\Partition2",
                ConfigKeys.MOUNT_LETTER: "V",
            },
        }

        # Should succeed without password
        result = normalize_mount_inputs(config, password=None)

        assert result["mode"] == SecurityMode.GPG_PW_ONLY.value
        assert result["password"] is None
        assert result["seed_gpg"] == "seed.gpg"

    def test_unknown_mode_raises(self):
        """Unknown security mode should raise controlled error."""
        config = {
            ConfigKeys.MODE: "unknown_mode_xyz",
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk1\\Partition2",
                ConfigKeys.MOUNT_LETTER: "V",
            },
        }

        with pytest.raises(ValueError, match="Invalid security mode"):
            normalize_mount_inputs(config, password="test123")

    def test_default_mount_letter(self):
        """Missing mount letter should default to 'V'."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk1\\Partition2",
                ConfigKeys.MOUNT_LETTER: None,  # None value
            },
        }

        result = normalize_mount_inputs(config, password="test123")

        assert result[ConfigKeys.WINDOWS][ConfigKeys.MOUNT_LETTER] == "V"

    def test_default_mount_point(self):
        """Missing mount point should default to '~/veradrive'."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_ONLY.value,
            ConfigKeys.UNIX: {ConfigKeys.VOLUME_PATH: "/dev/sdb2", ConfigKeys.MOUNT_POINT: None},  # None value
        }

        # Mock platform to be Unix for this test
        with unittest.mock.patch("scripts.mount.platform.system", return_value="Linux"):
            result = normalize_mount_inputs(config, password="test123")

            assert result[ConfigKeys.UNIX][ConfigKeys.MOUNT_POINT] == "~/veradrive"


class TestDefensiveCoding:
    """Test defensive coding patterns prevent crashes."""

    def test_get_with_none_value_safe(self):
        """dict.get() returning None should be handled safely."""
        config = {
            ConfigKeys.ENCRYPTED_KEYFILE: None,  # Explicitly None in JSON
        }

        # This pattern should not crash
        value = (config.get(ConfigKeys.ENCRYPTED_KEYFILE) or "").strip()
        assert value == ""

    def test_nested_get_with_none_section_safe(self):
        """Nested dict.get() with None section should be handled."""
        config = {ConfigKeys.WINDOWS: None}  # Section is None

        # This pattern should not crash
        cfg_win = config.get(ConfigKeys.WINDOWS) or {}
        value = (cfg_win.get(ConfigKeys.VOLUME_PATH) or "").strip()
        assert value == ""


class TestTmpKeyRegressionFix:
    """
    Regression tests for tmp_key UnboundLocalError (P0 bug).

    Error was: "cannot access local variable 'tmp_key' where it is not associated with a value"
    Root cause: Error handler referenced tmp_key but it was only defined in conditional branches.
    """

    def test_mount_error_message_no_keyfile(self):
        """Error message should not crash when no keyfile is used (password-only mode)."""
        # Simulate what happens in mount_veracrypt_windows error handler
        tmp_keys: list[Path] = []  # No keyfiles - password only mode
        volume_path = "\\Device\\Harddisk1\\Partition2"
        mount_letter = "V"

        # This is the fixed pattern - should NOT raise UnboundLocalError
        keyfile_info = "(none - password only)"
        if tmp_keys and len(tmp_keys) > 0:
            keyfile_info = ", ".join(str(k) for k in tmp_keys)

        error_msg = f"Keyfile: {keyfile_info}"

        # Should contain safe string, not crash
        assert "(none - password only)" in error_msg

    def test_mount_error_message_with_keyfiles(self):
        """Error message should list keyfiles when present."""
        # Simulate with keyfiles
        tmp_keys: list[Path] = [Path("/tmp/key1"), Path("/tmp/key2")]

        keyfile_info = "(none - password only)"
        if tmp_keys and len(tmp_keys) > 0:
            keyfile_info = ", ".join(str(k) for k in tmp_keys)

        error_msg = f"Keyfile: {keyfile_info}"

        # Should contain keyfile paths
        assert "key1" in error_msg
        assert "key2" in error_msg

    def test_mount_veracrypt_windows_error_path_no_crash(self):
        """mount_veracrypt_windows error path should not raise UnboundLocalError."""
        from scripts.mount import mount_veracrypt_windows

        # Test with empty keyfile list (password-only scenario that caused the bug)
        config = {
            ConfigKeys.WINDOWS: {
                ConfigKeys.VOLUME_PATH: "\\Device\\Harddisk999\\Partition99",  # Invalid path
                ConfigKeys.MOUNT_LETTER: "Z",
            }
        }

        # This should raise RuntimeError with helpful message, NOT UnboundLocalError
        with pytest.raises(RuntimeError) as exc_info:
            # Pass empty keyfile list (the scenario that triggered the bug)
            mount_veracrypt_windows(
                vc_exe=Path("C:\\") / "Program Files" / "VeraCrypt" / Paths.VERACRYPT_EXE_NAME,
                cfg=config,
                tmp_keys=None,  # No keyfiles
                password="test",
            )

        # Verify error is descriptive, not a crash
        error_str = str(exc_info.value)
        # Should NOT contain "UnboundLocalError" anywhere
        assert "UnboundLocalError" not in error_str
        # Should contain helpful error info
        assert "volume" in error_str.lower() or "mount" in error_str.lower()
