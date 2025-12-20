#!/usr/bin/env python3
"""
QR Chain Utility - core/qr_chain.py

SINGLE SOURCE OF TRUTH for QR code chunking and reconstruction.

Provides:
- encode_chunks(): Split data into annotated QR-scannable chunks
- decode_chunks(): Reconstruct data from scanned chunks
- QR code generation with error correction

Each chunk contains:
- TYPE: Identifies the data type (SEED, CONFIG, KEYFILE, etc.)
- INDEX/TOTAL: Position and total count
- CHECKSUM: Per-chunk integrity check
- DATA: Base64-encoded payload

Per AGENT_ARCHITECTURE.md:
- Deterministic ordering
- Self-describing format (order-independent reconstruction)
- Integrity verification at chunk and full-data level
"""

import base64
import hashlib
import json
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

# =============================================================================
# Constants
# =============================================================================

# Maximum bytes per chunk for reliable QR scanning
# QR codes can hold ~2900 bytes in binary mode, but for reliability
# with alphanumeric encoding, we use a conservative limit
DEFAULT_CHUNK_SIZE = 1800

# Chunk format version
CHUNK_VERSION = "v1"


# Data type identifiers
class DataType:
    """SSOT for QR chunk data types."""

    SEED_GPG = "SEED"  # GPG-encrypted seed
    CONFIG = "CONFIG"  # Config snapshot JSON
    KEYFILE_GPG = "KEYFILE"  # GPG-encrypted keyfile
    HEADER = "HEADER"  # VeraCrypt header backup
    PHRASE = "PHRASE"  # BIP39 phrase (plain)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ChunkInfo:
    """Information about a single QR chunk."""

    data_type: str
    index: int
    total: int
    checksum: str
    data: str
    full_hash: str  # Hash of complete data (for verification)

    def to_qr_string(self) -> str:
        """
        Format chunk for QR encoding.

        Format: TYPE:VERSION:INDEX/TOTAL:FULLHASH:DATA:CHECKSUM
        """
        return (
            f"{self.data_type}:{CHUNK_VERSION}:{self.index}/{self.total}:{self.full_hash}:{self.data}:{self.checksum}"
        )

    @classmethod
    def from_qr_string(cls, qr_str: str) -> Optional["ChunkInfo"]:
        """Parse a QR string back into ChunkInfo."""
        try:
            parts = qr_str.split(":", 5)
            if len(parts) != 6:
                return None

            data_type = parts[0]
            version = parts[1]
            if version != CHUNK_VERSION:
                # Future: handle version migration
                return None

            pos = parts[2].split("/")
            if len(pos) != 2:
                return None

            index = int(pos[0])
            total = int(pos[1])
            full_hash = parts[3]
            data = parts[4]
            checksum = parts[5]

            return cls(data_type=data_type, index=index, total=total, checksum=checksum, data=data, full_hash=full_hash)
        except (ValueError, IndexError):
            return None


# =============================================================================
# Encoding Functions
# =============================================================================


def _compute_checksum(data: str) -> str:
    """Compute short checksum for chunk integrity."""
    return hashlib.sha256(data.encode()).hexdigest()[:8]


def _compute_full_hash(data: bytes) -> str:
    """Compute hash of full data for verification."""
    return hashlib.sha256(data).hexdigest()[:16]


def encode_chunks(
    data: Union[bytes, str], data_type: str, chunk_size: int = DEFAULT_CHUNK_SIZE, compress: bool = True
) -> List[ChunkInfo]:
    """
    Split data into annotated QR-scannable chunks.

    Each chunk is self-describing with:
    - Type identifier
    - Index and total count
    - Integrity checksum
    - Full data hash (for reconstruction verification)

    Args:
        data: Raw bytes or string to encode
        data_type: Type identifier (use DataType constants)
        chunk_size: Maximum bytes per chunk
        compress: Compress data before encoding (default True)

    Returns:
        List of ChunkInfo objects in order
    """
    # Convert to bytes if string
    if isinstance(data, str):
        data = data.encode("utf-8")

    # Optionally compress
    if compress:
        compressed = zlib.compress(data, level=9)
        # Only use compression if it actually helps
        if len(compressed) < len(data):
            data = compressed

    # Compute full hash before encoding
    full_hash = _compute_full_hash(data)

    # Base64 encode
    encoded = base64.b64encode(data).decode("ascii")

    # Split into chunks
    chunks = []
    total_chunks = (len(encoded) + chunk_size - 1) // chunk_size

    for i in range(total_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, len(encoded))
        chunk_data = encoded[start:end]

        # Compute chunk checksum
        checksum = _compute_checksum(chunk_data)

        chunk = ChunkInfo(
            data_type=data_type,
            index=i + 1,  # 1-indexed for human readability
            total=total_chunks,
            checksum=checksum,
            data=chunk_data,
            full_hash=full_hash,
        )
        chunks.append(chunk)

    return chunks


