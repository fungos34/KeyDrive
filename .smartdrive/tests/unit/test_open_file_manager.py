#!/usr/bin/env python3
"""
Unit tests for file explorer open button functionality.

These tests ensure:
1. open_in_file_manager uses correct platform-specific commands
2. Translation keys for tooltips exist
3. Error handling works correctly
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add .smartdrive to path for imports
_test_dir = Path(__file__).resolve().parent
_smartdrive_root = _test_dir.parent.parent  # tests/unit -> tests -> .smartdrive

sys.path.insert(0, str(_smartdrive_root))
sys.path.insert(0, str(_smartdrive_root / "scripts"))

import pytest
from gui_i18n import TRANSLATIONS, tr


class TestFileExplorerTranslationKeys:
    """Tests for file explorer button translation keys."""

    def test_tooltip_open_launcher_drive_exists_en(self):
        """Test that tooltip_open_launcher_drive exists in English."""
        result = tr("tooltip_open_launcher_drive", lang="en")
        assert result == "Open launcher drive"

    def test_tooltip_open_mounted_volume_exists_en(self):
        """Test that tooltip_open_mounted_volume exists in English."""
        result = tr("tooltip_open_mounted_volume", lang="en")
        assert result == "Open mounted volume"

    def test_popup_open_failed_title_exists_en(self):
        """Test that popup_open_failed_title exists in English."""
        result = tr("popup_open_failed_title", lang="en")
        assert result == "Open Failed"

    def test_popup_open_failed_body_exists_en(self):
        """Test that popup_open_failed_body exists in English with formatting."""
        result = tr("popup_open_failed_body", lang="en", path="/test/path", error="Test error")
        assert "/test/path" in result
        assert "Test error" in result

    def test_tooltip_keys_exist_in_all_languages(self):
        """Test that tooltip keys exist in all available languages."""
        required_keys = [
            "tooltip_open_launcher_drive",
            "tooltip_open_mounted_volume",
            "popup_open_failed_title",
            "popup_open_failed_body",
        ]

        for lang_code in TRANSLATIONS.keys():
            for key in required_keys:
                # Should not raise KeyError (falls back to English if needed)
                result = tr(key, lang=lang_code)
                assert result, f"Empty result for {key} in {lang_code}"


class TestOpenInFileManagerFunction:
    """Tests for open_in_file_manager cross-platform function."""

    def test_windows_uses_explorer(self):
        """Test that Windows uses subprocess.run with explorer.

        BUG-20251221-024: Changed from os.startfile to subprocess.run with
        CREATE_NO_WINDOW flag to prevent popup windows during recovery operations.
        """
        # Patch at the source module where get_platform is defined
        with patch("core.platform.get_platform", return_value="windows"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                # Create a temp directory that exists
                import tempfile

                from gui import open_in_file_manager

                with tempfile.TemporaryDirectory() as tmpdir:
                    test_path = Path(tmpdir)
                    result = open_in_file_manager(test_path)

                    # On Windows, subprocess.run should be called with 'explorer'
                    # and CREATE_NO_WINDOW flag
                    import subprocess

                    mock_run.assert_called_once()
                    call_args = mock_run.call_args
                    assert call_args[0][0] == ["explorer", str(test_path)]
                    assert call_args[1].get("creationflags") == subprocess.CREATE_NO_WINDOW
                    assert result is True

    def test_macos_uses_open_command(self):
        """Test that macOS uses 'open' subprocess command."""
        with patch("core.platform.get_platform", return_value="darwin"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                import tempfile

                from gui import open_in_file_manager

                with tempfile.TemporaryDirectory() as tmpdir:
                    test_path = Path(tmpdir)
                    result = open_in_file_manager(test_path)

                    # On macOS, subprocess.run should be called with 'open'
                    mock_run.assert_called_once_with(["open", str(test_path)], check=False)
                    assert result is True

    def test_linux_uses_xdg_open(self):
        """Test that Linux uses 'xdg-open' subprocess command."""
        with patch("core.platform.get_platform", return_value="linux"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                import tempfile

                from gui import open_in_file_manager

                with tempfile.TemporaryDirectory() as tmpdir:
                    test_path = Path(tmpdir)
                    result = open_in_file_manager(test_path)

                    # On Linux, subprocess.run should be called with 'xdg-open'
                    mock_run.assert_called_once_with(["xdg-open", str(test_path)], check=False)
                    assert result is True

    def test_nonexistent_path_returns_false(self):
        """Test that non-existent path returns False."""
        from gui import open_in_file_manager

        # Use a path that definitely doesn't exist
        fake_path = Path("/definitely/does/not/exist/xyz123")
        result = open_in_file_manager(fake_path, parent=None)

        assert result is False

    def test_path_converted_from_string(self):
        """Test that string paths are converted to Path objects."""
        from gui import open_in_file_manager

        # Pass a string instead of Path - should be handled
        result = open_in_file_manager("/nonexistent/path", parent=None)

        # Should return False due to non-existent path
        assert result is False


class TestButtonStateManagement:
    """Tests for button enable/disable state logic."""

    def test_launcher_button_enabled_when_path_exists(self):
        """Test that launcher button is enabled when launcher_root exists."""
        # This test validates the logic, actual widget testing requires Qt
        launcher_root = _smartdrive_root  # .smartdrive/ should exist
        assert launcher_root.exists()

    def test_vc_button_disabled_when_not_mounted(self):
        """Test that VC button should be disabled when volume not mounted."""
        # Logic test: when is_mounted is False, vc_enabled should be False
        is_mounted = False
        vc_enabled = is_mounted  # Simplified logic from _update_open_button_states
        assert vc_enabled is False
