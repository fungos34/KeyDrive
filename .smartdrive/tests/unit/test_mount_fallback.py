#!/usr/bin/env python3
"""
Unit tests for BUG-20251221-037: Mount point fallback behavior.

Tests:
1. find_available_mount_letter returns available letter when preferred is in use
2. find_available_mount_letter respects max_attempts limit
3. find_available_mount_letter raises RuntimeError when all letters exhausted
4. is_mount_point_available_unix returns correct availability status
5. find_available_mount_point_unix finds alternatives when preferred is unavailable
6. find_available_mount_point_unix respects max_attempts limit
7. Error messages clearly distinguish mount point issues from credential issues
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add .smartdrive to path for imports
_test_dir = Path(__file__).resolve().parent
_smartdrive_root = _test_dir.parent.parent  # tests/unit -> tests -> .smartdrive

sys.path.insert(0, str(_smartdrive_root))

import pytest

from core.limits import Limits


class TestFindAvailableMountLetter:
    """Tests for find_available_mount_letter function."""

    def test_returns_preferred_when_available(self):
        """Should return preferred letter when it's available."""
        from scripts.mount import find_available_mount_letter

        # Mock Path.exists to make Z: available
        with patch.object(Path, "exists", return_value=False):
            letter, attempted = find_available_mount_letter("Z", max_attempts=Limits.MOUNT_MAX_ATTEMPTS)
            assert letter == "Z"
            assert attempted == ["Z"]

    def test_returns_alternative_when_preferred_in_use(self):
        """Should return next available letter when preferred is in use."""
        from scripts.mount import find_available_mount_letter

        # Mock: Z: in use, W: available
        def mock_exists(self):
            path_str = str(self)
            if "Z:\\" in path_str:
                return True  # Z: is in use
            return False  # Other letters are available

        with patch.object(Path, "exists", mock_exists):
            letter, attempted = find_available_mount_letter("Z", max_attempts=Limits.MOUNT_MAX_ATTEMPTS)
            # Should get next letter after Z (wraps around or picks from start)
            assert letter != "Z"
            assert len(attempted) >= 1
            assert "Z" in attempted  # Z was attempted first

    def test_respects_max_attempts(self):
        """Should only try max_attempts letters."""
        from scripts.mount import find_available_mount_letter

        attempt_count = 0

        def mock_exists(self):
            nonlocal attempt_count
            attempt_count += 1
            return True  # All letters in use

        with patch.object(Path, "exists", mock_exists):
            with pytest.raises(RuntimeError) as exc_info:
                find_available_mount_letter("Z", max_attempts=Limits.MOUNT_MAX_ATTEMPTS)

            # Should have tried exactly MOUNT_MAX_ATTEMPTS letters
            assert attempt_count == Limits.MOUNT_MAX_ATTEMPTS
            assert "mount point issue" in str(exc_info.value).lower()
            assert "credential" in str(exc_info.value).lower()

    def test_skips_reserved_letters(self):
        """Should skip system letters A, B, C."""
        from scripts.mount import find_available_mount_letter

        attempted_letters = []

        def mock_exists(self):
            path_str = str(self)
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if f"{letter}:\\" in path_str:
                    attempted_letters.append(letter)
                    break
            return True  # All letters in use

        with patch.object(Path, "exists", mock_exists):
            with pytest.raises(RuntimeError):
                # Use a large max_attempts to test all letters
                find_available_mount_letter("D", max_attempts=26)

            # A, B, C should never be in attempted list
            assert "A" not in attempted_letters
            assert "B" not in attempted_letters
            assert "C" not in attempted_letters

    def test_error_message_distinguishes_from_credentials(self):
        """Error message must clearly state it's NOT a credential problem."""
        from scripts.mount import find_available_mount_letter

        with patch.object(Path, "exists", return_value=True):
            with pytest.raises(RuntimeError) as exc_info:
                find_available_mount_letter("Z", max_attempts=Limits.MOUNT_MAX_ATTEMPTS)

            error_msg = str(exc_info.value).lower()
            assert "mount point" in error_msg
            assert "not" in error_msg and "credential" in error_msg


