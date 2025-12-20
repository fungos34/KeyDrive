#!/usr/bin/env python3
"""
Unit test for deep merge preserving unknown keys
Tests that consolidate_duplicates() preserves nested unknown keys
"""

import sys
import tempfile
import unittest
from pathlib import Path

_test_dir = Path(__file__).resolve().parent
_project_root = _test_dir.parent.parent

if str(_project_root / ".smartdrive") not in sys.path:
    sys.path.insert(0, str(_project_root / ".smartdrive"))

from core.path_resolver import RuntimePaths, _deep_merge, consolidate_duplicates


class TestDeepMergeUnknownKeys(unittest.TestCase):
    """Test deep merge preserves unknown keys."""

    def test_deep_merge_preserves_unknown_keys(self):
        """_deep_merge() should preserve unknown keys."""
        base = {"a": 1, "b": {"c": 2}}
        overlay = {"b": {"d": 3}, "e": 4}

        _deep_merge(base, overlay)

        # All keys preserved
        self.assertEqual(base["a"], 1)
        self.assertEqual(base["b"]["c"], 2)
        self.assertEqual(base["b"]["d"], 3)
        self.assertEqual(base["e"], 4)

    def test_deep_merge_nested_unknown_keys(self):
        """_deep_merge() should preserve deeply nested unknown keys."""
        base = {"known": {"nested": {"value": 1}}, "unknown_root": {"unknown_nested": {"deep": "preserve me"}}}
        overlay = {"known": {"nested": {"value": 2, "new": 3}}, "another_unknown": "also preserve"}

        _deep_merge(base, overlay)

        # Nested unknown keys preserved
        self.assertEqual(base["unknown_root"]["unknown_nested"]["deep"], "preserve me")
        self.assertEqual(base["another_unknown"], "also preserve")
        self.assertEqual(base["known"]["nested"]["value"], 2)
        self.assertEqual(base["known"]["nested"]["new"], 3)

    def test_consolidate_duplicates_preserves_unknown_keys(self):
        """consolidate_duplicates() should preserve unknown keys in config merge."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            paths = RuntimePaths.for_target(target, create_dirs=True)

            # Create canonical config with known key
            # NOTE: Canonical location is now .smartdrive/config.json
            canonical_data = {"known_key": "canonical_value"}
            paths.config_file.write_text(json.dumps(canonical_data), encoding="utf-8")

            # Create duplicate at OLD location (.smartdrive/scripts/config.json)
            dup = target / ".smartdrive" / "scripts" / "config.json"
            dup.parent.mkdir(parents=True, exist_ok=True)
            dup_data = {"unknown_key": "preserve_this"}
            dup.write_text(json.dumps(dup_data), encoding="utf-8")

            # Consolidate
            actions = consolidate_duplicates(paths, dry_run=False)

            # Verify merged config has both keys
            merged = json.loads(paths.config_file.read_text(encoding="utf-8"))
            self.assertIn("known_key", merged)
            self.assertIn("unknown_key", merged)
            self.assertEqual(merged["unknown_key"], "preserve_this")


if __name__ == "__main__":
    unittest.main()
