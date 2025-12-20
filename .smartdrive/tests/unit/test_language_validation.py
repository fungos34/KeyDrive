#!/usr/bin/env python3
"""
Unit tests for language system validation.

Tests:
- All languages have complete translation keys
- New languages (bs, es, fr, zh) exist
- Translation key consistency across languages
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Add scripts to path
scripts_dir = project_root / ".smartdrive" / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from gui_i18n import AVAILABLE_LANGUAGES, TRANSLATIONS


def test_seven_languages_available():
    """Test that exactly 7 languages are available."""
    expected_langs = {"en", "de", "bs", "es", "fr", "ru", "zh"}
    actual_langs = set(AVAILABLE_LANGUAGES.keys())

    assert actual_langs == expected_langs, f"Expected languages {expected_langs}, got {actual_langs}"


def test_new_languages_added():
    """Test that the 5 additional languages were added correctly."""
    new_langs = {"bs", "es", "fr", "ru", "zh"}

    for lang in new_langs:
        assert lang in AVAILABLE_LANGUAGES, f"Language '{lang}' should be in AVAILABLE_LANGUAGES"
        assert lang in TRANSLATIONS, f"Language '{lang}' should be in TRANSLATIONS"


def test_english_is_reference():
    """Test that English translations exist (used as reference)."""
    assert "en" in TRANSLATIONS, "English translations must exist"
    assert len(TRANSLATIONS["en"]) > 0, "English translations should not be empty"


def test_all_languages_have_same_keys():
    """Test that all languages have the same translation keys as English."""
    english_keys = set(TRANSLATIONS["en"].keys())

    for lang_code in TRANSLATIONS:
        if lang_code == "en":
            continue

        lang_keys = set(TRANSLATIONS[lang_code].keys())
        missing_keys = english_keys - lang_keys
        extra_keys = lang_keys - english_keys

        assert not missing_keys, f"Language '{lang_code}' is missing keys: {missing_keys}"
        assert not extra_keys, f"Language '{lang_code}' has unexpected keys: {extra_keys}"


def test_error_message_keys_exist():
    """Test that error message translation keys exist."""
    required_error_keys = {
        "error_update_server_url_not_configured",
        "error_update_local_root_not_configured",
        "error_update_local_root_not_found",
        "error_update_install_dir_not_found",
        "error_update_unknown_source_type",
        "error_hardware_key_missing_title",
        "error_hardware_key_missing_body",
    }

    english_keys = set(TRANSLATIONS["en"].keys())
    missing_keys = required_error_keys - english_keys

    assert not missing_keys, f"Missing error translation keys: {missing_keys}"


def test_theme_translation_keys_exist():
    """Test that theme translation keys exist."""
    required_theme_keys = {
        "theme_brand",
        "theme_green",
        "theme_blue",
        "theme_rose",
        "theme_slate",
        "label_theme",
    }

    english_keys = set(TRANSLATIONS["en"].keys())
    missing_keys = required_theme_keys - english_keys

    assert not missing_keys, f"Missing theme translation keys: {missing_keys}"


def test_parametrized_translations_have_placeholders():
    """Test that parametrized translation strings contain their placeholders."""
    parametrized_keys = {
        "error_update_local_root_not_found": ["{path}"],
        "error_update_install_dir_not_found": ["{path}"],
        "error_update_unknown_source_type": ["{type}"],
        "keyfile_selected_many": ["{count}"],
        "size_free": ["{size}"],
    }

    for key, placeholders in parametrized_keys.items():
        if key in TRANSLATIONS["en"]:
            translation = TRANSLATIONS["en"][key]
            for placeholder in placeholders:
                assert placeholder in translation, f"Translation key '{key}' should contain placeholder '{placeholder}'"


def test_translations_are_strings():
    """Test that all translation values are strings."""
    for lang_code, translations in TRANSLATIONS.items():
        for key, value in translations.items():
            assert isinstance(value, str), f"Translation '{lang_code}.{key}' should be a string, got {type(value)}"


def test_available_languages_display_names():
    """Test that AVAILABLE_LANGUAGES has display names for all languages."""
    for lang_code in TRANSLATIONS.keys():
        assert lang_code in AVAILABLE_LANGUAGES, f"Language code '{lang_code}' should be in AVAILABLE_LANGUAGES"

        display_name = AVAILABLE_LANGUAGES[lang_code]
        assert isinstance(display_name, str), f"Display name for '{lang_code}' should be a string"
        assert len(display_name) > 0, f"Display name for '{lang_code}' should not be empty"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
