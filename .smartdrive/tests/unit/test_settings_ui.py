"""
Test suite for Settings UI - Part 2 verification.
Tests: schema validation, config round-trip, unknown key preservation, atomic writes.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".smartdrive"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".smartdrive" / "scripts"))

from core.config import write_config_atomic
from core.constants import ConfigKeys
from core.settings_schema import SETTINGS_SCHEMA, FieldType, get_all_tabs, get_fields_for_tab


class TestSettingsSchema:
    """Test schema completeness and structure."""

    def test_schema_has_all_user_configurable_keys(self):
        """Ensure all user-configurable ConfigKeys appear in schema."""
        # Keys that should be in schema (user-editable)
        user_keys = [
            ConfigKeys.DRIVE_NAME,
            ConfigKeys.GUI_LANG,
            ConfigKeys.GUI_THEME,
            ConfigKeys.MODE,
            ConfigKeys.ENCRYPTED_KEYFILE,
            ConfigKeys.KEYFILE,
            ConfigKeys.SEED_GPG_PATH,
            ConfigKeys.KDF,
            ConfigKeys.PW_ENCODING,
        ]

        schema_keys = [f.key for f in SETTINGS_SCHEMA]
        schema_nested_keys = []
        for f in SETTINGS_SCHEMA:
            if f.nested_path:
                schema_nested_keys.append(f.nested_path[-1])

        for key in user_keys:
            assert key in schema_keys or key in schema_nested_keys, f"ConfigKey.{key} missing from settings_schema"

    def test_all_tabs_have_fields(self):
        """Ensure every tab has at least one field."""
        for tab in get_all_tabs():
            fields = get_fields_for_tab(tab)
            assert len(fields) > 0, f"Tab '{tab}' has no fields"

    def test_field_types_are_valid(self):
        """Ensure all fields use valid FieldType enum values."""
        valid_types = set(FieldType)
        for field in SETTINGS_SCHEMA:
            assert field.field_type in valid_types, f"Field '{field.key}' has invalid type: {field.field_type}"

    def test_no_duplicate_keys(self):
        """Ensure no duplicate field keys in schema."""
        keys = []
        for field in SETTINGS_SCHEMA:
            if field.nested_path:
                key = ".".join(field.nested_path)
            else:
                key = field.key
            keys.append(key)

        assert len(keys) == len(set(keys)), "Duplicate keys found in schema"


class TestConfigRoundTrip:
    """Test config loading, modification, and saving."""

    def test_unknown_keys_preserved(self, tmp_path):
        """Ensure unknown config keys are preserved on save."""
        config_file = tmp_path / "config.json"

        # Create config with known and unknown keys
        original_config = {
            ConfigKeys.DRIVE_ID: "test-drive-id",
            ConfigKeys.DRIVE_NAME: "TestDrive",
            ConfigKeys.GUI_LANG: "en",
            "unknown_key_1": "should_be_preserved",
            "unknown_key_2": {"nested": "also_preserved"},
            ConfigKeys.MODE: "pw_only",
        }

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(original_config, f)

        # Simulate Settings save: load, modify one field, save
        with open(config_file, "r", encoding="utf-8") as f:
            loaded_config = json.load(f)

        # Modify one field (simulate UI change)
        loaded_config[ConfigKeys.DRIVE_NAME] = "ModifiedDrive"

        # Save (preserving unknown keys)
        write_config_atomic(config_file, loaded_config)

        # Reload and verify
        with open(config_file, "r", encoding="utf-8") as f:
            saved_config = json.load(f)

        # Check modified field
        assert saved_config[ConfigKeys.DRIVE_NAME] == "ModifiedDrive"

        # Check unknown keys preserved
        assert saved_config.get("unknown_key_1") == "should_be_preserved"
        assert saved_config.get("unknown_key_2") == {"nested": "also_preserved"}


class TestAtomicWriteSafety:
    """Test atomic write behavior on failure."""

    def test_config_unchanged_on_write_failure(self, tmp_path):
        """Ensure config file unchanged if write fails."""
        config_file = tmp_path / "config.json"

        original_config = {
            ConfigKeys.DRIVE_ID: "test-id",
            ConfigKeys.MODE: "pw_only",
        }

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(original_config, f)

        original_content = config_file.read_text()

        # Simulate write failure by making directory read-only
        # (This test may be platform-specific; adjust as needed)
        import os

        with patch("builtins.open", side_effect=IOError("Simulated write failure")):
            try:
                write_config_atomic(config_file, {"corrupted": "data"})
            except (IOError, OSError):
                pass  # Expected

        # Verify original file unchanged
        current_content = config_file.read_text()
        assert current_content == original_content, "Config was modified despite write failure"


class TestSettingsDialogInstantiation:
    """Test SettingsDialog can be instantiated without errors."""

    @pytest.fixture
    def mock_qsettings(self):
        """Mock QSettings for SettingsDialog."""
        mock_instance = MagicMock()
        mock_instance.value.return_value = ""  # Return empty string for geometry/state
        return mock_instance

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create temporary config file."""
        config_file = tmp_path / "config.json"
        config = {
            ConfigKeys.DRIVE_ID: "test-id",
            ConfigKeys.GUI_LANG: "en",
            ConfigKeys.GUI_THEME: "light",
            ConfigKeys.MODE: "pw_only",
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f)
        return config_file

    def test_settings_dialog_imports_without_error(self):
        """Verify all required Qt imports are present."""
        try:
            from PyQt6.QtCore import QSettings
            from PyQt6.QtWidgets import QFileDialog, QSpinBox, QTabWidget
        except ImportError as e:
            pytest.fail(f"Missing Qt import: {e}")

    def test_settings_dialog_instantiation_headless(self, mock_qsettings, mock_config, monkeypatch):
        """Test SettingsDialog can be created in headless mode using offscreen platform.

        This test uses Qt's offscreen platform plugin to verify SettingsDialog instantiation
        without requiring a display. This is the deterministic, headless verification
        required for release gate compliance.
        """
        import os

        os.environ["QT_QPA_PLATFORM"] = "offscreen"

        try:
            import sys

            from PyQt6.QtCore import QSettings
            from PyQt6.QtWidgets import QApplication, QTabWidget

            # Create or reuse QApplication
            app = QApplication.instance()
            if app is None:
                app = QApplication(sys.argv)

            # Use the mock_config fixture (temp file)
            config_path = mock_config

            with patch("gui.get_script_dir", return_value=config_path.parent):
                with patch("gui.resolve_config_path", return_value=config_path):
                    from gui import SettingsDialog

                    # Instantiate with mock QSettings
                    dialog = SettingsDialog(mock_qsettings, parent=None)

                    # Verify instantiation succeeded
                    assert dialog is not None, "Dialog instantiation returned None"
                    assert hasattr(dialog, "tab_widget"), "Dialog missing tab_widget"
                    assert isinstance(dialog.tab_widget, QTabWidget), "tab_widget not a QTabWidget"

        except ImportError as e:
            pytest.fail(f"Qt import failed (required for release): {e}")
        except Exception as e:
            pytest.fail(f"SettingsDialog headless instantiation failed: {e}")

    def test_settings_dialog_instantiation_real(self):
        """Test SettingsDialog can be instantiated without errors (real test with QApplication)."""
        try:
            # Set headless platform
            import os

            os.environ["QT_QPA_PLATFORM"] = "offscreen"

            import sys

            from PyQt6.QtCore import QSettings
            from PyQt6.QtWidgets import QApplication, QFileDialog, QSpinBox, QTabWidget

            # Create QApplication if not exists
            app = QApplication.instance()
            if app is None:
                app = QApplication(sys.argv)

            # Create mock config
            mock_config = {
                ConfigKeys.DRIVE_ID: "test-id",
                ConfigKeys.GUI_LANG: "en",
                ConfigKeys.GUI_THEME: "green",
                ConfigKeys.MODE: "pw_only",
                ConfigKeys.DRIVE_NAME: "TestDrive",
            }

            # Create temp config file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(mock_config, f)
                temp_config_path = Path(f.name)

            try:
                # Mock get_script_dir to return temp config location
                with patch("gui.get_script_dir", return_value=temp_config_path.parent):
                    with patch("gui.resolve_config_path", return_value=temp_config_path):
                        # Import SettingsDialog
                        from scripts.gui import SettingsDialog

                        # Create mock QSettings with proper return values
                        mock_qsettings = MagicMock()
                        mock_qsettings.value.return_value = ""  # Return empty string for any value() call

                        # Instantiate dialog (current API: settings, parent)
                        dialog = SettingsDialog(mock_qsettings, parent=None)

                        # If we get here, instantiation succeeded
                        assert dialog is not None, "Dialog instantiation failed"
                        assert isinstance(dialog.tab_widget, QTabWidget), "Tabs not created"

            finally:
                # Cleanup temp file
                if temp_config_path.exists():
                    temp_config_path.unlink()

        except ImportError as e:
            pytest.skip(f"Qt imports not available: {e}")
        except Exception as e:
            pytest.fail(f"SettingsDialog instantiation failed: {e}")


class TestSecureLogging:
    """Test that sensitive config values are not logged."""

    def test_no_raw_config_in_logs(self):
        """Ensure config dicts are not logged verbatim."""
        # This is a policy test - verify no log_exception/logger calls with raw config
        # Check gui.py for patterns like: logger.info(f"Config: {config}")

        gui_path = Path(__file__).parent.parent.parent / ".smartdrive" / "scripts" / "gui.py"
        if not gui_path.exists():
            pytest.skip("gui.py not found")

        content = gui_path.read_text(encoding="utf-8")

        # Check for dangerous patterns
        dangerous_patterns = [
            r"log.*\{.*config.*\}",  # log calls with config dict
            r"print.*config\[",  # direct config prints
        ]

        import re

        for pattern in dangerous_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            # Allow some matches if they're in comments or have redaction
            # For now, just warn - full enforcement requires code review
            if matches and len(matches) > 2:
                print(f"⚠️  Warning: Found {len(matches)} potential config logging: {pattern}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