class TestIsMountPointAvailableUnix:
    """Tests for is_mount_point_available_unix function."""

    def test_nonexistent_path_is_available(self):
        """Non-existent path should be considered available."""
        from scripts.mount import is_mount_point_available_unix

        nonexistent = Path("/nonexistent/path/that/does/not/exist")
        assert is_mount_point_available_unix(nonexistent) is True

    def test_empty_directory_is_available(self):
        """Empty directory should be considered available."""
        from scripts.mount import is_mount_point_available_unix

        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = Path(tmpdir)
            assert is_mount_point_available_unix(empty_dir) is True

    def test_nonempty_directory_is_unavailable(self):
        """Non-empty directory should be considered unavailable."""
        from scripts.mount import is_mount_point_available_unix

        with tempfile.TemporaryDirectory() as tmpdir:
            nonempty_dir = Path(tmpdir)
            # Create a file in the directory
            (nonempty_dir / "testfile.txt").touch()
            assert is_mount_point_available_unix(nonempty_dir) is False


class TestFindAvailableMountPointUnix:
    """Tests for find_available_mount_point_unix function."""

    def test_returns_preferred_when_available(self):
        """Should return preferred path when it's available."""
        from scripts.mount import find_available_mount_point_unix

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use a path that doesn't exist yet (inside tmpdir)
            preferred = str(Path(tmpdir) / "veradrive")

            path, attempted = find_available_mount_point_unix(preferred, max_attempts=Limits.MOUNT_MAX_ATTEMPTS)
            assert path == Path(preferred)
            assert len(attempted) == 1

    def test_returns_alternative_when_preferred_unavailable(self):
        """Should return numbered alternative when preferred is unavailable."""
        from scripts.mount import find_available_mount_point_unix

        with tempfile.TemporaryDirectory() as tmpdir:
            preferred_dir = Path(tmpdir) / "veradrive"
            preferred_dir.mkdir()
            # Make preferred unavailable by adding a file
            (preferred_dir / "existing_file.txt").touch()

            path, attempted = find_available_mount_point_unix(
                str(preferred_dir), max_attempts=Limits.MOUNT_MAX_ATTEMPTS
            )
            # Should get veradrive_1 or veradrive_2
            assert "veradrive_" in str(path)
            assert len(attempted) >= 2

    def test_respects_max_attempts(self):
        """Should only try max_attempts paths."""
        from scripts.mount import find_available_mount_point_unix

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "veradrive"

            # Create all potential paths as non-empty directories
            for suffix in ["", "_1", "_2", "_3"]:
                dir_path = Path(str(base) + suffix)
                dir_path.mkdir()
                (dir_path / "blocking_file.txt").touch()

            with pytest.raises(RuntimeError) as exc_info:
                find_available_mount_point_unix(str(base), max_attempts=Limits.MOUNT_MAX_ATTEMPTS)

            assert "mount point issue" in str(exc_info.value).lower()
            assert "credential" in str(exc_info.value).lower()

    def test_error_message_distinguishes_from_credentials(self):
        """Error message must clearly state it's NOT a credential problem."""
        from scripts.mount import find_available_mount_point_unix

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "veradrive"

            # Create all potential paths as non-empty directories
            for suffix in ["", "_1", "_2"]:
                dir_path = Path(str(base) + suffix)
                dir_path.mkdir()
                (dir_path / "blocking_file.txt").touch()

            with pytest.raises(RuntimeError) as exc_info:
                find_available_mount_point_unix(str(base), max_attempts=Limits.MOUNT_MAX_ATTEMPTS)

            error_msg = str(exc_info.value).lower()
            assert "mount point" in error_msg
            assert "not" in error_msg and "credential" in error_msg


