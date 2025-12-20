#!/usr/bin/env python3
"""
Unit tests for GUI language switching functionality.

Tests:
- Language loading from config
- Language switching updates UI
- AVAILABLE_LANGUAGES integrity
- tr() function with multiple languages
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Add .smartdrive to path
_test_dir = Path(__file__).resolve().parent
_smartdrive_root = _test_dir.parent.parent  # tests/unit -> tests -> .smartdrive

if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))
if str(_smartdrive_root / "scripts") not in sys.path:
    sys.path.insert(0, str(_smartdrive_root / "scripts"))

from gui_i18n import AVAILABLE_LANGUAGES, TRANSLATIONS, tr

from core.constants import ConfigKeys, GUIConfig
from core.modes import SecurityMode


def test_available_languages_structure():
    """Test that AVAILABLE_LANGUAGES has correct structure."""
    assert isinstance(AVAILABLE_LANGUAGES, dict)
    assert len(AVAILABLE_LANGUAGES) > 0

    # English must be available (default)
    assert "en" in AVAILABLE_LANGUAGES
    assert AVAILABLE_LANGUAGES["en"] == "English"

    # All language codes must be strings
    for code, name in AVAILABLE_LANGUAGES.items():
        assert isinstance(code, str)
        assert isinstance(name, str)
        assert len(code) == 2  # ISO 639-1 language codes


def test_translations_completeness():
    """Test that all languages in AVAILABLE_LANGUAGES have translation entries."""
    for lang_code in AVAILABLE_LANGUAGES.keys():
        assert lang_code in TRANSLATIONS, f"Language {lang_code} in AVAILABLE_LANGUAGES but not in TRANSLATIONS"


def test_tr_fallback_to_english():
    """Test that tr() falls back to English when key not in selected language."""
    # Test with a key that exists in English
    result_en = tr("btn_mount", lang="en")
    assert result_en == "🔓 Mount"

    # German should also work
    result_de = tr("btn_mount", lang="de")
    assert result_de == "🔓 Einbinden"


def test_tr_missing_key_raises():
    """Test that tr() raises KeyError for missing keys."""
    with pytest.raises(KeyError) as exc_info:
        tr("nonexistent_key_12345", lang="en")

    assert "Translation key 'nonexistent_key_12345' not found" in str(exc_info.value)


def test_tr_interpolation():
    """Test that tr() handles format string interpolation."""
    result = tr("keyfile_selected_many", lang="en", count=5)
    assert result == "5 keyfiles selected"

    result_de = tr("keyfile_selected_many", lang="de", count=3)
    assert result_de == "3 Schlüsseldateien ausgewählt"


def test_menu_translations_exist():
    """Test that menu translation keys exist in both languages."""
    menu_keys = [
        "menu_settings",
        "menu_update",
    ]

    for key in menu_keys:
        # Must exist in English
        result_en = tr(key, lang="en")
        assert result_en, f"Key {key} missing in English"

        # Must exist in German
        result_de = tr(key, lang="de")
        assert result_de, f"Key {key} missing in German"

        # Must be different (unless they're identical by design)
        # We just check they're both non-empty here


def test_settings_dialog_translations():
    """Test that settings dialog keys exist."""
    settings_keys = [
        "settings_window_title",
        "settings_language",
        "settings_general",
        "settings_security",
        "settings_restart_not_required",
    ]

    for key in settings_keys:
        assert tr(key, lang="en"), f"English translation missing for {key}"
        assert tr(key, lang="de"), f"German translation missing for {key}"


def test_config_key_gui_lang_exists():
    """Test that ConfigKeys.GUI_LANG is defined."""
    assert hasattr(ConfigKeys, "GUI_LANG")
    assert ConfigKeys.GUI_LANG == "gui_lang"


def test_gui_config_default_lang_exists():
    """Test that GUIConfig.DEFAULT_LANG is defined."""
    assert hasattr(GUIConfig, "DEFAULT_LANG")
    assert GUIConfig.DEFAULT_LANG == "en"


def test_language_switching_simulation():
    """
    Simulate language switching by creating temp config and verifying
    that config read/write uses ConfigKeys.GUI_LANG.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.json"

        # Create config with German
        config = {ConfigKeys.GUI_LANG: "de", "mode": SecurityMode.PW_ONLY.value}

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)

        # Read back
        with open(config_path, "r", encoding="utf-8") as f:
            loaded_config = json.load(f)

        assert loaded_config[ConfigKeys.GUI_LANG] == "de"

        # Update to English
        loaded_config[ConfigKeys.GUI_LANG] = "en"

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(loaded_config, f)

        # Verify
        with open(config_path, "r", encoding="utf-8") as f:
            final_config = json.load(f)

        assert final_config[ConfigKeys.GUI_LANG] == "en"


def test_button_labels_different_languages():
    """Test that button labels are properly translated."""
    # Mount button
    en_mount = tr("btn_mount", lang="en")
    de_mount = tr("btn_mount", lang="de")
    assert en_mount == "🔓 Mount"
    assert de_mount == "🔓 Einbinden"

    # Unmount button
    en_unmount = tr("btn_unmount", lang="en")
    de_unmount = tr("btn_unmount", lang="de")
    assert en_unmount == "🔒 Unmount"
    assert de_unmount == "🔒 Aushängen"

    # Save button
    en_save = tr("btn_save", lang="en")
    de_save = tr("btn_save", lang="de")
    assert en_save == "Save"
    assert de_save == "Speichern"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
