#!/usr/bin/env python3
"""
Unit Tests for Clipboard SSOT Module

Tests the core/clipboard.py module functionality including:
- Platform detection
- Clipboard operations (set, get, clear)
- TTL functionality
- Error handling with actionable messages

These tests use mocking to avoid actual clipboard access in CI.
"""

import hashlib
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Add paths for imports
_test_dir = Path(__file__).resolve().parent
_smartdrive_root = _test_dir.parent.parent
sys.path.insert(0, str(_smartdrive_root))
sys.path.insert(0, str(_smartdrive_root / "scripts"))


class TestClipboardModuleImport:
    """Test that clipboard module imports correctly."""

    def test_module_imports(self):
        """Verify clipboard module can be imported."""
        from core.clipboard import ClipboardError, clear_best_effort, clear_if_ours, get_text, is_available, set_text

        assert callable(is_available)
        assert callable(set_text)
        assert callable(get_text)
        assert callable(clear_if_ours)
        assert callable(clear_best_effort)
        assert issubclass(ClipboardError, Exception)

    def test_clipboard_error_has_required_attributes(self):
        """ClipboardError must have message, methods_tried, remediation."""
        from core.clipboard import ClipboardError

        err = ClipboardError(message="Test error", methods_tried=[("method1", "error1")], remediation="Do this to fix")

        assert err.message == "Test error"
        assert len(err.methods_tried) == 1
        assert err.methods_tried[0] == ("method1", "error1")
        assert err.remediation == "Do this to fix"

    def test_clipboard_error_format_message(self):
        """ClipboardError should format message with all details."""
        from core.clipboard import ClipboardError

        err = ClipboardError(
            message="Failed to copy",
            methods_tried=[("clip.exe", "not found"), ("PowerShell", "timeout")],
            remediation="Install clipboard tool",
        )

        formatted = str(err)
        assert "Failed to copy" in formatted
        assert "clip.exe" in formatted
        assert "not found" in formatted
        assert "PowerShell" in formatted
        assert "Install clipboard tool" in formatted


class TestWindowsClipboardFunctions:
    """Test Windows-specific clipboard functions."""

    @patch("subprocess.Popen")
    def test_windows_clip_exe_success(self, mock_popen):
        """Test clip.exe subprocess call on success."""
        from core.clipboard import _windows_clip_exe

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        success, error = _windows_clip_exe("test text")

        assert success is True
        assert error == ""
        mock_popen.assert_called_once()
        # Verify stdin was passed the text
        mock_proc.communicate.assert_called_once()

    @patch("subprocess.Popen")
    def test_windows_clip_exe_failure(self, mock_popen):
        """Test clip.exe error handling."""
        from core.clipboard import _windows_clip_exe

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"Access denied")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        success, error = _windows_clip_exe("test text")

        assert success is False
        assert "clip.exe returned 1" in error

    @patch("subprocess.Popen")
    def test_windows_clip_exe_not_found(self, mock_popen):
        """Test handling when clip.exe not found."""
        from core.clipboard import _windows_clip_exe

        mock_popen.side_effect = FileNotFoundError()

        success, error = _windows_clip_exe("test text")

        assert success is False
        assert "not found" in error.lower()

    @patch("subprocess.Popen")
    def test_windows_powershell_fallback(self, mock_popen):
        """Test PowerShell Set-Clipboard fallback."""
        from core.clipboard import _windows_powershell_set_clipboard

        mock_proc = MagicMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        success, error = _windows_powershell_set_clipboard("test text")

        assert success is True
        # Verify PowerShell command
        call_args = mock_popen.call_args
        assert "powershell.exe" in call_args[0][0]


