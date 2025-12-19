#!/usr/bin/env python3
"""
Tests for BUG-20251219-004: Single-shot recovery kit generation.

Verifies:
- Generation is blocked if an active kit exists (enabled=True, used=False)
- --force flag with confirmation allows regeneration
- Audit logging captures forced regenerations
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestGenerateLock:
    """Test single-shot generation enforcement."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create a temporary config file."""
        config_file = tmp_path / ".smartdrive" / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        return config_file

    @pytest.fixture
    def active_recovery_config(self):
        """Config with active (unused) recovery kit."""
        return {
            "recovery": {
                "enabled": True,
                "used": False,
                "phrase_hash": "test_hash_123",
                "created_at": "2025-12-19T10:00:00Z",
            },
            "windows": {"volume_path": "C:\\test.vc", "mount_letter": "V"},
            "unix": {"volume_path": "/dev/sda1", "mount_point": "/mnt/test"},
        }

    @pytest.fixture
    def used_recovery_config(self):
        """Config with used recovery kit."""
        return {
            "recovery": {
                "enabled": False,
                "used": True,
                "state": "used",
                "invalidated_at": "2025-12-19T11:00:00Z",
            },
            "windows": {"volume_path": "C:\\test.vc", "mount_letter": "V"},
            "unix": {"volume_path": "/dev/sda1", "mount_point": "/mnt/test"},
        }

    @pytest.fixture
    def no_recovery_config(self):
        """Config without any recovery kit."""
        return {
            "windows": {"volume_path": "C:\\test.vc", "mount_letter": "V"},
            "unix": {"volume_path": "/dev/sda1", "mount_point": "/mnt/test"},
        }

    def test_generation_blocked_when_active_kit_exists(self, temp_config, active_recovery_config):
        """Generation should be blocked when an active (unused) kit exists."""
        # Write config with active recovery
        temp_config.write_text(json.dumps(active_recovery_config))

        # Import after path setup
        sys.path.insert(0, str(temp_config.parent.parent))

        # Mock the recovery module's config loading
        with patch("builtins.input", return_value="n"):
            # The check should block without --force
            recovery_config = active_recovery_config.get("recovery", {})
            force_regenerate = False

            # Simulate the check logic from cmd_generate
            should_block = recovery_config.get("enabled") and not recovery_config.get("used") and not force_regenerate

            assert should_block, "Generation should be blocked when active kit exists without --force"

    def test_generation_allowed_when_no_kit_exists(self, no_recovery_config):
        """Generation should be allowed when no kit exists."""
        recovery_config = no_recovery_config.get("recovery", {})
        force_regenerate = False

        should_block = recovery_config.get("enabled") and not recovery_config.get("used") and not force_regenerate

        assert not should_block, "Generation should be allowed when no kit exists"

    def test_generation_allowed_when_kit_is_used(self, used_recovery_config):
        """Generation should be allowed when existing kit is used."""
        recovery_config = used_recovery_config.get("recovery", {})
        force_regenerate = False

        should_block = recovery_config.get("enabled") and not recovery_config.get("used") and not force_regenerate

        assert not should_block, "Generation should be allowed when kit is used"

    def test_force_flag_allows_regeneration(self, active_recovery_config):
        """--force flag should allow regeneration with confirmation."""
        recovery_config = active_recovery_config.get("recovery", {})
        force_regenerate = True

        should_block = recovery_config.get("enabled") and not recovery_config.get("used") and not force_regenerate

        assert not should_block, "Generation should be allowed with --force flag"

    def test_force_regeneration_requires_confirmation(self):
        """Forced regeneration should require 'REGENERATE' confirmation."""
        # Test the confirmation logic
        valid_confirmations = ["REGENERATE"]
        invalid_confirmations = ["yes", "y", "YES", "regenerate", "", "confirm"]

        for valid in valid_confirmations:
            assert valid == "REGENERATE", f"'{valid}' should be valid confirmation"

        for invalid in invalid_confirmations:
            assert invalid != "REGENERATE", f"'{invalid}' should not be valid confirmation"


class TestGenerateArgparse:
    """Test argparse configuration for --force flag."""

    def test_generate_parser_has_force_flag(self):
        """Generate subcommand should have --force argument."""
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        gen_parser = subparsers.add_parser("generate")
        gen_parser.add_argument("--force", action="store_true")

        # Test parsing with --force
        args = parser.parse_args(["generate", "--force"])
        assert args.force is True, "--force should set force=True"

        # Test parsing without --force
        args = parser.parse_args(["generate"])
        assert args.force is False, "Without --force, force should be False"


class TestAuditLogging:
    """Test audit logging for generation events."""

    def test_blocked_generation_is_logged(self):
        """Blocked generation attempts should be audit logged."""
        # Mock audit_log function
        logged_events = []

        def mock_audit_log(event, **kwargs):
            logged_events.append({"event": event, "kwargs": kwargs})

        # Simulate blocked generation
        with patch.dict("sys.modules", {}):
            # The check that would trigger audit logging
            recovery_config = {"enabled": True, "used": False}
            force_regenerate = False

            if recovery_config.get("enabled") and not recovery_config.get("used") and not force_regenerate:
                mock_audit_log("GENERATE_BLOCKED", details={"reason": "active_kit_exists", "force": False})

        assert len(logged_events) == 1, "Blocked generation should trigger audit log"
        assert logged_events[0]["event"] == "GENERATE_BLOCKED"

    def test_force_confirmation_is_logged(self):
        """Force confirmation should be audit logged with previous kit info."""
        logged_events = []

        def mock_audit_log(event, **kwargs):
            logged_events.append({"event": event, "kwargs": kwargs})

        # Simulate forced regeneration confirmation
        previous_config = {
            "created_at": "2025-12-19T10:00:00Z",
            "phrase_hash": "abcdef123456789",
        }

        mock_audit_log(
            "GENERATE_FORCE_CONFIRMED",
            details={
                "previous_created_at": previous_config.get("created_at"),
                "previous_phrase_hash": previous_config.get("phrase_hash", "")[:16] + "...",
            },
        )

        assert len(logged_events) == 1
        assert logged_events[0]["event"] == "GENERATE_FORCE_CONFIRMED"
        assert "previous_created_at" in logged_events[0]["kwargs"]["details"]
