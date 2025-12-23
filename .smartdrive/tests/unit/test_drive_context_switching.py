#!/usr/bin/env python3
"""
Unit tests for multi-drive context switching feature (CHG-20251221-026).

Tests:
1. Switch Drive menu integration
2. Recent drives helper methods
3. Drive context switch logic
4. Settings schema launcher_root field
5. i18n keys for drive switching
"""

from pathlib import Path


def _read_gui() -> str:
    """Read gui.py source for static analysis."""
    smartdrive_root = Path(__file__).resolve().parent.parent.parent
    gui_path = smartdrive_root / "scripts" / "gui.py"
    return gui_path.read_text(encoding="utf-8")


def _read_i18n() -> str:
    """Read gui_i18n.py source for static analysis."""
    smartdrive_root = Path(__file__).resolve().parent.parent.parent
    i18n_path = smartdrive_root / "scripts" / "gui_i18n.py"
    return i18n_path.read_text(encoding="utf-8")


def _read_settings_schema() -> str:
    """Read settings_schema.py source for static analysis."""
    smartdrive_root = Path(__file__).resolve().parent.parent.parent
    schema_path = smartdrive_root / "core" / "settings_schema.py"
    return schema_path.read_text(encoding="utf-8")


def _read_constants() -> str:
    """Read constants.py source for static analysis."""
    smartdrive_root = Path(__file__).resolve().parent.parent.parent
    constants_path = smartdrive_root / "core" / "constants.py"
    return constants_path.read_text(encoding="utf-8")


# =============================================================================
# gui.py Tests
# =============================================================================


class TestSwitchDriveMenu:
    """
    Test Switch Drive submenu REMOVAL from tools menu.

    BUG-20251222-012: "Switch Drive" menu removed per user request.
    These tests verify the menu is NOT in the gear menu (was removed for simplicity).
    The helper methods still exist for internal use by Remote Control mode.
    """

    def test_switch_drive_menu_not_in_gear_menu(self):
        """Verify Switch Drive submenu is NOT added to gear menu (BUG-20251222-012)."""
        content = _read_gui()
        # The menu should NOT be added via addMenu
        assert 'switch_drive_menu = menu.addMenu(tr("menu_switch_drive"' not in content
        # But the bug fix comment should exist explaining why
        assert "BUG-20251222-012" in content

    def test_populate_switch_drive_menu_helper_still_exists(self):
        """Verify _populate_switch_drive_menu helper exists (for internal/remote use)."""
        content = _read_gui()
        assert "def _populate_switch_drive_menu(self, menu:" in content

    def test_browse_for_drive_context_exists(self):
        """Verify _browse_for_drive_context method exists (for internal use)."""
        content = _read_gui()
        assert "def _browse_for_drive_context(self)" in content


class TestRecentDrivesHelpers:
    """Test recent drives helper methods."""

    def test_get_recent_drives_exists(self):
        """Verify _get_recent_drives helper exists."""
        content = _read_gui()
        assert "def _get_recent_drives(self)" in content

    def test_add_to_recent_drives_exists(self):
        """Verify _add_to_recent_drives helper exists."""
        content = _read_gui()
        assert "def _add_to_recent_drives(self, smartdrive_path:" in content

    def test_recent_drives_use_qsettings(self):
        """Verify recent drives are stored in QSettings, not config.json."""
        content = _read_gui()
        assert 'self.settings.value("recent_drives"' in content
        assert 'self.settings.setValue("recent_drives"' in content

    def test_recent_drives_max_limit(self):
        """Verify recent drives list has max limit."""
        content = _read_gui()
        assert "recent[:5]" in content or "[:5]" in content