class TestClipboardSetText:
    """Test the main set_text() function."""

    @patch("core.clipboard._get_platform", return_value="windows")
    @patch("core.clipboard._windows_clip_exe")
    def test_set_text_windows_success(self, mock_clip, mock_plat):
        """set_text() should use clip.exe on Windows."""
        from core.clipboard import set_text

        mock_clip.return_value = (True, "")

        # Should not raise
        set_text("secret", label="password")

        mock_clip.assert_called_once()
        # Verify the text was passed
        call_args = mock_clip.call_args[0]
        assert call_args[0] == "secret"

    @patch("core.clipboard._get_platform", return_value="windows")
    @patch("core.clipboard._windows_clip_exe")
    @patch("core.clipboard._windows_powershell_set_clipboard")
    def test_set_text_windows_fallback(self, mock_ps, mock_clip, mock_plat):
        """set_text() should fallback to PowerShell if clip.exe fails."""
        from core.clipboard import set_text

        mock_clip.return_value = (False, "clip.exe failed")
        mock_ps.return_value = (True, "")

        set_text("secret", label="password")

        mock_clip.assert_called_once()
        mock_ps.assert_called_once()

    @patch("core.clipboard._get_platform", return_value="windows")
    @patch("core.clipboard._windows_clip_exe")
    @patch("core.clipboard._windows_powershell_set_clipboard")
    def test_set_text_windows_all_fail_raises(self, mock_ps, mock_clip, mock_plat):
        """set_text() should raise ClipboardError if all methods fail."""
        from core.clipboard import ClipboardError, set_text

        mock_clip.return_value = (False, "clip.exe failed")
        mock_ps.return_value = (False, "PowerShell failed")

        with pytest.raises(ClipboardError) as exc_info:
            set_text("secret", label="password")

        assert "clip.exe" in str(exc_info.value)
        assert "PowerShell" in str(exc_info.value)

    @patch("core.clipboard._get_platform", return_value="macos")
    @patch("core.clipboard._macos_pbcopy")
    def test_set_text_macos(self, mock_pbcopy, mock_plat):
        """set_text() should use pbcopy on macOS."""
        from core.clipboard import set_text

        mock_pbcopy.return_value = (True, "")

        set_text("secret", label="password")

        mock_pbcopy.assert_called_once_with("secret")

    @patch("core.clipboard._get_platform", return_value="linux")
    @patch("core.clipboard._linux_set_clipboard")
    def test_set_text_linux(self, mock_linux, mock_plat):
        """set_text() should use Linux clipboard tools."""
        from core.clipboard import set_text

        mock_linux.return_value = (True, "")

        set_text("secret", label="password")

        mock_linux.assert_called_once_with("secret")


class TestClipboardTTL:
    """Test TTL (time-to-live) clipboard clearing."""

    @patch("core.clipboard._get_platform", return_value="windows")
    @patch("core.clipboard._windows_clip_exe")
    @patch("core.clipboard.get_text")
    @patch("core.clipboard.clear_best_effort")
    def test_ttl_clears_after_timeout(self, mock_clear, mock_get, mock_clip, mock_plat):
        """TTL should clear clipboard after specified seconds."""
        from core.clipboard import set_text

        mock_clip.return_value = (True, "")
        mock_get.return_value = "secret"  # Clipboard unchanged

        # Very short TTL for testing
        set_text("secret", ttl_seconds=0.1, label="password")

        # Wait for TTL
        time.sleep(0.3)

        # Should have attempted to clear
        mock_clear.assert_called()

    @patch("core.clipboard._get_platform", return_value="windows")
    @patch("core.clipboard._windows_clip_exe")
    @patch("core.clipboard.get_text")
    @patch("core.clipboard.clear_best_effort")
    def test_ttl_does_not_clear_if_changed(self, mock_clear, mock_get, mock_clip, mock_plat):
        """TTL should NOT clear clipboard if user changed it."""
        from core.clipboard import set_text

        mock_clip.return_value = (True, "")
        mock_get.return_value = "different text"  # User changed clipboard

        set_text("secret", ttl_seconds=0.1, label="password")
        time.sleep(0.3)

        # Should NOT have cleared because content changed
        mock_clear.assert_not_called()


class TestClipboardMarker:
    """Test ClipboardMarker for tracking copied content."""

    def test_marker_hashes_content(self):
        """Marker should store hash, not plaintext."""
        from core.clipboard import ClipboardMarker

        marker = ClipboardMarker.from_content("secret password", "password")

        # Should NOT contain the plaintext
        assert "secret password" not in marker.content_hash
        # Should be a SHA256 hash
        expected = hashlib.sha256("secret password".encode()).hexdigest()
        assert marker.content_hash == expected

    def test_marker_stores_label(self):
        """Marker should store human-readable label."""
        from core.clipboard import ClipboardMarker

        marker = ClipboardMarker.from_content("data", "my_label")
        assert marker.label == "my_label"


