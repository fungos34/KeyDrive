#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: On-Demand Secrets Handler (TODO 5)

Per AGENT_ARCHITECTURE.md Section 10.3:
- Secrets MUST NOT be decrypted until user explicitly requests them
- Clipboard auto-clears after timeout
- CPW/CKF/CDP commands respect single entry pattern
- clear_all() must exist and work

This test verifies:
1. OnDemandSecretsHandler initializes without decrypting secrets
2. Password getter is NOT called until CPW command
3. Keyfile getter is NOT called until CKF command
4. clear_all() method exists and clears clipboard
5. Cleanup removes temporary files
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestOnDemandSecretsInitialization(unittest.TestCase):
    """Test that secrets are not decrypted at initialization time."""

    def test_password_not_decrypted_at_init(self):
        """Password getter should NOT be called during __init__."""
        from veracrypt_cli import OnDemandSecretsHandler

        password_getter = MagicMock(return_value="secret_password")

        test_volume = str(Path("C:\\") / "test" / "volume.hc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, password_getter=password_getter, keyfile_getter=None)

        # Password getter should NOT have been called yet
        password_getter.assert_not_called()

    def test_keyfile_not_decrypted_at_init(self):
        """Keyfile getter should NOT be called during __init__."""
        from veracrypt_cli import OnDemandSecretsHandler

        keyfile_getter = MagicMock(return_value=Path("C:\\") / "test" / "keyfile.key")

        test_volume = str(Path("C:\\") / "test" / "volume.hc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, password_getter=None, keyfile_getter=keyfile_getter)

        # Keyfile getter should NOT have been called yet
        keyfile_getter.assert_not_called()


class TestOnDemandSecretsCPWCommand(unittest.TestCase):
    """Test CPW command behavior."""

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_cpw_decrypts_password_on_demand(self, mock_clip_avail, mock_set_text):
        """CPW command should call password getter only when executed."""
        from veracrypt_cli import OnDemandSecretsHandler

        password_getter = MagicMock(return_value="secret_password")

        test_volume = str(Path("C:\\") / "test" / "volume.hc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, password_getter=password_getter, keyfile_getter=None)

        # Password getter not called yet
        password_getter.assert_not_called()

        # Now handle CPW command
        handler.handle_command("CPW")

        # NOW password getter should have been called
        password_getter.assert_called_once()

        # And password should have been copied via SSOT module
        mock_set_text.assert_called_once()
        call_args = mock_set_text.call_args
        assert call_args[0][0] == "secret_password"
        assert call_args[1]["label"] == "password"

    @patch("veracrypt_cli.clipboard_available", return_value=False)
    def test_cpw_handles_no_clipboard(self, mock_clip_avail):
        """CPW should handle missing clipboard gracefully."""
        from veracrypt_cli import OnDemandSecretsHandler

        password_getter = MagicMock(return_value="secret_password")

        test_volume = str(Path("C:\\") / "test" / "volume.hc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, password_getter=password_getter)

        # Should NOT crash, should return True (handled)
        result = handler.handle_command("CPW")
        self.assertTrue(result)

        # Password getter should NOT be called when clipboard unavailable
        password_getter.assert_not_called()


class TestOnDemandSecretsCKFCommand(unittest.TestCase):
    """Test CKF command behavior."""

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_ckf_decrypts_keyfile_on_demand(self, mock_clip_avail, mock_set_text):
        """CKF command should call keyfile getter only when executed."""
        from veracrypt_cli import OnDemandSecretsHandler

        keyfile_path = Path("C:\\") / "test" / "keyfile.key"
        keyfile_getter = MagicMock(return_value=keyfile_path)

        test_volume = str(Path("C:\\") / "test" / "volume.hc")
        handler = OnDemandSecretsHandler(volume_path=test_volume, password_getter=None, keyfile_getter=keyfile_getter)

        # Keyfile getter not called yet
        keyfile_getter.assert_not_called()

        # Now handle CKF command
        handler.handle_command("CKF")

        # NOW keyfile getter should have been called
        keyfile_getter.assert_called_once()

        # And keyfile path should have been copied via SSOT module
        mock_set_text.assert_called_once()


class TestOnDemandSecretsCDPCommand(unittest.TestCase):
    """Test CDP command behavior (non-secret device path)."""

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_cdp_copies_volume_path(self, mock_clip_avail, mock_set_text):
        """CDP command should copy volume path without calling any getter."""
        from veracrypt_cli import OnDemandSecretsHandler

        password_getter = MagicMock(return_value="secret")
        keyfile_getter = MagicMock(return_value=Path("C:\\") / "keyfile")

        test_volume = str(Path("C:\\") / "test" / "volume.hc")
        handler = OnDemandSecretsHandler(
            volume_path=test_volume, password_getter=password_getter, keyfile_getter=keyfile_getter
        )

        # Handle CDP command
        handler.handle_command("CDP")

        # Volume path should be copied via SSOT module
        mock_set_text.assert_called_once()
        call_args = mock_set_text.call_args
        assert call_args[0][0] == test_volume
        # Non-secret should have no TTL
        assert call_args[1]["ttl_seconds"] is None

        # But NO secret getters should have been called
        password_getter.assert_not_called()
        keyfile_getter.assert_not_called()


class TestOnDemandSecretsCleanup(unittest.TestCase):
    """Test cleanup and clear_all methods."""

    def test_clear_all_method_exists(self):
        """OnDemandSecretsHandler must have clear_all() method."""
        from veracrypt_cli import OnDemandSecretsHandler

        handler = OnDemandSecretsHandler(volume_path=str(Path("C:\\") / "test"))

        self.assertTrue(hasattr(handler, "clear_all"), "clear_all method must exist")
        self.assertTrue(callable(handler.clear_all), "clear_all must be callable")

    def test_cleanup_method_exists(self):
        """OnDemandSecretsHandler must have cleanup() method."""
        from veracrypt_cli import OnDemandSecretsHandler

        handler = OnDemandSecretsHandler(volume_path=str(Path("C:\\") / "test"))

        self.assertTrue(hasattr(handler, "cleanup"), "cleanup method must exist")
        self.assertTrue(callable(handler.cleanup), "cleanup must be callable")

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_clear_if_ours")
    def test_cleanup_clears_clipboard_if_password_copied(self, mock_clear):
        """cleanup() should clear clipboard if password was copied."""
        from veracrypt_cli import OnDemandSecretsHandler

        handler = OnDemandSecretsHandler(volume_path=str(Path("C:\\") / "test"))
        handler._password_copied = True

        handler.cleanup()

        mock_clear.assert_called_once()
        self.assertFalse(handler._password_copied)

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_clear_if_ours")
    def test_clear_all_is_alias_for_cleanup(self, mock_clear):
        """clear_all() should behave identically to cleanup()."""
        from veracrypt_cli import OnDemandSecretsHandler

        handler = OnDemandSecretsHandler(volume_path=str(Path("C:\\") / "test"))
        handler._password_copied = True

        handler.clear_all()

        mock_clear.assert_called_once()
        self.assertFalse(handler._password_copied)


class TestCommandCaseInsensitivity(unittest.TestCase):
    """Test that commands are case-insensitive."""

    @patch("veracrypt_cli._CLIPBOARD_SSOT_AVAILABLE", True)
    @patch("veracrypt_cli._clipboard_set_text")
    @patch("veracrypt_cli.clipboard_available", return_value=True)
    def test_commands_case_insensitive(self, mock_clip_avail, mock_set_text):
        """Commands should work regardless of case."""
        from veracrypt_cli import OnDemandSecretsHandler

        test_volume = str(Path("C:\\") / "test" / "volume.hc")
        handler = OnDemandSecretsHandler(
            volume_path=test_volume, password_getter=lambda: "password", keyfile_getter=lambda: Path("C:\\") / "keyfile"
        )

        # Test lowercase
        result = handler.handle_command("cpw")
        self.assertTrue(result)

        # Test mixed case
        result = handler.handle_command("Cdp")
        self.assertTrue(result)

        # Test with whitespace
        result = handler.handle_command("  CKF  ")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
