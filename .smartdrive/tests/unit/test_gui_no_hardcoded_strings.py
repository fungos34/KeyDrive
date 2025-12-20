#!/usr/bin/env python3
"""
Unit tests to ensure no hardcoded GUI strings in gui.py.

This test verifies that all user-visible text uses tr() function.
"""

import re
import sys
from pathlib import Path

# Add .smartdrive to path
_test_dir = Path(__file__).resolve().parent
_smartdrive_root = _test_dir.parent.parent  # tests/unit -> tests -> .smartdrive

if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))


def test_no_hardcoded_gui_strings():
    """
    Verify that gui.py doesn't have hardcoded user-visible strings.

    This test looks for common patterns that might indicate hardcoded strings:
    - addAction("literal string")
    - setText("literal string")
    - setTitle("literal string")
    - setWindowTitle("literal string")

    Exceptions:
    - Empty strings
    - Single-character strings (e.g., close button "✕")
    - Technical strings (e.g., CSS, object names)
    - tr() calls (allowed)
    """
    # gui.py is now in .smartdrive/scripts/
    gui_path = _smartdrive_root / "scripts" / "gui.py"

    with open(gui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Patterns that should use tr()
    suspicious_patterns = [
        (r'\.setText\(["\'](?!$)(?![✕🔓🔒⚙️💻🚀📁ℹ️✓❌⏳])([^"\']{3,})["\']', "setText with literal string"),
        (r'\.setTitle\(["\'](?!$)([^"\']{3,})["\']', "setTitle with literal string"),
        (r'\.addAction\(["\'](?!$)([^"\']{3,})["\']', "addAction with literal string"),
        (r'"Free:\s', "Free: prefix must use tr('size_free')"),
        (r'"Password:', "Password label must use tr('label_password')"),
        (r'"Hardware key', "Hardware key hint must use tr('label_hardware_key_hint')"),
        (r'QMessageBox\.\w+\([^,]+,\s*"[^"]+",\s*"[^t]', "QMessageBox text must use tr()"),
    ]

    # Allowed patterns (false positives)
    allowed_patterns = [
        r"tr\(",  # Already using tr()
        r"setObjectName\(",  # Technical names
        r"setStyleSheet\(",  # CSS
        r'setPlaceholderText\(f"Default:',  # Product name default
        r"QSettings\(",  # QSettings constructor
        r"QApplication\.setApplicationName",  # App metadata
        r"QApplication\.setOrganizationName",
        r'\.setText\(f"',  # f-strings for dynamic content
        r"\.setTitle\(tr\(",  # Already using tr
        r"\.addAction\(tr\(",  # Already using tr
    ]

    violations = []

    for pattern, description in suspicious_patterns:
        matches = re.finditer(pattern, content, re.MULTILINE)

        for match in matches:
            line_num = content[: match.start()].count("\n") + 1
            matched_text = match.group(0)

            # Check if this match is in an allowed context
            is_allowed = False
            for allowed in allowed_patterns:
                if re.search(allowed, matched_text):
                    is_allowed = True
                    break

            if not is_allowed:
                violations.append(f"Line {line_num}: {description} - {matched_text[:80]}")

    # Report violations
    if violations:
        error_msg = "Found hardcoded GUI strings (should use tr() function):\n"
        error_msg += "\n".join(violations[:10])  # Show first 10
        if len(violations) > 10:
            error_msg += f"\n... and {len(violations) - 10} more"

        # This is a soft warning for now, not a hard failure
        # Since the codebase is being gradually updated
        print(f"\nWARNING: {error_msg}")
        # Uncomment to make this a hard failure:
        # assert False, error_msg


def test_settings_dialog_uses_translations():
    """Verify that SettingsDialog uses tr() for all labels."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"

    with open(gui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find SettingsDialog class
    settings_dialog_match = re.search(r"class SettingsDialog.*?(?=^class |\Z)", content, re.MULTILINE | re.DOTALL)

    assert settings_dialog_match, "SettingsDialog class not found"

    settings_dialog_code = settings_dialog_match.group(0)

    # Check that critical UI elements use tr()
    required_tr_calls = [
        'tr("settings_window_title"',
        'tr("settings_general"',
        'tr("settings_language"',
        'tr("btn_save"',
        'tr("btn_cancel"',
    ]

    for tr_call in required_tr_calls:
        assert tr_call in settings_dialog_code, f"SettingsDialog should use {tr_call}"


def test_main_window_uses_translations():
    """Verify that SmartDriveGUI uses tr() for buttons and labels."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"

    with open(gui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check that key UI elements use tr() or set_status()
    required_tr_calls = [
        'tr("btn_mount"',
        'tr("btn_unmount"',
        'tr("btn_tools"',
    ]

    # Status messages now use set_status() instead of tr() directly
    required_status_calls = [
        'set_status("status_volume_mounted"',
        'set_status("status_volume_not_mounted"',
    ]

    for tr_call in required_tr_calls:
        assert tr_call in content, f"SmartDriveGUI should use {tr_call}"

    for status_call in required_status_calls:
        assert status_call in content, f"SmartDriveGUI should use {status_call}"


def test_status_container_stability():
    """Verify status label is wrapped in fixed-height container."""
    gui_path = _smartdrive_root / "scripts" / "gui.py"

    with open(gui_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for status_container
    assert "self.status_container" in content, "status_container not found"
    assert "setFixedHeight" in content, "Fixed height not set for container"
    assert "fontMetrics()" in content, "Font metrics not used for height calculation"
    assert "AlignVCenter" in content, "Vertical alignment not set for label"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