class TestClearIfOurs:
    """Test the clear_if_ours() function."""

    @patch("core.clipboard.get_text")
    @patch("core.clipboard.clear_best_effort")
    def test_clear_if_ours_matches(self, mock_clear, mock_get):
        """clear_if_ours() should clear if content matches."""
        import core.clipboard as cb
        from core.clipboard import ClipboardMarker, _current_marker, clear_if_ours

        # Set up marker
        cb._current_marker = ClipboardMarker.from_content("test", "test")
        mock_get.return_value = "test"  # Matches
        mock_clear.return_value = True

        result = clear_if_ours()

        assert result is True
        mock_clear.assert_called_once()

    @patch("core.clipboard.get_text")
    @patch("core.clipboard.clear_best_effort")
    def test_clear_if_ours_different(self, mock_clear, mock_get):
        """clear_if_ours() should NOT clear if content changed."""
        import core.clipboard as cb
        from core.clipboard import ClipboardMarker, clear_if_ours

        cb._current_marker = ClipboardMarker.from_content("original", "test")
        mock_get.return_value = "user changed this"  # Different

        result = clear_if_ours()

        assert result is False
        mock_clear.assert_not_called()


class TestOnDemandSecretsIntegration:
    """Test OnDemandSecretsHandler with new clipboard module."""

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_cpw_derives_only_on_command(self, mock_avail, mock_set_text):
        """CPW should only derive password when command is executed."""
        from veracrypt_cli import OnDemandSecretsHandler

        password_calls = []

        def password_getter():
            password_calls.append(1)
            return "derived_password"

        test_volume = str(Path("E:\\") / "test.vc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, password_getter=password_getter, clipboard_timeout=30)

        # Password should NOT be derived yet
        assert len(password_calls) == 0

        # Execute CPW
        handler.handle_command("CPW")

        # NOW password should be derived
        assert len(password_calls) == 1

        # Verify clipboard was called with the password
        mock_set_text.assert_called_once()
        call_kwargs = mock_set_text.call_args[1]
        assert call_kwargs["label"] == "password"

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_ckf_decrypts_only_on_command(self, mock_avail, mock_set_text):
        """CKF should only decrypt keyfile when command is executed."""
        from veracrypt_cli import OnDemandSecretsHandler

        keyfile_calls = []

        def keyfile_getter():
            keyfile_calls.append(1)
            return Path("C:\\") / "decrypted" / "keyfile.bin"

        test_volume = str(Path("E:\\") / "test.vc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, keyfile_getter=keyfile_getter, clipboard_timeout=30)

        # Keyfile should NOT be decrypted yet
        assert len(keyfile_calls) == 0

        # Execute CKF
        handler.handle_command("CKF")

        # NOW keyfile should be decrypted
        assert len(keyfile_calls) == 1
        mock_set_text.assert_called_once()

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_cdp_copies_volume_path(self, mock_avail, mock_set_text):
        """CDP should copy volume path (non-secret)."""
        from veracrypt_cli import OnDemandSecretsHandler

        test_volume = str(Path("E:\\") / "my_volume.vc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, clipboard_timeout=30)

        handler.handle_command("CDP")

        mock_set_text.assert_called_once()
        call_args = mock_set_text.call_args
        assert call_args[0][0] == test_volume
        # Non-secret should have no TTL
        assert call_args[1]["ttl_seconds"] is None

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_cpw_can_be_repeated(self, mock_avail, mock_set_text):
        """CPW should work multiple times."""
        from veracrypt_cli import OnDemandSecretsHandler

        call_count = [0]

        def password_getter():
            call_count[0] += 1
            return f"password_{call_count[0]}"

        test_volume = str(Path("E:\\") / "test.vc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, password_getter=password_getter, clipboard_timeout=30)

        handler.handle_command("CPW")
        handler.handle_command("CPW")
        handler.handle_command("CPW")

        assert call_count[0] == 3
        assert mock_set_text.call_count == 3


class TestClipboardErrorMessages:
    """Test that error messages are actionable."""

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_error_message_contains_actionable_steps(self, mock_avail, mock_set_text, capsys):
        """Error messages should contain actionable remediation steps."""
        from veracrypt_cli import ClipboardError, OnDemandSecretsHandler

        mock_set_text.side_effect = ClipboardError(
            message="Failed to copy",
            methods_tried=[("clip.exe", "not found")],
            remediation="Install clipboard tool or run with GUI",
        )

        handler = OnDemandSecretsHandler(
            volume_path=str(Path("E:\\") / "test.vc"), password_getter=lambda: "test", clipboard_timeout=30
        )

        handler.handle_command("CPW")

        captured = capsys.readouterr()
        # Should show the error
        assert "Clipboard error" in captured.out or "Failed" in captured.out
        # Should show methods tried
        assert "clip.exe" in captured.out
        # Should show remediation
        assert "Install" in captured.out or "clipboard" in captured.out.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
