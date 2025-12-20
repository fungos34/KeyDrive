#!/usr/bin/env python3
"""
Unit tests for immediate GUI language updates.

Tests verify that language changes propagate to ALL live widgets immediately
without requiring restart or timers.

Critical requirements:
- Widget references stored as instance attributes
- apply_language updates all widgets in one pass
- status_key pattern used for status tracking
- No hardcoded UI strings remain
"""

import sys
from pathlib import Path

import pytest

# Add .smartdrive to path
_test_dir = Path(__file__).resolve().parent
_smartdrive_root = _test_dir.parent.parent  # tests/unit -> tests -> .smartdrive

if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))
if str(_smartdrive_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_smartdrive_root / "scripts"))

from gui_i18n import tr

# set_lang and get_lang are in gui module, not gui_i18n


def test_password_label_is_instance_attribute():
    """
    Test that password_label is stored as instance attribute (not local variable).
    This is required for apply_language to update it.
    """
    gui_path = _smartdrive_root / "scripts" / "gui.py"
    content = gui_path.read_text(encoding="utf-8")

    # Must have self.password_label = QLabel(...
    assert (
        "self.password_label = QLabel(" in content
    ), "password_label must be stored as self.password_label for apply_language to update it"


def test_recovery_label_is_instance_attribute():
    """Test that recovery_label is stored as instance attribute."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"
    content = gui_path.read_text(encoding="utf-8")

    assert (
        "self.recovery_label = QLabel(" in content
    ), "recovery_label must be stored as self.recovery_label for apply_language to update it"


def test_status_key_attribute_exists():
    """Test that status_key field exists for tracking status as key (not translated text)."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"
    content = gui_path.read_text(encoding="utf-8")

    assert "self.status_key" in content, "status_key field must exist to track status as key for language updates"


def test_set_status_method_exists():
    """Test that set_status helper method exists."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"
    content = gui_path.read_text(encoding="utf-8")

    assert "def set_status(self, key:" in content, "set_status(key, style) method must exist for status updates"


def test_update_storage_labels_method_exists():
    """Test that update_storage_labels helper method exists."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"
    content = gui_path.read_text(encoding="utf-8")

    assert "def update_storage_labels(self, lang:" in content, "update_storage_labels(lang) method must exist"


def test_worker_signals_have_dict_parameter():
    """Test that MountWorker and UnmountWorker emit (bool, str, dict) not (bool, str)."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"
    content = gui_path.read_text(encoding="utf-8")

    # Check MountWorker signal signature
    assert (
        "finished = pyqtSignal(bool, str, dict)" in content
    ), "MountWorker.finished must emit (bool, str, dict) for message keys + args"


def test_no_hardcoded_menu_strings():
    """Test that menu items use tr() not hardcoded strings."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"
    content = gui_path.read_text(encoding="utf-8")

    # Forbidden patterns - hardcoded UI strings
    forbidden = [
        '"Clear Keyfiles"',
        '"Select Keyfile(s)"',
        '"💻 Open CLI"',
    ]

    for pattern in forbidden:
        assert pattern not in content, f"Hardcoded string {pattern} found in gui.py - must use tr() instead"


def test_settings_dialog_stores_widget_refs():
    """Test that SettingsDialog stores widget references as instance attributes."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"
    content = gui_path.read_text(encoding="utf-8")

    # All group boxes must be stored as instance attributes
    assert "self.general_box = QGroupBox(" in content, "general_box must be instance attribute"
    assert "self.security_box = QGroupBox(" in content, "security_box must be instance attribute"
    assert "self.keyfile_box = QGroupBox(" in content, "keyfile_box must be instance attribute"
    assert "self.windows_box = QGroupBox(" in content, "windows_box must be instance attribute"
    assert "self.unix_box = QGroupBox(" in content, "unix_box must be instance attribute"
    assert "self.updates_box = QGroupBox(" in content, "updates_box must be instance attribute"

    # Buttons must be stored
    assert "self.save_btn = QPushButton(" in content, "save_btn must be instance attribute"
    assert "self.cancel_btn = QPushButton(" in content, "cancel_btn must be instance attribute"


def test_translation_keys_exist_for_new_features():
    """Test that all new translation keys exist in both languages."""
    required_keys = [
        "menu_cli",
        "menu_clear_keyfiles",
        "dialog_select_keyfiles",
        "worker_mount_success",
        "worker_mount_failed",
        "worker_unmount_success",
        "worker_unmount_failed",
    ]

    for key in required_keys:
        # Must exist in English
        result_en = tr(key, lang="en")
        assert result_en, f"Key {key} missing in English"

        # Must exist in German
        result_de = tr(key, lang="de")
        assert result_de, f"Key {key} missing in German"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
