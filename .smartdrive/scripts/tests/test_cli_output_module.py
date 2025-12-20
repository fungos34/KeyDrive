#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: CLI Output Formatting Module (TODO 9)

Per AGENT_ARCHITECTURE.md Phase 5:
- All user output should route through formatting module
- Module must handle ASCII fallback for broken Windows consoles
- Consistent [INFO]/[WARN]/[ERROR] prefixes

This test verifies:
1. CLIOutput class exists and can be instantiated
2. Auto-detection works for console capabilities
3. ASCII and Unicode modes both work
4. All output methods exist (info, warn, error, step, section, etc.)
5. Module-level convenience functions exist
"""

import os
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCLIOutputInstantiation(unittest.TestCase):
    """Test CLIOutput class can be instantiated."""

    def test_default_instantiation(self):
        """CLIOutput() should work with defaults."""
        from cli_output import CLIOutput

        out = CLIOutput()

        self.assertIsInstance(out, CLIOutput)
        self.assertTrue(hasattr(out, "use_unicode"))
        self.assertTrue(hasattr(out, "width"))

    def test_explicit_unicode_mode(self):
        """CLIOutput with explicit unicode mode."""
        from cli_output import CLIOutput

        out = CLIOutput(use_unicode=True)
        self.assertTrue(out.use_unicode)

        out = CLIOutput(use_unicode=False)
        self.assertFalse(out.use_unicode)

    def test_detect_returns_clioutput(self):
        """CLIOutput.detect() should return CLIOutput instance."""
        from cli_output import CLIOutput

        out = CLIOutput.detect()

        self.assertIsInstance(out, CLIOutput)


class TestCLIOutputMethods(unittest.TestCase):
    """Test all required output methods exist and work."""

    def setUp(self):
        """Create CLIOutput instance for tests."""
        from cli_output import CLIOutput

        self.out = CLIOutput(use_unicode=True, width=70)

    def test_info_method_exists(self):
        """info() method should exist and be callable."""
        self.assertTrue(hasattr(self.out, "info"))
        self.assertTrue(callable(self.out.info))

    def test_warn_method_exists(self):
        """warn() method should exist and be callable."""
        self.assertTrue(hasattr(self.out, "warn"))
        self.assertTrue(callable(self.out.warn))

    def test_error_method_exists(self):
        """error() method should exist and be callable."""
        self.assertTrue(hasattr(self.out, "error"))
        self.assertTrue(callable(self.out.error))

    def test_step_method_exists(self):
        """step() method should exist and be callable."""
        self.assertTrue(hasattr(self.out, "step"))
        self.assertTrue(callable(self.out.step))

    def test_section_method_exists(self):
        """section() method should exist and be callable."""
        self.assertTrue(hasattr(self.out, "section"))
        self.assertTrue(callable(self.out.section))

    def test_separator_method_exists(self):
        """separator() method should exist and be callable."""
        self.assertTrue(hasattr(self.out, "separator"))
        self.assertTrue(callable(self.out.separator))

    def test_bullet_method_exists(self):
        """bullet() method should exist and be callable."""
        self.assertTrue(hasattr(self.out, "bullet"))
        self.assertTrue(callable(self.out.bullet))

    def test_table_method_exists(self):
        """table() method should exist and be callable."""
        self.assertTrue(hasattr(self.out, "table"))
        self.assertTrue(callable(self.out.table))


class TestCLIOutputSymbols(unittest.TestCase):
    """Test symbol sets for Unicode and ASCII modes."""

    def test_unicode_symbols_defined(self):
        """Unicode symbol set should be defined."""
        from cli_output import CLIOutput

        self.assertTrue(hasattr(CLIOutput, "UNICODE_SYMBOLS"))
        self.assertIsInstance(CLIOutput.UNICODE_SYMBOLS, dict)
        self.assertIn("info", CLIOutput.UNICODE_SYMBOLS)
        self.assertIn("warn", CLIOutput.UNICODE_SYMBOLS)
        self.assertIn("error", CLIOutput.UNICODE_SYMBOLS)

    def test_ascii_symbols_defined(self):
        """ASCII symbol set should be defined."""
        from cli_output import CLIOutput

        self.assertTrue(hasattr(CLIOutput, "ASCII_SYMBOLS"))
        self.assertIsInstance(CLIOutput.ASCII_SYMBOLS, dict)
        self.assertIn("info", CLIOutput.ASCII_SYMBOLS)
        self.assertIn("warn", CLIOutput.ASCII_SYMBOLS)
        self.assertIn("error", CLIOutput.ASCII_SYMBOLS)

    def test_unicode_mode_uses_unicode_symbols(self):
        """Unicode mode should use Unicode symbols."""
        from cli_output import CLIOutput

        out = CLIOutput(use_unicode=True)

        # Should use Unicode checkmark
        self.assertEqual(out.sym["info"], CLIOutput.UNICODE_SYMBOLS["info"])

    def test_ascii_mode_uses_ascii_symbols(self):
        """ASCII mode should use ASCII symbols."""
        from cli_output import CLIOutput

        out = CLIOutput(use_unicode=False)

        # Should use ASCII [OK]
        self.assertEqual(out.sym["info"], CLIOutput.ASCII_SYMBOLS["info"])


class TestModuleFunctions(unittest.TestCase):
    """Test module-level convenience functions."""

    def test_get_output_returns_clioutput(self):
        """get_output() should return CLIOutput instance."""
        from cli_output import get_output

        out = get_output()

        from cli_output import CLIOutput

        self.assertIsInstance(out, CLIOutput)

    def test_info_function_exists(self):
        """Module-level info() should exist."""
        from cli_output import info

        self.assertTrue(callable(info))

    def test_warn_function_exists(self):
        """Module-level warn() should exist."""
        from cli_output import warn

        self.assertTrue(callable(warn))

    def test_error_function_exists(self):
        """Module-level error() should exist."""
        from cli_output import error

        self.assertTrue(callable(error))

    def test_step_function_exists(self):
        """Module-level step() should exist."""
        from cli_output import step

        self.assertTrue(callable(step))

    def test_section_function_exists(self):
        """Module-level section() should exist."""
        from cli_output import section

        self.assertTrue(callable(section))


class TestASCIIFallback(unittest.TestCase):
    """Test ASCII fallback for encoding issues."""

    def test_ascii_mode_output_is_safe(self):
        """ASCII mode output should only contain ASCII characters."""
        from cli_output import CLIOutput

        out = CLIOutput(use_unicode=False)

        # All symbols should be ASCII-safe
        for key, symbol in out.sym.items():
            try:
                symbol.encode("ascii")
            except UnicodeEncodeError:
                self.fail(f"Symbol '{key}' = '{symbol}' is not ASCII-safe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
