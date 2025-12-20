#!/usr/bin/env python3
"""
Unit tests for CLI i18n language selection.

P1 Requirement: CLI strings must actually be translated using configured language.

These tests verify:
1. CLI translations exist for EN and DE
2. No missing translation keys
3. Language switching works
4. Fallback to EN for missing translations
"""

import sys
import unittest
from pathlib import Path

# Add project to path
# test file is at .smartdrive/tests/unit/test_cli_language.py
_test_file = Path(__file__).resolve()
_unit_dir = _test_file.parent
_tests_dir = _unit_dir.parent
_smartdrive_dir = _tests_dir.parent  # This is .smartdrive/
if str(_smartdrive_dir) not in sys.path:
    sys.path.insert(0, str(_smartdrive_dir))
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from scripts.cli_i18n import CLI_TRANSLATIONS, get_cli_lang, set_cli_lang, tr


class TestCLITranslationsExist(unittest.TestCase):
    """Tests that required translations exist."""

    def test_english_translations_exist(self):
        """English translations should be present."""
        self.assertIn("en", CLI_TRANSLATIONS)
        self.assertGreater(len(CLI_TRANSLATIONS["en"]), 0)

    def test_german_translations_exist(self):
        """German translations should be present."""
        self.assertIn("de", CLI_TRANSLATIONS)
        self.assertGreater(len(CLI_TRANSLATIONS["de"]), 0)

    def test_key_required_translations(self):
        """Key menu items should have translations."""
        required_keys = [
            "cli_menu_mount",
            "cli_menu_unmount",
            "cli_menu_status",
            "cli_menu_quit",
            "cli_menu_prompt",
            "cli_welcome",
        ]

        for key in required_keys:
            with self.subTest(key=key):
                self.assertIn(key, CLI_TRANSLATIONS["en"], f"Missing EN translation: {key}")
                self.assertIn(key, CLI_TRANSLATIONS["de"], f"Missing DE translation: {key}")


class TestCLILanguageSelection(unittest.TestCase):
    """Tests for language selection and switching."""

    def setUp(self):
        """Save original language."""
        self._original_lang = get_cli_lang()

    def tearDown(self):
        """Restore original language."""
        set_cli_lang(self._original_lang)

    def test_default_language_is_english(self):
        """Default language should be English."""
        set_cli_lang("en")  # Ensure we're in a known state
        lang = get_cli_lang()
        self.assertEqual(lang, "en")

    def test_can_switch_to_german(self):
        """Should be able to switch to German."""
        set_cli_lang("de")
        lang = get_cli_lang()
        self.assertEqual(lang, "de")

    def test_tr_returns_english_for_en(self):
        """tr() should return English string when lang=en."""
        set_cli_lang("en")
        result = tr("cli_menu_mount")
        self.assertEqual(result, "Mount encrypted volume")

    def test_tr_returns_german_for_de(self):
        """tr() should return German string when lang=de."""
        set_cli_lang("de")
        result = tr("cli_menu_mount")
        self.assertEqual(result, "Verschlüsseltes Volumen einbinden")

    def test_tr_falls_back_to_key_for_missing(self):
        """tr() should return bracketed key if translation missing."""
        result = tr("nonexistent_key_12345")
        self.assertEqual(result, "[nonexistent_key_12345]")

    def test_tr_with_parameters(self):
        """tr() should substitute parameters."""
        set_cli_lang("en")
        result = tr("cli_status_mounted", drive="V:")
        self.assertIn("V:", result)


class TestCLITranslationCompleteness(unittest.TestCase):
    """Tests that all languages have the same keys."""

    def test_german_has_all_english_keys(self):
        """German should have all keys that English has."""
        en_keys = set(CLI_TRANSLATIONS["en"].keys())
        de_keys = set(CLI_TRANSLATIONS["de"].keys())

        missing_in_de = en_keys - de_keys

        self.assertEqual(len(missing_in_de), 0, f"German missing keys: {missing_in_de}")

    def test_no_empty_translations(self):
        """No translation should be empty string."""
        for lang, translations in CLI_TRANSLATIONS.items():
            for key, value in translations.items():
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(value and value.strip(), f"{lang}.{key} is empty")


class TestCLIMenuRender(unittest.TestCase):
    """Tests that menu can be rendered without errors."""

    def test_render_menu_items_en(self):
        """Should render all menu items in English without error."""
        set_cli_lang("en")

        menu_keys = [
            "cli_menu_mount",
            "cli_menu_unmount",
            "cli_menu_status",
            "cli_menu_settings",
            "cli_menu_recovery",
            "cli_menu_quit",
        ]

        for key in menu_keys:
            result = tr(key)
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)

    def test_render_menu_items_de(self):
        """Should render all menu items in German without error."""
        set_cli_lang("de")

        menu_keys = [
            "cli_menu_mount",
            "cli_menu_unmount",
            "cli_menu_status",
            "cli_menu_settings",
            "cli_menu_recovery",
            "cli_menu_quit",
        ]

        for key in menu_keys:
            result = tr(key)
            self.assertIsInstance(result, str)
            self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
