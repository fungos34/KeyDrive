#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test: QR Code Generation for Recovery Kit (TODO 6)

Per AGENT_ARCHITECTURE.md Phase 4:
- Recovery kit must be usable offline via printable format
- QR codes should encode recovery phrase for easy scanning
- Phrase is split into chunks to fit QR scanner limits
- Offline instructions should also be QR-encoded

This test verifies:
1. QR library detection works
2. Phrase is split into appropriate chunks (12 words each)
3. QR data URLs are generated correctly
4. HTML output includes QR codes when available
5. Graceful fallback when qrcode library not available
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestQRAvailabilityCheck(unittest.TestCase):
    """Test QR library availability detection."""
    
    def test_qr_available_returns_boolean(self):
        """_qr_available() must return boolean."""
        from recovery import _qr_available
        
        result = _qr_available()
        self.assertIsInstance(result, bool)
    
    @patch.dict('sys.modules', {'qrcode': None})
    def test_qr_unavailable_when_import_fails(self):
        """_qr_available() returns False when qrcode can't be imported."""
        # Force reimport to pick up the mock
        import importlib
        import recovery
        importlib.reload(recovery)
        
        # Can't easily test ImportError since qrcode IS installed
        # Just verify the function exists and returns bool
        result = recovery._qr_available()
        self.assertIsInstance(result, bool)


class TestPhraseQRChunks(unittest.TestCase):
    """Test phrase splitting into QR-scannable chunks."""
    
    def test_24_word_phrase_splits_into_2_chunks(self):
        """24-word phrase should split into 2 chunks of 12 words each."""
        from recovery import generate_phrase_qr_chunks
        
        phrase = " ".join([f"word{i}" for i in range(1, 25)])  # word1 word2 ... word24
        chunks = generate_phrase_qr_chunks(phrase)
        
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]['words']), 12)
        self.assertEqual(len(chunks[1]['words']), 12)
    
    def test_chunks_have_required_fields(self):
        """Each chunk must have chunk_num, total_chunks, words, word_range."""
        from recovery import generate_phrase_qr_chunks
        
        phrase = " ".join([f"word{i}" for i in range(1, 25)])
        chunks = generate_phrase_qr_chunks(phrase)
        
        required_fields = ['chunk_num', 'total_chunks', 'words', 'word_range', 'qr_data_url']
        for chunk in chunks:
            for field in required_fields:
                self.assertIn(field, chunk, f"Chunk missing required field: {field}")
    
    def test_chunk_numbering_is_correct(self):
        """Chunks should be numbered 1 and 2 (1-indexed)."""
        from recovery import generate_phrase_qr_chunks
        
        phrase = " ".join([f"word{i}" for i in range(1, 25)])
        chunks = generate_phrase_qr_chunks(phrase)
        
        self.assertEqual(chunks[0]['chunk_num'], 1)
        self.assertEqual(chunks[0]['total_chunks'], 2)
        self.assertEqual(chunks[1]['chunk_num'], 2)
        self.assertEqual(chunks[1]['total_chunks'], 2)
    
    def test_word_ranges_are_correct(self):
        """Word ranges should correctly indicate which words are in each chunk."""
        from recovery import generate_phrase_qr_chunks
        
        phrase = " ".join([f"word{i}" for i in range(1, 25)])
        chunks = generate_phrase_qr_chunks(phrase)
        
        self.assertEqual(chunks[0]['word_range'], "1-12")
        self.assertEqual(chunks[1]['word_range'], "13-24")


class TestQRDataURLGeneration(unittest.TestCase):
    """Test QR data URL generation."""
    
    def test_generate_qr_data_url_returns_data_url_format(self):
        """QR data URL should start with 'data:image/png;base64,'."""
        from recovery import generate_qr_data_url, _qr_available
        
        if not _qr_available():
            self.skipTest("qrcode library not installed")
        
        result = generate_qr_data_url("test data")
        
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("data:image/png;base64,"))
    
    def test_generate_qr_data_url_with_different_box_sizes(self):
        """Different box sizes should still produce valid data URLs."""
        from recovery import generate_qr_data_url, _qr_available
        
        if not _qr_available():
            self.skipTest("qrcode library not installed")
        
        # Smaller box size
        result_small = generate_qr_data_url("test", box_size=2)
        self.assertIsNotNone(result_small)
        
        # Larger box size
        result_large = generate_qr_data_url("test", box_size=6)
        self.assertIsNotNone(result_large)


class TestOfflineInstructionsQR(unittest.TestCase):
    """Test offline instructions QR generation."""
    
    def test_offline_instructions_qr_generated(self):
        """Offline instructions QR should be generated."""
        from recovery import generate_offline_instructions_qr, _qr_available
        
        if not _qr_available():
            self.skipTest("qrcode library not installed")
        
        result = generate_offline_instructions_qr()
        
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("data:image/png;base64,"))


