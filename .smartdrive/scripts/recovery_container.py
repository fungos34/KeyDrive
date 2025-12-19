#!/usr/bin/env python3
"""
Recovery Container - Binary Format & Encryption

Provides a sealed container format for recovery credentials:
- MAGIC + VERSION + SALT + NONCE + CIPHERTEXT + TAG
- AES-256-GCM encryption
- Chunking for QR/paper encoding
- Self-contained (all parameters in envelope)

Container holds JSON payload with mount credentials.
"""

import base64
import hashlib
import json
import secrets
import struct
import zlib
from pathlib import Path
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    from argon2.low_level import hash_secret_raw, Type
    ARGON2_AVAILABLE = True
except ImportError:
    ARGON2_AVAILABLE = False


# Container format constants
CONTAINER_MAGIC = b"SDRC"  # SmartDrive Recovery Container
CONTAINER_VERSION = 1
SALT_SIZE = 16  # bytes
NONCE_SIZE = 12  # bytes for AES-GCM
TAG_SIZE = 16   # bytes for AES-GCM


class RecoveryContainerError(Exception):
    """Recovery container operation failed."""
    pass


def check_crypto_available():
    """Check if crypto libraries are available."""
    if not CRYPTO_AVAILABLE:
        raise RecoveryContainerError(
            "cryptography library not installed. Install with: pip install cryptography"
        )


def derive_key_from_phrase(phrase: str, salt: bytes) -> bytes:
    """
    Derive 256-bit encryption key from recovery phrase using Argon2id.
    
    SECURITY: Argon2id is REQUIRED. No fallback to weaker KDF.
    
    Args:
        phrase: Recovery phrase (24 words)
        salt: Random salt (16 bytes)
        
    Returns:
        32-byte encryption key
        
    Raises:
        RecoveryContainerError: If argon2-cffi is not installed
    """
    check_crypto_available()
    
    if not ARGON2_AVAILABLE:
        raise RecoveryContainerError(
            "Recovery requires Argon2id.\n"
            "Install dependencies with:\n"
            "  pip install -r requirements.txt\n\n"
            "Or directly:\n"
            "  pip install argon2-cffi"
        )
    
    phrase_bytes = phrase.encode('utf-8')
    
    # Argon2id parameters (balanced CPU/memory hard)
    # time_cost: iterations
    # memory_cost: memory in KiB (64 MB)
    # parallelism: threads
    key = hash_secret_raw(
        secret=phrase_bytes,
        salt=salt,
        time_cost=3,          # iterations
        memory_cost=65536,    # 64 MB
        parallelism=4,        # threads
        hash_len=32,          # output bytes
        type=Type.ID          # Argon2id (hybrid)
    )
    return key


def create_container(
    credentials: dict,
    phrase: str,
    compress: bool = True
) -> bytes:
    """
    Create encrypted recovery container.
    
    Args:
        credentials: Dict with mount credentials:
            - volume_path: str
            - security_mode: str
            - mount_password: str (optional)
            - keyfile_bytes_b64: str (optional)
            - seed_bytes_b64: str (optional)
            - mount_target: str
            - created_at: str (ISO timestamp)
            - veracrypt_args: dict (optional, text mode flags etc)
        phrase: Recovery phrase (24 words)
        compress: Compress plaintext before encryption
        
    Returns:
        Binary container (bytes)
        
    Container format:
        MAGIC (4 bytes) + VERSION (1 byte) + SALT (16 bytes) + 
        NONCE (12 bytes) + CIPHERTEXT (variable) + TAG (16 bytes)
    """
    check_crypto_available()
    
    # Validate credentials
    required = ["volume_path", "security_mode", "created_at"]
    for field in required:
        if field not in credentials:
            raise RecoveryContainerError(f"Missing required field: {field}")
    
    # Must have at least one credential type
    has_creds = any(k in credentials for k in [
        "mount_password", "keyfile_bytes_b64", "seed_bytes_b64"
    ])
    if not has_creds:
        raise RecoveryContainerError(
            "Container must include at least one credential type"
        )
    
    # Serialize to JSON
    plaintext = json.dumps(credentials, indent=2).encode('utf-8')
    
    # Optional compression
    if compress:
        plaintext = zlib.compress(plaintext, level=9)
    
    # Generate random salt and nonce
    salt = secrets.token_bytes(SALT_SIZE)
    nonce = secrets.token_bytes(NONCE_SIZE)
    
    # Derive encryption key from phrase
    key = derive_key_from_phrase(phrase, salt)
    
    # Encrypt with AES-GCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    # ciphertext includes appended authentication tag
    
    # Build container envelope
    container = bytearray()
    container.extend(CONTAINER_MAGIC)
    container.append(CONTAINER_VERSION)
    container.extend(salt)
    container.extend(nonce)
    container.extend(ciphertext)  # includes tag
    
    return bytes(container)


