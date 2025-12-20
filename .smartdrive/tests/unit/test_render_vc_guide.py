"""
Unit tests for render_vc_guide function in veracrypt_cli.py

Tests verify:
1. Function accepts notes parameter (API fix)
2. Output is ASCII-safe (no problematic Unicode)
3. All parameters work correctly
"""

import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".smartdrive"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / ".smartdrive" / "scripts"))

from veracrypt_cli import render_vc_guide


class TestRenderVcGuide:
    """Tests for render_vc_guide function."""

    def test_accepts_notes_parameter(self, capsys):
        """Test that render_vc_guide accepts notes parameter without error."""
        steps = [{"text": "Step 1", "substeps": ["Sub-step A", "Sub-step B"]}, "Step 2"]
        notes = ["Note 1", "Note 2"]

        # Should not raise TypeError
        render_vc_guide(title="TEST GUIDE", steps=steps, copy_values={"Key": "Value"}, notes=notes)

        captured = capsys.readouterr()
        assert "TEST GUIDE" in captured.out
        assert "Note 1" in captured.out
        assert "Note 2" in captured.out

    def test_notes_displayed_at_end(self, capsys):
        """Test that notes are displayed after steps."""
        steps = ["Step 1"]
        notes = ["Important note"]

        render_vc_guide("TITLE", steps, notes=notes)

        captured = capsys.readouterr()
        output = captured.out

        # Notes section should appear after STEPS
        steps_pos = output.find("STEPS:")
        notes_pos = output.find("NOTES:")

        assert steps_pos > -1, "STEPS section not found"
        assert notes_pos > -1, "NOTES section not found"
        assert notes_pos > steps_pos, "NOTES should appear after STEPS"

    def test_works_without_notes(self, capsys):
        """Test backward compatibility - works without notes parameter."""
        steps = ["Step 1", "Step 2"]

        # Should not raise - notes defaults to None
        render_vc_guide("TITLE", steps)

        captured = capsys.readouterr()
        assert "TITLE" in captured.out
        assert "Step 1" in captured.out

    def test_ascii_safe_output(self, capsys):
        """Test that output contains no problematic Unicode characters."""
        steps = [{"text": "Step with substeps", "substeps": ["A", "B"]}, "Regular step"]
        notes = ["A note"]

        render_vc_guide("TITLE", steps, {"Key": "Val"}, notes)

        captured = capsys.readouterr()
        output = captured.out

        # Check for problematic Unicode characters that break in elevated PowerShell
        problematic_chars = ["✓", "✗", "⚠️", "❌", "→", "•", "═", "║", "╔", "╗", "╚", "╝"]

        for char in problematic_chars:
            assert char not in output, f"Found problematic Unicode char: {char}"

        # Verify ASCII arrows are used instead
        assert "->" in output, "Should use ASCII arrow (->)"

    def test_copy_values_displayed(self, capsys):
        """Test that copy values are displayed in a copyable format."""
        copy_values = {"Volume Path": "/dev/sdb1", "Password": "secret123"}

        render_vc_guide("TITLE", ["Step"], copy_values=copy_values)

        captured = capsys.readouterr()
        output = captured.out

        # Check for copy values header (SSOT uses "VALUES TO COPY:")
        assert "VALUES TO COPY:" in output
        assert "Volume Path" in output
        assert "/dev/sdb1" in output

    def test_substeps_displayed(self, capsys):
        """Test that substeps are properly displayed with indentation."""
        steps = [{"text": "Main step", "substeps": ["Sub A", "Sub B", "Sub C"]}]

        render_vc_guide("TITLE", steps)

        captured = capsys.readouterr()
        output = captured.out

        assert "Main step" in output
        assert "Sub A" in output
        assert "Sub B" in output
        assert "Sub C" in output


class TestRenderVcGuideEdgeCases:
    """Edge case tests for render_vc_guide."""

    def test_empty_steps(self, capsys):
        """Test handling of empty steps list."""
        render_vc_guide("TITLE", [])

        captured = capsys.readouterr()
        assert "TITLE" in captured.out

    def test_empty_notes(self, capsys):
        """Test that empty notes list doesn't cause issues."""
        render_vc_guide("TITLE", ["Step"], notes=[])

        captured = capsys.readouterr()
        # Empty notes should not display NOTES section
        assert "NOTES:" not in captured.out

    def test_none_copy_values(self, capsys):
        """Test that None copy_values is handled."""
        render_vc_guide("TITLE", ["Step"], copy_values=None)

        captured = capsys.readouterr()
        assert "COPY THESE VALUES:" not in captured.out

    def test_mixed_step_types(self, capsys):
        """Test mixing string steps and dict steps."""
        steps = ["String step", {"text": "Dict step", "substeps": ["Sub"]}, "Another string"]

        render_vc_guide("TITLE", steps)

        captured = capsys.readouterr()
        output = captured.out

        assert "String step" in output
        assert "Dict step" in output
        assert "Another string" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
