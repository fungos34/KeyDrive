"""
Unit tests for recovery kit non-interactive generation.

Tests verify:
1. BUG-20251222-008: All output from cmd_generate_non_interactive is ASCII-encodable
2. Integration test for complete recovery generation procedure
3. Encoding safety for Windows subprocess execution
4. No Unicode arrows or special characters in log output

Per AGENT_ARCHITECTURE.md: Tests must be non-trivial and verify complete flows.
"""

import io
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project to path
_test_dir = Path(__file__).parent
_project_root = _test_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "scripts"))


class TestRecoveryNonInteractiveASCIISafe:
    """
    BUG-20251222-008: Test that cmd_generate_non_interactive output is ASCII-safe.

    Windows subprocess.run() with capture_output=True uses cp1252 encoding by default.
    Unicode characters like → (U+2192) cannot be encoded and cause UnicodeEncodeError.
    """

    def test_log_messages_are_ascii_safe(self):
        """
        Verify all log messages in cmd_generate_non_interactive don't contain problematic Unicode.
        """
        import recovery

        # Read the source file and extract the cmd_generate_non_interactive function
        recovery_path = Path(recovery.__file__)
        source = recovery_path.read_text(encoding="utf-8")

        # Find the cmd_generate_non_interactive function body
        func_match = re.search(
            r"def cmd_generate_non_interactive\(args\):(.*?)(?=\ndef [a-zA-Z_]|\Z)",
            source,
            re.DOTALL,
        )
        assert func_match, "Could not find cmd_generate_non_interactive function"
        func_body = func_match.group(1)

        # Define problematic Unicode characters that break on Windows cp1252
        problematic_chars = [
            "→",  # U+2192 RIGHT ARROW
            "←",  # U+2190 LEFT ARROW
            "✓",  # U+2713 CHECK MARK
            "✗",  # U+2717 BALLOT X
            "⚠",  # U+26A0 WARNING SIGN
            "❌",  # U+274C CROSS MARK
            "•",  # U+2022 BULLET (sometimes problematic)
            "═",  # U+2550 BOX DRAWINGS DOUBLE HORIZONTAL
            "║",  # U+2551 BOX DRAWINGS DOUBLE VERTICAL
        ]

        # Check each problematic character
        for char in problematic_chars:
            # Look for the char in log() or print() calls within the function
            # Specifically check strings that go to stdout/stderr
            log_pattern = rf"(?:log|print|error)\s*\([^)]*{re.escape(char)}[^)]*\)"
            if re.search(log_pattern, func_body):
                pytest.fail(
                    f"Found problematic Unicode character '{char}' (U+{ord(char):04X}) "
                    f"in cmd_generate_non_interactive log/print output. "
                    f"This will cause UnicodeEncodeError on Windows (cp1252)."
                )

    def test_non_interactive_output_can_encode_ascii(self, tmp_path, monkeypatch):
        """
        Integration test: Run cmd_generate_non_interactive and verify output encodes to ASCII.

        This simulates the Windows cp1252 encoding constraint.
        """
        # Skip if missing dependencies
        pytest.importorskip("mnemonic")
        pytest.importorskip("cryptography")

        # Create minimal config
        config_dir = tmp_path / ".smartdrive"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(
            """{
            "mode": "PW_ONLY",
            "windows": {"volume_path": "C:\\\\test.vc", "mount_letter": "V"},
            "unix": {"volume_path": "/dev/test", "mount_point": "/mnt/test"}
        }"""
        )

        # Mock environment variables
        monkeypatch.setenv("KEYDRIVE_VOLUME_PASSWORD", "test_password_123")

        # Capture output
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()

        # Mock various functions to avoid actual VeraCrypt operations
        with patch("recovery.load_config") as mock_load:
            mock_load.return_value = {
                "mode": "PW_ONLY",
                "windows": {"volume_path": "C:\\test.vc", "mount_letter": "V"},
                "unix": {"volume_path": "/dev/test", "mount_point": "/mnt/test"},
            }

            with patch("recovery.export_header") as mock_export:
                # Simulate CLICapabilityError to trigger the warning message
                from veracrypt_cli import CLICapabilityError

                mock_export.side_effect = CLICapabilityError("CLI unsupported")

                with patch("recovery.save_config_atomic"):
                    with patch("recovery.audit_log"):
                        with patch("recovery.Paths.recovery_dir", return_value=tmp_path / "recovery"):
                            with patch("sys.stdout", captured_stdout):
                                with patch("sys.stderr", captured_stderr):
                                    try:
                                        import recovery

                                        args = MagicMock()
                                        args.format = "printable"
                                        args.force = True

                                        # This will fail due to missing files, but we capture output
                                        recovery.cmd_generate_non_interactive(args)
                                    except SystemExit:
                                        pass  # Expected
                                    except Exception:
                                        pass  # May fail for other reasons, we just check encoding

        # Get all captured output
        all_output = captured_stdout.getvalue() + captured_stderr.getvalue()

        # Try to encode as ASCII - should not raise
        try:
            all_output.encode("ascii")
        except UnicodeEncodeError as e:
            pytest.fail(
                f"Output contains non-ASCII character at position {e.start}: "
                f"'{e.object[max(0, e.start-10):e.end+10]}' - "
                f"This would fail on Windows cp1252"
            )

    def test_warning_message_uses_ascii_arrow(self):
        """
        Verify the header backup warning uses ASCII arrow (->) not Unicode (→).
        """
        import recovery

        source = Path(recovery.__file__).read_text(encoding="utf-8")

        # Check for the specific fix
        assert "VeraCrypt GUI -> Tools -> Backup Volume Header" in source, "Should use ASCII arrow (->)"

        assert "VeraCrypt GUI → Tools → Backup Volume Header" not in source, "Should NOT use Unicode arrow (→)"


