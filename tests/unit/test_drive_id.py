#!/usr/bin/env python3
"""
Tests for drive_id generation, persistence, and config migration.

Tests config.py functionality including:
- UUID validation
- drive_id generation on first run
- drive_id preservation across restarts
- Invalid drive_id regeneration
- lost_and_found validation
- Atomic config writes
"""

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# Add project root to path for imports
_test_dir = Path(__file__).resolve().parent
_tests_root = _test_dir.parent.parent
_project_root = _tests_root
_smartdrive_root = _project_root / ".smartdrive"

if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


from core.config import (
    generate_drive_id,
    get_default_lost_and_found,
    get_drive_id,
    is_valid_uuid4,
    load_config,
    load_or_create_config,
    migrate_config,
    validate_lost_and_found_message,
    write_config_atomic,
)
from core.constants import ConfigKeys
from core.limits import Limits
from core.modes import SecurityMode

# =============================================================================
# UUID Validation Tests
# =============================================================================


class TestUUIDValidation:
    """Tests for is_valid_uuid4() function."""

    def test_valid_uuid4(self):
        """Valid UUIDv4 should pass validation."""
        valid_uuid = str(uuid.uuid4())
        assert is_valid_uuid4(valid_uuid)

    def test_valid_uuid4_generated(self):
        """Generated drive_id should be valid."""
        drive_id = generate_drive_id()
        assert is_valid_uuid4(drive_id)

    def test_invalid_uuid_not_string(self):
        """Non-string values should fail validation."""
        assert not is_valid_uuid4(None)
        assert not is_valid_uuid4(123)
        assert not is_valid_uuid4(["a", "b"])
        assert not is_valid_uuid4({})

    def test_invalid_uuid_wrong_format(self):
        """Incorrectly formatted strings should fail validation."""
        assert not is_valid_uuid4("")
        assert not is_valid_uuid4("not-a-uuid")
        assert not is_valid_uuid4("12345678-1234-1234-1234-123456789012")  # UUIDv1 format
        assert not is_valid_uuid4("12345678123412341234123456789012")  # No hyphens

    def test_uuid_case_sensitivity(self):
        """UUIDs should be lowercase (canonical form)."""
        valid_uuid = str(uuid.uuid4())
        uppercase_uuid = valid_uuid.upper()
        # Our validation requires lowercase canonical form
        assert is_valid_uuid4(valid_uuid)
        # Uppercase should also work (uuid.UUID normalizes)
        assert is_valid_uuid4(uppercase_uuid)


# =============================================================================
# drive_id Generation Tests
# =============================================================================


class TestDriveIdGeneration:
    """Tests for generate_drive_id() function."""

    def test_generates_valid_uuid4(self):
        """Generated drive_id should be valid UUIDv4."""
        drive_id = generate_drive_id()
        assert is_valid_uuid4(drive_id)

    def test_generates_unique_ids(self):
        """Each call should generate a unique ID."""
        ids = [generate_drive_id() for _ in range(100)]
        assert len(set(ids)) == 100  # All unique

    def test_format_is_canonical(self):
        """Generated IDs should be in canonical format (lowercase with hyphens)."""
        drive_id = generate_drive_id()
        assert "-" in drive_id
        assert drive_id == drive_id.lower()
        assert len(drive_id) == 36  # Standard UUID length


# =============================================================================
# Lost and Found Validation Tests
# =============================================================================


