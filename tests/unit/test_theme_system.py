#!/usr/bin/env python3
"""
Unit tests for theme system functionality.

Tests:
- Theme palette structure validation
- Theme switching mechanism
- ConfigKeys.GUI_THEME existence
"""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Add .smartdrive to path for core imports
smartdrive_root = project_root / ".smartdrive"
if str(smartdrive_root) not in sys.path:
    sys.path.insert(0, str(smartdrive_root))


def test_theme_palettes_exist():
    """Test that THEME_PALETTES is defined in core.constants."""
    from core.constants import THEME_PALETTES

    assert THEME_PALETTES is not None, "THEME_PALETTES should be defined"
    assert isinstance(THEME_PALETTES, dict), "THEME_PALETTES should be a dictionary"


def test_theme_palette_structure():
    """Test that each theme has all required color keys."""
    from core.constants import THEME_PALETTES

    required_keys = {
        "primary",
        "primary_hover",
        "success",
        "error",
        "warning",
        "background",
        "surface",
        "border",
        "text",
        "text_secondary",
        "text_disabled",
    }

    for theme_id, palette in THEME_PALETTES.items():
        assert isinstance(palette, dict), f"Theme '{theme_id}' palette should be a dictionary"

        palette_keys = set(palette.keys())
        missing_keys = required_keys - palette_keys
        extra_keys = palette_keys - required_keys

        assert not missing_keys, f"Theme '{theme_id}' is missing keys: {missing_keys}"
        # Allow extra keys but warn if unexpected
        if extra_keys:
            print(f"Note: Theme '{theme_id}' has extra keys: {extra_keys}")


def test_default_themes_exist():
    """Test that the 4 default themes are present."""
    from core.constants import THEME_PALETTES

    expected_themes = {"green", "blue", "rose", "slate"}
    actual_themes = set(THEME_PALETTES.keys())

    missing_themes = expected_themes - actual_themes
    assert not missing_themes, f"Missing expected themes: {missing_themes}"


def test_gui_theme_config_key_exists():
    """Test that ConfigKeys.GUI_THEME is defined."""
    from core.constants import ConfigKeys

    assert hasattr(ConfigKeys, "GUI_THEME"), "ConfigKeys should have GUI_THEME attribute"
    assert ConfigKeys.GUI_THEME == "gui_theme", "GUI_THEME should equal 'gui_theme'"


def test_default_theme_defined():
    """Test that GUIConfig.DEFAULT_THEME is defined."""
    from core.constants import GUIConfig

    assert hasattr(GUIConfig, "DEFAULT_THEME"), "GUIConfig should have DEFAULT_THEME attribute"
    assert GUIConfig.DEFAULT_THEME in [
        "green",
        "blue",
        "rose",
        "slate",
    ], f"DEFAULT_THEME '{GUIConfig.DEFAULT_THEME}' should be one of the valid themes"


def test_color_values_are_hex():
    """Test that all color values are valid hex color strings."""
    import re

    from core.constants import THEME_PALETTES

    hex_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")

    for theme_id, palette in THEME_PALETTES.items():
        for color_key, color_value in palette.items():
            assert isinstance(color_value, str), f"Theme '{theme_id}' color '{color_key}' should be a string"
            assert hex_pattern.match(
                color_value
            ), f"Theme '{theme_id}' color '{color_key}' value '{color_value}' is not a valid hex color"


def test_theme_translation_keys_exist():
    """Test that theme names have translation keys."""
    import sys
    from pathlib import Path

    from core.constants import THEME_PALETTES

    # Import gui_i18n
    scripts_dir = project_root / ".smartdrive" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from gui_i18n import TRANSLATIONS

    for theme_id in THEME_PALETTES.keys():
        theme_key = f"theme_{theme_id}"
        assert theme_key in TRANSLATIONS["en"], f"Translation key '{theme_key}' should exist in English translations"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
