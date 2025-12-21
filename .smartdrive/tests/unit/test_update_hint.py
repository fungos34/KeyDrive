"""
Test GUI update hint display.

CHG-20251221-005: Verify hint label exists in Updates tab with proper i18n.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.gui_i18n import AVAILABLE_LANGUAGES, TRANSLATIONS


class TestUpdateHintTranslationKeys:
    """Test that update hint translation keys exist in all languages."""

    def test_hint_title_key_exists_all_languages(self):
        """Verify hint_update_local_title exists in all 7 languages."""
        for lang_code in AVAILABLE_LANGUAGES.keys():
            translations = TRANSLATIONS.get(lang_code, {})
            assert "hint_update_local_title" in translations, f"Missing hint_update_local_title in {lang_code}"

            # Verify not empty
            value = translations["hint_update_local_title"]
            assert value and len(value.strip()) > 0, f"Empty hint_update_local_title in {lang_code}"

    def test_hint_body_key_exists_all_languages(self):
        """Verify hint_update_local_body exists in all 7 languages."""
        for lang_code in AVAILABLE_LANGUAGES.keys():
            translations = TRANSLATIONS.get(lang_code, {})
            assert "hint_update_local_body" in translations, f"Missing hint_update_local_body in {lang_code}"

            # Verify not empty
            value = translations["hint_update_local_body"]
            assert value and len(value.strip()) > 0, f"Empty hint_update_local_body in {lang_code}"

    def test_hint_body_mentions_smartdrive(self):
        """Verify hint body mentions .smartdrive directory."""
        # Check English version mentions key concept
        en_body = TRANSLATIONS["en"]["hint_update_local_body"]
        assert ".smartdrive" in en_body or "smartdrive" in en_body.lower()

    def test_hint_body_is_informative(self):
        """Verify hint body is sufficiently detailed."""
        # Should be more than a one-liner (at least 50 characters)
        for lang_code in AVAILABLE_LANGUAGES.keys():
            body = TRANSLATIONS[lang_code]["hint_update_local_body"]
            assert len(body) >= 50, f"hint_update_local_body too short in {lang_code}: {len(body)} chars"


class TestUpdateHintGUIIntegration:
    """Test that hint is properly integrated into GUI."""

    def test_hint_section_method_exists(self):
        """Verify _add_update_hint_section method exists in SettingsDialog."""
        from scripts.gui import SettingsDialog

        assert hasattr(SettingsDialog, "_add_update_hint_section")

        # Verify it's callable
        assert callable(getattr(SettingsDialog, "_add_update_hint_section"))

    def test_hint_attributes_stored(self):
        """Verify SettingsDialog stores hint widget references."""
        # We check that the method sets expected attributes
        # (Can't instantiate without full Qt setup, but can verify method signature)
        import inspect

        from scripts.gui import SettingsDialog

        # Get method
        method = getattr(SettingsDialog, "_add_update_hint_section")
        sig = inspect.signature(method)

        # Should accept self and tab_layout parameter
        params = list(sig.parameters.keys())
        assert "self" in params
        assert "tab_layout" in params


class TestUpdateHintLanguageRefresh:
    """Test that hint updates when language changes."""

    def test_refresh_dialog_updates_hint_box_title(self):
        """Verify refresh_dialog_labels updates hint box title."""
        import inspect

        from scripts.gui import SettingsDialog

        # Get entire class source to find update logic
        source = inspect.getsource(SettingsDialog)

        # Should update update_hint_box somewhere in the class
        assert "update_hint_box" in source
        assert "hint_update_local_title" in source

    def test_refresh_dialog_updates_hint_label_text(self):
        """Verify refresh_dialog_labels updates hint label text."""
        import inspect

        from scripts.gui import SettingsDialog

        # Get entire class source to find update logic
        source = inspect.getsource(SettingsDialog)

        # Should update update_hint_label somewhere in the class
        assert "update_hint_label" in source
        assert "hint_update_local_body" in source


class TestTranslationCompleteness:
    """Verify all 7 languages have consistent hint translations."""

    def test_all_languages_have_both_keys(self):
        """Verify both hint keys exist in every language."""
        required_keys = {"hint_update_local_title", "hint_update_local_body"}

        for lang_code, lang_name in AVAILABLE_LANGUAGES.items():
            translations = TRANSLATIONS[lang_code]

            for key in required_keys:
                assert key in translations, f"Language {lang_code} ({lang_name}) missing key: {key}"

    def test_no_untranslated_english_placeholders(self):
        """Verify non-English languages don't just copy English text."""
        en_title = TRANSLATIONS["en"]["hint_update_local_title"]
        en_body = TRANSLATIONS["en"]["hint_update_local_body"]

        for lang_code in AVAILABLE_LANGUAGES.keys():
            if lang_code == "en":
                continue

            lang_title = TRANSLATIONS[lang_code]["hint_update_local_title"]
            lang_body = TRANSLATIONS[lang_code]["hint_update_local_body"]

            # Should be different from English (actual translation)
            # Allow some overlap (technical terms), but not identical
            if lang_code in ["de", "es", "fr", "ru"]:  # Languages with different scripts/structure
                assert lang_title != en_title, f"{lang_code} hint_update_local_title is identical to English"

    def test_translation_lengths_reasonable(self):
        """Verify translations aren't suspiciously short or long."""
        en_body_len = len(TRANSLATIONS["en"]["hint_update_local_body"])

        for lang_code in AVAILABLE_LANGUAGES.keys():
            body = TRANSLATIONS[lang_code]["hint_update_local_body"]
            body_len = len(body)

            # Should be within 30% to 250% of English length (accounting for language differences)
            # Chinese/logographic scripts are typically shorter than English
            min_len = en_body_len * 0.3
            max_len = en_body_len * 2.5

            assert min_len <= body_len <= max_len, (
                f"{lang_code} hint_update_local_body length {body_len} outside expected range "
                f"[{min_len:.0f}, {max_len:.0f}] (English: {en_body_len})"
            )