class TestLostAndFoundValidation:
    """Tests for validate_lost_and_found_message()."""

    def test_valid_message(self):
        """Valid messages should pass."""
        valid, sanitized = validate_lost_and_found_message("Return to example@email.com")
        assert valid
        assert sanitized == "Return to example@email.com"

    def test_none_message(self):
        """None should be valid (returns empty string)."""
        valid, sanitized = validate_lost_and_found_message(None)
        assert valid
        assert sanitized == ""

    def test_empty_message(self):
        """Empty string should be valid."""
        valid, sanitized = validate_lost_and_found_message("")
        assert valid
        assert sanitized == ""

    def test_whitespace_stripping(self):
        """Leading/trailing whitespace should be stripped."""
        valid, sanitized = validate_lost_and_found_message("  test message  ")
        assert valid
        assert sanitized == "test message"

    def test_line_ending_normalization(self):
        """Line endings should be normalized to LF."""
        valid, sanitized = validate_lost_and_found_message("line1\r\nline2\rline3")
        assert valid
        assert sanitized == "line1\nline2\nline3"

    def test_max_length_exceeded(self):
        """Messages exceeding max length should fail."""
        long_message = "x" * (Limits.LOST_AND_FOUND_MESSAGE_MAX_LENGTH + 1)
        valid, error = validate_lost_and_found_message(long_message)
        assert not valid
        assert "exceeds" in error.lower()

    def test_max_length_boundary(self):
        """Messages at exactly max length should pass."""
        exact_message = "x" * Limits.LOST_AND_FOUND_MESSAGE_MAX_LENGTH
        valid, sanitized = validate_lost_and_found_message(exact_message)
        assert valid
        assert len(sanitized) == Limits.LOST_AND_FOUND_MESSAGE_MAX_LENGTH

    def test_non_string_fails(self):
        """Non-string values should fail."""
        valid, error = validate_lost_and_found_message(123)
        assert not valid
        assert "string" in error.lower()

    def test_unicode_message(self):
        """Unicode messages should be valid."""
        valid, sanitized = validate_lost_and_found_message("返回至 example@email.com 获得10%奖励")
        assert valid
        assert "返回至" in sanitized


# =============================================================================
# Config Migration Tests
# =============================================================================


class TestConfigMigration:
    """Tests for migrate_config()."""

    def test_adds_drive_id_when_missing(self):
        """Migration should add drive_id when missing."""
        config = {ConfigKeys.MODE: SecurityMode.PW_GPG_KEYFILE.value}
        migrated, result = migrate_config(config)

        assert ConfigKeys.DRIVE_ID in migrated
        assert is_valid_uuid4(migrated[ConfigKeys.DRIVE_ID])
        assert result.migrated
        assert result.drive_id is not None

    def test_preserves_existing_valid_drive_id(self):
        """Migration should preserve valid existing drive_id."""
        original_id = generate_drive_id()
        config = {ConfigKeys.MODE: SecurityMode.PW_GPG_KEYFILE.value, ConfigKeys.DRIVE_ID: original_id}

        migrated, result = migrate_config(config)

        assert migrated[ConfigKeys.DRIVE_ID] == original_id
        assert result.drive_id == original_id

    def test_regenerates_invalid_drive_id(self):
        """Migration should regenerate invalid drive_id."""
        config = {ConfigKeys.MODE: SecurityMode.PW_GPG_KEYFILE.value, ConfigKeys.DRIVE_ID: "not-a-valid-uuid"}

        migrated, result = migrate_config(config)

        assert is_valid_uuid4(migrated[ConfigKeys.DRIVE_ID])
        assert migrated[ConfigKeys.DRIVE_ID] != "not-a-valid-uuid"
        assert result.migrated

    def test_adds_lost_and_found_when_missing(self):
        """Migration should add lost_and_found defaults when missing."""
        config = {ConfigKeys.MODE: SecurityMode.PW_GPG_KEYFILE.value}
        migrated, result = migrate_config(config)

        assert ConfigKeys.LOST_AND_FOUND in migrated
        laf = migrated[ConfigKeys.LOST_AND_FOUND]
        assert ConfigKeys.LOST_AND_FOUND_ENABLED in laf
        assert ConfigKeys.LOST_AND_FOUND_MESSAGE in laf
        assert laf[ConfigKeys.LOST_AND_FOUND_ENABLED] == False
        assert laf[ConfigKeys.LOST_AND_FOUND_MESSAGE] == ""

    def test_preserves_existing_lost_and_found(self):
        """Migration should preserve valid lost_and_found config."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_GPG_KEYFILE.value,
            ConfigKeys.LOST_AND_FOUND: {
                ConfigKeys.LOST_AND_FOUND_ENABLED: True,
                ConfigKeys.LOST_AND_FOUND_MESSAGE: "Contact me@example.com",
            },
        }

        migrated, result = migrate_config(config)

        laf = migrated[ConfigKeys.LOST_AND_FOUND]
        assert laf[ConfigKeys.LOST_AND_FOUND_ENABLED] == True
        assert "me@example.com" in laf[ConfigKeys.LOST_AND_FOUND_MESSAGE]

    def test_fixes_incomplete_lost_and_found(self):
        """Migration should add missing fields to incomplete lost_and_found."""
        config = {
            ConfigKeys.MODE: SecurityMode.PW_GPG_KEYFILE.value,
            ConfigKeys.LOST_AND_FOUND: {ConfigKeys.LOST_AND_FOUND_MESSAGE: "test"},
        }

        migrated, result = migrate_config(config)

        laf = migrated[ConfigKeys.LOST_AND_FOUND]
        assert ConfigKeys.LOST_AND_FOUND_ENABLED in laf
        assert laf[ConfigKeys.LOST_AND_FOUND_ENABLED] == False
        assert result.migrated


# =============================================================================
# Atomic Write Tests
# =============================================================================


class TestAtomicWrite:
    """Tests for write_config_atomic()."""

    def test_basic_write(self):
        """Basic write should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config = {"test": "value", "number": 42}

            write_config_atomic(config_path, config)

            assert config_path.exists()
            with open(config_path, "r") as f:
                loaded = json.load(f)
            assert loaded == config

    def test_overwrites_existing(self):
        """Write should overwrite existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Write initial
            write_config_atomic(config_path, {"initial": True})

            # Overwrite
            write_config_atomic(config_path, {"updated": True})

            with open(config_path, "r") as f:
                loaded = json.load(f)
            assert loaded == {"updated": True}

    def test_creates_parent_directories(self):
        """Write should create parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nested" / "path" / "config.json"

            write_config_atomic(config_path, {"test": True})

            assert config_path.exists()

    def test_unicode_content(self):
        """Write should handle Unicode content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config = {"message": "返回至 example@email.com"}

            write_config_atomic(config_path, config)

            with open(config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            assert loaded["message"] == "返回至 example@email.com"


# =============================================================================
# Load/Create Config Tests
# =============================================================================


class TestLoadOrCreateConfig:
    """Tests for load_or_create_config()."""

    def test_creates_new_config_with_drive_id(self):
        """Creating new config should add drive_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            config, result = load_or_create_config(config_path)

            assert ConfigKeys.DRIVE_ID in config
            assert is_valid_uuid4(config[ConfigKeys.DRIVE_ID])
            assert result.migrated

    def test_loads_existing_config(self):
        """Loading existing config should work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            original_id = generate_drive_id()

            # Create config manually
            with open(config_path, "w") as f:
                json.dump({ConfigKeys.DRIVE_ID: original_id, "mode": "test"}, f)

            config, result = load_or_create_config(config_path)

            assert config[ConfigKeys.DRIVE_ID] == original_id
            assert config["mode"] == "test"

    def test_migrates_existing_config(self):
        """Loading existing config should migrate if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create config without drive_id
            with open(config_path, "w") as f:
                json.dump({"mode": "test"}, f)

            config, result = load_or_create_config(config_path)

            assert ConfigKeys.DRIVE_ID in config
            assert result.migrated


