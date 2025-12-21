"""
Unit tests for version compatibility checking (CHG-20251221-041).

Tests:
- Version string parsing (semantic versioning)
- Version comparison
- Drive compatibility detection
"""

import pytest

from core.version import (
    CURRENT_SCHEMA_VERSION,
    MIN_SCHEMA_VERSION,
    VERSION,
    compare_versions,
    is_version_compatible,
    parse_version,
)


class TestParseVersion:
    """Tests for parse_version function."""

    def test_parse_full_version(self):
        """Parse standard three-part version."""
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_parse_version_with_zeros(self):
        """Parse version with zero components."""
        assert parse_version("0.0.1") == (0, 0, 1)
        assert parse_version("1.0.0") == (1, 0, 0)

    def test_parse_two_part_version(self):
        """Parse two-part version (missing patch)."""
        assert parse_version("1.2") == (1, 2, 0)

    def test_parse_single_part_version(self):
        """Parse single major version."""
        assert parse_version("5") == (5, 0, 0)

    def test_parse_version_with_whitespace(self):
        """Parse version with leading/trailing whitespace."""
        assert parse_version("  1.2.3  ") == (1, 2, 3)

    def test_parse_invalid_empty_string(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version("")

    def test_parse_invalid_none(self):
        """None raises ValueError."""
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version(None)

    def test_parse_invalid_non_numeric(self):
        """Non-numeric component raises ValueError."""
        with pytest.raises(ValueError, match="Invalid version component"):
            parse_version("1.2.beta")

    def test_parse_invalid_too_many_parts(self):
        """More than 3 parts raises ValueError."""
        with pytest.raises(ValueError, match="Version must have 1-3 parts"):
            parse_version("1.2.3.4")


class TestCompareVersions:
    """Tests for compare_versions function."""

    def test_compare_equal(self):
        """Equal versions return 0."""
        assert compare_versions("1.0.0", "1.0.0") == 0
        assert compare_versions("0.0.1", "0.0.1") == 0

    def test_compare_major_greater(self):
        """Greater major version returns 1."""
        assert compare_versions("2.0.0", "1.9.9") == 1

    def test_compare_major_lesser(self):
        """Lesser major version returns -1."""
        assert compare_versions("1.0.0", "2.0.0") == -1

    def test_compare_minor_greater(self):
        """Greater minor version returns 1."""
        assert compare_versions("1.5.0", "1.4.9") == 1

    def test_compare_minor_lesser(self):
        """Lesser minor version returns -1."""
        assert compare_versions("1.4.0", "1.5.0") == -1

    def test_compare_patch_greater(self):
        """Greater patch version returns 1."""
        assert compare_versions("1.0.5", "1.0.4") == 1

    def test_compare_patch_lesser(self):
        """Lesser patch version returns -1."""
        assert compare_versions("1.0.4", "1.0.5") == -1

    def test_compare_with_padding(self):
        """Versions with different parts compare correctly."""
        assert compare_versions("1.0", "1.0.0") == 0
        assert compare_versions("2", "1.9.9") == 1


class TestIsVersionCompatible:
    """Tests for is_version_compatible function."""

    def test_same_version_same_schema_compatible(self):
        """Same version and schema is fully compatible."""
        is_compat, severity, msg = is_version_compatible(VERSION, CURRENT_SCHEMA_VERSION)
        assert is_compat is True
        assert severity == "OK"

    def test_older_version_same_schema_compatible(self):
        """Older version with same schema is compatible (downward compat)."""
        is_compat, severity, msg = is_version_compatible("0.0.0", CURRENT_SCHEMA_VERSION)
        assert is_compat is True
        assert severity == "OK"

    def test_newer_version_same_schema_warning(self):
        """Newer version with same schema triggers warning."""
        is_compat, severity, msg = is_version_compatible("99.0.0", CURRENT_SCHEMA_VERSION)
        assert is_compat is True  # Can proceed
        assert severity == "WARNING"
        assert "newer" in msg.lower() or "99.0.0" in msg

    def test_too_old_schema_error(self):
        """Schema below minimum is fatal error."""
        old_schema = MIN_SCHEMA_VERSION - 1
        is_compat, severity, msg = is_version_compatible(VERSION, old_schema)
        assert is_compat is False
        assert severity == "ERROR"
        assert "too old" in msg.lower() or "minimum" in msg.lower()

    def test_newer_schema_warning(self):
        """Schema above current triggers warning."""
        future_schema = CURRENT_SCHEMA_VERSION + 1
        is_compat, severity, msg = is_version_compatible(VERSION, future_schema)
        assert is_compat is True  # Can proceed
        assert severity == "WARNING"
        assert "unknown fields" in msg.lower() or str(future_schema) in msg

    def test_invalid_version_string_error(self):
        """Invalid version string returns error."""
        is_compat, severity, msg = is_version_compatible("invalid", CURRENT_SCHEMA_VERSION)
        assert is_compat is False
        assert severity == "ERROR"
        assert "parse" in msg.lower() or "invalid" in msg.lower()

    def test_version_compatible_with_min_schema(self):
        """Version at minimum schema is compatible."""
        is_compat, severity, msg = is_version_compatible(VERSION, MIN_SCHEMA_VERSION)
        assert is_compat is True
        assert severity == "OK"


class TestVersionConstants:
    """Tests for version constants consistency."""

    def test_current_version_parseable(self):
        """Current VERSION is parseable."""
        result = parse_version(VERSION)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_min_schema_is_integer(self):
        """MIN_SCHEMA_VERSION is an integer."""
        assert isinstance(MIN_SCHEMA_VERSION, int)
        assert MIN_SCHEMA_VERSION > 0

    def test_current_schema_is_integer(self):
        """CURRENT_SCHEMA_VERSION is an integer."""
        assert isinstance(CURRENT_SCHEMA_VERSION, int)
        assert CURRENT_SCHEMA_VERSION >= MIN_SCHEMA_VERSION
