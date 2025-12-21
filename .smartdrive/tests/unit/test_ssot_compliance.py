#!/usr/bin/env python3
"""
SSOT Compliance Tests - Verify all constant references are valid.

This test module ensures that all code references to FileNames and Paths classes
use attributes that actually exist. Prevents AttributeError at runtime due to
typos or using wrong constants class.

Per AGENT_ARCHITECTURE.md:
- Every shared value MUST be defined exactly once in authoritative modules
- Violations cause runtime AttributeError
- This test catches violations at CI time, not production runtime
"""

import ast
import re
import sys
from pathlib import Path

import pytest

# Add project paths
_tests_dir = Path(__file__).resolve().parent.parent
_smartdrive_root = _tests_dir.parent
sys.path.insert(0, str(_smartdrive_root))

from core.constants import FileNames
from core.paths import Paths


def get_class_attributes(cls) -> set[str]:
    """Get all public class attributes (not methods or dunders)."""
    attrs = set()
    for name in dir(cls):
        if name.startswith("_"):
            continue
        value = getattr(cls, name)
        # Skip methods and callable class attributes
        if callable(value):
            continue
        attrs.add(name)
    return attrs


# Valid attributes that can be referenced
VALID_FILENAMES_ATTRS = get_class_attributes(FileNames)
VALID_PATHS_ATTRS = get_class_attributes(Paths)


def find_attribute_references(file_path: Path, class_name: str) -> list[tuple[int, str]]:
    """
    Find all references to ClassName.ATTR in a Python file.

    Returns list of (line_number, attribute_name) tuples.
    """
    pattern = re.compile(rf"{class_name}\.([A-Z_][A-Z0-9_]*)")
    references = []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    for line_num, line in enumerate(content.splitlines(), 1):
        # Skip comments
        if line.strip().startswith("#"):
            continue

        for match in pattern.finditer(line):
            attr_name = match.group(1)
            references.append((line_num, attr_name))

    return references


def get_all_python_files() -> list[Path]:
    """Get all Python files in the project (scripts and core)."""
    files = []
    for subdir in ["scripts", "core"]:
        dir_path = _smartdrive_root / subdir
        if dir_path.exists():
            files.extend(dir_path.glob("*.py"))
    return files


class TestFileNamesSSotCompliance:
    """Test that all FileNames.X references use valid attributes."""

    def test_filenames_class_has_expected_attributes(self):
        """Verify FileNames class has expected core attributes."""
        # These are critical attributes that MUST exist
        required = {
            "CONFIG_JSON",
            "BAT_LAUNCHER",
            "SH_LAUNCHER",
            "GUI_EXE",
            "README",
            "KEYFILE_BIN",
            "KEYFILE_GPG",
        }
        missing = required - VALID_FILENAMES_ATTRS
        assert not missing, f"FileNames missing required attributes: {missing}"

    def test_no_directory_attributes_in_filenames(self):
        """FileNames should NOT contain directory-related attributes (belong in Paths)."""
        # These patterns indicate misplaced constants
        directory_patterns = {"_DIR", "SUBDIR"}

        suspicious = [
            attr
            for attr in VALID_FILENAMES_ATTRS
            if any(pattern in attr for pattern in directory_patterns)
            and attr != "DISTRIBUTION_DIR"  # Exception: build output dir
        ]

        assert not suspicious, (
            f"FileNames contains directory attributes that should be in Paths: {suspicious}\n"
            "Directory paths belong in core/paths.py Paths class"
        )

    @pytest.mark.parametrize("py_file", get_all_python_files(), ids=lambda p: p.name)
    def test_filenames_references_are_valid(self, py_file):
        """Test all FileNames.X references use valid attributes."""
        references = find_attribute_references(py_file, "FileNames")

        invalid = []
        for line_num, attr in references:
            if attr not in VALID_FILENAMES_ATTRS:
                invalid.append(f"  Line {line_num}: FileNames.{attr}")

        if invalid:
            pytest.fail(
                f"{py_file.name} has invalid FileNames references:\n"
                + "\n".join(invalid)
                + f"\n\nValid attributes: {sorted(VALID_FILENAMES_ATTRS)[:10]}..."
            )


class TestPathsSSotCompliance:
    """Test that all Paths.X references use valid attributes."""

    def test_paths_class_has_expected_attributes(self):
        """Verify Paths class has expected core attributes."""
        required = {
            "SMARTDRIVE_DIR_NAME",
            "SCRIPTS_SUBDIR",
            "STATIC_SUBDIR",
        }
        missing = required - VALID_PATHS_ATTRS
        assert not missing, f"Paths missing required attributes: {missing}"

    @pytest.mark.parametrize("py_file", get_all_python_files(), ids=lambda p: p.name)
    def test_paths_references_are_valid(self, py_file):
        """Test all Paths.X references use valid attributes."""
        references = find_attribute_references(py_file, "Paths")

        invalid = []
        for line_num, attr in references:
            if attr not in VALID_PATHS_ATTRS:
                invalid.append(f"  Line {line_num}: Paths.{attr}")

        if invalid:
            pytest.fail(
                f"{py_file.name} has invalid Paths references:\n"
                + "\n".join(invalid)
                + f"\n\nValid attributes: {sorted(VALID_PATHS_ATTRS)}"
            )