# =============================================================================
# drive_id Persistence Tests
# =============================================================================


class TestDriveIdPersistence:
    """Tests for drive_id persistence across restarts."""

    def test_drive_id_preserved_across_loads(self):
        """drive_id should remain the same across multiple loads."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # First load (creates drive_id)
            config1, result1 = load_or_create_config(config_path)
            drive_id1 = config1[ConfigKeys.DRIVE_ID]

            # Second load (should preserve)
            config2, result2 = load_or_create_config(config_path)
            drive_id2 = config2[ConfigKeys.DRIVE_ID]

            # Third load (should still preserve)
            config3, result3 = load_or_create_config(config_path)
            drive_id3 = config3[ConfigKeys.DRIVE_ID]

            assert drive_id1 == drive_id2 == drive_id3

    def test_get_drive_id_helper(self):
        """get_drive_id() should return valid ID from config."""
        config = {ConfigKeys.DRIVE_ID: generate_drive_id()}
        assert get_drive_id(config) is not None
        assert is_valid_uuid4(get_drive_id(config))

    def test_get_drive_id_returns_none_for_invalid(self):
        """get_drive_id() should return None for invalid/missing ID."""
        assert get_drive_id({}) is None
        assert get_drive_id({ConfigKeys.DRIVE_ID: "invalid"}) is None
        assert get_drive_id({ConfigKeys.DRIVE_ID: None}) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
