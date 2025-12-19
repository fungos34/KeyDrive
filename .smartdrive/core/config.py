# core/config.py - Configuration loading, migration, and validation
"""
SINGLE SOURCE OF TRUTH for configuration handling.

This module provides:
- Atomic config file writes (temp file + rename)
- Config migration (schema upgrades, drive_id generation)
- drive_id validation and generation
- lost_and_found validation

Per AGENT_ARCHITECTURE.md:
- All path operations use pathlib.Path
- Atomic writes protect against partial/corrupt writes
- Explicit logging for all migration steps
"""

import json
import logging
import os
import platform
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from core.constants import ConfigKeys, Defaults
from core.limits import Limits

# Logger for config operations
_config_logger = logging.getLogger('SmartDrive.config')


# =============================================================================
# UUID Validation and Generation
# =============================================================================

def is_valid_uuid4(value: Any) -> bool:
    """
    Check if a value is a valid UUIDv4 string.
    
    Args:
        value: Value to check
        
    Returns:
        True if value is a valid UUIDv4 canonical string, False otherwise
    """
    if not isinstance(value, str):
        return False
    
    try:
        parsed = uuid.UUID(value, version=4)
        # Ensure canonical form (lowercase with hyphens)
        return str(parsed) == value.lower()
    except (ValueError, AttributeError):
        return False


def generate_drive_id() -> str:
    """
    Generate a new UUIDv4 drive identifier.
    
    Returns:
        Canonical UUIDv4 string (lowercase with hyphens)
    """
    return str(uuid.uuid4())


# =============================================================================
# Lost and Found Validation
# =============================================================================

def validate_lost_and_found_message(message: Any) -> Tuple[bool, str]:
    """
    Validate a lost_and_found message.
    
    Args:
        message: The message to validate
        
    Returns:
        Tuple of (is_valid, sanitized_message or error)
    """
    if message is None:
        return True, ""
    
    if not isinstance(message, str):
        return False, "Message must be a string"
    
    # Check length
    if len(message) > Limits.LOST_AND_FOUND_MESSAGE_MAX_LENGTH:
        return False, f"Message exceeds {Limits.LOST_AND_FOUND_MESSAGE_MAX_LENGTH} characters"
    
    # Ensure UTF-8 safe (should always be true for Python str, but validate)
    try:
        message.encode('utf-8')
    except UnicodeEncodeError:
        return False, "Message contains invalid characters"
    
    # Strip leading/trailing whitespace, normalize line endings
    sanitized = message.strip().replace('\r\n', '\n').replace('\r', '\n')
    
    return True, sanitized


def get_default_lost_and_found() -> Dict[str, Any]:
    """Get default lost_and_found configuration."""
    return {
        ConfigKeys.LOST_AND_FOUND_ENABLED: False,
        ConfigKeys.LOST_AND_FOUND_MESSAGE: "",
    }


# =============================================================================
# Atomic Config Write
# =============================================================================

def write_config_atomic(config_path: Path, config: Dict[str, Any]) -> None:
    """
    Write configuration to file atomically.
    
    Uses write-to-temp + rename strategy to prevent partial writes.
    
    Args:
        config_path: Path to the config file
        config: Configuration dictionary to write
        
    Raises:
        OSError: If write fails
        json.JSONEncodeError: If config is not JSON serializable
    """
    config_path = Path(config_path)
    
    # Create parent directory if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temp file in same directory (ensures same filesystem for rename)
    temp_path = None
    
    try:
        # Use tempfile to generate unique name
        temp_fd, temp_path_str = tempfile.mkstemp(
            suffix='.tmp',
            prefix='config_',
            dir=str(config_path.parent)
        )
        os.close(temp_fd)  # Close fd, we'll use open() instead for testability
        temp_path = Path(temp_path_str)
        
        # Write config to temp file using open() (allows mocking in tests)
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write('\n')  # Trailing newline for POSIX compatibility
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        
        # Atomic rename (on same filesystem)
        # On Windows, we need to remove existing file first
        if platform.system().lower() == 'windows' and config_path.exists():
            config_path.unlink()
        
        temp_path.rename(config_path)
        temp_path = None  # Prevent cleanup since rename succeeded
        
        _config_logger.info(f"Config written atomically to {config_path}")
        
    finally:
        # Clean up temp file if something went wrong
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def write_file_atomic(file_path: Path, content: str | bytes, encoding: str = 'utf-8') -> None:
    """
    Write text or binary content to file atomically.
    
    Uses write-to-temp + rename strategy to prevent partial writes.
    Unlike write_config_atomic, this writes raw content, not JSON.
    
    Args:
        file_path: Path to the file to write
        content: Text (str) or binary (bytes) content to write
        encoding: Text encoding (default: utf-8, ignored for bytes)
        
    Raises:
        OSError: If write fails
    """
    file_path = Path(file_path)
    
    # Create parent directory if needed
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Determine if binary mode is needed
    is_binary = isinstance(content, bytes)
    
    temp_fd = None
    temp_path = None
    
    try:
        temp_fd, temp_path = tempfile.mkstemp(
            suffix='.tmp',
            prefix='atomic_',
            dir=str(file_path.parent)
        )
        
        # Open in binary or text mode based on content type
        if is_binary:
            with os.fdopen(temp_fd, 'wb') as f:
                temp_fd = None  # Prevent double-close
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        else:
            with os.fdopen(temp_fd, 'w', encoding=encoding) as f:
                temp_fd = None  # Prevent double-close
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
        
        temp_path_obj = Path(temp_path)
        
        # On Windows, remove existing file first
        if platform.system().lower() == 'windows' and file_path.exists():
            file_path.unlink()
        
        temp_path_obj.rename(file_path)
        temp_path = None
        
        _config_logger.debug(f"File written atomically to {file_path}")
        
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