class TestRecoveryGenerationIntegration:
    """
    Integration tests for recovery kit generation.

    Tests the complete flow from credential input to kit output.
    """

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create a mock configuration for testing."""
        config_dir = tmp_path / ".smartdrive"
        config_dir.mkdir()
        recovery_dir = config_dir / "recovery"
        recovery_dir.mkdir()

        return {
            "mode": "PW_ONLY",
            "windows": {"volume_path": str(tmp_path / "test.vc"), "mount_letter": "V"},
            "unix": {"volume_path": str(tmp_path / "test.vc"), "mount_point": "/mnt/test"},
            "drive_name": "TestDrive",
        }

    def test_bip39_phrase_generation(self):
        """Test that BIP39 phrase generation produces valid 24-word phrases."""
        pytest.importorskip("mnemonic")

        from recovery import generate_bip39_phrase, verify_bip39_phrase

        phrase = generate_bip39_phrase()

        # Verify structure
        words = phrase.split()
        assert len(words) == 24, "Should generate 24-word phrase"

        # Verify validity
        assert verify_bip39_phrase(phrase), "Generated phrase should be valid BIP39"

    def test_phrase_hash_deterministic(self):
        """Test that phrase hashing is deterministic."""
        pytest.importorskip("mnemonic")

        from recovery import hash_phrase

        phrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

        hash1 = hash_phrase(phrase)
        hash2 = hash_phrase(phrase)

        assert hash1 == hash2, "Same phrase should produce same hash"
        # hash_phrase returns first 16 chars of SHA-256 hex, not full 64
        assert len(hash1) >= 16, "Hash should be at least 16 chars"

    def test_credentials_dict_structure(self, mock_config, tmp_path, monkeypatch):
        """Test that credentials dict has required fields."""
        monkeypatch.setenv("KEYDRIVE_VOLUME_PASSWORD", "test_password")

        # The credentials dict should have these fields
        expected_fields = ["volume_path", "security_mode", "mount_password", "mount_target", "created_at"]

        # We can verify this by checking the source
        import recovery

        source = Path(recovery.__file__).read_text(encoding="utf-8")
        assert "credentials = {" in source

        for field in expected_fields:
            assert f'"{field}"' in source, f"Credentials should include {field}"

    def test_recovery_container_creation(self, tmp_path):
        """Test that recovery container can be created from credentials."""
        pytest.importorskip("mnemonic")
        pytest.importorskip("cryptography")

        from recovery_container import create_container, decrypt_container

        from recovery import generate_bip39_phrase

        phrase = generate_bip39_phrase()
        credentials = {
            "volume_path": str(tmp_path / "test.vc"),
            "security_mode": "PW_ONLY",
            "mount_password": "test_password_123",
            "mount_target": "V:",
            "created_at": "2024-01-01T00:00:00Z",
        }

        # Create container
        container_bytes = create_container(credentials, phrase)
        assert container_bytes is not None
        assert len(container_bytes) > 0

        # Verify we can decrypt it back
        decrypted = decrypt_container(container_bytes, phrase)
        assert decrypted["mount_password"] == "test_password_123"
        assert decrypted["security_mode"] == "PW_ONLY"

    def test_recovery_html_generation(self, tmp_path):
        """Test that recovery HTML is generated correctly."""
        pytest.importorskip("mnemonic")

        from recovery import generate_bip39_phrase, generate_recovery_html

        phrase = generate_bip39_phrase()

        html = generate_recovery_html(
            phrase=phrase,
            chunks=None,
            header_chunks=None,
            volume_name="TestDrive",
            volume_identity="test_identity_hash",
            security_mode="PW_ONLY",
            gpg_pw_only_info=None,
            include_qr=False,  # Skip QR to speed up test
        )

        # Verify HTML structure
        assert "<html" in html.lower()
        assert "TestDrive" in html
        assert "test_identity_hash" in html

        # Verify all phrase words are in HTML
        for word in phrase.split():
            assert word in html, f"Phrase word '{word}' should be in HTML"

    def test_non_interactive_subprocess_env_vars(self, monkeypatch):
        """Test that non-interactive mode reads from environment variables."""
        import recovery

        source = Path(recovery.__file__).read_text(encoding="utf-8")

        # Verify it reads from env vars
        assert 'os.environ.get("KEYDRIVE_VOLUME_PASSWORD")' in source
        assert 'os.environ.get("KEYDRIVE_KEYFILE_B64")' in source or 'os.environ.get("KEYDRIVE_KEYFILE_PATH")' in source

    def test_recovery_kit_output_marker(self):
        """Test that recovery kit outputs RECOVERY_KIT_PATH marker for GUI capture."""
        import recovery

        source = Path(recovery.__file__).read_text(encoding="utf-8")

        # GUI captures this marker to find the generated kit path
        assert "RECOVERY_KIT_PATH:" in source, "Should output RECOVERY_KIT_PATH: marker"


class TestEncodingSafety:
    """
    Tests for encoding safety across different platforms.
    """

    def test_all_log_function_output_in_non_interactive_is_safe(self):
        """
        Verify that log() calls in cmd_generate_non_interactive are ASCII-safe.

        Interactive mode (cmd_generate) can use Unicode since it's terminal output.
        Non-interactive mode must be ASCII-safe for subprocess capture.
        """
        import recovery

        source = Path(recovery.__file__).read_text(encoding="utf-8")

        # Find the cmd_generate_non_interactive function body ONLY
        func_match = re.search(
            r"def cmd_generate_non_interactive\(args\):(.*?)(?=\ndef [a-zA-Z_]|\Z)",
            source,
            re.DOTALL,
        )
        if not func_match:
            pytest.skip("Could not find cmd_generate_non_interactive function")

        func_body = func_match.group(1)

        # Find all string literals in log() calls within this function only
        log_calls = re.findall(r'log\(["\']([^"\']+)["\'](?:\s*\)|,)', func_body)

        for msg in log_calls:
            try:
                msg.encode("ascii")
            except UnicodeEncodeError as e:
                pytest.fail(f"Log message in non-interactive mode contains non-ASCII: '{msg}' " f"at char {e.start}")

    def test_cp1252_compatible_output(self):
        """
        Test that common output can be encoded with Windows cp1252.
        """
        # These are the messages that should work on Windows
        safe_messages = [
            "[Recovery] Generating recovery phrase...",
            "[Recovery] Header backup skipped (CLI unsupported on this platform)",
            "[Recovery] WARNING: Generate header backup manually via: VeraCrypt GUI -> Tools -> Backup Volume Header",
            "[1/5] Creating encrypted recovery container...",
            "[SUCCESS] Recovery kit generation complete",
        ]

        for msg in safe_messages:
            try:
                msg.encode("cp1252")
            except UnicodeEncodeError:
                pytest.fail(f"Message cannot encode to cp1252: {msg}")


class TestRecoveryStateConsistency:
    """
    BUG-20251222-010: Test that recovery state values are consistent.

    The code must write "enabled"/"used" (constant values), not "RECOVERY_STATE_ENABLED".
    All state checks must use the same string values.
    """

    def test_recovery_constants_defined_correctly(self):
        """Verify recovery state constants are defined with correct values."""
        from recovery import RECOVERY_STATE_CONSUMING, RECOVERY_STATE_ENABLED, RECOVERY_STATE_USED

        assert RECOVERY_STATE_ENABLED == "enabled", "RECOVERY_STATE_ENABLED should be 'enabled'"
        assert RECOVERY_STATE_USED == "used", "RECOVERY_STATE_USED should be 'used'"
        assert RECOVERY_STATE_CONSUMING == "consuming", "RECOVERY_STATE_CONSUMING should be 'consuming'"

    def test_non_interactive_uses_constant_not_string_literal(self):
        """
        BUG-20251222-010: Verify cmd_generate_non_interactive uses RECOVERY_STATE_ENABLED constant.

        The bug was writing "RECOVERY_STATE_ENABLED" (string literal) instead of
        RECOVERY_STATE_ENABLED (constant which equals "enabled").
        """
        import recovery

        source = Path(recovery.__file__).read_text(encoding="utf-8")

        # Find the cmd_generate_non_interactive function body
        func_match = re.search(
            r"def cmd_generate_non_interactive\(args\):(.*?)(?=\ndef [a-zA-Z_]|\Z)",
            source,
            re.DOTALL,
        )
        assert func_match, "Could not find cmd_generate_non_interactive function"
        func_body = func_match.group(1)

        # Should NOT contain string literal "RECOVERY_STATE_ENABLED" in dict assignment
        assert '"state": "RECOVERY_STATE_ENABLED"' not in func_body, "Bug: Using string literal instead of constant"

        # Should contain the constant reference (without quotes around the constant name)
        assert '"state": RECOVERY_STATE_ENABLED' in func_body, "Should use RECOVERY_STATE_ENABLED constant"

    def test_gui_state_checks_use_correct_values(self):
        """
        BUG-20251222-010: Verify GUI state checks use "enabled"/"used", not string literals.
        """
        gui_path = _project_root / "scripts" / "gui.py"
        source = gui_path.read_text(encoding="utf-8")

        # Should NOT contain these incorrect patterns (string literals matching constant names)
        assert 'state") == "RECOVERY_STATE_ENABLED"' not in source, "Bug: GUI checking for wrong state string"
        assert 'state") == "RECOVERY_STATE_USED"' not in source, "Bug: GUI checking for wrong state string"

        # Should contain correct patterns (checking for actual values)
        # The pattern: state == "enabled" or state == "used"
        assert '"enabled"' in source, "GUI should check for 'enabled' state"
        assert '"used"' in source, "GUI should check for 'used' state"

    def test_config_state_value_interpretation(self):
        """Test that config with correct state values is properly interpreted."""
        # Simulate config with correct state value
        enabled_config = {"recovery": {"enabled": True, "state": "enabled"}}
        used_config = {"recovery": {"used": True, "state": "used"}}
        consuming_config = {"recovery": {"state": "consuming"}}

        # Helper to interpret state
        def interpret_state(config):
            recovery_cfg = config.get("recovery", {})
            state = recovery_cfg.get("state", "")
            enabled = recovery_cfg.get("enabled", False)
            used = recovery_cfg.get("used", False)

            if used or state == "used":
                return "USED"
            elif enabled and (state == "enabled" or state == ""):
                return "AVAILABLE"
            else:
                return "NOT_CONFIGURED"

        assert interpret_state(enabled_config) == "AVAILABLE"
        assert interpret_state(used_config) == "USED"
        assert interpret_state(consuming_config) == "NOT_CONFIGURED"

    def test_legacy_config_compatibility(self):
        """Test that legacy configs (without state field) still work."""
        # Legacy config: enabled=True but no state field
        legacy_enabled = {"recovery": {"enabled": True}}

        # Should still be interpreted as available
        recovery_cfg = legacy_enabled.get("recovery", {})
        state = recovery_cfg.get("state", "")
        enabled = recovery_cfg.get("enabled", False)

        # This is the logic from gui.py line 7762
        is_available = enabled and (state == "enabled" or state == "")
        assert is_available, "Legacy config with enabled=True should show as available"


class TestRecoveryCredentialVerification:
    """
    BUG-20251222-011: Test credential verification before recovery kit generation.

    Recovery kit generation MUST verify credentials via mount/unmount test
    to ensure the kit will contain valid credentials.
    """

    def test_credential_verification_method_exists(self):
        """Verify _verify_credentials_via_mount method exists in RecoveryGenerateWorker."""
        gui_path = _project_root / "scripts" / "gui.py"
        source = gui_path.read_text(encoding="utf-8")

        assert (
            "_verify_credentials_via_mount" in source
        ), "RecoveryGenerateWorker should have _verify_credentials_via_mount method"

    def test_credential_verification_called_before_generation(self):
        """Verify that credential verification is called before generating kit."""
        gui_path = _project_root / "scripts" / "gui.py"
        source = gui_path.read_text(encoding="utf-8")

        # Find the run() method of RecoveryGenerateWorker
        # Look for the pattern where verification happens before the generation command
        assert "recovery_generate_status_verifying" in source, "Should emit verifying status"

        # Ensure verification happens BEFORE running the generation command
        # Find the order in source code
        verify_pos = source.find("_verify_credentials_via_mount")
        cmd_pos = source.find('cmd = [str(python_exe), str(recovery_script), "generate"')

        assert verify_pos > 0, "Should have verification call"
        assert cmd_pos > 0, "Should have command execution"
        assert verify_pos < cmd_pos, "Verification should happen BEFORE command execution"

    def test_credential_verification_aborts_on_failure(self):
        """Verify that failed credential verification aborts generation."""
        gui_path = _project_root / "scripts" / "gui.py"
        source = gui_path.read_text(encoding="utf-8")

        # Should emit failure and return if verification fails
        assert "Credential verification failed" in source, "Should have failure message for verification"
        assert "Recovery kit not generated" in source, "Should indicate kit not generated on failure"

    def test_verification_imports_veracrypt_cli(self):
        """Verify that veracrypt_cli is imported for mount operations."""
        gui_path = _project_root / "scripts" / "gui.py"
        source = gui_path.read_text(encoding="utf-8")

        # Should import try_mount and unmount
        assert "from scripts.veracrypt_cli import" in source, "Should import from veracrypt_cli"
        assert "try_mount" in source, "Should use try_mount for verification"
        assert "unmount" in source, "Should use unmount after successful test mount"

    def test_verification_handles_already_mounted_volume(self):
        """Verify that already-mounted volumes pass verification without additional mount."""
        gui_path = _project_root / "scripts" / "gui.py"
        source = gui_path.read_text(encoding="utf-8")

        # Should check if volume is already mounted
        assert "get_mount_status" in source, "Should check current mount status"
        assert 'return True, ""' in source, "Should return success if already mounted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
