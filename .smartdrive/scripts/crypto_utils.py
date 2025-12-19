#!/usr/bin/env python3
"""
SmartDrive Cryptographic Utilities

Shared helpers for cryptographic operations across all scripts.
Handles GPG decryption, password derivation, and memory hygiene.
"""

import base64
import hashlib
import hmac
import os
import subprocess
import sys
from pathlib import Path

# =============================================================================
# Core module imports - SINGLE SOURCE OF TRUTH
# =============================================================================
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
if _script_dir.parent.name == ".smartdrive":
    _project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

try:
    from core.constants import CryptoParams
    from core.limits import Limits

    SEED_SIZE = CryptoParams.SEED_SIZE
    SALT_SIZE = CryptoParams.SALT_SIZE
    HKDF_INFO = CryptoParams.HKDF_INFO_DEFAULT.encode("utf-8")
    DERIVED_PW_LENGTH = CryptoParams.DERIVED_PASSWORD_LENGTH
except ImportError:
    # Fallback for standalone operation
    SEED_SIZE = 32
    SALT_SIZE = 16
    HKDF_INFO = b"smartdrive-vc-pw-v1"
    DERIVED_PW_LENGTH = 32


def gpg_decrypt_bytes(path: Path) -> bytes:
    """
    Decrypt GPG file to bytes in memory.
    Prompts for PIN/touch via gpg-agent.
    Returns binary bytes.

    BUG-20251219-001 FIX: Uses --no-tty and timeout to prevent terminal hang.
    """
    # Use Limits.GPG_DECRYPT_TIMEOUT if available, fallback to 30s
    timeout = getattr(Limits, "GPG_DECRYPT_TIMEOUT", 30) if Limits else 30
    try:
        # BUG-20251219-001 FIX: Add --no-tty to prevent terminal hang
        result = subprocess.run(
            ["gpg", "--no-tty", "--decrypt", str(path)], capture_output=True, check=True, timeout=timeout
        )
        return result.stdout  # Binary bytes
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"GPG decryption timed out (check YubiKey)")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"GPG decryption failed: {e.stderr.decode()}")


def derive_veracrypt_password(seed: bytes, salt: bytes) -> str:
    """
    Derive VeraCrypt password from seed using HKDF-SHA256.

    Args:
        seed: High-entropy random bytes (32 bytes)
        salt: Random salt bytes (16-32 bytes)

    Returns:
        ASCII string suitable for VeraCrypt password
    """
    # HKDF implementation for deterministic derivation
    prk = hmac.new(salt, seed, hashlib.sha256).digest()
    info = b"smartdrive-vc-pw-v1"
    length = 32
    t = b""
    okm = b""
    for i in range((length + 31) // 32):
        t = hmac.new(prk, t + info + bytes([i + 1]), hashlib.sha256).digest()
        okm += t
    pw_bytes = okm[:length]

    # Encode as base64url without padding
    encoded = base64.urlsafe_b64encode(pw_bytes).decode("ascii").rstrip("=")

    # Memory hygiene: Overwrite buffer
    pw_buffer = bytearray(pw_bytes)
    for i in range(len(pw_buffer)):
        pw_buffer[i] = 0

    return encoded


def secure_wipe_buffer(buffer: bytearray) -> None:
    """Securely wipe a bytearray buffer in memory."""
    if buffer:
        for i in range(len(buffer)):
            buffer[i] = 0


def generate_salt(length: int = 16) -> bytes:
    """Generate cryptographically secure random salt."""
    return os.urandom(length)


def generate_seed(length: int = 32) -> bytes:
    """Generate cryptographically secure random seed."""
    return os.urandom(length)
