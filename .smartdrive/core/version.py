# core/version.py - SINGLE SOURCE OF TRUTH for version string
"""
This is the ONLY place where VERSION is defined.
All other modules MUST import VERSION from here.
"""
from __future__ import annotations

from typing import Tuple

VERSION = "1.0.0"

# Build metadata (optional)
BUILD_ID = None  # Set by CI/CD if needed
COMPATIBILITY_VERSION = "2.0"  # Minimum compatible config schema version

# Minimum schema version this software can safely read
MIN_SCHEMA_VERSION = 2

# Current schema version this software writes
CURRENT_SCHEMA_VERSION = 3


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """
    Parse a semantic version string into a tuple of (major, minor, patch).

    Args:
        version_str: Version string like "1.2.3" or "0.0.1"

    Returns:
        Tuple of (major, minor, patch) integers

    Raises:
        ValueError: If version string is malformed
    """
    if not version_str or not isinstance(version_str, str):
        raise ValueError(f"Invalid version string: {version_str!r}")

    parts = version_str.strip().split(".")
    if len(parts) < 1 or len(parts) > 3:
        raise ValueError(f"Version must have 1-3 parts: {version_str!r}")

    result = []
    for i, part in enumerate(parts):
        try:
            result.append(int(part))
        except ValueError:
            raise ValueError(f"Invalid version component at position {i}: {part!r}")

    # Pad with zeros if needed
    while len(result) < 3:
        result.append(0)

    return (result[0], result[1], result[2])


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two semantic version strings.

    Args:
        v1: First version string
        v2: Second version string

    Returns:
        -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2

    Raises:
        ValueError: If either version string is malformed
    """
    t1 = parse_version(v1)
    t2 = parse_version(v2)

    if t1 < t2:
        return -1
    elif t1 > t2:
        return 1
    else:
        return 0


def is_version_compatible(target_version: str, target_schema: int) -> Tuple[bool, str, str]:
    """
    Check if a target drive's version is compatible with the current instance.

    Compatibility rules:
    - Schema version must be >= MIN_SCHEMA_VERSION (older schemas not readable)
    - Older software versions are compatible (downward compatibility)
    - Newer software versions trigger a warning (may have unknown features)
    - Newer schema versions trigger a warning (may have unknown config fields)

    Args:
        target_version: Target drive's software version string
        target_schema: Target drive's config schema version (integer)

    Returns:
        Tuple of (is_compatible, severity, message):
        - is_compatible: True if safe to proceed, False if incompatible
        - severity: "OK", "WARNING", or "ERROR"
        - message: Human-readable explanation
    """
    try:
        target_parsed = parse_version(target_version)
        current_parsed = parse_version(VERSION)
    except ValueError as e:
        return (False, "ERROR", f"Cannot parse version: {e}")

    # Check schema version - too old is incompatible
    if target_schema < MIN_SCHEMA_VERSION:
        return (
            False,
            "ERROR",
            f"Target drive has schema version {target_schema}, "
            f"but minimum supported is {MIN_SCHEMA_VERSION}. "
            f"Configuration format is too old and cannot be read safely.",
        )

    # Check schema version - newer is a warning
    if target_schema > CURRENT_SCHEMA_VERSION:
        return (
            True,
            "WARNING",
            f"Target drive has schema version {target_schema}, "
            f"but current instance uses schema {CURRENT_SCHEMA_VERSION}. "
            f"Configuration may contain unknown fields that will be ignored.",
        )

    # Check software version - newer is a warning
    if target_parsed > current_parsed:
        return (
            True,
            "WARNING",
            f"Target drive has software version {target_version}, "
            f"but current instance is version {VERSION}. "
            f"Managing a newer version may cause compatibility issues.",
        )

    # Older or same version is fully compatible
    return (True, "OK", "Version compatible.")
