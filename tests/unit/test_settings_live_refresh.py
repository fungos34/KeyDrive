#!/usr/bin/env python3
"""
Test that changing language/theme via SettingsDialog does not crash and applies live changes.
This test instantiates a QApplication and a SmartDriveGUI to emulate a running GUI.
"""
import sys
from pathlib import Path

import pytest

# Skip if pytest-qt is not installed
pytest.importorskip("pytestqt", reason="pytest-qt not installed")

# Ensure test imports from project
_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent
_smartdrive_root = _project_root / ".smartdrive"
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))
if str(_smartdrive_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_smartdrive_root / "scripts"))

from gui_i18n import AVAILABLE_LANGUAGES
from PyQt6.QtWidgets import QApplication


def test_change_theme_and_language_no_crash(qtbot):
    """Ensure theme and language changes don't raise exceptions."""
    app = QApplication.instance() or QApplication(sys.argv)

    # Import GUI classes inside test to ensure paths are set
    from gui import SettingsDialog, SmartDriveGUI

    window = SmartDriveGUI()
    # Do not show the window to avoid blocking UI

    dialog = SettingsDialog(window.settings, parent=window)

    # Choose a different language if possible (avoid no-op)
    current_lang = dialog.lang_combo.currentData()
    target_lang = next((c for c in AVAILABLE_LANGUAGES.keys() if c != current_lang), current_lang)

    # Simulate selection change
    lang_changed = False
    lang_idx = dialog.lang_combo.findData(target_lang)
    if lang_idx >= 0 and target_lang != current_lang:
        dialog.lang_combo.setCurrentIndex(lang_idx)
        # Call handler directly to emulate user change
        dialog.on_language_changed(dialog.lang_combo.currentIndex())
        lang_changed = True

    # Simulate theme change to an available theme (first one)
    # Find theme combo data index 0
    theme_changed = False
    current_theme = dialog.theme_combo.currentData()
    # Pick a different theme if available
    target_theme_index = None
    for i in range(dialog.theme_combo.count()):
        if dialog.theme_combo.itemData(i) != current_theme:
            target_theme_index = i
            break
    if target_theme_index is not None:
        dialog.theme_combo.setCurrentIndex(target_theme_index)
        dialog.on_theme_changed(target_theme_index)
        theme_changed = True

    # Verify restart info label is not explicitly hidden when something changed.
    # Note: the dialog is not shown in this test, so QWidget.isVisible() will be False
    # even after setVisible(True) because the parent widget isn't visible.
    if lang_changed or theme_changed:
        assert not dialog.restart_info_label.isHidden()

    # Clean up
    dialog.close()
    window.close()
    app.quit()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
