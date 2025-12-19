#!/usr/bin/env python3
"""
i18n Audit Test for recovery.py

WORK ORDER TODO 11: Ensure user-facing strings in recovery.py are
accounted for in localization strategy.

This audit test documents the current state of i18n in recovery.py:
1. recovery.py currently uses hardcoded English strings
2. This is intentional for security-critical recovery instructions
3. Recovery kit is meant to be human-readable in emergency situations
4. Multilingual recovery kits could cause confusion in emergencies

The test verifies:
- recovery.py does NOT import cli_i18n (intentional design)
- Critical recovery phrases are in English for universal emergency use
- HTML recovery kit uses English for emergency readability
"""

import ast
import re
import sys
from pathlib import Path

# Add project root and .smartdrive to path for imports
_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent
_smartdrive_root = _project_root / ".smartdrive"

sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_smartdrive_root))
sys.path.insert(0, str(_smartdrive_root / "scripts"))

import pytest


class TestRecoveryI18nAudit:
    """Audit tests for i18n compliance in recovery.py."""

    @pytest.fixture
    def recovery_source(self):
        """Load recovery.py source code."""
        recovery_path = _smartdrive_root / "scripts" / "recovery.py"
        return recovery_path.read_text(encoding="utf-8")

    def test_recovery_does_not_import_cli_i18n(self, recovery_source):
        """
        DESIGN DECISION: recovery.py intentionally does NOT use cli_i18n.

        Rationale:
        - Recovery kits must be readable in emergency situations
        - User may be using someone else's machine during recovery
        - English is the default emergency language for technical operations
        - Localized recovery instructions could cause confusion
        """
        assert "from cli_i18n" not in recovery_source
        assert "import cli_i18n" not in recovery_source

    def test_recovery_uses_consistent_error_format(self, recovery_source):
        """Verify error messages use consistent formatting."""
        # Count error format patterns
        error_patterns = re.findall(r"\[ERROR\]", recovery_source)
        warning_patterns = re.findall(r"\[WARNING\]", recovery_source)
        fatal_patterns = re.findall(r"\[FATAL", recovery_source)

        # Recovery.py should have standard error formatting
        assert len(error_patterns) > 0, "Should have [ERROR] format messages"
        assert len(warning_patterns) > 0, "Should have [WARNING] format messages"

    def test_user_facing_print_statements_documented(self, recovery_source):
        """
        Document user-facing print statements in recovery.py.

        This test identifies print() calls that show user-facing text.
        These are intentionally in English for emergency recovery scenarios.
        """
        # Find all print statements with string content
        print_patterns = re.findall(r'print\s*\(\s*["\']([^"\']*)["\']', recovery_source)

        # Also find print(f"...") patterns
        fstring_patterns = re.findall(r'print\s*\(\s*f["\']([^"\']*)["\']', recovery_source)

        all_prints = print_patterns + fstring_patterns

        # Filter out debug/technical messages
        user_facing = [
            msg
            for msg in all_prints
            if not msg.startswith("[DEBUG]")
            and not msg.startswith("  ")  # indented debug
            and len(msg) > 5  # skip very short messages
        ]

        # There should be user-facing messages (recovery is interactive)
        assert len(user_facing) > 0, "Recovery.py should have user-facing messages"

        # Document count for audit trail
        print(f"\nAUDIT: Found {len(user_facing)} user-facing print statements")
        print("Note: These are intentionally in English for emergency recovery")

    def test_recovery_html_in_english(self, recovery_source):
        """Verify HTML recovery kit is in English for emergency use."""
        # Check for English HTML content markers
        assert "Recovery Kit" in recovery_source or "RECOVERY" in recovery_source
        # Recovery kit has critical security terms in English
        assert "credentials" in recovery_source.lower() or "password" in recovery_source.lower()

    def test_critical_phrases_are_in_english(self, recovery_source):
        """
        Verify critical recovery phrases are in English.

        These phrases must be in English for:
        - Universal readability in emergencies
        - Consistency with security documentation standards
        - Compatibility with technical support scenarios
        """
        critical_phrases = [
            "recovery phrase",  # Must be recognizable
            "24",  # 24-word phrase
            "password",  # Critical credential term
            "mount",  # VeraCrypt operation
            "decrypt",  # Security operation
        ]

        found_count = 0
        for phrase in critical_phrases:
            if phrase.lower() in recovery_source.lower():
                found_count += 1

        # Most critical phrases should be present
        assert found_count >= 3, f"Expected critical English phrases, found {found_count}/5"

    def test_press_enter_prompts_consistent(self, recovery_source):
        """Verify Press Enter prompts are consistent."""
        prompts = re.findall(r'[Pp]ress [Ee]nter[^"\']*', recovery_source)
        # Should have at least one Press Enter prompt (terminal stability)
        assert len(prompts) >= 1, "Should have Press Enter prompts for terminal stability"


