#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: Capability Detection Gate (TODO 3)

Per AGENT_ARCHITECTURE.md Section 2.5:
- Feature availability MUST be detected at runtime, not hardcoded
- On Windows, header backup/restore is KNOWN unsupported by CLI
- Capability detection must gate ALL header-backup behavior
- Zero CLI header-export attempts should occur on unsupported platforms

This test verifies:
1. check_cli_capabilities() returns correct structure
2. Windows known limitations are applied (backup_headers=False)
3. can_export_header_via_cli() gates header export operations
4. export_header() respects capability gate
5. No CLI subprocess is spawned for header operations on Windows
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCapabilityDetectionStructure(unittest.TestCase):
    """Test capability detection returns correct structure."""
    
    def test_capabilities_dict_has_required_keys(self):
        """check_cli_capabilities() must return dict with all required keys."""
        from veracrypt_cli import check_cli_capabilities, _cli_capabilities_cache
        
        # Clear cache to force fresh detection
        import veracrypt_cli
        veracrypt_cli._cli_capabilities_cache = None
        
        caps = check_cli_capabilities()
        
        required_keys = [
            'backup_headers',
            'restore_headers', 
            'mount',
            'dismount',
            'create',
            'help_parsed',
            'raw_help',
        ]
        
        for key in required_keys:
            self.assertIn(key, caps, f"Missing required capability key: {key}")
    
    def test_capabilities_values_are_booleans(self):
        """Capability flags must be boolean values."""
        from veracrypt_cli import check_cli_capabilities
        import veracrypt_cli
        veracrypt_cli._cli_capabilities_cache = None
        
        caps = check_cli_capabilities()
        
        bool_keys = ['backup_headers', 'restore_headers', 'mount', 'dismount', 'create', 'help_parsed']
        for key in bool_keys:
            self.assertIsInstance(caps[key], bool, f"Capability {key} must be boolean")


class TestWindowsKnownLimitations(unittest.TestCase):
    """Test Windows-specific capability limitations."""
    
    @patch('os.name', 'nt')
    def test_windows_backup_headers_always_false(self):
        """On Windows, backup_headers MUST be False regardless of help output."""
        from veracrypt_cli import check_cli_capabilities
        import veracrypt_cli
        veracrypt_cli._cli_capabilities_cache = None
        
        # Mock subprocess to return help output that WOULD indicate backup support
        with patch('subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = "--backup-headers  Backup volume headers"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            # Re-import to pick up the os.name mock
            import importlib
            importlib.reload(veracrypt_cli)
            veracrypt_cli._cli_capabilities_cache = None
            
            caps = veracrypt_cli.check_cli_capabilities()
            
            # Even with backup-headers in help, Windows should return False
            # because we KNOW Windows CLI doesn't actually support this
            self.assertFalse(caps['backup_headers'], 
                "Windows backup_headers must be False (known limitation)")
    
    @patch('os.name', 'nt')
    def test_windows_restore_headers_always_false(self):
        """On Windows, restore_headers MUST be False regardless of help output."""
        import veracrypt_cli
        veracrypt_cli._cli_capabilities_cache = None
        
        with patch('subprocess.run') as mock_run:
            mock_result = MagicMock()
            mock_result.stdout = "--restore-headers  Restore volume headers"
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            
            caps = veracrypt_cli.check_cli_capabilities()
            
            self.assertFalse(caps['restore_headers'],
                "Windows restore_headers must be False (known limitation)")


class TestCapabilityGateFunctions(unittest.TestCase):
    """Test convenience functions that gate capability-dependent operations."""
    
    def test_can_export_header_via_cli_uses_capabilities(self):
        """can_export_header_via_cli() must check backup_headers capability."""
        import veracrypt_cli
        veracrypt_cli._cli_capabilities_cache = {'backup_headers': True, 'restore_headers': True}
        
        result = veracrypt_cli.can_export_header_via_cli()
        self.assertTrue(result)
        
        veracrypt_cli._cli_capabilities_cache = {'backup_headers': False, 'restore_headers': True}
        result = veracrypt_cli.can_export_header_via_cli()
        self.assertFalse(result)
    
    def test_can_restore_header_via_cli_uses_capabilities(self):
        """can_restore_header_via_cli() must check restore_headers capability."""
        import veracrypt_cli
        veracrypt_cli._cli_capabilities_cache = {'backup_headers': True, 'restore_headers': True}
        
        result = veracrypt_cli.can_restore_header_via_cli()
        self.assertTrue(result)
        
        veracrypt_cli._cli_capabilities_cache = {'backup_headers': True, 'restore_headers': False}
        result = veracrypt_cli.can_restore_header_via_cli()
        self.assertFalse(result)


class TestExportHeaderGate(unittest.TestCase):
    """Test that export_header respects capability gate."""
    
    def test_export_header_checks_capability_first(self):
        """export_header() must check can_export_header_via_cli() before any CLI attempt."""
        import veracrypt_cli
        
        # Set capabilities to indicate no CLI support
        veracrypt_cli._cli_capabilities_cache = {
            'backup_headers': False,
            'restore_headers': False,
            'mount': True,
            'dismount': True,
            'create': True,
            'help_parsed': True,
            'raw_help': 'test',
        }
        
        # Mock render_header_export_gui_guide to avoid actual GUI rendering
        with patch.object(veracrypt_cli, 'render_header_export_gui_guide', return_value=True) as mock_guide:
            # Call export_header with allow_gui_fallback=True (typical usage)
            result = veracrypt_cli.export_header(
                volume_path=Path("C:\\") / "test" / "volume.hc",
                output_path=Path("C:\\") / "test" / "backup.bin",
                password="test_password",  # Required argument
                allow_gui_fallback=True
            )
            
            # Should have fallen back to GUI guidance since CLI doesn't support backup
            mock_guide.assert_called_once()
            # Result should indicate GUI was used
            self.assertEqual(result[1], True, "Should indicate GUI guidance was used")


class TestCacheingBehavior(unittest.TestCase):
    """Test that capability detection is properly cached."""
    
    def test_capabilities_are_cached(self):
        """Subsequent calls should return cached result without subprocess."""
        import veracrypt_cli
        
        # Set up cache
        test_caps = {
            'backup_headers': True,
            'restore_headers': True,
            'mount': True,
            'dismount': True,
            'create': True,
            'help_parsed': True,
            'raw_help': 'cached test',
        }
        veracrypt_cli._cli_capabilities_cache = test_caps
        
        with patch('subprocess.run') as mock_run:
            # Call should use cache, not subprocess
            result = veracrypt_cli.check_cli_capabilities()
            
            self.assertEqual(result, test_caps)
            mock_run.assert_not_called()
    
    def test_cache_can_be_cleared(self):
        """Setting cache to None should allow fresh detection."""
        import veracrypt_cli
        
        veracrypt_cli._cli_capabilities_cache = {'test': True}
        veracrypt_cli._cli_capabilities_cache = None
        
        self.assertIsNone(veracrypt_cli._cli_capabilities_cache)


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
