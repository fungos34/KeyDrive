"""
Unit tests for HTML browser opening (BUG-20251223-004).

Tests verify that open_html_in_browser() correctly handles:
- Windows: Uses webbrowser.open(path.as_uri()) for proper URI encoding
- macOS: Uses 'open' command
- Linux: Uses 'xdg-open' command
- Error handling: Graceful failure with proper logging
- Path validation: File must exist and be a file

BUG-20251223-004: Windows "Syntaxfehler in der Kommandozeile" dialog when using
cmd /c start or os.startfile() for HTML recovery kit display.
Solution: Use webbrowser.open() with Path.as_uri() which properly encodes the
file path and uses ShellExecute internally without cmd.exe involvement.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


class TestOpenHtmlInBrowser:
    """Tests for open_html_in_browser() cross-platform HTML opening."""

    @pytest.fixture
    def mock_html_path(self, tmp_path):
        """Create a temporary HTML file for testing."""
        html_file = tmp_path / "test_recovery.html"
        html_file.write_text("<html><body>Test</body></html>", encoding="utf-8")
        return html_file

    @pytest.fixture
    def mock_html_path_special_chars(self, tmp_path):
        """Create a temporary HTML file in a directory with special characters."""
        # BUG-20251223-004: Test paths with characters that break cmd.exe
        special_dir = tmp_path / "test & dir (with) special^chars"
        special_dir.mkdir(parents=True, exist_ok=True)
        html_file = special_dir / "recovery_kit.html"
        html_file.write_text("<html><body>Test</body></html>", encoding="utf-8")
        return html_file

    def test_open_html_windows_uses_webbrowser(self, mock_html_path):
        """
        BUG-20251223-004 FIX: Verify Windows uses webbrowser.open() with file URI.

        webbrowser.open() with Path.as_uri() properly encodes the path and
        uses ShellExecute internally without cmd.exe involvement.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="Windows"):
            with patch("webbrowser.open") as mock_open:
                result = open_html_in_browser(mock_html_path)

                # Verify webbrowser.open was called with file URI
                mock_open.assert_called_once()
                call_arg = mock_open.call_args[0][0]
                assert call_arg.startswith("file:///")
                assert result is True

    def test_open_html_windows_no_cmd_exe(self, mock_html_path):
        """
        BUG-20251223-004 FIX: Verify Windows does NOT call cmd.exe or subprocess.

        The new implementation uses webbrowser.open() which internally uses
        ShellExecute, avoiding all cmd.exe involvement.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="Windows"):
            with patch("webbrowser.open") as mock_open:
                with patch("subprocess.run") as mock_run:
                    result = open_html_in_browser(mock_html_path)

                    # subprocess.run should NOT be called on Windows
                    mock_run.assert_not_called()
                    # webbrowser.open should be called
                    mock_open.assert_called_once()
                    assert result is True

    def test_open_html_windows_special_characters(self, mock_html_path_special_chars):
        """
        BUG-20251223-004 FIX: Verify paths with special characters work on Windows.

        Characters like &, (, ), ^, %, ! break cmd.exe parsing but work with
        webbrowser.open() using proper URI encoding.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="Windows"):
            with patch("webbrowser.open") as mock_open:
                result = open_html_in_browser(mock_html_path_special_chars)

                # Should handle special characters without error
                mock_open.assert_called_once()
                call_arg = mock_open.call_args[0][0]
                # URI should be properly encoded
                assert call_arg.startswith("file:///")
                assert result is True

    def test_open_html_windows_uri_format(self, mock_html_path):
        """
        BUG-20251223-004 FIX: Verify file URI format is correct.

        Path.as_uri() should produce file:///C:/path/to/file.html format
        with forward slashes and proper encoding.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="Windows"):
            with patch("webbrowser.open") as mock_open:
                result = open_html_in_browser(mock_html_path)

                call_arg = mock_open.call_args[0][0]
                # Should be valid file URI
                assert call_arg.startswith("file:///")
                # Should NOT contain backslashes
                assert "\\" not in call_arg
                assert result is True

    def test_open_html_macos(self, mock_html_path):
        """Verify macOS uses 'open' command."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="darwin"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = None

                result = open_html_in_browser(mock_html_path)

                mock_run.assert_called_once()
                actual_cmd = mock_run.call_args[0][0]
                assert actual_cmd[0] == "open"
                assert str(mock_html_path) in actual_cmd[-1]
                assert result is True

    def test_open_html_linux(self, mock_html_path):
        """Verify Linux uses 'xdg-open' command."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="linux"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = None

                result = open_html_in_browser(mock_html_path)

                mock_run.assert_called_once()
                actual_cmd = mock_run.call_args[0][0]
                assert actual_cmd[0] == "xdg-open"
                assert str(mock_html_path) in actual_cmd[-1]
                assert result is True

    def test_open_html_nonexistent_file(self, tmp_path):
        """Verify graceful handling of nonexistent files."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        nonexistent = tmp_path / "does_not_exist.html"

        result = open_html_in_browser(nonexistent)

        # Should return False for nonexistent file
        assert result is False

    def test_open_html_directory_not_file(self, tmp_path):
        """Verify graceful handling when path is a directory, not a file."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        result = open_html_in_browser(tmp_path)

        # Should return False for directory
        assert result is False

    def test_open_html_error_handling(self, mock_html_path):
        """
        Verify graceful failure with logging when browser cannot open.

        Ensures errors don't crash the application.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="linux"):
            with patch("subprocess.run", side_effect=Exception("Browser not found")):
                # Should not raise exception
                result = open_html_in_browser(mock_html_path)

                # Should return False on error
                assert result is False

    def test_open_html_windows_webbrowser_error(self, mock_html_path):
        """
        Verify graceful handling of webbrowser.open() errors on Windows.

        webbrowser.open() can fail if no browser is configured.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="Windows"):
            with patch("webbrowser.open", side_effect=Exception("No browser configured")):
                result = open_html_in_browser(mock_html_path)

                # Should return False on error
                assert result is False

    def test_open_html_macos_no_creationflags(self, mock_html_path):
        """Verify macOS calls don't include Windows-specific creationflags."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="darwin"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = None

                result = open_html_in_browser(mock_html_path)

                call_kwargs = mock_run.call_args[1]
                assert "creationflags" not in call_kwargs
                assert result is True

    def test_open_html_timeout_parameter(self, mock_html_path):
        """Verify timeout is set to prevent hanging on unresponsive systems."""
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="linux"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = None

                open_html_in_browser(mock_html_path)

                call_kwargs = mock_run.call_args[1]
                assert call_kwargs["timeout"] == 5
                assert call_kwargs["check"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
