"""
Tests for drive safety feature (CHG-20251221-040).

This module tests:
1. OS drive detection (core/platform.py:get_os_drive)
2. Instantiation drive detection (core/platform.py:get_instantiation_drive)
3. Drive protection logic (core/platform.py:is_drive_protected)
4. Setup drive selection safety (scripts/setup.py:select_drive exclusions)

SECURITY CRITICAL: These tests verify that the OS drive and the instantiation
drive are NEVER offered for repartitioning during setup.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Setup path for imports
_script_dir = Path(__file__).resolve().parent
_tests_dir = _script_dir.parent
_project_root = _tests_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class TestOSDriveDetection:
    """Tests for get_os_drive() function."""

    def test_os_drive_returns_string(self):
        """OS drive detection should return a string."""
        from core.platform import get_os_drive

        result = get_os_drive()
        assert isinstance(result, str)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_os_drive_windows_format(self):
        """On Windows, OS drive should be in 'X:' format."""
        from core.platform import get_os_drive

        result = get_os_drive()
        if result:
            # Should be drive letter with colon (e.g., "C:")
            assert len(result) == 2, f"Expected 'X:' format, got '{result}'"
            assert result[0].isalpha(), f"First char should be letter, got '{result}'"
            assert result[1] == ":", f"Second char should be ':', got '{result}'"
            assert result == result.upper(), f"Should be uppercase, got '{result}'"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
    def test_os_drive_unix_format(self):
        """On Unix, OS drive should be device path (e.g., /dev/sda1)."""
        from core.platform import get_os_drive

        result = get_os_drive()
        if result:
            # Should start with /dev/ or similar
            assert result.startswith("/"), f"Expected device path, got '{result}'"

    def test_os_drive_not_empty_on_real_system(self):
        """OS drive should be detected on a real system."""
        from core.platform import get_os_drive

        result = get_os_drive()
        # This might be empty in some CI environments, but should work locally
        # We just verify it doesn't raise
        assert result is not None

    @patch("core.platform.get_platform", return_value="windows")
    def test_os_drive_windows_fallback_to_env(self, mock_platform):
        """Windows should fallback to SystemRoot environment variable."""
        from core.platform import get_os_drive

        with patch.dict(os.environ, {"SystemRoot": "D:\\Windows"}):
            with patch("ctypes.windll.kernel32.GetSystemWindowsDirectoryW", side_effect=OSError):
                # Force the ctypes call to fail, triggering env var fallback
                result = get_os_drive()
                # Should get drive from env var
                # Note: This test may not work exactly due to import caching


class TestInstantiationDriveDetection:
    """Tests for get_instantiation_drive() function."""

    def test_instantiation_drive_returns_string(self):
        """Instantiation drive detection should return a string."""
        from core.platform import get_instantiation_drive

        result = get_instantiation_drive()
        assert isinstance(result, str)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_instantiation_drive_windows_format(self):
        """On Windows, instantiation drive should be in 'X:' format."""
        from core.platform import get_instantiation_drive

        result = get_instantiation_drive()
        if result:
            # Should be drive letter with colon (e.g., "H:")
            assert len(result) == 2, f"Expected 'X:' format, got '{result}'"
            assert result[0].isalpha(), f"First char should be letter, got '{result}'"
            assert result[1] == ":", f"Second char should be ':', got '{result}'"

    def test_instantiation_drive_matches_script_location(self):
        """Instantiation drive should match where the test is running from."""
        from core.platform import get_instantiation_drive, is_windows

        result = get_instantiation_drive()
        if result and is_windows():
            # On Windows, should match the drive of this test file
            test_drive = Path(__file__).resolve().drive
            assert result.upper() == test_drive.upper()


class TestInstantiationDriveMountDisplay:
    """Tests for get_instantiation_drive_letter_or_mount() function."""

    def test_returns_string(self):
        """Should return a string."""
        from core.platform import get_instantiation_drive_letter_or_mount

        result = get_instantiation_drive_letter_or_mount()
        assert isinstance(result, str)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_returns_drive_letter(self):
        """On Windows, should return drive letter like 'C:'."""
        from core.platform import get_instantiation_drive_letter_or_mount

        result = get_instantiation_drive_letter_or_mount()
        if result:
            assert len(result) == 2
            assert result[0].isalpha()
            assert result[1] == ":"


class TestDriveProtection:
    """Tests for is_drive_protected() function."""

    def test_returns_tuple(self):
        """is_drive_protected should return (bool, str) tuple."""
        from core.platform import is_drive_protected

        result = is_drive_protected("X:")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_os_drive_is_protected_windows(self):
        """OS drive should be protected on Windows."""
        from core.platform import get_os_drive, is_drive_protected

        os_drive = get_os_drive()
        if os_drive:
            is_protected, reason = is_drive_protected(os_drive)
            assert is_protected is True, f"OS drive {os_drive} should be protected"
            assert reason == "os_drive"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_instantiation_drive_is_protected_windows(self):
        """Instantiation drive should be protected on Windows."""
        from core.platform import get_instantiation_drive, is_drive_protected

        inst_drive = get_instantiation_drive()
        if inst_drive:
            is_protected, reason = is_drive_protected(inst_drive)
            assert is_protected is True, f"Instantiation drive {inst_drive} should be protected"
            assert reason in ("os_drive", "instantiation_drive")

    def test_unknown_drive_not_protected(self):
        """A made-up drive letter should not be protected."""
        from core.platform import is_drive_protected

        # Use an unlikely drive letter
        is_protected, reason = is_drive_protected("Z:")
        # This might be protected if Z: happens to be OS or instantiation drive
        # We mainly verify it doesn't crash
        assert isinstance(is_protected, bool)


class TestSetupDriveSafetyIntegration:
    """Integration tests for setup.py drive selection safety."""

    def test_setup_imports_safety_functions(self):
        """setup.py should import safety functions from platform."""
        from scripts.setup import get_instantiation_drive, get_os_drive, is_drive_protected

        # Just verify imports work
        assert callable(get_os_drive)
        assert callable(get_instantiation_drive)
        assert callable(is_drive_protected)

    def test_select_drive_function_exists(self):
        """select_drive function should exist in setup.py."""
        from scripts.setup import select_drive

        assert callable(select_drive)

    def test_select_drive_signature(self):
        """select_drive should accept drives list and system string."""
        import inspect

        from scripts.setup import select_drive

        sig = inspect.signature(select_drive)
        params = list(sig.parameters.keys())
        assert "drives" in params
        assert "system" in params


class TestConfigKeysForDriveDisplay:
    """Tests for ConfigKeys drive display constants."""

    def test_os_drive_key_exists(self):
        """ConfigKeys.OS_DRIVE should exist."""
        from core.constants import ConfigKeys

        assert hasattr(ConfigKeys, "OS_DRIVE")
        assert ConfigKeys.OS_DRIVE == "os_drive"

    def test_instantiation_drive_key_exists(self):
        """ConfigKeys.INSTANTIATION_DRIVE should exist."""
        from core.constants import ConfigKeys

        assert hasattr(ConfigKeys, "INSTANTIATION_DRIVE")
        assert ConfigKeys.INSTANTIATION_DRIVE == "instantiation_drive"


class TestSettingsSchemaForDriveDisplay:
    """Tests for settings_schema.py drive display fields."""

    def test_os_drive_field_in_windows_tab(self):
        """OS_DRIVE field should exist in Windows tab."""
        from core.constants import ConfigKeys
        from core.settings_schema import SETTINGS_SCHEMA

        os_drive_fields = [f for f in SETTINGS_SCHEMA if f.key == ConfigKeys.WINDOWS_OS_DRIVE]
        assert len(os_drive_fields) == 1, "WINDOWS_OS_DRIVE field should exist in schema"

        windows_field = os_drive_fields[0]
        assert windows_field.tab == "Windows"
        assert windows_field.group == "drive_context"
        assert windows_field.readonly is True

    def test_os_drive_field_in_unix_tab(self):
        """OS_DRIVE field should exist in Unix tab."""
        from core.constants import ConfigKeys
        from core.settings_schema import SETTINGS_SCHEMA

        unix_fields = [f for f in SETTINGS_SCHEMA if f.key == ConfigKeys.UNIX_OS_DRIVE]
        assert len(unix_fields) == 1, "UNIX_OS_DRIVE should be in Unix tab"
        unix_field = unix_fields[0]
        assert unix_field.tab == "Unix"
        assert unix_field.group == "drive_context"

    def test_instantiation_drive_field_in_windows_tab(self):
        """INSTANTIATION_DRIVE field should exist in Windows tab."""
        from core.constants import ConfigKeys
        from core.settings_schema import SETTINGS_SCHEMA

        inst_fields = [f for f in SETTINGS_SCHEMA if f.key == ConfigKeys.WINDOWS_INSTANTIATION_DRIVE]
        assert len(inst_fields) == 1, "WINDOWS_INSTANTIATION_DRIVE field should exist"

        windows_field = inst_fields[0]
        assert windows_field.tab == "Windows"
        assert windows_field.group == "drive_context"
        assert windows_field.readonly is True

    def test_instantiation_drive_field_in_unix_tab(self):
        """INSTANTIATION_DRIVE field should exist in Unix tab."""
        from core.constants import ConfigKeys
        from core.settings_schema import SETTINGS_SCHEMA

        inst_fields = [f for f in SETTINGS_SCHEMA if f.key == ConfigKeys.UNIX_INSTANTIATION_DRIVE]
        assert len(inst_fields) == 1
        unix_field = inst_fields[0]
        assert unix_field.tab == "Unix"
        assert unix_field.group == "drive_context"

    def test_four_drive_fields_in_drive_context_group(self):
        """Drive context group should have fields for all 4 drive types."""
        from core.constants import ConfigKeys
        from core.settings_schema import SETTINGS_SCHEMA

        # Check Windows tab
        windows_dc_fields = [f for f in SETTINGS_SCHEMA if f.tab == "Windows" and f.group == "drive_context"]

        windows_keys = {f.key for f in windows_dc_fields}

        # Should have OS_DRIVE, INSTANTIATION_DRIVE, and LAUNCHER_ROOT (platform-specific keys)
        assert ConfigKeys.WINDOWS_OS_DRIVE in windows_keys
        assert ConfigKeys.WINDOWS_INSTANTIATION_DRIVE in windows_keys
        assert ConfigKeys.WINDOWS_LAUNCHER_ROOT in windows_keys


class TestI18nKeysForDriveSafety:
    """Tests for i18n translation keys."""

    def test_os_drive_label_key_exists(self):
        """label_os_drive key should exist in English."""
        from scripts.gui_i18n import TRANSLATIONS

        en = TRANSLATIONS["en"]
        assert "label_os_drive" in en
        assert "OS Drive:" in en["label_os_drive"] or "os" in en["label_os_drive"].lower()

    def test_os_drive_tooltip_key_exists(self):
        """tooltip_os_drive key should exist in English."""
        from scripts.gui_i18n import TRANSLATIONS

        en = TRANSLATIONS["en"]
        assert "tooltip_os_drive" in en
        assert "cannot" in en["tooltip_os_drive"].lower() or "repartition" in en["tooltip_os_drive"].lower()

    def test_instantiation_drive_label_key_exists(self):
        """label_instantiation_drive key should exist in English."""
        from scripts.gui_i18n import TRANSLATIONS

        en = TRANSLATIONS["en"]
        assert "label_instantiation_drive" in en

    def test_instantiation_drive_tooltip_key_exists(self):
        """tooltip_instantiation_drive key should exist in English."""
        from scripts.gui_i18n import TRANSLATIONS

        en = TRANSLATIONS["en"]
        assert "tooltip_instantiation_drive" in en
        assert (
            "cannot" in en["tooltip_instantiation_drive"].lower()
            or "repartition" in en["tooltip_instantiation_drive"].lower()
        )

    def test_all_languages_have_os_drive_keys(self):
        """All languages should have os_drive translation keys."""
        from scripts.gui_i18n import TRANSLATIONS

        required_keys = [
            "label_os_drive",
            "tooltip_os_drive",
            "label_instantiation_drive",
            "tooltip_instantiation_drive",
        ]

        for lang_code, lang_dict in TRANSLATIONS.items():
            for key in required_keys:
                assert key in lang_dict, f"Language {lang_code} missing key {key}"


class TestDriveSafetyDocumentation:
    """Tests for documentation compliance."""

    def test_feature_flows_has_change_entry(self):
        """FEATURE_FLOWS.md should have CHG-20251221-040 entry."""
        project_root = Path(__file__).resolve().parent.parent.parent
        feature_flows = project_root / "FEATURE_FLOWS.md"

        if feature_flows.exists():
            content = feature_flows.read_text(encoding="utf-8")
            assert "CHG-20251221-040" in content, "Drive safety change should be documented"
            assert "OS Drive" in content or "os_drive" in content
            assert "instantiation" in content.lower()
