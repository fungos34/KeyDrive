#!/usr/bin/env python3
"""
SmartDrive keyfile utility

Manual utility for YubiKey-encrypted file operations:
- Create a new VeraCrypt keyfile encrypted to YubiKeys
- Encrypt any file to YubiKeys
- Decrypt any GPG-encrypted file

Use cases:
- Manual keyfile backup/restore
- Decrypt keyfile for plain VeraCrypt access (migration away from YubiKey)
- Debugging when rekey.py fails
- Encrypt other sensitive files to YubiKeys

Usage:
    python keyfile.py create [--output FILE]     # Generate keyfile + encrypt to YubiKeys
    python keyfile.py encrypt <file>             # Encrypt any file to YubiKeys
    python keyfile.py decrypt <file.gpg> [-o FILE]  # Decrypt GPG-encrypted file

Dependencies (runtime):
- Python 3
- gpg in PATH with YubiKeys configured
"""

import argparse
import hashlib
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ===========================================================================
# Core module imports (single source of truth)
# ===========================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
from core.paths import Paths
if _script_dir.parent.name == Paths.SMARTDRIVE_DIR_NAME:
    # Deployed on drive: .smartdrive/scripts/keyfile.py
    # DEPLOY_ROOT = .smartdrive/, add to path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/keyfile.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.constants import CryptoParams
from core.limits import Limits
from core.paths import Paths
from core.version import VERSION

# Keyfile size from core constants
KEYFILE_SIZE = CryptoParams.KEYFILE_SIZE