def encode_file_to_chunks(file_path: Path, data_type: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[ChunkInfo]:
    """
    Encode a file into QR chunks.

    Args:
        file_path: Path to file to encode
        data_type: Type identifier
        chunk_size: Max bytes per chunk

    Returns:
        List of ChunkInfo objects

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    data = file_path.read_bytes()
    return encode_chunks(data, data_type, chunk_size)


def encode_config_snapshot(config: dict) -> List[ChunkInfo]:
    """
    Encode config snapshot as QR chunks.

    Args:
        config: Config dict to encode

    Returns:
        List of ChunkInfo objects
    """
    # Serialize with sorted keys for determinism
    json_str = json.dumps(config, sort_keys=True, indent=None, separators=(",", ":"))
    return encode_chunks(json_str, DataType.CONFIG)


# =============================================================================
# Decoding Functions
# =============================================================================


def decode_chunks(chunks: List[Union[str, ChunkInfo]]) -> Tuple[Optional[bytes], str, List[str]]:
    """
    Reconstruct data from QR chunks.

    Handles out-of-order chunks by sorting on index.
    Verifies chunk integrity via checksums.
    Verifies full data integrity via hash.

    Args:
        chunks: List of QR strings or ChunkInfo objects

    Returns:
        Tuple of:
        - Reconstructed bytes (None if failed)
        - Data type string
        - List of error messages (empty if successful)
    """
    errors = []
    parsed: List[ChunkInfo] = []

    # Parse all chunks
    for chunk in chunks:
        if isinstance(chunk, str):
            info = ChunkInfo.from_qr_string(chunk)
            if info is None:
                errors.append(f"Invalid chunk format: {chunk[:50]}...")
                continue
            parsed.append(info)
        elif isinstance(chunk, ChunkInfo):
            parsed.append(chunk)
        else:
            errors.append(f"Unknown chunk type: {type(chunk)}")

    if not parsed:
        errors.append("No valid chunks found")
        return None, "", errors

    # Verify all chunks are same type and have same total/full_hash
    data_type = parsed[0].data_type
    total = parsed[0].total
    full_hash = parsed[0].full_hash

    for chunk in parsed[1:]:
        if chunk.data_type != data_type:
            errors.append(f"Inconsistent data types: {data_type} vs {chunk.data_type}")
        if chunk.total != total:
            errors.append(f"Inconsistent total count: {total} vs {chunk.total}")
        if chunk.full_hash != full_hash:
            errors.append(f"Inconsistent full hash: {full_hash} vs {chunk.full_hash}")

    # Verify chunk checksums
    for chunk in parsed:
        expected_checksum = _compute_checksum(chunk.data)
        if chunk.checksum != expected_checksum:
            errors.append(f"Chunk {chunk.index} checksum mismatch")

    # Sort by index
    parsed.sort(key=lambda c: c.index)

    # Check for missing chunks
    indices = [c.index for c in parsed]
    expected = list(range(1, total + 1))
    missing = set(expected) - set(indices)
    if missing:
        errors.append(f"Missing chunks: {sorted(missing)}")

    # Check for duplicates
    if len(indices) != len(set(indices)):
        errors.append("Duplicate chunk indices found")

    if errors:
        return None, data_type, errors

    # Reconstruct base64 data
    b64_data = "".join(c.data for c in parsed)

    try:
        # Decode base64
        raw_data = base64.b64decode(b64_data)

        # Verify full hash
        computed_hash = _compute_full_hash(raw_data)
        if computed_hash != full_hash:
            errors.append(f"Full data hash mismatch: expected {full_hash}, got {computed_hash}")
            return None, data_type, errors

        # Try to decompress
        try:
            decompressed = zlib.decompress(raw_data)
            return decompressed, data_type, []
        except zlib.error:
            # Data wasn't compressed
            return raw_data, data_type, []

    except Exception as e:
        errors.append(f"Decode error: {e}")
        return None, data_type, errors


def decode_chunks_to_file(chunks: List[Union[str, ChunkInfo]], output_path: Path) -> Tuple[bool, List[str]]:
    """
    Decode chunks and write to file.

    Args:
        chunks: QR chunk strings or ChunkInfo objects
        output_path: Where to write decoded data

    Returns:
        Tuple of (success, error_messages)
    """
    data, data_type, errors = decode_chunks(chunks)

    if data is None:
        return False, errors

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        return True, []
    except Exception as e:
        return False, [f"Failed to write file: {e}"]


def decode_config_snapshot(chunks: List[Union[str, ChunkInfo]]) -> Tuple[Optional[dict], List[str]]:
    """
    Decode config snapshot from QR chunks.

    Args:
        chunks: QR chunk strings or ChunkInfo objects

    Returns:
        Tuple of (config_dict, error_messages)
    """
    data, data_type, errors = decode_chunks(chunks)

    if data is None:
        return None, errors

    if data_type != DataType.CONFIG:
        errors.append(f"Expected CONFIG type, got {data_type}")
        return None, errors

    try:
        config = json.loads(data.decode("utf-8"))
        return config, []
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, [f"Failed to parse config JSON: {e}"]


# =============================================================================
# QR Code Generation (optional - depends on qrcode library)
# =============================================================================


def _qr_available() -> bool:
    """Check if QR code library is available."""
    try:
        import qrcode

        return True
    except ImportError:
        return False


def generate_qr_data_url(data: str, box_size: int = 4) -> Optional[str]:
    """
    Generate QR code as base64 data URL for embedding in HTML.

    Args:
        data: String data to encode in QR
        box_size: Size of each QR module (smaller = more compact)

    Returns:
        Data URL string (data:image/png;base64,...) or None if unavailable.
    """
    if not _qr_available():
        return None

    try:
        from io import BytesIO

        import qrcode

        qr = qrcode.QRCode(
            version=None,  # Auto-determine size
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=box_size,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

        return f"data:image/png;base64,{b64}"
    except Exception:
        return None


def chunks_to_qr_data_urls(chunks: List[ChunkInfo], box_size: int = 3) -> List[dict]:
    """
    Convert chunks to QR data URLs for embedding.

    Args:
        chunks: List of ChunkInfo objects
        box_size: QR module size

    Returns:
        List of dicts with chunk_num, total, qr_data_url, qr_string
    """
    results = []
    for chunk in chunks:
        qr_str = chunk.to_qr_string()
        qr_url = generate_qr_data_url(qr_str, box_size)

        results.append(
            {
                "chunk_num": chunk.index,
                "total": chunk.total,
                "data_type": chunk.data_type,
                "qr_string": qr_str,
                "qr_data_url": qr_url,
            }
        )

    return results