def decrypt_container(
    container: bytes,
    phrase: str
) -> dict:
    """
    Decrypt recovery container and extract credentials.
    
    Args:
        container: Binary container bytes
        phrase: Recovery phrase
        
    Returns:
        Credentials dict
        
    Raises:
        RecoveryContainerError: Invalid container or wrong phrase
    """
    check_crypto_available()
    
    # Validate magic and version
    if len(container) < 4:
        raise RecoveryContainerError("Container too short")
    
    magic = container[:4]
    if magic != CONTAINER_MAGIC:
        raise RecoveryContainerError(
            f"Invalid container magic: {magic!r} (expected {CONTAINER_MAGIC!r})"
        )
    
    version = container[4]
    if version != CONTAINER_VERSION:
        raise RecoveryContainerError(
            f"Unsupported container version: {version} (expected {CONTAINER_VERSION})"
        )
    
    # Extract envelope components
    offset = 5
    salt = container[offset:offset+SALT_SIZE]
    offset += SALT_SIZE
    
    nonce = container[offset:offset+NONCE_SIZE]
    offset += NONCE_SIZE
    
    ciphertext = container[offset:]  # includes tag
    
    if len(salt) != SALT_SIZE or len(nonce) != NONCE_SIZE:
        raise RecoveryContainerError("Corrupted container (truncated)")
    
    # Derive key from phrase
    try:
        key = derive_key_from_phrase(phrase, salt)
    except Exception as e:
        raise RecoveryContainerError(f"Key derivation failed: {e}")
    
    # Decrypt
    try:
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    except Exception as e:
        raise RecoveryContainerError(
            "Decryption failed - wrong phrase or corrupted container"
        )
    
    # Decompress if needed (try both)
    try:
        decompressed = zlib.decompress(plaintext)
        plaintext = decompressed
    except zlib.error:
        pass  # Not compressed
    
    # Parse JSON
    try:
        credentials = json.loads(plaintext.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RecoveryContainerError(f"Invalid container payload: {e}")
    
    return credentials


def chunk_container_for_paper(
    container: bytes,
    chunk_size: int = 1800
) -> list[str]:
    """
    Split container into base64 chunks for QR encoding.
    
    Each chunk is self-describing with index/total/hash/CRC.
    Order-independent reconstruction.
    
    Args:
        container: Binary container
        chunk_size: Max bytes per chunk (QR size limit ~2953 for alphanumeric)
        
    Returns:
        List of chunk strings formatted as:
        "SDRC:v1:INDEX/TOTAL:HASH:DATA:CRC"
    """
    # Calculate total hash for verification
    total_hash = hashlib.sha256(container).hexdigest()[:16]
    
    # Base64 encode container
    encoded = base64.b64encode(container).decode('ascii')
    
    # Split into chunks
    chunks = []
    total_chunks = (len(encoded) + chunk_size - 1) // chunk_size
    
    for i in range(total_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, len(encoded))
        chunk_data = encoded[start:end]
        
        # Calculate chunk CRC for integrity
        chunk_crc = hashlib.sha256(chunk_data.encode()).hexdigest()[:8]
        
        # Format: SDRC:v1:INDEX/TOTAL:TOTALHASH:DATA:CRC
        chunk_str = f"SDRC:v1:{i+1}/{total_chunks}:{total_hash}:{chunk_data}:{chunk_crc}"
        chunks.append(chunk_str)
    
    return chunks


def reconstruct_from_chunks(chunks: list[str]) -> bytes:
    """
    Reconstruct container from paper chunks (order-independent).
    
    Args:
        chunks: List of chunk strings from scanning QR codes
        
    Returns:
        Reconstructed binary container
        
    Raises:
        RecoveryContainerError: Invalid or incomplete chunks
    """
    if not chunks:
        raise RecoveryContainerError("No chunks provided")
    
    # Parse all chunks
    parsed_chunks = {}
    total_count = None
    expected_hash = None
    
    for chunk_str in chunks:
        parts = chunk_str.strip().split(":")
        
        if len(parts) != 6:
            raise RecoveryContainerError(f"Invalid chunk format: {chunk_str[:50]}...")
        
        magic, version, index_info, total_hash, data, crc = parts
        
        if magic != "SDRC" or version != "v1":
            raise RecoveryContainerError(f"Invalid chunk header: {magic}:{version}")
        
        # Parse index
        try:
            index_str, count_str = index_info.split("/")
            index = int(index_str)
            count = int(count_str)
        except ValueError:
            raise RecoveryContainerError(f"Invalid chunk index: {index_info}")
        
        # Verify consistency
        if total_count is None:
            total_count = count
            expected_hash = total_hash
        else:
            if count != total_count:
                raise RecoveryContainerError(
                    f"Inconsistent chunk count: {count} vs {total_count}"
                )
            if total_hash != expected_hash:
                raise RecoveryContainerError("Chunks from different containers")
        
        # Verify chunk CRC
        actual_crc = hashlib.sha256(data.encode()).hexdigest()[:8]
        if actual_crc != crc:
            raise RecoveryContainerError(f"Chunk {index} corrupted (CRC mismatch)")
        
        # Store chunk data
        if index in parsed_chunks:
            # Duplicate - verify it matches
            if parsed_chunks[index] != data:
                raise RecoveryContainerError(f"Duplicate chunk {index} with different data")
        else:
            parsed_chunks[index] = data
    
    # Check we have all chunks
    if len(parsed_chunks) != total_count:
        missing = set(range(1, total_count + 1)) - set(parsed_chunks.keys())
        raise RecoveryContainerError(
            f"Missing chunks: {sorted(missing)} (have {len(parsed_chunks)}/{total_count})"
        )
    
    # Reconstruct data in order
    encoded = "".join(parsed_chunks[i] for i in range(1, total_count + 1))
    
    # Decode base64
    try:
        container = base64.b64decode(encoded)
    except Exception as e:
        raise RecoveryContainerError(f"Failed to decode container: {e}")
    
    # Verify total hash
    actual_hash = hashlib.sha256(container).hexdigest()[:16]
    if actual_hash != expected_hash:
        raise RecoveryContainerError(
            f"Container hash mismatch: {actual_hash} vs {expected_hash}"
        )
    
    return container


def save_container(container: bytes, output_path: Path):
    """Save container to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(container)


def load_container(input_path: Path) -> bytes:
    """Load container from file."""
    if not input_path.exists():
        raise RecoveryContainerError(f"Container file not found: {input_path}")
    return input_path.read_bytes()