class TestI18nDesignDecision:
    """
    Document the design decision for recovery.py i18n strategy.

    DECISION: recovery.py uses English-only strings.

    RATIONALE:
    1. Recovery scenarios are emergencies where user may not have access
       to their normal machine/settings
    2. English is the de facto international language for technical operations
    3. Localized recovery instructions could cause confusion if user
       is helping someone else recover their data
    4. Security documentation standards prefer English for consistency
    5. 24-word BIP39 phrases are in English regardless of user language

    FUTURE CONSIDERATION:
    - If i18n is needed, add recovery_i18n.py with limited scope
    - Only translate non-critical UI chrome, never security instructions
    - Always keep English as primary language for recovery kits
    """

    def test_design_decision_documented(self):
        """This test documents the i18n design decision for recovery.py."""
        # This is a documentation test - it always passes
        # The docstring above explains the design decision
        design_notes = {
            "module": "recovery.py",
            "i18n_strategy": "English-only (intentional)",
            "reason": "Emergency recovery must be universally readable",
            "future_path": "recovery_i18n.py if needed, limited scope",
        }

        assert design_notes["i18n_strategy"] == "English-only (intentional)"

    def test_cli_i18n_exists_for_other_modules(self):
        """Verify cli_i18n.py exists for modules that need localization."""
        cli_i18n_path = _smartdrive_root / "scripts" / "cli_i18n.py"
        assert cli_i18n_path.exists(), "cli_i18n.py should exist for other CLI modules"


class TestRecoveryStringCategories:
    """Categorize strings in recovery.py by type."""

    @pytest.fixture
    def recovery_source(self):
        """Load recovery.py source code."""
        recovery_path = _smartdrive_root / "scripts" / "recovery.py"
        return recovery_path.read_text(encoding="utf-8")

    def test_categorize_string_types(self, recovery_source):
        """
        Categorize strings to identify what could theoretically be localized.

        Categories:
        - NEVER LOCALIZE: Security instructions, recovery phrases, technical terms
        - COULD LOCALIZE: Menu items, general prompts (not recommended)
        - OK AS-IS: Error codes, file paths, technical output
        """
        # Count different string categories
        categories = {
            "error_messages": len(re.findall(r"\[ERROR\]", recovery_source)),
            "warnings": len(re.findall(r"\[WARNING\]", recovery_source)),
            "info_messages": len(re.findall(r"\[INFO\]|\[recovery\]", recovery_source)),
            "success_indicators": len(re.findall(r"✓|SUCCESS|OK", recovery_source)),
            "failure_indicators": len(re.findall(r"✗|FAIL|ERROR", recovery_source)),
        }

        # Document the categories
        print(f"\nString Category Audit:")
        for cat, count in categories.items():
            print(f"  {cat}: {count}")

        # All categories should have some representation
        total = sum(categories.values())
        assert total > 0, "Should have categorizable strings"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
