#!/usr/bin/env python3
"""
Tests for single-instance-per-drive functionality.

Tests core/single_instance.py including:
- Server name sanitization
- Lock file path generation
- IPC message creation/parsing
- Basic single instance behavior
"""

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

# Add .smartdrive to path for imports
_test_dir = Path(__file__).resolve().parent
_smartdrive_root = _test_dir.parent.parent  # tests/unit -> tests -> .smartdrive

if str(_smartdrive_root) not in sys.path:
    sys.path.insert(0, str(_smartdrive_root))


from core.single_instance import (
    IPC_CMD_ACTIVATE,
    IPC_CMD_PING,
    IPC_PROTOCOL_VERSION,
    IPC_RESP_OK,
    SERVER_NAME_PREFIX,
    create_ipc_message,
    get_lock_file_path,
    parse_ipc_message,
    sanitize_server_name,
)

# =============================================================================
# Server Name Sanitization Tests
# =============================================================================


class TestServerNameSanitization:
    """Tests for sanitize_server_name() function."""

    def test_basic_sanitization(self):
        """Basic UUID should be sanitized correctly."""
        drive_id = str(uuid.uuid4())
        server_name = sanitize_server_name(drive_id)

        assert server_name.startswith(SERVER_NAME_PREFIX)
        assert len(server_name) <= 50  # Safe for all platforms

    def test_consistent_output(self):
        """Same drive_id should always produce same server name."""
        drive_id = "12345678-1234-4234-8234-123456789012"

        name1 = sanitize_server_name(drive_id)
        name2 = sanitize_server_name(drive_id)
        name3 = sanitize_server_name(drive_id)

        assert name1 == name2 == name3

    def test_different_ids_different_names(self):
        """Different drive_ids should produce different server names."""
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())

        name1 = sanitize_server_name(id1)
        name2 = sanitize_server_name(id2)

        assert name1 != name2

    def test_valid_characters_only(self):
        """Server name should contain only valid characters."""
        drive_id = str(uuid.uuid4())
        server_name = sanitize_server_name(drive_id)

        # Should only contain alphanumeric, dots, and hyphens
        valid_chars = set("abcdefghijklmnopqrstuvwxyz0123456789.-")
        assert all(c.lower() in valid_chars for c in server_name)


# =============================================================================
# Lock File Path Tests
# =============================================================================


class TestLockFilePath:
    """Tests for get_lock_file_path() function."""

    def test_returns_path_object(self):
        """Should return a Path object."""
        drive_id = str(uuid.uuid4())
        lock_path = get_lock_file_path(drive_id)

        assert isinstance(lock_path, Path)

    def test_path_ends_with_lock(self):
        """Lock file should end with .lock extension."""
        drive_id = str(uuid.uuid4())
        lock_path = get_lock_file_path(drive_id)

        assert lock_path.suffix == ".lock"

    def test_consistent_path(self):
        """Same drive_id should produce same lock path."""
        drive_id = "12345678-1234-4234-8234-123456789012"

        path1 = get_lock_file_path(drive_id)
        path2 = get_lock_file_path(drive_id)

        assert path1 == path2

    def test_different_ids_different_paths(self):
        """Different drive_ids should produce different lock paths."""
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())

        path1 = get_lock_file_path(id1)
        path2 = get_lock_file_path(id2)

        assert path1 != path2


# =============================================================================
# IPC Message Tests
# =============================================================================


class TestIPCMessages:
    """Tests for IPC message creation and parsing."""

    def test_create_activate_message(self):
        """ACTIVATE message should be valid JSON."""
        msg = create_ipc_message(IPC_CMD_ACTIVATE)

        assert isinstance(msg, bytes)
        parsed = json.loads(msg.decode("utf-8"))
        assert parsed["version"] == IPC_PROTOCOL_VERSION
        assert parsed["command"] == IPC_CMD_ACTIVATE

    def test_create_ping_message(self):
        """PING message should be valid JSON."""
        msg = create_ipc_message(IPC_CMD_PING)

        assert isinstance(msg, bytes)
        parsed = json.loads(msg.decode("utf-8"))
        assert parsed["command"] == IPC_CMD_PING

    def test_create_message_with_extra_fields(self):
        """Extra fields should be included in message."""
        msg = create_ipc_message(IPC_CMD_ACTIVATE, extra_field="test_value")

        parsed = json.loads(msg.decode("utf-8"))
        assert parsed["extra_field"] == "test_value"

    def test_parse_valid_message(self):
        """Valid message should parse correctly."""
        msg = create_ipc_message(IPC_CMD_ACTIVATE)
        parsed = parse_ipc_message(msg)

        assert parsed is not None
        assert parsed["command"] == IPC_CMD_ACTIVATE
        assert parsed["version"] == IPC_PROTOCOL_VERSION

    def test_parse_invalid_json(self):
        """Invalid JSON should return None."""
        assert parse_ipc_message(b"not json") is None
        assert parse_ipc_message(b"{broken") is None

    def test_parse_missing_fields(self):
        """Message missing required fields should return None."""
        # Missing 'command'
        msg = json.dumps({"version": 1}).encode("utf-8")
        assert parse_ipc_message(msg) is None

        # Missing 'version'
        msg = json.dumps({"command": "TEST"}).encode("utf-8")
        assert parse_ipc_message(msg) is None

    def test_parse_non_dict(self):
        """Non-dict JSON should return None."""
        msg = json.dumps([1, 2, 3]).encode("utf-8")
        assert parse_ipc_message(msg) is None

        msg = json.dumps("just a string").encode("utf-8")
        assert parse_ipc_message(msg) is None

    def test_roundtrip(self):
        """Create and parse should roundtrip correctly."""
        original = create_ipc_message(IPC_CMD_PING, test="value")
        parsed = parse_ipc_message(original)

        assert parsed["command"] == IPC_CMD_PING
        assert parsed["test"] == "value"


# =============================================================================
# Protocol Version Tests
# =============================================================================


class TestProtocolVersion:
    """Tests for protocol versioning."""

    def test_version_is_integer(self):
        """Protocol version should be an integer."""
        assert isinstance(IPC_PROTOCOL_VERSION, int)

    def test_version_in_messages(self):
        """All messages should include version."""
        msg = create_ipc_message("TEST")
        parsed = parse_ipc_message(msg)

        assert "version" in parsed
        assert parsed["version"] == IPC_PROTOCOL_VERSION


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