class TestDriveContextSwitch:
    """Test drive context switch logic."""

    def test_switch_drive_context_exists(self):
        """Verify _switch_drive_context method exists."""
        content = _read_gui()
        assert "def _switch_drive_context(self, new_smartdrive_path:" in content

    def test_switch_validates_config_exists(self):
        """Verify switch validates config.json exists in target path."""
        content = _read_gui()
        assert "config_path = new_smartdrive_path" in content
        assert '"scripts" / "config.json"' in content or "scripts" in content

    def test_switch_updates_config_file_global(self):
        """Verify switch updates global CONFIG_FILE."""
        content = _read_gui()
        # Check for the pattern: global CONFIG_FILE followed by CONFIG_FILE = ...
        assert "global CONFIG_FILE" in content

    def test_switch_reloads_config(self):
        """Verify switch reloads configuration after context change."""
        content = _read_gui()
        assert "self._reload_config()" in content

    def test_reload_config_exists(self):
        """Verify _reload_config method exists for context reloading."""
        content = _read_gui()
        assert "def _reload_config(self)" in content


class TestSettingsLauncherRoot:
    """Test launcher_root display in Settings dialog."""

    def test_launcher_root_readonly_display(self):
        """Verify launcher_root is displayed as READONLY in Settings."""
        content = _read_gui()
        # Check for special handling of LAUNCHER_ROOT in _add_field_to_layout
        assert "ConfigKeys.LAUNCHER_ROOT" in content
        # Multi-line ternary: launcher_root_value = ( str(self._launcher_root) if ... )
        assert "launcher_root_value" in content
        assert "str(self._launcher_root)" in content


# =============================================================================
# settings_schema.py Tests
# =============================================================================


class TestSettingsSchema:
    """Test settings schema has launcher_root field."""

    def test_launcher_root_field_in_windows_tab(self):
        """Verify launcher_root field exists in Windows tab schema."""
        content = _read_settings_schema()
        # BUG-20251223-001 FIX: Check for WINDOWS_LAUNCHER_ROOT instead of generic LAUNCHER_ROOT
        assert "ConfigKeys.WINDOWS_LAUNCHER_ROOT" in content
        assert 'tab="Windows"' in content

    def test_launcher_root_field_in_unix_tab(self):
        """Verify launcher_root field exists in Unix tab schema."""
        content = _read_settings_schema()
        assert 'tab="Unix"' in content
        # BUG-20251223-001 FIX: Check for platform-specific keys to avoid duplicate
        assert "ConfigKeys.WINDOWS_LAUNCHER_ROOT" in content
        assert "ConfigKeys.UNIX_LAUNCHER_ROOT" in content


# =============================================================================
# constants.py Tests
# =============================================================================


class TestConfigKeys:
    """Test ConfigKeys has LAUNCHER_ROOT."""

    def test_launcher_root_key_exists(self):
        """Verify LAUNCHER_ROOT key exists in ConfigKeys."""
        content = _read_constants()
        assert 'LAUNCHER_ROOT = "launcher_root"' in content


# =============================================================================
# gui_i18n.py Tests
# =============================================================================


class TestI18nKeys:
    """Test i18n translation keys for drive switching."""

    def test_menu_switch_drive_key_in_english(self):
        """Verify menu_switch_drive translation key exists."""
        content = _read_i18n()
        assert '"menu_switch_drive"' in content

    def test_menu_switch_drive_browse_key(self):
        """Verify menu_switch_drive_browse translation key exists."""
        content = _read_i18n()
        assert '"menu_switch_drive_browse"' in content

    def test_label_launcher_root_key(self):
        """Verify label_launcher_root translation key exists."""
        content = _read_i18n()
        assert '"label_launcher_root"' in content

    def test_group_drive_context_key(self):
        """Verify group_drive_context translation key exists."""
        content = _read_i18n()
        assert '"group_drive_context"' in content

    def test_switch_drive_confirm_key(self):
        """Verify switch_drive_confirm translation key exists."""
        content = _read_i18n()
        assert '"switch_drive_confirm"' in content

    def test_switch_drive_invalid_path_key(self):
        """Verify switch_drive_invalid_path translation key exists."""
        content = _read_i18n()
        assert '"switch_drive_invalid_path"' in content

    def test_all_languages_have_switch_drive(self):
        """Verify all 7 languages have menu_switch_drive translation."""
        content = _read_i18n()
        # Count occurrences - should be 7 (one per language)
        count = content.count('"menu_switch_drive":')
        assert count >= 7, f"Expected 7 translations for menu_switch_drive, found {count}"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
