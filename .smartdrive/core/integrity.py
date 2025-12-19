# core/integrity.py - SINGLE SOURCE OF TRUTH for integrity validation
"""
Integrity validation for scripts and modules.

This module provides:
- Script hash calculation (deterministic)
- Manifest validation
- GPG signature verification (optional)
- Integrity gate for setup/GUI entry

Usage:
    from core.integrity import Integrity, IntegrityResult
    
    result = Integrity.validate_integrity(launcher_root)
    if not result.valid:
        if not bypass_enabled:
            raise RuntimeError(result.message)
"""

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from core.limits import Limits


@dataclass
class IntegrityResult:
    """Result of integrity validation."""
    
    valid: bool
    expected_hash: Optional[str]
    actual_hash: str
    mismatched_files: List[str] = field(default_factory=list)
    message: str = ""
    signature_valid: Optional[bool] = None  # None = not checked
    signer_info: Optional[str] = None


class Integrity:
    """
    Integrity validation for scripts and modules.
    
    SSOT for all integrity-related operations.
    """
    
    # Manifest file names (relative to integrity dir)
    MANIFEST_FILE = "scripts.sha256"
    SIGNATURE_FILE = "scripts.sha256.sig"
    
    # Scripts included in integrity hash (deterministic order)
    # Must match Paths.REQUIRED_SCRIPTS + security-relevant optional scripts
    HASHED_SCRIPTS = [
        "crypto_utils.py",
        "keyfile.py",
        "mount.py",
        "recovery.py",
        "recovery_container.py",
        "rekey.py",
        "smartdrive.py",
        "unmount.py",
        "veracrypt_cli.py",
    ]
    
    @classmethod
    def calculate_scripts_hash(cls, scripts_dir: Path) -> str:
        """
        Calculate deterministic SHA256 hash of all scripts.
        
        Hash is computed over sorted file list to ensure determinism.
        Each file's name and contents are included to detect renames.
        
        Args:
            scripts_dir: Path to scripts directory
            
        Returns:
            Hex-encoded SHA256 hash
        """
        hasher = hashlib.sha256()
        
        # Process in deterministic order (sorted)
        for script_name in sorted(cls.HASHED_SCRIPTS):
            script_path = scripts_dir / script_name
            if script_path.exists():
                # Include filename in hash to detect renames
                hasher.update(script_name.encode('utf-8'))
                # Include file contents
                hasher.update(script_path.read_bytes())
        
        return hasher.hexdigest()
    
    @classmethod
    def validate_integrity(
        cls,
        launcher_root: Path,
        bypass_enabled: bool = False,
        verify_signature: bool = True
    ) -> IntegrityResult:
        """
        Validate script integrity against signed manifest.
        
        Args:
            launcher_root: Root directory (drive root or repo root)
            bypass_enabled: If True, return valid=True even on failure (with warning)
            verify_signature: If True and GPG available, verify manifest signature
            
        Returns:
            IntegrityResult with validation outcome
        """
        from core.paths import Paths
        
        scripts_dir = Paths.scripts_dir(launcher_root)
        integrity_dir = Paths.integrity_dir(launcher_root)
        manifest_file = integrity_dir / cls.MANIFEST_FILE
        signature_file = integrity_dir / cls.SIGNATURE_FILE
        
        # Calculate actual hash
        actual_hash = cls.calculate_scripts_hash(scripts_dir)
        
        # Check for manifest existence
        if not manifest_file.exists():
            msg = "Integrity manifest not found - scripts may be unsigned"
            if bypass_enabled:
                return IntegrityResult(
                    valid=True,
                    expected_hash=None,
                    actual_hash=actual_hash,
                    mismatched_files=[],
                    message=f"[BYPASSED] {msg}"
                )
            return IntegrityResult(
                valid=False,
                expected_hash=None,
                actual_hash=actual_hash,
                mismatched_files=[],
                message=msg
            )
        
        # Read expected hash from manifest
        try:
            manifest_content = manifest_file.read_text(encoding='utf-8').strip()
            # Format: "HASH  filename" or just "HASH"
            expected_hash = manifest_content.split()[0]
        except Exception as e:
            msg = f"Failed to read manifest: {e}"
            if bypass_enabled:
                return IntegrityResult(
                    valid=True,
                    expected_hash=None,
                    actual_hash=actual_hash,
                    mismatched_files=[],
                    message=f"[BYPASSED] {msg}"
                )
            return IntegrityResult(
                valid=False,
                expected_hash=None,
                actual_hash=actual_hash,
                mismatched_files=[],
                message=msg
            )
        
        # Compare hashes
        hash_matches = actual_hash.lower() == expected_hash.lower()
        
        # Optionally verify GPG signature
        signature_valid = None
        signer_info = None
        
        if verify_signature and signature_file.exists() and shutil.which("gpg"):
            sig_result = cls._verify_gpg_signature(manifest_file, signature_file)
            signature_valid = sig_result[0]
            signer_info = sig_result[1]
        
        # Build result
        if hash_matches:
            msg = "Integrity check passed"
            if signature_valid is True:
                msg += f" (signed by {signer_info})"
            elif signature_valid is False:
                msg += " [WARNING: signature verification failed]"
            
            return IntegrityResult(
                valid=True,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                mismatched_files=[],
                message=msg,
                signature_valid=signature_valid,
                signer_info=signer_info
            )
        else:
            # Hash mismatch
            msg = (
                "INTEGRITY CHECK FAILED\n\n"
                f"Expected: {expected_hash}\n"
                f"Actual:   {actual_hash}\n\n"
                "Scripts may have been modified since signing.\n"
                "This could indicate:\n"
                "  - Legitimate update without re-signing\n"
                "  - Accidental modification\n"
                "  - Malicious tampering\n\n"
                "RECOMMENDED: Re-download from trusted source and verify signatures"
            )
            
            if bypass_enabled:
                return IntegrityResult(
                    valid=True,
                    expected_hash=expected_hash,
                    actual_hash=actual_hash,
                    mismatched_files=["(hash mismatch)"],
                    message=f"[BYPASSED] {msg}",
                    signature_valid=signature_valid,
                    signer_info=signer_info
                )
            
            return IntegrityResult(
                valid=False,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                mismatched_files=["(hash mismatch)"],
                message=msg,
                signature_valid=signature_valid,
                signer_info=signer_info
            )
    
    @classmethod
    def _verify_gpg_signature(
        cls,
        manifest_file: Path,
        signature_file: Path
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify GPG detached signature.
        
        Returns:
            Tuple of (valid: bool, signer_info: Optional[str])
        """
        try:
            result = subprocess.run(
                ["gpg", "--verify", str(signature_file), str(manifest_file)],
                capture_output=True,
                text=True,
                timeout=Limits.GPG_CARD_STATUS_TIMEOUT
            )
            
            if result.returncode == 0:
                # Extract signer info from stderr (GPG outputs there)
                signer = None
                for line in result.stderr.splitlines():
                    if "Good signature from" in line:
                        # Extract quoted name
                        start = line.find('"')
                        end = line.rfind('"')
                        if start != -1 and end > start:
                            signer = line[start+1:end]
                        break
                return (True, signer)
            else:
                return (False, None)
                
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return (False, None)
    
    @classmethod
    def create_manifest(cls, launcher_root: Path) -> Tuple[str, Path]:
        """
        Create integrity manifest (hash file).
        
        Args:
            launcher_root: Root directory
            
        Returns:
            Tuple of (hash: str, manifest_path: Path)
        """
        from core.paths import Paths
        
        scripts_dir = Paths.scripts_dir(launcher_root)
        integrity_dir = Paths.integrity_dir(launcher_root)
        
        # Ensure integrity dir exists
        integrity_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate hash
        hash_value = cls.calculate_scripts_hash(scripts_dir)
        
        # Write manifest
        manifest_path = integrity_dir / cls.MANIFEST_FILE
        manifest_path.write_text(f"{hash_value}  scripts\n", encoding='utf-8')
        
        return (hash_value, manifest_path)
    
    @classmethod
    def sign_manifest(cls, launcher_root: Path, key_id: Optional[str] = None) -> bool:
        """
        Sign the integrity manifest with GPG.
        
        Args:
            launcher_root: Root directory
            key_id: Optional GPG key ID to use (default: default key)
            
        Returns:
            True if signing succeeded
        """
        from core.paths import Paths
        
        integrity_dir = Paths.integrity_dir(launcher_root)
        manifest_file = integrity_dir / cls.MANIFEST_FILE
        signature_file = integrity_dir / cls.SIGNATURE_FILE
        
        if not manifest_file.exists():
            return False
        
        if not shutil.which("gpg"):
            return False
        
        # Remove old signature if exists
        if signature_file.exists():
            signature_file.unlink()
        
        # Build GPG command
        cmd = ["gpg", "--detach-sign"]
        if key_id:
            cmd.extend(["--local-user", key_id])
        cmd.append(str(manifest_file))
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=Limits.GPG_DECRYPT_TIMEOUT
            )
            return result.returncode == 0 and signature_file.exists()
        except (subprocess.TimeoutExpired, Exception):
            return False


def integrity_gate(
    launcher_root: Path,
    bypass_setting: bool = False,
    on_failure: str = "abort"
) -> IntegrityResult:
    """
    Pre-setup/pre-operation integrity gate.
    
    MUST be called before:
    - Entering Setup screen (GUI)
    - Running Setup wizard (CLI)
    - Any security-critical operation
    
    Args:
        launcher_root: Root directory to validate
        bypass_setting: User's bypass preference (from settings/advanced)
        on_failure: "abort" (raise), "warn" (return result), "skip" (return valid)
        
    Returns:
        IntegrityResult
        
    Raises:
        RuntimeError: If on_failure="abort" and validation fails
    """
    result = Integrity.validate_integrity(
        launcher_root,
        bypass_enabled=(bypass_setting or on_failure == "skip")
    )
    
    if not result.valid and on_failure == "abort":
        raise RuntimeError(
            f"Integrity gate failed - aborting operation.\n\n{result.message}"
        )
    
    return result
