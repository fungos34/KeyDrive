"""
Unit tests for HTML browser opening (BUG-20251221-001).

Tests verify that open_html_in_browser() correctly handles:
- Windows: Uses 'cmd /c start' with CREATE_NO_WINDOW flag to prevent popups
- macOS: Uses 'open' command
- Linux: Uses 'xdg-open' command
- Error handling: Graceful failure with proper logging

BUG-20251221-001: Windows "syntax error in command line" popup when using
webbrowser.open() for HTML recovery kit display.
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

    @pytest.mark.parametrize(
        "platform_name,expected_cmd",
        [
            ("windows", ["cmd", "/c", "start", "", "test.html"]),
            ("darwin", ["open", "test.html"]),
            ("linux", ["xdg-open", "test.html"]),
        ],
    )
    def test_open_html_crossplatform(self, platform_name, expected_cmd):
        """
        Verify correct command is used per platform.

        BUG-20251221-001: Ensures each OS uses its appropriate browser opener.
        """
        # Import recovery module to get open_html_in_browser
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        test_path = Path("test.html")

        with patch("platform.system", return_value=platform_name):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = None  # Simulate successful run

                result = open_html_in_browser(test_path)

                # Verify subprocess.run was called with correct command
                assert mock_run.called
                actual_call = mock_run.call_args
                actual_cmd = actual_call[0][0]  # First positional arg is the command list

                # Verify command structure (normalize path for Windows)
                assert actual_cmd[: len(expected_cmd) - 1] == expected_cmd[:-1]
                assert str(test_path) in actual_cmd[-1] or "test.html" in actual_cmd[-1]

                # Verify timeout parameter
                assert actual_call[1].get("timeout") == 5
                assert actual_call[1].get("check") is False

                # Verify result
                assert result is True

    def test_open_html_windows_no_popup(self, mock_html_path):
        """
        Mock subprocess.run and verify CREATE_NO_WINDOW flag is set on Windows.

        BUG-20251221-001: This is the critical fix - CREATE_NO_WINDOW prevents
        the "syntax error in command line" popup on Windows.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="Windows"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = None

                result = open_html_in_browser(mock_html_path)

                # Verify subprocess.run was called
                assert mock_run.called
                call_kwargs = mock_run.call_args[1]

                # CRITICAL: Verify CREATE_NO_WINDOW flag is set
                assert "creationflags" in call_kwargs
                assert call_kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW

                # Verify command structure includes empty string for window title
                actual_cmd = mock_run.call_args[0][0]
                assert actual_cmd[0] == "cmd"
                assert actual_cmd[1] == "/c"
                assert actual_cmd[2] == "start"
                assert actual_cmd[3] == ""  # Empty window title required for 'start'

                assert result is True

    def test_open_html_error_handling(self, mock_html_path):
        """
        Verify graceful failure with logging when browser cannot open.

        BUG-20251221-001: Ensures errors don't crash the application and
        user gets helpful feedback.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="linux"):
            with patch("subprocess.run", side_effect=Exception("Browser not found")):
                # Should not raise exception
                result = open_html_in_browser(mock_html_path)

                # Should return False on error
                assert result is False

    def test_open_html_macos_no_creationflags(self, mock_html_path):
        """
        Verify macOS/Linux calls don't include Windows-specific creationflags.

        This ensures cross-platform compatibility.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        for platform_name in ["darwin", "linux"]:
            with patch("platform.system", return_value=platform_name):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = None

                    result = open_html_in_browser(mock_html_path)

                    # Verify no creationflags on non-Windows platforms
                    call_kwargs = mock_run.call_args[1]
                    assert "creationflags" not in call_kwargs
                    assert result is True

    def test_open_html_timeout_parameter(self, mock_html_path):
        """
        Verify timeout is set to prevent hanging on unresponsive systems.
        """
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        from recovery import open_html_in_browser

        with patch("platform.system", return_value="linux"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = None

                open_html_in_browser(mock_html_path)

                call_kwargs = mock_run.call_args[1]
                assert call_kwargs["timeout"] == 5
                assert call_kwargs["check"] is False  # Don't raise on non-zero exit


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