def log(msg: str) -> None:
    print(f"[SmartDrive Keyfile] {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def have(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def run_cmd(args, *, check=True, capture_output=False, text=True, input_text=None):
    """Run a subprocess command with basic error handling."""
    try:
        result = subprocess.run(
            args,
            check=check,
            capture_output=capture_output,
            text=text,
            input=input_text,
        )
        return result
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n" f"stderr: {e.stderr}")


def compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def get_available_fingerprints() -> list[tuple[str, str]]:
    """
    Retrieve available GPG key fingerprints from the keyring.
    Returns list of (fingerprint, uid) tuples.
    """
    try:
        result = run_cmd(
            ["gpg", "--list-keys", "--with-colons"],
            check=True,
            capture_output=True,
            text=True,
        )

        fingerprints = []
        current_fpr = None
        current_uid = None

        for line in result.stdout.splitlines():
            parts = line.split(":")
            if parts[0] == "fpr":
                current_fpr = parts[9]
            elif parts[0] == "uid" and current_fpr:
                current_uid = parts[9]
                if current_fpr and current_uid:
                    fingerprints.append((current_fpr, current_uid))
                    current_fpr = None
                    current_uid = None

        return fingerprints
    except Exception:
        return []


def validate_fingerprint(fpr: str) -> str:
    """Validate and normalize a fingerprint string."""
    normalized = fpr.replace(" ", "").upper()

    if len(normalized) != 40:
        raise RuntimeError(f"Invalid fingerprint length: {len(normalized)} (expected 40)")

    if not all(c in "0123456789ABCDEF" for c in normalized):
        raise RuntimeError("Invalid fingerprint: must contain only hex characters")

    return normalized


def prompt_for_fingerprints(available_fprs: list[tuple[str, str]]) -> list[str]:
    """
    Prompt user to select one or more fingerprints.
    Returns list of validated fingerprints.
    """
    selected = []

    print("\nSelect YubiKey(s) for encryption:")
    print("You can select multiple keys (main + backup recommended)")

    if available_fprs:
        print("\nAvailable GPG keys:")
        for i, (fpr, uid) in enumerate(available_fprs, 1):
            formatted = " ".join([fpr[j : j + 4] for j in range(0, len(fpr), 4)])
            print(f"  [{i}] {formatted}")
            print(f"      {uid}")
        print(f"  [m] Enter fingerprint manually")
        print(f"  [d] Done selecting")
        print()

        while True:
            choice = input("Select key [1-9/m/d]: ").strip().lower()

            if choice == "d":
                if not selected:
                    print("Please select at least one key.")
                    continue
                break
            elif choice == "m":
                fpr_input = input("Enter fingerprint (40 hex chars): ").strip()
                try:
                    fpr = validate_fingerprint(fpr_input)
                    if fpr not in selected:
                        selected.append(fpr)
                        log(f"Added: {fpr}")
                    else:
                        print("Already selected.")
                except RuntimeError as e:
                    error(str(e))
            elif choice.isdigit() and 1 <= int(choice) <= len(available_fprs):
                fpr = available_fprs[int(choice) - 1][0]
                if fpr not in selected:
                    selected.append(fpr)
                    log(f"Added: {fpr}")
                else:
                    print("Already selected.")
            else:
                print("Invalid selection.")
    else:
        print("\nNo keys found in keyring. Manual entry required.")
        while True:
            fpr_input = input("Enter fingerprint (40 hex chars) or 'd' when done: ").strip()
            if fpr_input.lower() == "d":
                if not selected:
                    print("Please enter at least one fingerprint.")
                    continue
                break
            try:
                fpr = validate_fingerprint(fpr_input)
                if fpr not in selected:
                    selected.append(fpr)
                    log(f"Added: {fpr}")
            except RuntimeError as e:
                error(str(e))

    return selected


def encrypt_file(input_path: Path, output_path: Path, fingerprints: list[str]) -> None:
    """Encrypt a file to multiple GPG recipients."""
    log(f"Encrypting: {input_path}")
    log(f"Recipients: {len(fingerprints)} key(s)")
    log("(You may be prompted for YubiKey PIN/touch)")

    args = ["gpg", "--encrypt", "--armor", "--output", str(output_path)]
    for fpr in fingerprints:
        args.extend(["--recipient", fpr])
    args.append(str(input_path))

    try:
        run_cmd(args, check=True)
        log(f"✓ Encrypted file: {output_path}")
    except RuntimeError as e:
        raise RuntimeError(f"Encryption failed: {e}")


def decrypt_file(input_path: Path, output_path: Path) -> None:
    """Decrypt a GPG-encrypted file."""
    log(f"Decrypting: {input_path}")
    log("Insert YubiKey and enter PIN when prompted...")

    args = [
        "gpg",
        "--decrypt",
        "--yes",  # Overwrite output if exists
        "--output",
        str(output_path),
        str(input_path),
    ]

    try:
        # Use subprocess.run with timeout to prevent hanging
        result = subprocess.run(args, capture_output=True, text=True, timeout=Limits.TIMEOUT_LONG)  # From core.limits

        if result.returncode != 0:
            raise RuntimeError(f"GPG decryption failed: {result.stderr}")

        log(f"✓ Decrypted file: {output_path}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "GPG decryption timed out. This usually means:\n"
            "1. GPG agent is not running (start Kleopatra)\n"
            "2. YubiKey is not inserted or detected\n"
            "3. Operation was cancelled\n\n"
            "Try: gpg-connect-agent /bye"
        )


def verify_encryption(encrypted_path: Path, original_hash: str) -> bool:
    """Verify encryption by decrypting and comparing hashes."""
    log("Verifying encryption/decryption cycle...")

    tmp_fd, tmp_path = tempfile.mkstemp(prefix="verify_", suffix=".bin")
    os.close(tmp_fd)
    tmp = Path(tmp_path)

    try:
        decrypt_file(encrypted_path, tmp)
        decrypted_hash = compute_sha256(tmp)

        if decrypted_hash != original_hash:
            error(f"Verification FAILED!")
            error(f"  Original:  {original_hash}")
            error(f"  Decrypted: {decrypted_hash}")
            return False

        log(f"✓ Verification successful! SHA256: {original_hash}")
        return True
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


# =============================================================================
# Command: create
# =============================================================================


def cmd_create(args) -> int:
    """Create a new VeraCrypt keyfile encrypted to YubiKeys."""
    log("Creating new VeraCrypt keyfile")

    # Determine output paths
    if args.output:
        encrypted_path = Path(args.output)
        if not encrypted_path.suffix:
            encrypted_path = encrypted_path.with_suffix(".gpg")
        plaintext_path = encrypted_path.with_suffix(".bin")
    else:
        script_dir = Path(__file__).resolve().parent
        keys_dir = script_dir.parent / Paths.KEYS_SUBDIR
        keys_dir.mkdir(parents=True, exist_ok=True)
        plaintext_path = keys_dir / FileNames.KEYFILE_BIN
        encrypted_path = keys_dir / FileNames.KEYFILE_GPG

    # Check if files exist
    if encrypted_path.exists():
        error(f"File already exists: {encrypted_path}")
        print("Delete it first or specify a different output with --output")
        return 1

    # Get YubiKey fingerprints
    available_fprs = get_available_fingerprints()
    try:
        fingerprints = prompt_for_fingerprints(available_fprs)
    except KeyboardInterrupt:
        error("\nAborted.")
        return 1

    # Generate random keyfile
    log(f"Generating random keyfile ({KEYFILE_SIZE} bytes)...")
    random_bytes = secrets.token_bytes(KEYFILE_SIZE)

    plaintext_path.parent.mkdir(parents=True, exist_ok=True)
    with plaintext_path.open("wb") as f:
        f.write(random_bytes)
    log(f"✓ Plaintext keyfile: {plaintext_path}")

    original_hash = compute_sha256(plaintext_path)

    # Encrypt to YubiKeys
    try:
        encrypt_file(plaintext_path, encrypted_path, fingerprints)
    except RuntimeError as e:
        error(str(e))
        return 1

    # Verify
    if not verify_encryption(encrypted_path, original_hash):
        return 1

    # Success message
    print("\n" + "=" * 60)
    print("SUCCESS!")
    print("=" * 60)
    print(f"\nGenerated files:")
    print(f"  Plaintext: {plaintext_path}")
    print(f"  Encrypted: {encrypted_path}")
    print("\nNext steps:")
    print("1. Use the PLAINTEXT keyfile to create your VeraCrypt volume")
    print("2. Test that you can mount the volume with the keyfile")
    print("3. SECURELY DELETE the plaintext keyfile:")
    print(f"   Windows: cipher /w:{plaintext_path}")
    print(f"   Linux:   shred -u {plaintext_path}")
    print("4. Keep only the encrypted version for daily use")
    print("=" * 60 + "\n")

    return 0


# =============================================================================
# Command: encrypt
# =============================================================================


def cmd_encrypt(args) -> int:
    """Encrypt any file to YubiKeys."""
    input_path = Path(args.file)

    if not input_path.exists():
        error(f"File not found: {input_path}")
        return 1

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.with_suffix(input_path.suffix + ".gpg")

    if output_path.exists() and not args.force:
        error(f"Output file exists: {output_path}")
        print("Use --force to overwrite or --output to specify different path")
        return 1

    # Get YubiKey fingerprints
    available_fprs = get_available_fingerprints()
    try:
        fingerprints = prompt_for_fingerprints(available_fprs)
    except KeyboardInterrupt:
        error("\nAborted.")
        return 1

    # Encrypt
    try:
        encrypt_file(input_path, output_path, fingerprints)
    except RuntimeError as e:
        error(str(e))
        return 1

    print(f"\n✓ Encrypted: {output_path}")
    return 0


# =============================================================================
# Command: decrypt
# =============================================================================


def cmd_decrypt(args) -> int:
    """Decrypt a GPG-encrypted file."""
    input_path = Path(args.file)

    if not input_path.exists():
        error(f"File not found: {input_path}")
        return 1

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        # Remove .gpg extension if present
        if input_path.suffix.lower() == ".gpg":
            output_path = input_path.with_suffix("")
        else:
            output_path = input_path.with_suffix(".decrypted")

    if output_path.exists() and not args.force:
        error(f"Output file exists: {output_path}")
        print("Use --force to overwrite or --output to specify different path")
        return 1

    # Decrypt
    try:
        decrypt_file(input_path, output_path)
    except RuntimeError as e:
        error(str(e))
        return 1

    print(f"\n✓ Decrypted: {output_path}")

    # Security warning
    print("\n⚠️  WARNING: The decrypted file contains sensitive data!")
    print("   Securely delete it when done:")
    print(f"   Windows: cipher /w:{output_path}")
    print(f"   Linux:   shred -u {output_path}")

    return 0


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    if not have("gpg"):
        error("gpg not found in PATH. Please install GnuPG.")
        return 1

    parser = argparse.ArgumentParser(
        description="SmartDrive keyfile utility - YubiKey-encrypted file operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python keyfile.py create                    # Create new VeraCrypt keyfile
  python keyfile.py create --output my.gpg   # Create with custom output path
  python keyfile.py encrypt secrets.txt       # Encrypt a file to YubiKeys
  python keyfile.py decrypt secrets.txt.gpg   # Decrypt a file
  python keyfile.py decrypt data.gpg -o out   # Decrypt to specific output
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Create command
    create_parser = subparsers.add_parser("create", help="Create new VeraCrypt keyfile")
    create_parser.add_argument("--output", "-o", help="Output path for encrypted keyfile")

    # Encrypt command
    encrypt_parser = subparsers.add_parser("encrypt", help="Encrypt a file to YubiKeys")
    encrypt_parser.add_argument("file", help="File to encrypt")
    encrypt_parser.add_argument("--output", "-o", help="Output path")
    encrypt_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing")

    # Decrypt command
    decrypt_parser = subparsers.add_parser("decrypt", help="Decrypt a GPG-encrypted file")
    decrypt_parser.add_argument("file", help="File to decrypt")
    decrypt_parser.add_argument("--output", "-o", help="Output path")
    decrypt_parser.add_argument("--force", "-f", action="store_true", help="Overwrite existing")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "create":
        return cmd_create(args)
    elif args.command == "encrypt":
        return cmd_encrypt(args)
    elif args.command == "decrypt":
        return cmd_decrypt(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