class TestConfigKeyExists:
    """Tests to verify SSOT keys are defined correctly."""

    def test_allow_mount_fallback_key_exists(self):
        """ALLOW_MOUNT_FALLBACK must be defined in ConfigKeys."""
        from core.constants import ConfigKeys

        assert hasattr(ConfigKeys, "ALLOW_MOUNT_FALLBACK")
        assert ConfigKeys.ALLOW_MOUNT_FALLBACK == "allow_mount_fallback"

    def test_windows_allow_mount_fallback_key_exists(self):
        """WINDOWS_ALLOW_MOUNT_FALLBACK must be defined for nested path."""
        from core.constants import ConfigKeys

        assert hasattr(ConfigKeys, "WINDOWS_ALLOW_MOUNT_FALLBACK")
        assert ConfigKeys.WINDOWS_ALLOW_MOUNT_FALLBACK == "windows.allow_mount_fallback"

    def test_unix_allow_mount_fallback_key_exists(self):
        """UNIX_ALLOW_MOUNT_FALLBACK must be defined for nested path."""
        from core.constants import ConfigKeys

        assert hasattr(ConfigKeys, "UNIX_ALLOW_MOUNT_FALLBACK")
        assert ConfigKeys.UNIX_ALLOW_MOUNT_FALLBACK == "unix.allow_mount_fallback"

    def test_default_allow_mount_fallback_is_true(self):
        """Default ALLOW_MOUNT_FALLBACK must be True."""
        from core.constants import Defaults

        assert hasattr(Defaults, "ALLOW_MOUNT_FALLBACK")
        assert Defaults.ALLOW_MOUNT_FALLBACK is True


class TestSettingsSchemaHasFallbackFields:
    """Tests to verify settings schema includes fallback toggle fields."""

    def test_windows_fallback_field_in_schema(self):
        """Windows tab must have allow_mount_fallback field."""
        from core.constants import ConfigKeys
        from core.settings_schema import SETTINGS_SCHEMA

        windows_fallback_fields = [f for f in SETTINGS_SCHEMA if f.key == ConfigKeys.WINDOWS_ALLOW_MOUNT_FALLBACK]
        assert len(windows_fallback_fields) == 1
        field = windows_fallback_fields[0]
        assert field.tab == "Windows"

    def test_unix_fallback_field_in_schema(self):
        """Unix tab must have allow_mount_fallback field."""
        from core.constants import ConfigKeys
        from core.settings_schema import SETTINGS_SCHEMA

        unix_fallback_fields = [f for f in SETTINGS_SCHEMA if f.key == ConfigKeys.UNIX_ALLOW_MOUNT_FALLBACK]
        assert len(unix_fallback_fields) == 1
        field = unix_fallback_fields[0]
        assert field.tab == "Unix"


class TestI18nKeysExist:
    """Tests to verify i18n keys are defined for all languages."""

    def test_fallback_label_key_exists_all_languages(self):
        """label_allow_mount_fallback must exist in all language dictionaries."""
        from scripts.gui_i18n import TRANSLATIONS

        for lang, translations in TRANSLATIONS.items():
            assert (
                "label_allow_mount_fallback" in translations
            ), f"Missing label_allow_mount_fallback in language '{lang}'"

    def test_fallback_tooltip_key_exists_all_languages(self):
        """tooltip_allow_mount_fallback must exist in all language dictionaries."""
        from scripts.gui_i18n import TRANSLATIONS

        for lang, translations in TRANSLATIONS.items():
            assert (
                "tooltip_allow_mount_fallback" in translations
            ), f"Missing tooltip_allow_mount_fallback in language '{lang}'"

    def test_error_occupied_key_exists_all_languages(self):
        """error_mount_point_occupied_fallback_disabled must exist in all languages."""
        from scripts.gui_i18n import TRANSLATIONS

        for lang, translations in TRANSLATIONS.items():
            assert (
                "error_mount_point_occupied_fallback_disabled" in translations
            ), f"Missing error_mount_point_occupied_fallback_disabled in language '{lang}'"

    def test_error_all_occupied_key_exists_all_languages(self):
        """error_mount_point_all_occupied must exist in all language dictionaries."""
        from scripts.gui_i18n import TRANSLATIONS

        for lang, translations in TRANSLATIONS.items():
            assert (
                "error_mount_point_all_occupied" in translations
            ), f"Missing error_mount_point_all_occupied in language '{lang}'"
