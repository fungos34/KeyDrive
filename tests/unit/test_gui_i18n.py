#!/usr/bin/env python3
"""
Unit tests for P1: GUI i18n (internationalization).

These tests ensure:
1. tr() falls back to English when key missing in selected language
2. Missing key in English raises KeyError
3. All GUI-required keys exist in English
"""

import sys
from pathlib import Path

# Add project root and .smartdrive to path for imports
_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent
_smartdrive_root = _project_root / ".smartdrive"

sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_smartdrive_root))
sys.path.insert(0, str(_smartdrive_root / "scripts"))

import pytest
from gui_i18n import TRANSLATIONS, tr, validate_keys


class TestTranslationFunction:
    """Tests for tr() translation function."""

    def test_english_key_found(self):
        """Test that existing English key is returned."""
        result = tr("btn_mount", lang="en")
        assert result == "🔓 Mount"

    def test_german_key_found(self):
        """Test that existing German key is returned."""
        result = tr("btn_mount", lang="de")
        assert result == "🔓 Einbinden"

    def test_fallback_to_english(self):
        """Test fallback to English when key missing in selected language."""
        # Add a key only in English for this test
        original_en = TRANSLATIONS["en"].copy()
        TRANSLATIONS["en"]["test_only_en"] = "English only"

        try:
            # German doesn't have this key, should fall back to English
            result = tr("test_only_en", lang="de")
            assert result == "English only"
        finally:
            # Restore
            TRANSLATIONS["en"] = original_en

    def test_missing_key_in_en_raises(self):
        """Test that missing key in English raises KeyError."""
        with pytest.raises(KeyError) as exc_info:
            tr("nonexistent_key_xyz123", lang="en")
        assert "nonexistent_key_xyz123" in str(exc_info.value)

    def test_missing_key_even_with_fallback_raises(self):
        """Test that missing key raises even after fallback attempt."""
        with pytest.raises(KeyError):
            tr("this_key_does_not_exist", lang="de")

    def test_format_arguments(self):
        """Test that format arguments work."""
        result = tr("keyfile_selected_many", lang="en", count=5)
        assert result == "5 keyfiles selected"

    def test_unknown_language_fallback(self):
        """Test that unknown language falls back to English."""
        result = tr("btn_mount", lang="xx_unknown")
        assert result == "🔓 Mount"


class TestRequiredGUIKeys:
    """Tests to ensure all GUI-required keys exist."""

    # Keys that must exist for GUI to function
    REQUIRED_KEYS = {
        # Window titles
        "window_title",
        "settings_window_title",
        # Button labels
        "btn_mount",
        "btn_unmount",
        "btn_cancel_auth",
        "btn_confirm_mount",
        "btn_tools",
        "btn_close",
        "btn_save",
        "btn_cancel",
        # Status messages
        "status_config_not_found",
        "status_volume_mounted",
        "status_volume_not_mounted",
        "status_mounting",
        "status_mounting_gpg",
        "status_unmounting",
        "status_mount_success",
        "status_mount_failed",
        "status_unmount_success",
        "status_unmount_failed",
        # Info labels
        "info_unavailable",
        "keyfile_selected_one",
        "keyfile_selected_many",
        # Size formatting
        "size_free",
        # Icons
        "icon_drive",
    }

    def test_all_required_keys_in_english(self):
        """All required keys must exist in English."""
        en_keys = set(TRANSLATIONS.get("en", {}).keys())
        missing = self.REQUIRED_KEYS - en_keys
        assert not missing, f"Missing required keys in 'en': {missing}"

    def test_validate_keys_function(self):
        """Test validate_keys function catches missing keys."""
        # Should pass with valid keys
        validate_keys({"btn_mount", "btn_unmount"})

        # Should raise with invalid keys
        with pytest.raises(KeyError):
            validate_keys({"nonexistent_key_abc"})

    def test_gui_import_no_keyerror(self):
        """Smoke test: GUI module import should not raise KeyError."""
        # This tests that all keys used in gui.py exist
        try:
            # Import the actual gui module from .smartdrive (not the dev wrapper)
            import gui  # from .smartdrive/scripts/ (already in path)
        except KeyError as e:
            pytest.fail(f"GUI import raised KeyError: {e}")
        except ImportError:
            # ImportError is OK (missing PyQt6), KeyError is not
            pass
        except SystemExit:
            # SystemExit is OK (GUI tried to start), KeyError during import is not
            pass


class TestGermanTranslations:
    """Tests for German translation stub."""

    def test_german_translations_exist(self):
        """German translation table must exist."""
        assert "de" in TRANSLATIONS

    def test_german_has_core_keys(self):
        """German should have core button/status keys."""
        de_keys = set(TRANSLATIONS.get("de", {}).keys())
        core_keys = {"btn_mount", "btn_unmount", "status_volume_mounted"}
        missing = core_keys - de_keys
        assert not missing, f"German missing core keys: {missing}"


class TestNoHardcodedGUIStrings:
    """
    Tests to detect hardcoded GUI string literals.

    Per AGENT_ARCHITECTURE.md Section 11.2:
    All GUI-visible text MUST use tr() function.
    This test scans gui.py for forbidden patterns.
    """

    # Patterns that indicate hardcoded GUI strings
    FORBIDDEN_PATTERNS = [
        # Button/Label constructors with string literals
        (r'QPushButton\(["\'][A-Za-z🔓🔒❌✅⚙️]', "QPushButton with literal text"),
        (r'QLabel\(["\'][A-Za-z💡🚀]', "QLabel with literal text"),
        # setText with literal text (not empty, not variable)
        (r'setText\(["\'][A-Za-z🚀💡]', "setText with literal text"),
        # setPlaceholderText with literal
        (r'setPlaceholderText\(["\'][A-Za-z]', "setPlaceholderText with literal"),
        # setToolTip with literal (except empty)
        (r'setToolTip\(["\'][A-Za-z]', "setToolTip with literal text"),
    ]

    # Allowed exceptions (comments, docstrings, etc.)
    EXCEPTIONS = [
        "# ",  # Comments
        '"""',  # Docstrings
        "'''",  # Docstrings
    ]

    def test_no_hardcoded_gui_strings(self):
        """Scan gui.py for forbidden GUI string patterns."""
        import re

        gui_path = _project_root / "scripts" / "gui.py"
        if not gui_path.exists():
            pytest.skip("gui.py not found")

        with open(gui_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        violations = []

        for line_num, line in enumerate(lines, 1):
            # Skip exception lines
            stripped = line.strip()
            if any(stripped.startswith(exc) for exc in self.EXCEPTIONS):
                continue

            for pattern, description in self.FORBIDDEN_PATTERNS:
                if re.search(pattern, line):
                    violations.append(f"Line {line_num}: {description} - {line.strip()[:60]}")

        assert not violations, (
            f"Found {len(violations)} hardcoded GUI string(s) in gui.py:\n"
            + "\n".join(violations[:10])  # Show first 10
            + ("\n... and more" if len(violations) > 10 else "")
        )

    def test_all_translation_keys_used_exist(self):
        """All tr() calls in gui.py must reference existing keys."""
        import re

        gui_path = _project_root / "scripts" / "gui.py"
        if not gui_path.exists():
            pytest.skip("gui.py not found")

        with open(gui_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find all tr("key_name") calls
        tr_pattern = r'tr\(["\']([a-z_]+)["\']'
        used_keys = set(re.findall(tr_pattern, content))

        # Check all exist in English
        en_keys = set(TRANSLATIONS.get("en", {}).keys())
        missing = used_keys - en_keys

        assert not missing, f"GUI uses undefined translation keys: {missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