# =============================================================================
# Config Migration
# =============================================================================

class ConfigMigrationResult:
    """Result of config migration operation."""
    
    def __init__(self):
        self.migrated = False
        self.changes: list[str] = []
        self.drive_id: Optional[str] = None
        self.errors: list[str] = []
    
    def add_change(self, description: str) -> None:
        """Record a migration change."""
        self.changes.append(description)
        self.migrated = True
        _config_logger.info(f"Migration: {description}")
    
    def add_error(self, description: str) -> None:
        """Record a migration error."""
        self.errors.append(description)
        _config_logger.error(f"Migration error: {description}")


def migrate_config(config: Dict[str, Any]) -> Tuple[Dict[str, Any], ConfigMigrationResult]:
    """
    Migrate configuration to latest schema.
    
    Handles:
    - drive_id generation if missing or invalid
    - lost_and_found defaults if missing
    - Schema version updates
    
    Args:
        config: Current configuration dictionary
        
    Returns:
        Tuple of (migrated_config, migration_result)
    """
    result = ConfigMigrationResult()
    config = config.copy()  # Don't modify original
    
    # --- drive_id migration ---
    drive_id = config.get(ConfigKeys.DRIVE_ID)
    
    if drive_id is None:
        # Generate new drive_id
        new_id = generate_drive_id()
        config[ConfigKeys.DRIVE_ID] = new_id
        result.drive_id = new_id
        result.add_change(f"Generated new drive_id: {new_id}")
    elif not is_valid_uuid4(drive_id):
        # Invalid drive_id - regenerate
        old_id = drive_id
        new_id = generate_drive_id()
        config[ConfigKeys.DRIVE_ID] = new_id
        result.drive_id = new_id
        result.add_change(f"Regenerated invalid drive_id: {old_id} -> {new_id}")
    else:
        result.drive_id = drive_id
    
    # --- lost_and_found migration ---
    lost_and_found = config.get(ConfigKeys.LOST_AND_FOUND)
    
    if lost_and_found is None:
        # Add default lost_and_found section
        config[ConfigKeys.LOST_AND_FOUND] = get_default_lost_and_found()
        result.add_change("Added default lost_and_found configuration")
    elif isinstance(lost_and_found, dict):
        # Validate and fix existing lost_and_found
        if ConfigKeys.LOST_AND_FOUND_ENABLED not in lost_and_found:
            lost_and_found[ConfigKeys.LOST_AND_FOUND_ENABLED] = False
            result.add_change("Added missing lost_and_found.enabled field")
        
        if ConfigKeys.LOST_AND_FOUND_MESSAGE not in lost_and_found:
            lost_and_found[ConfigKeys.LOST_AND_FOUND_MESSAGE] = ""
            result.add_change("Added missing lost_and_found.message field")
        else:
            # Validate existing message
            is_valid, sanitized = validate_lost_and_found_message(
                lost_and_found.get(ConfigKeys.LOST_AND_FOUND_MESSAGE)
            )
            if is_valid:
                lost_and_found[ConfigKeys.LOST_AND_FOUND_MESSAGE] = sanitized
            else:
                # Invalid message - reset to empty
                lost_and_found[ConfigKeys.LOST_AND_FOUND_MESSAGE] = ""
                result.add_change(f"Reset invalid lost_and_found.message: {sanitized}")
    else:
        # Invalid type - replace with defaults
        config[ConfigKeys.LOST_AND_FOUND] = get_default_lost_and_found()
        result.add_change("Replaced invalid lost_and_found with defaults")
    
    # --- Schema version update ---
    current_schema = config.get(ConfigKeys.SCHEMA_VERSION, 1)
    if current_schema < 3:  # New schema version with drive_id
        config[ConfigKeys.SCHEMA_VERSION] = 3
        result.add_change(f"Updated schema_version: {current_schema} -> 3")
    
    return config, result


def load_config(config_path: Path) -> Tuple[Dict[str, Any], ConfigMigrationResult]:
    """
    Load configuration from file with automatic migration.
    
    If migration occurs, config is written back atomically.
    
    Args:
        config_path: Path to config.json
        
    Returns:
        Tuple of (config_dict, migration_result)
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        json.JSONDecodeError: If config is invalid JSON
    """
    config_path = Path(config_path)
    
    _config_logger.info(f"Loading config from {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Perform migration
    migrated_config, result = migrate_config(config)
    
    # Write back if migrated
    if result.migrated:
        _config_logger.info(f"Config migration required, writing changes")
        write_config_atomic(config_path, migrated_config)
    
    return migrated_config, result


def load_or_create_config(config_path: Path, defaults: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], ConfigMigrationResult]:
    """
    Load configuration or create with defaults if not found.
    
    Args:
        config_path: Path to config.json
        defaults: Default configuration (if None, uses minimal defaults)
        
    Returns:
        Tuple of (config_dict, migration_result)
    """
    config_path = Path(config_path)
    
    if config_path.exists():
        return load_config(config_path)
    
    # Create new config with defaults
    if defaults is None:
        defaults = {}
    
    _config_logger.info(f"Creating new config at {config_path}")
    
    # Migrate the defaults to add drive_id etc.
    migrated_config, result = migrate_config(defaults)
    
    # Write the new config
    write_config_atomic(config_path, migrated_config)
    result.add_change(f"Created new config file at {config_path}")
    
    return migrated_config, result


def get_drive_id(config: Dict[str, Any]) -> Optional[str]:
    """
    Get drive_id from config, validating format.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Valid drive_id string or None if missing/invalid
    """
    drive_id = config.get(ConfigKeys.DRIVE_ID)
    if is_valid_uuid4(drive_id):
        return drive_id
    return None