class TestCrossClassViolations:
    """Test for common SSOT mistakes - using wrong class for constant type."""

    def test_no_path_constants_in_filenames_usage(self):
        """
        Detect if code tries to use directory constants from FileNames.

        Common mistakes:
        - FileNames.MAIN_DIR -> should be Paths.SMARTDRIVE_DIR_NAME
        - FileNames.SCRIPTS_DIR -> should be Paths.SCRIPTS_SUBDIR
        - FileNames.STATIC_DIR -> should be Paths.STATIC_SUBDIR
        """
        # Pattern for potential misuse (referenced but doesn't exist)
        potential_dir_constants = {"MAIN_DIR", "SCRIPTS_DIR", "STATIC_DIR", "CORE_DIR"}

        violations = []
        for py_file in get_all_python_files():
            refs = find_attribute_references(py_file, "FileNames")
            for line_num, attr in refs:
                if attr in potential_dir_constants:
                    violations.append(
                        f"{py_file.name}:{line_num} - FileNames.{attr} " f"should use Paths class instead"
                    )

        assert not violations, (
            "Found FileNames references to directory constants:\n"
            + "\n".join(violations)
            + "\n\nUse Paths class for directory constants:\n"
            "  - Paths.SMARTDRIVE_DIR_NAME for .smartdrive directory name\n"
            "  - Paths.SCRIPTS_SUBDIR for scripts/ subdirectory\n"
            "  - Paths.STATIC_SUBDIR for static/ subdirectory"
        )


def uses_class_in_code(content: str, class_name: str) -> bool:
    """
    Check if a class is used in actual code (not comments or strings).

    Returns True if ClassName.ATTR_NAME pattern is found in code,
    excluding comments and string literals.
    """
    pattern = re.compile(rf"{class_name}\.[A-Z_]+")

    for line in content.splitlines():
        stripped = line.strip()

        # Skip comment-only lines
        if stripped.startswith("#"):
            continue

        # Remove inline comments
        if "#" in line:
            code_part = line.split("#")[0]
        else:
            code_part = line

        # Check for pattern in code part (excluding obvious strings)
        # This is a heuristic - we look for usage that isn't in quotes
        if pattern.search(code_part):
            # Verify it's not inside a string literal
            # Simple check: if quotes surround it, it's likely in a string
            match = pattern.search(code_part)
            if match:
                before = code_part[: match.start()]
                # Count quotes before match - odd count means we're inside a string
                single_quotes = before.count("'") - before.count("\\'")
                double_quotes = before.count('"') - before.count('\\"')

                if single_quotes % 2 == 0 and double_quotes % 2 == 0:
                    # Not inside a string literal
                    return True

    return False


class TestConstantsImports:
    """Test that scripts properly import the constants they use."""

    @pytest.mark.parametrize("py_file", get_all_python_files(), ids=lambda p: p.name)
    def test_filenames_imported_when_used(self, py_file):
        """Verify FileNames is imported in files that use it."""
        content = py_file.read_text(encoding="utf-8")

        uses_filenames = uses_class_in_code(content, "FileNames")
        imports_filenames = (
            "from core.constants import" in content and "FileNames" in content
        ) or "import core.constants" in content

        if uses_filenames and not imports_filenames:
            pytest.fail(f"{py_file.name} uses FileNames but doesn't import it from core.constants")

    @pytest.mark.parametrize("py_file", get_all_python_files(), ids=lambda p: p.name)
    def test_paths_imported_when_used(self, py_file):
        """Verify Paths is imported in files that use it."""
        content = py_file.read_text(encoding="utf-8")

        uses_paths = uses_class_in_code(content, "Paths")
        imports_paths = ("from core.paths import" in content and "Paths" in content) or "import core.paths" in content

        if uses_paths and not imports_paths:
            pytest.fail(f"{py_file.name} uses Paths but doesn't import it from core.paths")


if __name__ == "__main__":
    # Allow running directly for quick checks
    print("FileNames attributes:", sorted(VALID_FILENAMES_ATTRS))
    print("\nPaths attributes:", sorted(VALID_PATHS_ATTRS))
    print("\n--- Running tests ---")
    pytest.main([__file__, "-v"])