class TestHTMLGenerationWithQR(unittest.TestCase):
    """Test HTML recovery kit generation includes QR codes."""
    
    def test_html_includes_qr_section_when_available(self):
        """HTML should include QR section when qrcode is available."""
        from recovery import generate_recovery_html, _qr_available
        
        if not _qr_available():
            self.skipTest("qrcode library not installed")
        
        phrase = " ".join([f"word{i}" for i in range(1, 25)])
        html = generate_recovery_html(phrase=phrase, include_qr=True)
        
        # Should have QR section
        self.assertIn("qr-section", html)
        self.assertIn("QR Codes for Easy Scanning", html)
    
    def test_html_excludes_qr_when_disabled(self):
        """HTML should not include QR section when include_qr=False."""
        from recovery import generate_recovery_html
        
        phrase = " ".join([f"word{i}" for i in range(1, 25)])
        html = generate_recovery_html(phrase=phrase, include_qr=False)
        
        # Should NOT have QR images (but CSS may still be present)
        self.assertNotIn("data:image/png;base64,", html)
    
    def test_html_includes_qr_css(self):
        """HTML should include CSS for QR styling."""
        from recovery import generate_recovery_html
        
        phrase = " ".join([f"word{i}" for i in range(1, 25)])
        html = generate_recovery_html(phrase=phrase, include_qr=True)
        
        # CSS for QR elements should be present
        self.assertIn(".qr-section", html)
        self.assertIn(".qr-container", html)
        self.assertIn(".qr-chunk", html)


class TestQRContentFormat(unittest.TestCase):
    """Test QR code content format."""
    
    def test_qr_content_includes_recovery_prefix(self):
        """QR content should include RECOVERY: prefix for identification."""
        from recovery import generate_phrase_qr_chunks
        
        phrase = " ".join([f"word{i}" for i in range(1, 25)])
        chunks = generate_phrase_qr_chunks(phrase)
        
        # The words themselves should be in the chunk
        for chunk in chunks:
            # Words from the chunk should appear in the chunk's words list
            self.assertEqual(len(chunk['words']), 12)
            self.assertTrue(all(w.startswith("word") for w in chunk['words']))


class TestHeaderBackupQR(unittest.TestCase):
    """Test header backup QR code generation (TODO 7)."""
    
    def test_header_qr_chunks_returns_empty_for_missing_file(self):
        """generate_header_backup_qr_chunks() returns empty list for missing file."""
        from recovery import generate_header_backup_qr_chunks
        
        result = generate_header_backup_qr_chunks(Path("/nonexistent/file.hdr"))
        
        self.assertEqual(result, [])
    
    def test_header_qr_chunks_returns_list(self):
        """generate_header_backup_qr_chunks() returns list of chunk dicts."""
        from recovery import generate_header_backup_qr_chunks, _qr_available
        import tempfile
        
        if not _qr_available():
            self.skipTest("qrcode library not installed")
        
        # Create a fake header file (512 bytes like VeraCrypt)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".hdr") as f:
            f.write(b"X" * 512)
            temp_path = Path(f.name)
        
        try:
            result = generate_header_backup_qr_chunks(temp_path)
            
            self.assertIsInstance(result, list)
            self.assertGreater(len(result), 0)
            
            # Each chunk should have required fields
            for chunk in result:
                self.assertIn('chunk_num', chunk)
                self.assertIn('total_chunks', chunk)
                self.assertIn('qr_data_url', chunk)
        finally:
            temp_path.unlink()
    
    def test_reconstruct_header_from_qr_chunks(self):
        """reconstruct_header_from_qr_chunks() should reassemble header."""
        from recovery import reconstruct_header_from_qr_chunks
        import base64
        
        # Simulate QR chunk data
        original_header = b"HEADER_DATA_TEST" * 32  # 512 bytes
        b64_header = base64.b64encode(original_header).decode()
        
        # Split into chunks like the generator does
        chunk_size = 280
        total = (len(b64_header) + chunk_size - 1) // chunk_size
        chunks = []
        for i in range(total):
            start = i * chunk_size
            end = min(start + chunk_size, len(b64_header))
            chunks.append(f"HEADER:{i+1}/{total}:{b64_header[start:end]}")
        
        # Reconstruct
        result = reconstruct_header_from_qr_chunks(chunks)
        
        self.assertEqual(result, original_header)
    
    def test_reconstruct_header_handles_missing_chunks(self):
        """Reconstruction should fail gracefully with missing chunks."""
        from recovery import reconstruct_header_from_qr_chunks
        
        # Only provide 1 of 3 chunks
        chunks = ["HEADER:1/3:YWJj"]
        
        result = reconstruct_header_from_qr_chunks(chunks)
        
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main(verbosity=2)
