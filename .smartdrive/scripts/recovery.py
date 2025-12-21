#!/usr/bin/env python3
"""
KeyDrive Recovery System

INVARIANT: Recovery NEVER mounts with a recovery password.
           Recovery ALWAYS reconstructs original credentials via encrypted container.
           Header backup is used ONLY for corruption recovery.

This is the sole orchestration layer for:
- generate: Create recovery kit with encrypted credential container
- recover: Use recovery phrase to restore access
- reconstruct: Rebuild container from paper chunks (offline recovery)

Dependencies (must be present):
- mnemonic: BIP39 phrase generation
- cryptography: AES-GCM encryption
- argon2-cffi: Key derivation (optional, falls back to PBKDF2)

Usage:
    python recovery.py generate [--offline]
    python recovery.py recover
    python recovery.py reconstruct <chunks.txt>

Timeout note:
    VeraCrypt mount operations have a 60 seconds timeout.
"""

import argparse
import base64
import datetime
import hashlib
import json
import os
import platform
import random
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

# =============================================================================
# Core module imports - SINGLE SOURCE OF TRUTH
# =============================================================================
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent

# Handle deployed vs development paths:
# Development: scripts/ is at project_root/scripts/, core is at project_root/core/
# Deployed: scripts is at .smartdrive/scripts/, core is at .smartdrive/core/

if _script_dir.parent.name == ".smartdrive":
    # Deployed on drive - core is sibling to scripts under .smartdrive/
    _smartdrive_dir = _script_dir.parent
    _project_root = _smartdrive_dir.parent
    # Add .smartdrive to path so 'from core.x import y' works
    if str(_smartdrive_dir) not in sys.path:
        sys.path.insert(0, str(_smartdrive_dir))
else:
    # Development - project_root/core/ is the target
    pass

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# =============================================================================
# MANDATORY SSOT IMPORTS - NO FALLBACKS ALLOWED
# =============================================================================
# Per AGENT_ARCHITECTURE.md: No fallback redefinitions of ConfigKeys, SecurityMode, etc.
# If import fails, script MUST abort with clear error message.

try:
    from core.constants import Branding, ConfigKeys, CryptoParams, Defaults, FileNames, UserInputs
    from core.limits import Limits
    from core.modes import RecoveryOutcome, SecurityMode
    from core.paths import Paths
    from core.qr_chain import DataType, chunks_to_qr_data_urls, encode_chunks, encode_config_snapshot
    from core.version import VERSION
except ImportError as e:
    # MANDATORY: Abort with clear error - NO FALLBACKS
    print("\\n" + "=" * 70, file=sys.stderr)
    print("CRITICAL: SSOT module import failed", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"\\nImport error: {e}", file=sys.stderr)
    print(f"\\nExpected DEPLOY_ROOT: {_script_dir.parent}", file=sys.stderr)
    print(f"Expected core/ at: {_script_dir.parent / 'core'}", file=sys.stderr)
    print("\\nThe core/ directory must be deployed alongside scripts/.", file=sys.stderr)
    print("\\nTo fix:", file=sys.stderr)
    print("  1. Ensure deployment copied core/ directory", file=sys.stderr)
    print("  2. Re-run setup.py to redeploy", file=sys.stderr)
    print("=" * 70 + "\\n", file=sys.stderr)
    sys.exit(2)

# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY CHECKS - Fail fast if requirements not met
# ─────────────────────────────────────────────────────────────────────────────


def check_dependencies():
    """
    Verify all required dependencies are installed.
    Fails with clear install instructions if any are missing.

    SECURITY: No silent downgrades. All crypto dependencies are REQUIRED.
    """
    missing = []

    try:
        import mnemonic
    except ImportError:
        missing.append("mnemonic")

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        missing.append("cryptography")

    # argon2-cffi is REQUIRED - no silent fallback to weaker KDF
    try:
        import argon2
    except ImportError:
        missing.append("argon2-cffi")

    if missing:
        error_msg = (
            "\n" + "=" * 70 + "\n"
            "MISSING REQUIRED DEPENDENCIES\n" + "=" * 70 + "\n\n"
            f"The following packages are required but not installed:\n\n"
        )
        for pkg in missing:
            error_msg += f"  - {pkg}\n"
        error_msg += (
            f"\nInstall with:\n\n"
            f"  pip install -r requirements.txt\n\n"
            f"Or directly:\n\n"
            f"  pip install {' '.join(missing)}\n\n" + "=" * 70
        )

        # In test environments, raise ImportError instead of sys.exit
        # This allows pytest to skip/handle the import gracefully
        if "pytest" in sys.modules or "unittest" in sys.modules:
            raise ImportError(error_msg)

        print(error_msg)
        sys.exit(1)


# Check dependencies at import time
try:
    check_dependencies()
except ImportError:
    # Re-raise ImportError for test environments
    raise


def _verify_config_keys():
    """
    Verify ConfigKeys is properly imported and contains required attributes.

    This is a startup self-check to catch deployment issues early.
    If ConfigKeys is missing or incomplete, prints actionable error and exits.
    """
    required_attrs = [
        "WINDOWS",
        "UNIX",
        "VOLUME_PATH",
        "MOUNT_LETTER",
        "MOUNT_POINT",
        "MODE",
        "ENCRYPTED_KEYFILE",
        "SEED_GPG_PATH",
        "SALT_B64",
    ]

    missing = []
    for attr in required_attrs:
        if not hasattr(ConfigKeys, attr):
            missing.append(attr)

    if missing:
        print("\n" + "=" * 70, file=sys.stderr)
        print("CRITICAL: ConfigKeys validation failed", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print(f"\nMissing attributes: {', '.join(missing)}", file=sys.stderr)
        print("\nThis indicates a deployment or import issue.", file=sys.stderr)
        print("Ensure the core/ directory is deployed alongside scripts/.", file=sys.stderr)
        print("=" * 70 + "\n", file=sys.stderr)
        sys.exit(2)


# Verify ConfigKeys at startup
_verify_config_keys()


# =============================================================================
# Datetime Helper - Replace deprecated utcnow()
# =============================================================================


def utc_timestamp_iso() -> str:
    """
    Get current UTC timestamp as ISO 8601 string with Z suffix.

    Uses datetime.now(timezone.utc) instead of deprecated utcnow().
    This is Python 3.12+ compatible.

    Returns:
        ISO 8601 timestamp string like "2024-01-15T12:30:45.123456Z"
    """
    # Python 3.11+ recommends datetime.now(timezone.utc) over utcnow()
    # timezone.utc was added in Python 3.2 so this is safe
    from datetime import timezone

    return datetime.datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Now safe to import our modules
def _ensure_recovery_container_on_path():
    """Ensure the directory containing recovery_container.py is on sys.path.

    This helps when running from a deployed `.smartdrive/scripts` location
    where the repository `scripts/` directory isn't on sys.path.
    """
    try:
        import recovery_container  # type: ignore

        return
    except Exception:
        pass

    candidates = []
    # Current script dir
    candidates.append(_script_dir)
    # Project-root scripts dir
    candidates.append(_project_root / "scripts")
    # Walk ancestors to find a sibling 'scripts' directory
    p = Path(__file__).resolve()
    for parent in list(p.parents)[:6]:
        candidates.append(parent / "scripts")

    for c in candidates:
        try:
            if c.exists() and (c / "recovery_container.py").exists():
                s = str(c)
                if s not in sys.path:
                    sys.path.insert(0, s)
                return
        except Exception:
            continue


_ensure_recovery_container_on_path()

# Import mnemonic for BIP39
from mnemonic import Mnemonic
from recovery_container import (
    RecoveryContainerError,
    chunk_container_for_paper,
    create_container,
    decrypt_container,
    load_container,
    reconstruct_from_chunks,
    save_container,
)
from veracrypt_cli import (
    HeaderCorruptionError,
    InvalidCredentialsError,
    VeraCryptError,
    export_header,
    get_mount_status,
    have_veracrypt,
    restore_header,
    try_mount,
    unmount,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
# Determine SMARTDRIVE_DIR (parent of scripts/)
_SMARTDRIVE_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.parent.name == ".smartdrive" else (SCRIPT_DIR.parent / ".smartdrive")
# CONFIG is at .smartdrive/config.json, NOT .smartdrive/scripts/config.json
CONFIG_FILE = _SMARTDRIVE_DIR / "config.json"

# Use Paths for recovery directory (single source of truth)
# RECOVERY_DIR_NAME is the folder name UNDER .smartdrive/, not the full path
try:
    from core.paths import Paths

    RECOVERY_DIR_NAME = Paths.RECOVERY_SUBDIR  # "recovery" (just the folder name)
except ImportError:
    RECOVERY_DIR_NAME = "recovery"  # Fallback - just folder name, NOT ".smartdrive/recovery"

# Recovery config keys
RECOVERY_CONFIG_KEY = "recovery"
POST_RECOVERY_KEY = "post_recovery"

# Recovery states for crash-safe commit ordering
RECOVERY_STATE_ENABLED = "enabled"
RECOVERY_STATE_CONSUMING = "consuming"  # Container deleted, config not yet updated
RECOVERY_STATE_USED = "used"

# Recovery audit log
RECOVERY_LOG_FILE = SCRIPT_DIR / "recovery.log"

# ─────────────────────────────────────────────────────────────────────────────
# RECOVERY OUTCOME CLASSIFICATION (P0)
# ─────────────────────────────────────────────────────────────────────────────
# Every recovery failure path MUST map to exactly one outcome.
# The outcome determines:
#   - Whether retry is safe
#   - Whether recovery state should transition
#   - What the user should do next


class RecoveryOutcome:
    """Deterministic failure classification for recovery operations."""

    SUCCESS = "SUCCESS"  # Recovery complete, kit invalidated

    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"  # Retry safe (mount failed but container intact)

    PERMANENT_FAILURE = "PERMANENT_FAILURE"  # Recovery burned (container deleted)

    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"  # Fix system, retry later (preflight failed)

    USER_ABORT = "USER_ABORT"  # User cancelled intentionally

    @classmethod
    def message(cls, outcome: str) -> str:
        """Get human-readable message for outcome."""
        messages = {
            cls.SUCCESS: (
                "Recovery SUCCESSFUL.\n"
                "Your recovery kit is now PERMANENTLY INVALIDATED.\n"
                "You MUST change credentials and generate a new kit."
            ),
            cls.TRANSIENT_FAILURE: (
                "Recovery FAILED but kit is PRESERVED.\n"
                "You can safely retry recovery after addressing the issue.\n"
                "The recovery container has NOT been consumed."
            ),
            cls.PERMANENT_FAILURE: (
                "Recovery FAILED and kit is BURNED.\n"
                "The recovery container has been consumed.\n"
                "You must restore from a different backup."
            ),
            cls.ENVIRONMENT_FAILURE: (
                "Recovery ABORTED due to environment issues.\n"
                "Fix the reported issues and retry.\n"
                "Recovery kit remains VALID and UNUSED."
            ),
            cls.USER_ABORT: ("Recovery CANCELLED by user.\n" "Recovery kit remains VALID and UNUSED."),
        }
        return messages.get(outcome, f"Unknown outcome: {outcome}")

    @classmethod
    def is_retry_safe(cls, outcome: str) -> bool:
        """Check if retry is safe for this outcome."""
        return outcome in (cls.TRANSIENT_FAILURE, cls.ENVIRONMENT_FAILURE, cls.USER_ABORT)


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────


def log(msg: str):
    """Print a log message."""
    print(f"[Recovery] {msg}")


def error(msg: str):
    """Print an error message."""
    print(f"[ERROR] {msg}", file=sys.stderr)


def warn(msg: str):
    """Print a warning message."""
    print(f"[WARNING] {msg}")


def wait_before_exit(message: str = "Press Enter to continue..."):
    """
    Wait for user input before exiting.

    TERMINAL STABILITY: Prevents premature terminal closure on Windows
    when scripts are launched via double-click. Users can read error
    messages before the window closes.

    Only prompts in interactive mode (tty attached).
    """
    # Only prompt if running in interactive terminal
    try:
        if sys.stdin.isatty():
            input(message)
    except (EOFError, KeyboardInterrupt):
        pass


def clear_terminal() -> None:
    """
    Clear the terminal screen.

    CHG-20251218-001 / BUG-20251218-005:
    Used to clear sensitive information (e.g., recovery phrases) from
    the terminal before verification tests.

    BUG-20251219-002: Preserve scrollback on Windows for consistency.

    Uses platform-appropriate method:
    - Windows: ANSI escape codes (preserves scrollback in modern terminals)
    - Unix: clear command or ANSI escape codes
    """
    if platform.system().lower() == "windows":
        # BUG-20251219-002 FIX: Use ANSI escape codes instead of cls
        # cls can resize/lose scrollback in some terminals
        try:
            # Check if ANSI is supported (Windows 10+)
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            if mode.value & 0x0004:
                print("\033[2J\033[H", end="", flush=True)
                return
        except Exception:
            pass
        # Fallback to cls if ANSI not supported
        os.system("cls")
    else:
        # Try clear command first, fallback to ANSI escape
        result = os.system("clear")
        if result != 0:
            # ANSI escape code fallback
            print("\033[2J\033[H", end="")


def open_html_in_browser(html_path: Path) -> bool:
    """
    Open an HTML file in the default browser using platform-appropriate method.

    BUG-20251221-001 FIX: Replaces webbrowser.open() to prevent Windows
    "syntax error in command line" popups.

    On Windows, webbrowser.open() internally uses os.startfile() or subprocess
    calls that may trigger command-line parsing errors. This function uses
    explicit subprocess calls with CREATE_NO_WINDOW flag on Windows to prevent
    popups and ensure silent execution.

    Args:
        html_path: Path to HTML file to open

    Returns:
        True if browser opened successfully, False on error

    Platform-specific behavior:
        - Windows: Uses 'cmd /c start ""' with CREATE_NO_WINDOW flag
        - macOS: Uses 'open' command
        - Linux: Uses 'xdg-open' command
    """
    try:
        system = platform.system().lower()

        if system == "windows":
            # Use 'cmd /c start ""' with CREATE_NO_WINDOW to prevent popup
            # Empty string "" is required as window title for start command
            subprocess.run(
                ["cmd", "/c", "start", "", str(html_path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
                timeout=5,
            )
        elif system == "darwin":  # macOS
            subprocess.run(
                ["open", str(html_path)],
                check=False,
                timeout=5,
            )
        else:  # Linux and other Unix-like systems
            subprocess.run(
                ["xdg-open", str(html_path)],
                check=False,
                timeout=5,
            )

        log(f"Opened HTML in browser: {html_path}")
        return True

    except Exception as e:
        warn(f"Could not open browser: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# RECOVERY PAGINATION (CHG-20251219-003b)
# ─────────────────────────────────────────────────────────────────────────────


class RecoveryPage:
    """
    Represents a single recovery page with header, content, and navigation.

    CHG-20251219-003b: Implements paginated recovery flow with forward/back navigation.

    SECURITY CONSTRAINTS:
    - Secrets (phrase, password, keyfile) are NEVER stored in page state
    - Going back to secret-entry pages requires re-entry
    - Only non-sensitive metadata is persisted between pages
    """

    def __init__(
        self,
        page_id: str,
        title: str,
        phase: str,
        page_number: int,
        total_pages: int,
        content_renderer: callable = None,
        can_go_back: bool = True,
        requires_secret_reentry: bool = False,
    ):
        self.page_id = page_id
        self.title = title
        self.phase = phase
        self.page_number = page_number
        self.total_pages = total_pages
        self.content_renderer = content_renderer
        self.can_go_back = can_go_back
        self.requires_secret_reentry = requires_secret_reentry
        self.result = None  # Non-sensitive page result only

    def render_header(self) -> None:
        """Render the page header with title, phase, and page number."""
        clear_terminal()
        print("=" * 70)
        print(f"  {Branding.PRODUCT_NAME.upper()} RECOVERY MODE")
        print(f"  Phase: {self.phase}")
        print(f"  [{self.page_number}/{self.total_pages}] {self.title}")
        print("=" * 70)
        print()

    def render(self) -> None:
        """Render the complete page (header + content)."""
        self.render_header()
        if self.content_renderer:
            self.content_renderer(self)

    def get_navigation_options(self) -> str:
        """Get available navigation options for this page."""
        options = []
        if self.can_go_back and self.page_number > 1:
            options.append("[B]ack")
        options.append("[N]ext")
        options.append("[Q]uit")
        return " | ".join(options)


class RecoveryPagination:
    """
    Manages page-based navigation for recovery flow.

    CHG-20251219-003b: Implements discrete pages with header, [B]ack/[N]ext navigation.

    SECURITY INVARIANTS:
    - Secrets stay in local variables only (never in self.page_results)
    - Going back past a secret-entry page clears the in-memory secret reference
    - Only non-sensitive page state is stored for navigation
    """

    PHASES = {
        "PREFLIGHT": "Environment Verification",
        "CONSENT": "Security Consent",
        "PHRASE": "Recovery Phrase Entry",
        "VERIFICATION": "Phrase Verification",
        "CONFIRMATION": "Final Confirmation",
        "DECRYPT": "Container Decryption",
        "MOUNT": "Volume Mount",
        "COMPLETE": "Recovery Complete",
    }

    def __init__(self):
        self.pages: list[RecoveryPage] = []
        self.current_page_index = 0
        self.page_results = {}  # Non-sensitive results only

    def add_page(
        self,
        page_id: str,
        title: str,
        phase: str,
        content_renderer: callable = None,
        can_go_back: bool = True,
        requires_secret_reentry: bool = False,
    ) -> RecoveryPage:
        """Add a page to the recovery flow."""
        page = RecoveryPage(
            page_id=page_id,
            title=title,
            phase=phase,
            page_number=len(self.pages) + 1,
            total_pages=0,  # Will be updated after all pages added
            content_renderer=content_renderer,
            can_go_back=can_go_back,
            requires_secret_reentry=requires_secret_reentry,
        )
        self.pages.append(page)
        return page

    def finalize_pages(self) -> None:
        """Update total_pages after all pages have been added."""
        total = len(self.pages)
        for page in self.pages:
            page.total_pages = total

    def get_current_page(self) -> RecoveryPage:
        """Get the current page."""
        return self.pages[self.current_page_index]

    def navigate_back(self) -> bool:
        """
        Go to the previous page. Returns False if at first page.

        SECURITY: If any page between current and target requires secret reentry,
        the caller is responsible for clearing the secret from memory.
        """
        if self.current_page_index > 0:
            self.current_page_index -= 1
            return True
        return False

    def navigate_next(self) -> bool:
        """Go to the next page. Returns False if at last page."""
        if self.current_page_index < len(self.pages) - 1:
            self.current_page_index += 1
            return True
        return False

    def store_result(self, page_id: str, result: any) -> None:
        """
        Store a NON-SENSITIVE result for a page.

        SECURITY: Never store secrets (phrase, password, keyfile) here.
        """
        self.page_results[page_id] = result

    def get_result(self, page_id: str, default=None) -> any:
        """Get a stored result from a previous page."""
        return self.page_results.get(page_id, default)

    def prompt_navigation(self, allow_back: bool = True, custom_prompt: str = None) -> str:
        """
        Show navigation options and get user choice.

        Returns: 'B' for back, 'N' for next, 'Q' for quit
        """
        page = self.get_current_page()
        options = []

        if allow_back and page.can_go_back and self.current_page_index > 0:
            options.append("[B]ack")
        options.append("[N]ext")
        options.append("[Q]uit")

        prompt = custom_prompt or f"  Navigation: {' | '.join(options)}"
        print(f"\n{prompt}")

        while True:
            try:
                choice = input("  Choice: ").strip().upper()
                if choice == "N":
                    return "N"
                elif choice == "B" and allow_back and page.can_go_back and self.current_page_index > 0:
                    return "B"
                elif choice == "Q":
                    return "Q"
                else:
                    valid = ["N", "Q"]
                    if allow_back and page.can_go_back and self.current_page_index > 0:
                        valid.insert(0, "B")
                    print(f"  Please enter one of: {', '.join(valid)}")
            except (KeyboardInterrupt, EOFError):
                return "Q"

    def pages_requiring_secret_reentry_between(self, from_idx: int, to_idx: int) -> bool:
        """
        Check if any page between from_idx and to_idx requires secret reentry.

        Used to determine if secrets must be cleared when navigating back.
        """
        if to_idx >= from_idx:
            return False  # Not going back
        for idx in range(to_idx, from_idx):
            if self.pages[idx].requires_secret_reentry:
                return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# RECOVERY AUDIT LOG (P1)
# ─────────────────────────────────────────────────────────────────────────────


def audit_log(
    event: str,
    outcome: Optional[str] = None,
    details: Optional[dict] = None,
):
    """
    Append entry to recovery audit log.

    Log format: timestamp | event | outcome | platform | details

    SECURITY: Never log secrets (passwords, keyfiles, phrases).
    This is for post-incident reconstruction only.
    """
    timestamp = utc_timestamp_iso()

    entry = {
        "timestamp": timestamp,
        "event": event,
        "outcome": outcome,
        "platform": {
            "os": platform.system(),
            "os_version": platform.version(),
            "python": platform.python_version(),
        },
    }

    if details:
        # Sanitize - never log secrets
        safe_details = {k: v for k, v in details.items() if k not in ("password", "phrase", "keyfile", "credentials")}
        entry["details"] = safe_details

    try:
        with open(RECOVERY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        # Logging should never break recovery
        pass


def get_veracrypt_version() -> Tuple[Optional[str], Optional[str]]:
    """
    Get VeraCrypt version string with error info.

    Per AGENT_ARCHITECTURE.md: No "unknown" placeholders.
    Returns (version, None) on success, (None, error_reason) on failure.
    """
    import shutil

    # First check if VeraCrypt is available
    vc_path = shutil.which("veracrypt")
    if not vc_path:
        # Try Windows standard path via SSOT
        try:
            from core.paths import Paths

            vc_path = Paths.veracrypt_exe()
            if vc_path and not vc_path.exists():
                vc_path = None
        except ImportError:
            pass

    if not vc_path:
        return None, "VeraCrypt not installed (not found in PATH or standard locations)"

    # Try to get version
    try:
        vc_exe = str(vc_path) if hasattr(vc_path, "__str__") else vc_path

        # Try --version first (Unix-style)
        # On Windows: CREATE_NO_WINDOW prevents GUI popup
        run_kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": Limits.GPG_CARD_STATUS_TIMEOUT,
        }
        if platform.system().lower() == "windows":
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        result = subprocess.run([vc_exe, "--text", "--version"], **run_kwargs)
        if result.returncode == 0 and result.stdout.strip():
            # Parse "VeraCrypt 1.26.7" from output
            for line in result.stdout.split("\n"):
                line = line.strip()
                if "veracrypt" in line.lower():
                    return line, None
            # Return first non-empty line
            lines = [l.strip() for l in result.stdout.split("\n") if l.strip()]
            if lines:
                return lines[0], None

        # Try /? for Windows
        if platform.system().lower() == "windows":
            # On Windows, check file version metadata
            try:
                import ctypes
                from ctypes import wintypes

                # GetFileVersionInfoSize / GetFileVersionInfo
                version_dll = ctypes.windll.version
                size = version_dll.GetFileVersionInfoSizeW(vc_exe, None)
                if size > 0:
                    res = ctypes.create_string_buffer(size)
                    version_dll.GetFileVersionInfoW(vc_exe, 0, size, res)

                    # Extract version string
                    buf = ctypes.c_void_p()
                    length = wintypes.UINT()
                    # Try to get FileVersion
                    if version_dll.VerQueryValueW(
                        res, "\\StringFileInfo\\040904b0\\FileVersion", ctypes.byref(buf), ctypes.byref(length)
                    ):
                        version_str = ctypes.wstring_at(buf, length.value - 1)
                        return f"VeraCrypt {version_str}", None
            except Exception:
                pass

            # Fallback: just report it exists
            return f"VeraCrypt (installed at {vc_exe})", None

        return None, f"Could not determine version (VeraCrypt at {vc_exe})"
    except subprocess.TimeoutExpired:
        return None, "VeraCrypt version check timed out"
    except FileNotFoundError:
        return None, "VeraCrypt executable not found"
    except Exception as e:
        return None, f"Version check failed: {type(e).__name__}: {e}"


def get_requirements_hash() -> Tuple[Optional[str], Optional[str]]:
    """
    Get SHA256 hash of requirements.txt for environment fingerprinting.

    Per AGENT_ARCHITECTURE.md: No "unknown" placeholders.
    Returns (hash, None) on success, (None, error_reason) on failure.
    """
    req_path = SCRIPT_DIR.parent / "requirements.txt"
    if req_path.exists():
        try:
            content = req_path.read_bytes()
            # Normalize: sort lines, strip whitespace, Unix newlines
            lines = sorted(line.strip() for line in content.decode("utf-8").splitlines() if line.strip())
            normalized = "\n".join(lines).encode("utf-8")
            return hashlib.sha256(normalized).hexdigest()[:16], None
        except Exception as e:
            return None, f"Failed to hash requirements.txt: {e}"

    # Try pip freeze as fallback
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=Limits.SUBPROCESS_DEFAULT_TIMEOUT,
        )
        if result.returncode == 0:
            lines = sorted(line.strip() for line in result.stdout.splitlines() if line.strip())
            normalized = "\n".join(lines).encode("utf-8")
            return f"pip:{hashlib.sha256(normalized).hexdigest()[:16]}", None
    except Exception:
        pass

    return None, "requirements.txt not found and pip freeze failed"


def get_volume_identity_info(config: dict = None) -> Tuple[Optional[dict], Optional[str]]:
    """
    Get volume identity information using SSOT types.

    Per AGENT_ARCHITECTURE.md: Use DiskIdentity, VolumeIdentifier from SSOT.
    Returns (identity_dict, None) on success, (None, error_reason) on failure.

    Args:
        config: Optional config dict with volume path info

    Returns:
        Tuple of (identity_dict, error_message)
    """
    try:
        from core.modes import VolumeIdentifier, VolumeIdentifierKind
        from core.safety import DiskIdentity
    except ImportError:
        return None, "SSOT types not available (core.modes, core.safety)"

    identity = {}

    # Extract volume path from config
    if config:
        volume_path = None
        if ConfigKeys.WINDOWS in config:
            volume_path = config[ConfigKeys.WINDOWS].get(ConfigKeys.VOLUME_PATH)
        if not volume_path and ConfigKeys.UNIX in config:
            volume_path = config[ConfigKeys.UNIX].get(ConfigKeys.VOLUME_PATH)

        if volume_path:
            identity[ConfigKeys.VOLUME_PATH] = volume_path

            # Try to create VolumeIdentifier
            try:
                if volume_path.startswith("\\\\?\\Volume{"):
                    vid = VolumeIdentifier.from_volume_guid(volume_path, "config")
                    identity["volume_kind"] = vid.kind.value
                    identity["volume_value"] = vid.value
                elif len(volume_path) == 2 and volume_path[1] == ":":
                    vid = VolumeIdentifier.from_drive_letter(volume_path[0], "config")
                    identity["volume_kind"] = vid.kind.value
                    identity["volume_value"] = vid.value
            except Exception:
                pass

    # Try to get disk identity on Windows
    if platform.system().lower() == "windows" and config:
        try:
            disk_number = config.get("disk_number")
            if disk_number is not None:
                from core.safety import get_target_disk_identity_windows

                disk_id = get_target_disk_identity_windows(disk_number)
                if disk_id:
                    identity["disk_unique_id"] = disk_id.unique_id or "(none)"
                    identity["disk_bus_type"] = disk_id.bus_type or "(unknown)"
                    identity["disk_friendly_name"] = disk_id.friendly_name or "(unknown)"
        except Exception:
            pass

    if identity:
        return identity, None
    else:
        return None, "Could not determine volume identity from config"


def get_environment_snapshot(config: dict = None) -> dict:
    """
    Capture current environment for embedding in recovery kit.

    Per AGENT_ARCHITECTURE.md: No "unknown" placeholders. If a value
    cannot be captured, include error class + reason in "_errors" field.

    Args:
        config: Optional config dict for volume identity lookup

    Returns:
        Environment snapshot dict with collected values and any errors
    """
    snapshot = {
        "python_version": platform.python_version(),
        "python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "os_family": platform.system(),
        "os_version": platform.version(),
        "captured_at": utc_timestamp_iso(),
    }

    errors = {}

    # VeraCrypt version
    vc_version, vc_error = get_veracrypt_version()
    if vc_version:
        snapshot["veracrypt_version"] = vc_version
    else:
        snapshot["veracrypt_version"] = None
        errors["veracrypt_version"] = vc_error

    # Requirements hash
    req_hash, req_error = get_requirements_hash()
    if req_hash:
        snapshot["requirements_hash"] = req_hash
    else:
        snapshot["requirements_hash"] = None
        errors["requirements_hash"] = req_error

    # Volume identity
    vol_id, vol_error = get_volume_identity_info(config)
    if vol_id:
        snapshot["volume_identity"] = vol_id
    else:
        snapshot["volume_identity"] = None
        if vol_error:
            errors["volume_identity"] = vol_error

    # Include errors if any
    if errors:
        snapshot["_errors"] = errors

    return snapshot


# ─────────────────────────────────────────────────────────────────────────────
# QR CODE GENERATION FOR RECOVERY KIT (Phase 4 - P0/P1)
# ─────────────────────────────────────────────────────────────────────────────


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
        warn("qrcode library not installed. QR codes will not be generated.")
        return None

    try:
        import base64
        from io import BytesIO

        import qrcode

        # Create QR code with error correction
        qr = qrcode.QRCode(
            version=None,  # Auto-determine size
            error_correction=qrcode.constants.ERROR_CORRECT_M,  # Medium error correction
            box_size=box_size,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)

        # Generate image
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64 data URL
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

        return f"data:image/png;base64,{b64}"
    except Exception as e:
        warn(f"Failed to generate QR code: {e}")
        return None


def generate_phrase_qr_chunks(phrase: str) -> list:
    """
    Split recovery phrase into QR-scannable chunks.

    A full 24-word BIP39 phrase may exceed simple QR scanner limits,
    so we split into smaller chunks (12 words each) with metadata.

    Returns:
        List of dicts with 'chunk_num', 'total_chunks', 'words', 'qr_data_url'
    """
    words = phrase.split()
    chunk_size = 12  # 12 words per QR code
    total_chunks = (len(words) + chunk_size - 1) // chunk_size

    chunks = []
    for i in range(total_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, len(words))
        chunk_words = words[start:end]

        # Format: "RECOVERY:1/2:word1 word2 word3..."
        data = f"RECOVERY:{i+1}/{total_chunks}:" + " ".join(chunk_words)

        qr_url = generate_qr_data_url(data, box_size=3)

        chunks.append(
            {
                "chunk_num": i + 1,
                "total_chunks": total_chunks,
                "words": chunk_words,
                "word_range": f"{start+1}-{end}",
                "qr_data_url": qr_url,
            }
        )

    return chunks


def generate_offline_instructions_qr() -> Optional[str]:
    """
    Generate QR code containing offline recovery instructions URL/data.

    Points to a URL with detailed recovery steps, or contains
    a compact version of instructions directly.
    """
    # Compact offline recovery instructions
    instructions = (
        "SMARTDRIVE OFFLINE RECOVERY:\n"
        "1. Install Python 3.10+\n"
        "2. pip install mnemonic cryptography\n"
        "3. Run: python recovery.py recover\n"
        "4. Enter 24-word phrase\n"
        "5. After success: python rekey.py\n"
        f"GITHUB: {Paths.REPO_URL}"
    )

    return generate_qr_data_url(instructions, box_size=2)


def generate_header_backup_qr_chunks(header_path: Path) -> list:
    """
    Generate QR codes for VeraCrypt header backup (optional, for offline recovery).

    A VeraCrypt header is 512 bytes. When base64 encoded (~684 bytes), this is
    too large for a single QR code with good error correction. We split into
    multiple chunks (~300 bytes each).

    SECURITY NOTE: The header backup contains encrypted data only - not the password.
    It's safe to store alongside the recovery phrase because both are needed for recovery.

    Args:
        header_path: Path to the header backup file

    Returns:
        List of dicts with chunk_num, total_chunks, qr_data_url
        Empty list if file doesn't exist or QR not available
    """
    if not header_path.exists():
        warn(f"Header backup not found: {header_path}")
        return []

    if not _qr_available():
        return []

    import base64

    try:
        header_bytes = header_path.read_bytes()
        header_b64 = base64.b64encode(header_bytes).decode("ascii")

        # Split into chunks (max ~300 chars per QR for reliable scanning)
        chunk_size = 280
        total_chunks = (len(header_b64) + chunk_size - 1) // chunk_size

        chunks = []
        for i in range(total_chunks):
            start = i * chunk_size
            end = min(start + chunk_size, len(header_b64))
            chunk_data = header_b64[start:end]

            # Format: "HEADER:n/N:base64data"
            data = f"HEADER:{i+1}/{total_chunks}:{chunk_data}"

            qr_url = generate_qr_data_url(data, box_size=2)

            chunks.append(
                {
                    "chunk_num": i + 1,
                    "total_chunks": total_chunks,
                    "qr_data_url": qr_url,
                }
            )

        return chunks
    except Exception as e:
        warn(f"Failed to generate header QR codes: {e}")
        return []


def reconstruct_header_from_qr_chunks(qr_chunks: list) -> Optional[bytes]:
    """
    Reconstruct VeraCrypt header from scanned QR code chunks.

    Args:
        qr_chunks: List of strings in format "HEADER:n/N:base64data"

    Returns:
        Header bytes if successful, None otherwise
    """
    import base64

    try:
        # Parse and sort chunks
        parsed = []
        for chunk in qr_chunks:
            if not chunk.startswith("HEADER:"):
                continue
            parts = chunk.split(":", 2)
            if len(parts) != 3:
                continue
            pos_info = parts[1].split("/")
            if len(pos_info) != 2:
                continue
            chunk_num = int(pos_info[0])
            total = int(pos_info[1])
            data = parts[2]
            parsed.append((chunk_num, total, data))

        if not parsed:
            return None

        # Sort by chunk number
        parsed.sort(key=lambda x: x[0])

        # Verify we have all chunks
        total = parsed[0][1]
        if len(parsed) != total:
            warn(f"Missing header chunks: have {len(parsed)}, need {total}")
            return None

        # Reconstruct
        b64_data = "".join(p[2] for p in parsed)
        return base64.b64decode(b64_data)
    except Exception as e:
        warn(f"Failed to reconstruct header from QR chunks: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MODE-AWARE RECOVERY ARTIFACTS (TODO 4)
# ─────────────────────────────────────────────────────────────────────────────


def collect_mode_artifacts(
    config: dict,
    smartdrive_dir: Path,
) -> Tuple[dict, dict]:
    """
    Collect mode-appropriate artifacts for recovery kit.

    Per AGENT_ARCHITECTURE.md TODO 4:
    - GPG_PW_ONLY: Include seed.gpg (essential for password derivation)
    - PW_GPG_KEYFILE: Include keyfile.vc.gpg (encrypted keyfile)
    - All modes: Include config snapshot (for reconstruction)

    Args:
        config: Current config dict
        smartdrive_dir: Path to .smartdrive directory

    Returns:
        (artifacts_dict, qr_chains_dict):
        - artifacts_dict: {name: bytes} of copied artifacts
        - qr_chains_dict: {name: list[ChunkInfo]} for QR encoding
    """
    artifacts = {}
    qr_chains = {}

    security_mode = config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)  # TODO 6: Use SSOT key
    keys_dir = smartdrive_dir / Paths.KEYS_SUBDIR

    # Config snapshot - all modes
    try:
        # Sanitize config (remove runtime state, keep recovery-relevant fields)
        recovery_config = {
            ConfigKeys.MODE: config.get(ConfigKeys.MODE),  # TODO 6: Use SSOT key
            ConfigKeys.VOLUME_PATH: config.get(ConfigKeys.VOLUME_PATH),
            ConfigKeys.MOUNT_POINT: config.get(ConfigKeys.MOUNT_POINT),
            ConfigKeys.VOLUME_IDENTITY: config.get(ConfigKeys.VOLUME_IDENTITY),
            # KDF params for GPG_PW_ONLY
            ConfigKeys.SALT_B64: config.get(ConfigKeys.SALT_B64, ""),  # TODO 6: Fixed key name
            ConfigKeys.HKDF_INFO: config.get(ConfigKeys.HKDF_INFO, ""),
        }
        # Remove None values
        recovery_config = {k: v for k, v in recovery_config.items() if v is not None}

        config_json = json.dumps(recovery_config, indent=2)
        artifacts["config_snapshot.json"] = config_json.encode("utf-8")

        # Generate QR chunks for config
        config_chunks = encode_config_snapshot(recovery_config)
        if config_chunks:
            qr_chains["config"] = config_chunks
            log(f"  Config snapshot: {len(config_chunks)} QR chunks")
    except Exception as e:
        warn(f"Failed to create config snapshot: {e}")

    # Mode-specific artifacts
    if security_mode == SecurityMode.GPG_PW_ONLY.value:
        # GPG_PW_ONLY: seed.gpg is ESSENTIAL for password derivation
        seed_path = config.get(ConfigKeys.SEED_GPG_PATH, "")
        if seed_path:
            full_seed_path = smartdrive_dir / seed_path
            if full_seed_path.exists():
                try:
                    seed_bytes = full_seed_path.read_bytes()
                    artifacts[FileNames.SEED_GPG] = seed_bytes

                    # Generate QR chunks for seed.gpg
                    seed_chunks = encode_chunks(seed_bytes, DataType.SEED_GPG)
                    if seed_chunks:
                        qr_chains[FileNames.SEED_GPG] = seed_chunks
                        log(f"  {FileNames.SEED_GPG}: {len(seed_bytes)} bytes, {len(seed_chunks)} QR chunks")
                except Exception as e:
                    warn(f"Failed to read {FileNames.SEED_GPG}: {e}")
            else:
                warn(f"{FileNames.SEED_GPG} not found at {full_seed_path}")

    elif security_mode == SecurityMode.PW_GPG_KEYFILE.value:
        # PW_GPG_KEYFILE: keyfile.vc.gpg needed for YubiKey decryption
        keyfile_path = config.get(ConfigKeys.ENCRYPTED_KEYFILE, "")
        if keyfile_path:
            full_keyfile_path = smartdrive_dir / keyfile_path
            if full_keyfile_path.exists():
                try:
                    keyfile_bytes = full_keyfile_path.read_bytes()
                    artifacts[FileNames.KEYFILE_GPG] = keyfile_bytes

                    # Generate QR chunks for keyfile.vc.gpg
                    keyfile_chunks = encode_chunks(keyfile_bytes, DataType.KEYFILE_GPG)
                    if keyfile_chunks:
                        qr_chains["keyfile_gpg"] = keyfile_chunks
                        log(f"  {FileNames.KEYFILE_GPG}: {len(keyfile_bytes)} bytes, {len(keyfile_chunks)} QR chunks")
                except Exception as e:
                    warn(f"Failed to read {FileNames.KEYFILE_GPG}: {e}")
            else:
                warn(f"{FileNames.KEYFILE_GPG} not found at {full_keyfile_path}")
    # PW_ONLY and PW_KEYFILE don't need additional artifacts
    # (password is derived from phrase, plain keyfile is in recovery container)

    return artifacts, qr_chains


def copy_artifacts_to_recovery_dir(
    artifacts: dict,
    recovery_dir: Path,
) -> int:
    """
    Copy collected artifacts to recovery directory.

    Args:
        artifacts: Dict of {filename: bytes}
        recovery_dir: Target recovery directory

    Returns:
        Number of artifacts successfully copied
    """
    copied = 0
    for name, data in artifacts.items():
        try:
            artifact_path = recovery_dir / name
            artifact_path.write_bytes(data)
            log(f"  Saved: {name}")
            copied += 1
        except Exception as e:
            warn(f"Failed to save {name}: {e}")

    return copied


# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT PREFLIGHT CHECK (P0)
# ─────────────────────────────────────────────────────────────────────────────


def run_preflight_checks(
    volume_path: str,
    mount_target: str,
    container_path: Optional[Path] = None,
) -> Tuple[bool, list]:
    """
    Run comprehensive environment checks BEFORE consuming recovery state.

    Preflight failures return ENVIRONMENT_FAILURE - recovery is NOT consumed.

    Checks:
    1. VeraCrypt binary exists and is executable
    2. Target volume path exists and is readable
    3. Mount target is writable (or can be created)
    4. Required privileges present (admin/sudo)
    5. Sufficient disk space for temp operations
    6. Recovery container exists (if path provided)

    Returns:
        (passed: bool, issues: list[str])
    """
    issues = []

    # 1. VeraCrypt binary
    if not have_veracrypt():
        issues.append("VeraCrypt not found in PATH. Install VeraCrypt and ensure it's accessible.")

    # 2. Volume path
    # On Windows, device paths like \\Device\\Harddisk1\\Partition2 can't be checked with Path()
    # Skip filesystem checks for device paths - trust the config value
    is_device_path = volume_path.startswith("\\Device\\") if platform.system().lower() == "windows" else False

    if not is_device_path:
        volume = Path(volume_path)
        if not volume.exists():
            issues.append(f"Volume not found: {volume_path}")
        elif not os.access(volume_path, os.R_OK):
            issues.append(f"Volume not readable: {volume_path} (check permissions)")

    # 3. Mount target
    mount = Path(mount_target)
    if platform.system().lower() == "windows":
        # Windows: drive letter - check if already mounted
        if mount.exists() and any(mount.iterdir()):
            issues.append(f"Mount point {mount_target} is already in use")
    else:
        # Unix: directory path
        if mount.exists():
            if not os.access(mount_target, os.W_OK):
                issues.append(f"Mount point not writable: {mount_target}")
        else:
            # Try to create it
            try:
                mount.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                issues.append(f"Cannot create mount point: {mount_target} (permission denied)")
            except Exception as e:
                issues.append(f"Cannot create mount point: {mount_target} ({e})")

    # 4. Privileges check
    is_windows = platform.system().lower() == "windows"
    if is_windows:
        # Windows: Check for admin (VeraCrypt usually needs it)
        try:
            import ctypes

            if not ctypes.windll.shell32.IsUserAnAdmin():
                issues.append("Not running as Administrator. VeraCrypt may require elevated privileges.")
        except Exception:
            pass  # Can't check, warn anyway
    else:
        # Unix: Check for root or sudo capability
        if os.geteuid() != 0:
            # Not root - check if user is in correct group
            issues.append("Not running as root. VeraCrypt mount typically requires sudo.")

    # 5. Disk space (need ~100MB for temp operations)
    temp_dir = get_ram_temp_dir()
    try:
        stat = shutil.disk_usage(temp_dir)
        if stat.free < 100 * 1024 * 1024:  # 100MB
            issues.append(f"Low disk space in temp directory ({temp_dir}): {stat.free // (1024*1024)}MB free")
    except Exception:
        pass  # Can't check disk space

    # 6. Recovery container (if path provided)
    if container_path and not container_path.exists():
        issues.append(f"Recovery container not found: {container_path}")

    passed = len(issues) == 0
    return passed, issues


def require_windows_consent_for_recovery():
    """
    On Windows, require explicit user consent before recovery.

    VeraCrypt on Windows requires passing password via command line,
    which may expose it to other local processes. User must acknowledge.
    """
    if platform.system().lower() != "windows":
        return  # Non-Windows systems use stdin

    print("\n" + "=" * 70)
    print("  ⚠️  WINDOWS SECURITY WARNING")
    print("=" * 70 + "\n")
    print("VeraCrypt on Windows requires passing the password via command line.")
    print("This may EXPOSE THE PASSWORD to other local processes.")
    print("\nThis is a known limitation of VeraCrypt on Windows.")
    print("On Linux/macOS, passwords are passed via stdin (more secure).\n")
    print("Only continue if:")
    print("  • This system is trusted (no malware)")
    print("  • No untrusted users have local access")
    print("  • You accept the risk of brief password exposure\n")

    confirm = input("Type YES to continue: ").strip()
    if confirm != UserInputs.YES:
        error("Recovery aborted - user did not confirm Windows security risk.")
        sys.exit(1)

    print()  # Blank line before continuing


def check_incomplete_recovery_state(config: dict) -> bool:
    """
    Check for incomplete recovery state from previous crash.

    If state is 'consuming', a previous recovery was interrupted after
    container deletion but before config update. Recovery is burned.

    Returns True if recovery can proceed, False if blocked.
    """
    recovery_config = config.get(RECOVERY_CONFIG_KEY, {})
    state = recovery_config.get("state", RECOVERY_STATE_ENABLED)

    if state == RECOVERY_STATE_CONSUMING:
        print("\n" + "=" * 70)
        print("  ⚠️  INCOMPLETE RECOVERY DETECTED")
        print("=" * 70 + "\n")
        print("A previous recovery attempt was interrupted after the")
        print("recovery container was deleted but before completion.\n")
        print("This recovery kit is now INVALID and cannot be used.")
        print("The container has already been destroyed.\n")
        print("If you need access, you must restore from a different backup.")
        return False

    return True


def check_pending_rekey(config: dict):
    """
    Check if a previous recovery left an incomplete rekey.

    Warns loudly if rekey was required but not completed.
    """
    post_recovery = config.get(POST_RECOVERY_KEY, {})

    if post_recovery.get("rekey_required") and not post_recovery.get("rekey_completed"):
        print("\n" + "=" * 70)
        print("  ⚠️  INCOMPLETE CREDENTIAL CHANGE DETECTED")
        print("=" * 70 + "\n")
        print("A previous recovery completed but credential change was not finished.")
        print("Your OLD CREDENTIALS may still be compromised!\n")
        print("You MUST complete the credential change before proceeding.\n")

        confirm = input("Run credential change now? [Y/n]: ")
        if confirm.lower() != "n":
            rekey_path = SCRIPT_DIR / "rekey.py"
            result = subprocess.run(
                [sys.executable, str(rekey_path)],
                cwd=str(SCRIPT_DIR),
            )
            if result.returncode == 0:
                # Mark rekey as completed
                config[POST_RECOVERY_KEY] = {
                    "rekey_required": False,
                    "rekey_completed": True,
                    "completed_at": utc_timestamp_iso(),
                }
                save_config_atomic(config)
                log("Credential change complete ✓")
            else:
                warn("Rekey did not complete. Run 'python rekey.py' manually.")
        else:
            warn("Proceeding without completing credential change - NOT RECOMMENDED!")


def get_recovery_dir(volume_mount: str) -> Path:
    """
    Get recovery directory path on mounted volume.

    SSOT: Uses Paths.recovery_dir() when available, else constructs from
    known constants. Result is: {volume_mount}/.smartdrive/recovery/
    """
    try:
        return Paths.recovery_dir(Path(volume_mount))
    except NameError:
        # Fallback if Paths not imported - construct canonical path manually
        return Path(volume_mount) / ".smartdrive" / RECOVERY_DIR_NAME


def get_container_path(recovery_dir: Path) -> Path:
    """Get path to recovery container file."""
    return recovery_dir / "recovery_container.bin"


def get_header_path(recovery_dir: Path) -> Path:
    """Get path to header backup file."""
    return recovery_dir / "header_backup.hdr"


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME IDENTITY (P1)
# ─────────────────────────────────────────────────────────────────────────────


def compute_volume_identity(volume_path: str) -> str:
    """
    Compute a stable identity hash for a VeraCrypt volume.

    Uses SHA256 of first 512 bytes (VeraCrypt header area).
    This creates a stable fingerprint that survives password changes
    but uniquely identifies this specific volume.

    Note: After header restore, this will match the backup header.

    TODO 5: Windows \\Device\\Harddisk paths cannot be opened as files.
    Volume identity should be computed ONCE during setup and stored in config.
    This function should only be called for file-based volumes, not device paths.

    Returns:
        Hex string of volume identity hash (first 32 chars of SHA256)
    """
    # TODO 5: Skip Windows device paths - cannot be opened as files
    if volume_path.startswith("\\\\Device\\\\") or volume_path.startswith("\\Device\\"):
        return "device-path-skip"

    # Skip paths that look like Windows device paths (case-insensitive)
    volume_lower = volume_path.lower()
    if "\\device\\" in volume_lower or volume_lower.startswith("\\\\?\\"):
        return "device-path-skip"

    try:
        with open(volume_path, "rb") as f:
            # Read first 512 bytes (salt + encrypted header)
            header_bytes = f.read(512)
            if len(header_bytes) < 512:
                return "unknown-small-volume"
            return hashlib.sha256(header_bytes).hexdigest()[:32]
    except Exception as e:
        warn(f"Could not compute volume identity: {e}")
        return "unknown-read-error"


def verify_volume_identity(
    expected_id: str,
    volume_path: str,
    header_backup_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """
    Verify volume identity matches expected.

    Also checks header backup identity if provided.

    Returns:
        (matches: bool, message: str)
    """
    current_id = compute_volume_identity(volume_path)

    if current_id.startswith("unknown"):
        return True, f"Volume identity unknown ({current_id}), skipping check"

    if expected_id == current_id:
        return True, "Volume identity verified ✓"

    # Check if header backup matches (volume may have been restored already)
    if header_backup_path and header_backup_path.exists():
        try:
            with open(header_backup_path, "rb") as f:
                backup_bytes = f.read(512)
                backup_id = hashlib.sha256(backup_bytes).hexdigest()[:32]
                if backup_id == current_id:
                    return True, "Volume identity matches header backup ✓"
        except Exception:
            pass

    return False, (
        f"VOLUME IDENTITY MISMATCH\\n"
        f"Expected: {expected_id}\\n"
        f"Current:  {current_id}\\n"
        f"This recovery kit may be for a different volume."
    )


def load_config() -> dict:
    """Load config.json, exit if not found."""
    if not CONFIG_FILE.exists():
        error(f"Config file not found: {CONFIG_FILE}")
        sys.exit(1)

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        error(f"Failed to load config: {e}")
        sys.exit(1)


def save_config_atomic(config: dict):
    """
    Atomically write config to disk.

    Writes to temp file, fsyncs, then renames over original.
    This ensures config is never corrupted on crash.
    """
    tmp_path = CONFIG_FILE.with_suffix(".json.tmp")

    try:
        # Write to temp file
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        # Atomic rename
        tmp_path.replace(CONFIG_FILE)

    except Exception as e:
        # Clean up temp file on failure
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def get_volume_info(config: dict) -> Tuple[str, str]:
    """
    Get volume path and mount target from config.

    Returns:
        (volume_path, mount_target) tuple
    """
    system = platform.system().lower()

    if system == "windows":
        volume_path = config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.VOLUME_PATH, "")
        mount_letter = config.get(ConfigKeys.WINDOWS, {}).get(ConfigKeys.MOUNT_LETTER, "V")
        mount_target = f"{mount_letter}:"
    else:
        volume_path = config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.VOLUME_PATH, "")
        mount_target = os.path.expanduser(config.get(ConfigKeys.UNIX, {}).get(ConfigKeys.MOUNT_POINT, "~/veradrive"))

    if not volume_path:
        error("Volume path not configured in config.json")
        sys.exit(1)

    return volume_path, mount_target


def hash_phrase(phrase: str) -> str:
    """
    Create a hash of the recovery phrase for verification.

    This is NOT for security - just to detect typos during recovery.
    Uses first 16 chars of SHA256 hex.
    """
    return hashlib.sha256(phrase.encode("utf-8")).hexdigest()[:16]


def generate_printable_recovery_kit(
    phrase: str,
    phrase_hash: str,
    volume_path: str,
    created_at: str,
    security_mode: str = None,
    gpg_pw_only_info: dict = None,
) -> Path:
    """
    Generate a printable recovery kit (PDF or TXT).

    Includes:
    - 24-word recovery phrase
    - Verification hash
    - Volume path
    - Creation timestamp
    - Security mode specific instructions
    - Recovery instructions and warnings

    Args:
        phrase: The 24-word BIP39 phrase
        phrase_hash: Hash for verification
        volume_path: Path to VeraCrypt volume
        created_at: Creation timestamp
        security_mode: One of: PW_ONLY, PW_KEYFILE, PW_GPG_KEYFILE, GPG_PW_ONLY
        gpg_pw_only_info: For GPG_PW_ONLY mode: {salt_b64, kdf, hkdf_info}

    Returns: Path to generated file, or None on failure
    """
    from datetime import datetime

    # Prepare content
    words = phrase.split()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Security mode description
    mode_description = {
        SecurityMode.PW_ONLY.value: "Password Only (no keyfile)",
        SecurityMode.PW_KEYFILE.value: "Password + Plain Keyfile",
        SecurityMode.PW_GPG_KEYFILE.value: "Password + GPG-Encrypted Keyfile (YubiKey)",
        SecurityMode.GPG_PW_ONLY.value: "GPG-Derived Password (YubiKey, no user password)",
    }.get(security_mode, "Unknown")

    content = f"""
{'='*80}
                    VERACRYPT RECOVERY KIT
{'='*80}

GENERATED:      {timestamp}
VOLUME:         {volume_path}
CREATED:        {created_at}
SECURITY MODE:  {mode_description}

{'='*80}
                    24-WORD RECOVERY PHRASE
{'='*80}

WRITE THIS PHRASE ON PAPER AND STORE IT SECURELY.
WITHOUT THIS PHRASE, YOUR ENCRYPTED DATA CANNOT BE RECOVERED.

"""

    # Format phrase (4 rows of 6 words each)
    for i in range(0, 24, 6):
        row = ""
        for j in range(6):
            idx = i + j
            row += f"{idx+1:2}. {words[idx]:12}  "
        content += row.rstrip() + "\n"

    content += f"""
{'-'*80}
VERIFICATION HASH: {phrase_hash}
{'-'*80}

"""

    # Add GPG_PW_ONLY specific info if applicable
    if security_mode == SecurityMode.GPG_PW_ONLY.value and gpg_pw_only_info:
        content += f"""
{'='*80}
                    GPG_PW_ONLY MODE - CRITICAL INFO
{'='*80}

In this mode, your VeraCrypt password is DERIVED from a cryptographic seed.
You do not know the actual password - it's generated automatically.

To recover, you need:
1. This 24-word phrase (to recreate the seed)
2. Your YubiKey (for GPG decryption)
3. The KDF parameters below

KDF (Key Derivation Function): {gpg_pw_only_info.get('kdf', 'hkdf-sha256')}
SALT (base64): {gpg_pw_only_info.get('salt_b64', '(missing)')}
HKDF INFO: {gpg_pw_only_info.get('hkdf_info', CryptoParams.HKDF_INFO_DEFAULT)}

The recovery process will:
1. Decrypt your seed using GPG (YubiKey required)
2. Derive the password using: HKDF(seed, salt, info)
3. Mount your volume with the derived password

"""

    content += f"""
{'='*80}
                    RECOVERY INSTRUCTIONS
{'='*80}

TO RECOVER YOUR VOLUME:

1. Run the setup script again and choose "RECOVER existing volume"
2. Enter all 24 words IN EXACT ORDER when prompted
3. The script will derive your password and keyfile from the phrase
4. Your volume will be automatically mounted
"""

    # Mode-specific recovery instructions
    if security_mode == SecurityMode.PW_ONLY.value:
        content += """
FOR PW_ONLY MODE:
- The recovery phrase will derive your VeraCrypt password
- No keyfile is used
"""
    elif security_mode == SecurityMode.PW_KEYFILE.value:
        content += """
FOR PW_KEYFILE MODE:
- The recovery phrase will derive both password AND keyfile
- Ensure the keyfile path is accessible
"""
    elif security_mode == SecurityMode.PW_GPG_KEYFILE.value:
        content += """
FOR PW_GPG_KEYFILE MODE:
- The recovery phrase will derive your password
- You will need your YubiKey to decrypt the keyfile
- Ensure GPG is installed and your YubiKey is available
"""
    elif security_mode == SecurityMode.GPG_PW_ONLY.value:
        content += """
FOR GPG_PW_ONLY MODE:
- The recovery phrase recreates your seed
- Your YubiKey derives the actual password from the seed
- You MUST have your YubiKey to recover
- If you lose your YubiKey: use the KDF params above to derive manually
"""

    content += f"""

CRITICAL WARNINGS:

⚠️  NEVER share this phrase with anyone
⚠️  Store this document in a physically secure location
⚠️  Consider storing copies in multiple secure locations
⚠️  If someone obtains this phrase, they can decrypt your data
⚠️  Test recovery BEFORE deleting any backups

{'='*80}
                    VERIFICATION HASH USAGE
{'='*80}

The verification hash above can be used to check if you typed the phrase
correctly during recovery WITHOUT revealing the actual phrase.

When recovering, the script will show you a hash of what you entered.
Compare it to the hash above - if they match, you typed it correctly.

{'='*80}
"""

    # Decide output format - try PDF first, fallback to TXT
    output_dir = Path.home() / "Documents" / "VeraCrypt_Recovery"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Try PDF generation
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

        pdf_filename = f"VeraCrypt_Recovery_Kit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = output_dir / pdf_filename

        doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        # Add content as preformatted text
        pre_style = styles["Code"]
        pre_style.fontSize = 9
        pre_style.fontName = "Courier"

        story.append(Preformatted(content, pre_style))
        doc.build(story)

        return pdf_path

    except ImportError:
        # Fallback to TXT
        txt_filename = f"VeraCrypt_Recovery_Kit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        txt_path = output_dir / txt_filename

        txt_path.write_text(content, encoding="utf-8")
        return txt_path

    except Exception as e:
        error(f"Could not generate PDF: {e}")
        # Fallback to TXT
        txt_filename = f"VeraCrypt_Recovery_Kit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        txt_path = output_dir / txt_filename

        txt_path.write_text(content, encoding="utf-8")
        return txt_path


def verify_bip39_phrase(phrase: str) -> bool:
    """
    Verify a phrase has valid BIP39 checksum.

    Returns True if valid, False otherwise.
    """
    try:
        m = Mnemonic("english")
        return m.check(phrase)
    except Exception:
        return False


def generate_bip39_phrase() -> str:
    """
    Generate a 24-word BIP39 recovery phrase.

    Uses the mnemonic library with 256-bit entropy.
    This gives 24 words with valid checksum.
    """
    m = Mnemonic("english")
    # 256 bits = 24 words
    entropy = secrets.token_bytes(32)
    return m.to_mnemonic(entropy)


def verify_phrase_recording(phrase: str) -> bool:
    """
    Verify user has correctly recorded the phrase.

    SECURITY: Redacts the phrase words with "****" keeping word indices visible.
    This forces the user to verify from their written copy, not the screen.
    Per AGENT_ARCHITECTURE.md: Manual steps acknowledged, not hidden.

    NOTE: Does NOT clear the screen - redacts in place so user can see
    the format and word count but not the actual words.

    Randomly selects 3 words and asks user to re-enter them.
    Returns True if all correct, False otherwise.
    """
    words = phrase.split()

    # Select 3 random indices for verification
    indices = sorted(random.sample(range(len(words)), 3))

    # SECURITY: Display redacted phrase - user sees word positions but not content
    # This acknowledges the phrase exists and shows format, but forces verification
    # from written copy
    redacted_words = ["****" for _ in words]
    redacted_display = " ".join(f"{i+1}:{w}" for i, w in enumerate(redacted_words))

    print("\n" + "=" * 70)
    print("  VERIFICATION: Confirm you recorded the phrase correctly")
    print("=" * 70)
    print("\n  The recovery phrase has been REDACTED below.")
    print("  You must enter the requested words from your WRITTEN copy.")
    print("\n  This ensures you have a valid backup before continuing.")
    print("\n  Redacted phrase (word positions only):")
    print(f"  {redacted_display}")
    print("\n" + "-" * 70)
    print("  Enter the requested words from your recovery phrase:\n")

    for idx in indices:
        # 1-indexed for human readability
        word_num = idx + 1
        prompt = f"  Word #{word_num}: "

        try:
            entered = input(prompt).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n\nVerification cancelled.")
            return False

        if entered != words[idx].lower():
            print(f"\n  ❌ Incorrect! Word #{word_num} does not match.")
            return False

        print("  ✓ Correct")

    print("\n  ✓ All words verified correctly!")
    return True


def get_ram_temp_dir() -> Path:
    """Get a RAM-backed temp directory if available, else system temp."""
    if platform.system() == "Linux":
        ram_dir = Path("/dev/shm")
        if ram_dir.exists() and os.access(ram_dir, os.W_OK):
            return ram_dir
    elif platform.system() == "Darwin":
        ram_dir = Path("/tmp")
        if ram_dir.exists() and os.access(ram_dir, os.W_OK):
            return ram_dir
    return Path(tempfile.gettempdir())


def secure_delete(file_path: Path, passes: int = 3):
    """Securely delete a file by overwriting with random data."""
    if not file_path.exists():
        return
    try:
        file_size = file_path.stat().st_size
        with open(file_path, "rb+") as f:
            for _ in range(passes):
                f.seek(0)
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())
        file_path.unlink()
    except Exception:
        # Fallback to regular delete
        try:
            file_path.unlink()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# AUTHENTICATION
# ─────────────────────────────────────────────────────────────────────────────


def authenticate_for_generate(config: dict) -> dict:
    """
    Authenticate user and collect credentials for container generation.

    Either:
    1. Verifies volume is mounted + prompts for password, OR
    2. Performs test mount with provided credentials

    For GPG_PW_ONLY mode:
    - Derives password from GPG-encrypted seed (YubiKey required)
    - User does NOT input password

    Returns:
        Credential dict with: password, keyfile_bytes (if applicable), volume_path, etc.
        For GPG_PW_ONLY: includes salt_b64, kdf, hkdf_info for recovery

    Raises:
        SystemExit if authentication fails
    """
    from getpass import getpass

    volume_path, mount_target = get_volume_info(config)
    mode = config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)

    log("Authenticating for recovery kit generation...")

    # Check if already mounted
    is_mounted = False
    if platform.system().lower() == "windows":
        is_mounted = Path(mount_target).exists() and any(Path(mount_target).iterdir())
    else:
        is_mounted = os.path.ismount(mount_target)

    if is_mounted:
        log(f"Volume is mounted at {mount_target}")
        log("Will collect credentials from your input.")
    else:
        log("Volume is not mounted. Will test credentials before proceeding.")

    # Handle GPG_PW_ONLY mode: derive password from GPG-encrypted seed
    if mode == SecurityMode.GPG_PW_ONLY.value:
        log("GPG_PW_ONLY mode: Deriving password from encrypted seed...")

        # Get seed path
        seed_path = config.get(ConfigKeys.SEED_GPG_PATH, "")
        if seed_path.startswith("../"):
            seed_path = seed_path[3:]  # Remove "../"
        seed_full_path = (SCRIPT_DIR.parent / seed_path).resolve()

        if not seed_full_path.exists():
            error(f"Encrypted seed not found: {seed_full_path}")
            sys.exit(1)

        # Get salt
        salt_b64 = config.get("salt_b64", "")
        if not salt_b64:
            error("Missing salt_b64 in config for GPG_PW_ONLY mode")
            sys.exit(1)

        log("Decrypting seed with GPG (YubiKey required)...")
        # BUG-20251219-001 FIX: Use --no-tty and timeout to prevent terminal hang
        gpg_timeout = getattr(Limits, "GPG_DECRYPT_TIMEOUT", 30) if Limits else 30
        try:
            result = subprocess.run(
                ["gpg", "--no-tty", "--yes", "--decrypt", str(seed_full_path)],
                check=True,
                capture_output=True,
                timeout=gpg_timeout,
            )
            seed = result.stdout
            log("Seed decrypted successfully ✓")
        except subprocess.TimeoutExpired:
            error("GPG decryption timed out (check YubiKey)")
            sys.exit(1)
        except subprocess.CalledProcessError as e:
            error(f"Failed to decrypt seed: {e.stderr.decode()}")
            sys.exit(1)

        # Derive password
        try:
            import base64

            from crypto_utils import derive_veracrypt_password

            salt = base64.b64decode(salt_b64)
            password = derive_veracrypt_password(seed, salt)
            log("Password derived from seed ✓")

            # Wipe seed from memory
            seed = bytearray(len(seed))
        except Exception as e:
            error(f"Failed to derive password: {e}")
            sys.exit(1)

        # Build credentials for GPG_PW_ONLY (include KDF params for recovery)
        credentials = {
            "volume_path": volume_path,
            "security_mode": mode,
            "mount_password": password,  # Derived password
            "mount_target": mount_target,
            "created_at": utc_timestamp_iso(),
            # KDF params needed to re-derive password from seed
            "kdf": config.get("kdf", CryptoParams.KDF_HKDF_SHA256),
            "salt_b64": salt_b64,
            "hkdf_info": config.get("hkdf_info", CryptoParams.HKDF_INFO_DEFAULT),
            "gpg_pw_only_note": "Password is derived from seed. Recovery requires the seed and these KDF params.",
        }
        return credentials

    # Non-GPG_PW_ONLY modes: prompt for password
    print()
    password = getpass("Enter your VeraCrypt password: ")
    if not password:
        error("Password cannot be empty")
        sys.exit(1)

    # Collect keyfile if needed
    keyfile_bytes = None
    keyfile_path = None

    if mode in (SecurityMode.PW_KEYFILE.value, SecurityMode.PW_GPG_KEYFILE.value):
        # For GPG-encrypted keyfile, decrypt it
        enc_keyfile = config.get(ConfigKeys.ENCRYPTED_KEYFILE, "")
        if enc_keyfile:
            enc_path = (SCRIPT_DIR / enc_keyfile).resolve()
            if not enc_path.exists():
                error(f"Encrypted keyfile not found: {enc_path}")
                sys.exit(1)

            log(f"Decrypting keyfile (YubiKey may be required)...")

            # BUG-20251219-001 FIX: Use --no-tty and timeout to prevent terminal hang
            gpg_timeout = getattr(Limits, "GPG_DECRYPT_TIMEOUT", 30) if Limits else 30
            try:
                result = subprocess.run(
                    ["gpg", "--no-tty", "--yes", "--decrypt", str(enc_path)],
                    check=True,
                    capture_output=True,
                    timeout=gpg_timeout,
                )
                keyfile_bytes = result.stdout
                log("Keyfile decrypted successfully ✓")
            except subprocess.TimeoutExpired:
                error("GPG decryption timed out (check YubiKey)")
                sys.exit(1)
            except subprocess.CalledProcessError as e:
                error(f"Failed to decrypt keyfile: {e.stderr.decode()}")
                sys.exit(1)

    # If not mounted, verify credentials with test mount
    if not is_mounted:
        log("Verifying credentials with test mount...")

        # Write keyfile to temp location if needed
        temp_keyfile = None
        if keyfile_bytes:
            temp_dir = get_ram_temp_dir()
            temp_keyfile = temp_dir / f"kf_{secrets.token_hex(8)}.tmp"
            temp_keyfile.write_bytes(keyfile_bytes)

        try:
            success, err = try_mount(
                volume_path=volume_path,
                mount_point=mount_target,
                password=password,
                keyfile_path=temp_keyfile,
            )

            if not success:
                error(f"Credential verification failed: {err}")
                sys.exit(1)

            log("Credentials verified ✓")

            # Unmount - we only needed to verify
            unmount(mount_target)

        except InvalidCredentialsError:
            error("Invalid password or keyfile")
            sys.exit(1)
        except VeraCryptError as e:
            error(f"VeraCrypt error: {e}")
            sys.exit(1)
        finally:
            if temp_keyfile and temp_keyfile.exists():
                secure_delete(temp_keyfile)

    # Build credentials payload
    credentials = {
        "volume_path": volume_path,
        "security_mode": mode,
        "mount_password": password,
        "mount_target": mount_target,
        "created_at": utc_timestamp_iso(),
    }

    if keyfile_bytes:
        credentials["keyfile_bytes_b64"] = base64.b64encode(keyfile_bytes).decode("ascii")

    return credentials


# ─────────────────────────────────────────────────────────────────────────────
# HTML RECOVERY KIT GENERATION
# ─────────────────────────────────────────────────────────────────────────────


def generate_recovery_html(
    phrase: str,
    chunks: Optional[list] = None,
    header_chunks: Optional[list] = None,
    volume_name: str = f"{Branding.PRODUCT_NAME} Volume",
    volume_identity: str = "",
    environment: Optional[dict] = None,
    security_mode: str = None,
    gpg_pw_only_info: dict = None,
    include_qr: bool = True,
    header_backup_path: Optional[Path] = None,
    artifact_qr_chains: Optional[dict] = None,
) -> str:
    """
    Generate a printable HTML recovery kit with optional QR codes.

    Args:
        phrase: 24-word BIP39 recovery phrase
        chunks: Optional container chunks for offline mode
        header_chunks: Optional header backup chunks for offline mode
        volume_name: Name of volume for identification
        volume_identity: Volume identity hash for verification
        environment: Environment snapshot dict
        security_mode: Security mode string
        gpg_pw_only_info: GPG_PW_ONLY mode info dict
        include_qr: If True, generate QR codes for phrase (default: True)
        header_backup_path: Optional path to header backup for QR encoding
        artifact_qr_chains: Optional dict of mode-specific artifact QR chains
            Keys: 'seed_gpg', 'keyfile_gpg', 'config' -> list of ChunkInfo

    Returns:
        HTML string ready for saving/printing
    """
    words = phrase.split()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    phrase_hash = hash_phrase(phrase)

    # Environment snapshot if provided (P1)
    env = environment or get_environment_snapshot()

    # Generate QR codes for phrase (Phase 4 - P0/P1)
    qr_section = ""
    header_qr_section = ""
    if include_qr and _qr_available():
        phrase_qr_chunks = generate_phrase_qr_chunks(phrase)
        instructions_qr = generate_offline_instructions_qr()

        qr_images_html = ""
        for qr_chunk in phrase_qr_chunks:
            if qr_chunk["qr_data_url"]:
                qr_images_html += f"""
                <div class="qr-chunk">
                    <img src="{qr_chunk['qr_data_url']}" alt="QR Code {qr_chunk['chunk_num']}/{qr_chunk['total_chunks']}" />
                    <p>Words {qr_chunk['word_range']}<br/>({qr_chunk['chunk_num']} of {qr_chunk['total_chunks']})</p>
                </div>
                """

        instructions_qr_html = ""
        if instructions_qr:
            instructions_qr_html = f"""
            <div class="qr-chunk" style="margin-top: 20px;">
                <img src="{instructions_qr}" alt="Recovery Instructions QR" />
                <p>📋 Scan for Recovery Instructions</p>
            </div>
            """

        qr_section = f"""
    <div class="qr-section">
        <h2>📱 QR Codes for Easy Scanning</h2>
        <p>Scan these QR codes to quickly capture your recovery phrase:</p>
        <div class="qr-container">
            {qr_images_html}
        </div>
        {instructions_qr_html}
        <p class="note"><em>Note: Each QR code contains part of your phrase. Scan ALL codes in order.</em></p>
    </div>
        """

        # Optional: Header backup QR codes (TODO 7)
        if header_backup_path and header_backup_path.exists():
            header_qr_chunks = generate_header_backup_qr_chunks(header_backup_path)
            if header_qr_chunks:
                header_qr_images = ""
                for hqr in header_qr_chunks:
                    if hqr["qr_data_url"]:
                        header_qr_images += f"""
                        <div class="qr-chunk">
                            <img src="{hqr['qr_data_url']}" alt="Header Chunk {hqr['chunk_num']}/{hqr['total_chunks']}" />
                            <p>Header {hqr['chunk_num']}/{hqr['total_chunks']}</p>
                        </div>
                        """

                header_qr_section = f"""
    <div class="qr-section" style="page-break-before: always;">
        <h2>🔧 Header Backup QR Codes (Optional)</h2>
        <p><strong>Use ONLY if your volume header becomes corrupted.</strong></p>
        <p>These QR codes contain your encrypted volume header backup. Scan ALL codes to reconstruct.</p>
        <div class="qr-container">
            {header_qr_images}
        </div>
        <div class="warning" style="background: #fff3cd; border-color: #856404;">
            <p><strong>Note:</strong> Header backup is separate from credential recovery. You only need this if your volume's header becomes damaged (rare corruption scenario).</p>
        </div>
    </div>
                """
    elif include_qr:
        # QR requested but library not available
        qr_section = """
    <div class="warning" style="background: #fff3cd; border-color: #856404;">
        <h3>📱 QR Codes Not Available</h3>
        <p>The qrcode library was not installed when this kit was generated.</p>
        <p>To enable QR codes, run: <code>pip install qrcode[pil]</code></p>
    </div>
        """

    # MODE-SPECIFIC ARTIFACT QR CODES (TODO 4)
    artifact_qr_section = ""
    if artifact_qr_chains and include_qr and _qr_available():
        artifact_sections = []

        # Seed.gpg QR codes (GPG_PW_ONLY mode)
        if "seed_gpg" in artifact_qr_chains:
            seed_chunks = artifact_qr_chains["seed_gpg"]
            seed_qr_items = chunks_to_qr_data_urls(seed_chunks)
            if seed_qr_items:
                seed_qr_images = ""
                for item in seed_qr_items:
                    if item.get("qr_data_url"):
                        seed_qr_images += f"""
                    <div class="qr-chunk">
                        <img src="{item['qr_data_url']}" alt="Seed GPG Chunk {item['chunk_num']}/{item['total']}" />
                        <p>Seed {item['chunk_num']}/{item['total']}</p>
                    </div>
                        """

                artifact_sections.append(
                    f"""
        <div class="artifact-qr-group">
            <h3>🔐 {FileNames.SEED_GPG} - GPG Encrypted Seed (ESSENTIAL)</h3>
            <p><strong>This file is CRITICAL for GPG_PW_ONLY recovery.</strong></p>
            <p>Your VeraCrypt password is derived from this seed using HKDF.</p>
            <div class="qr-container">{seed_qr_images}</div>
        </div>
                """
                )

        # Keyfile.vc.gpg QR codes (PW_GPG_KEYFILE mode)
        if "keyfile_gpg" in artifact_qr_chains:
            keyfile_chunks = artifact_qr_chains["keyfile_gpg"]
            keyfile_qr_items = chunks_to_qr_data_urls(keyfile_chunks)
            if keyfile_qr_items:
                keyfile_qr_images = ""
                for item in keyfile_qr_items:
                    if item.get("qr_data_url"):
                        keyfile_qr_images += f"""
                    <div class="qr-chunk">
                        <img src="{item['qr_data_url']}" alt="Keyfile GPG Chunk {item['chunk_num']}/{item['total']}" />
                        <p>Keyfile {item['chunk_num']}/{item['total']}</p>
                    </div>
                        """

                artifact_sections.append(
                    f"""
        <div class="artifact-qr-group">
            <h3>🔑 {FileNames.KEYFILE_GPG} - GPG Encrypted Keyfile</h3>
            <p><strong>Required for PW_GPG_KEYFILE mode recovery.</strong></p>
            <p>This keyfile must be decrypted with your YubiKey before mounting.</p>
            <div class="qr-container">{keyfile_qr_images}</div>
        </div>
                """
                )

        # Config snapshot QR codes (all modes)
        if "config" in artifact_qr_chains:
            config_chunks = artifact_qr_chains["config"]
            config_qr_items = chunks_to_qr_data_urls(config_chunks)
            if config_qr_items:
                config_qr_images = ""
                for item in config_qr_items:
                    if item.get("qr_data_url"):
                        config_qr_images += f"""
                    <div class="qr-chunk">
                        <img src="{item['qr_data_url']}" alt="Config Chunk {item['chunk_num']}/{item['total']}" />
                        <p>Config {item['chunk_num']}/{item['total']}</p>
                    </div>
                        """

                artifact_sections.append(
                    f"""
        <div class="artifact-qr-group">
            <h3>📋 Configuration Snapshot</h3>
            <p>Contains paths, security mode, and KDF parameters for reconstruction.</p>
            <div class="qr-container">{config_qr_images}</div>
        </div>
                """
                )

        if artifact_sections:
            artifact_qr_section = f"""
    <div class="qr-section" style="page-break-before: always;">
        <h2>🔧 Mode-Specific Recovery Artifacts</h2>
        <p><strong>These QR codes contain encrypted files needed for full recovery.</strong></p>
        <p>Scan ALL codes for each artifact in order.</p>
        {"".join(artifact_sections)}
        <div class="instructions" style="margin-top: 20px;">
            <h4>To reconstruct artifacts:</h4>
            <ol>
                <li>Scan all QR codes for each artifact</li>
                <li>Save scanned data to a text file</li>
                <li>Run: <code>python recovery.py reconstruct-artifact chunks.txt</code></li>
            </ol>
        </div>
    </div>
            """

    # Security mode description
    mode_descriptions = {
        SecurityMode.PW_ONLY.value: "Password Only (no keyfile)",
        SecurityMode.PW_KEYFILE.value: "Password + Plain Keyfile",
        SecurityMode.PW_GPG_KEYFILE.value: "Password + GPG-Encrypted Keyfile (YubiKey)",
        SecurityMode.GPG_PW_ONLY.value: "GPG-Derived Password (YubiKey, no user password)",
    }
    mode_desc = mode_descriptions.get(security_mode, "Not specified")

    # GPG_PW_ONLY specific section
    gpg_pw_only_section = ""
    if security_mode == SecurityMode.GPG_PW_ONLY.value and gpg_pw_only_info:
        gpg_pw_only_section = f"""
    <div class="warning" style="background: #fff3cd; border-color: #856404;">
        <h3>🔑 GPG_PW_ONLY MODE - CRITICAL RECOVERY INFO</h3>
        <p>In this mode, your VeraCrypt password is <strong>DERIVED</strong> from a cryptographic seed.
        You do not know the actual password - it's generated automatically using your YubiKey.</p>
        
        <p><strong>To recover, you need:</strong></p>
        <ol>
            <li>This 24-word phrase (to recreate the seed)</li>
            <li>Your YubiKey (for GPG decryption)</li>
            <li>The KDF parameters below</li>
        </ol>
        
        <table style="font-size: 12px; background: #f8f9fa;">
            <tr><td><strong>KDF Function</strong></td><td><code>{gpg_pw_only_info.get('kdf', 'hkdf-sha256')}</code></td></tr>
            <tr><td><strong>Salt (base64)</strong></td><td><code style="word-break: break-all;">{gpg_pw_only_info.get('salt_b64', '(missing)')}</code></td></tr>
            <tr><td><strong>HKDF Info</strong></td><td><code>{gpg_pw_only_info.get('hkdf_info', CryptoParams.HKDF_INFO_DEFAULT)}</code></td></tr>
        </table>
        
        <p><strong>Recovery process:</strong></p>
        <ol>
            <li>Decrypt your seed using GPG (YubiKey required)</li>
            <li>Derive the password: <code>HKDF(seed, salt, info)</code></li>
            <li>Mount your volume with the derived password</li>
        </ol>
        
        <p><em>⚠️ If you lose your YubiKey, you can manually derive the password using these parameters.</em></p>
    </div>
        """

    # Word grid (6x4)
    word_rows = []
    for i in range(0, 24, 6):
        row_html = "<tr>"
        for j in range(6):
            idx = i + j
            row_html += f'<td><span class="word-num">{idx+1}.</span> {words[idx]}</td>'
        row_html += "</tr>"
        word_rows.append(row_html)

    word_table = "\n".join(word_rows)

    # Chunk section for offline mode
    chunk_section = ""
    page_count_warning = ""
    if chunks:
        # Estimate page count: ~3 chunks per page (conservative)
        total_chunks = len(chunks) + (len(header_chunks) if header_chunks else 0)
        estimated_pages = max(1, (total_chunks + 2) // 3) + 1  # +1 for phrase page

        chunk_html = ""
        for i, chunk in enumerate(chunks, 1):
            chunk_html += f"""
            <div class="chunk">
                <div class="chunk-header">Container Chunk {i}/{len(chunks)}</div>
                <pre class="chunk-data">{chunk}</pre>
            </div>
            """

        header_html = ""
        if header_chunks:
            for i, chunk in enumerate(header_chunks, 1):
                header_html += f"""
                <div class="chunk">
                    <div class="chunk-header">Header Chunk {i}/{len(header_chunks)}</div>
                    <pre class="chunk-data">{chunk}</pre>
                </div>
                """

        page_count_warning = f"""
        <div class="warning" style="background: #fff3cd; border-color: #856404;">
            <h3>📄 OFFLINE KIT SIZE WARNING</h3>
            <p><strong>This document is approximately {estimated_pages} pages.</strong></p>
            <p>Offline recovery requires ALL {total_chunks} data chunks to be present and readable.
            A single lost or damaged page makes recovery IMPOSSIBLE.</p>
            <p><strong>Recommendations:</strong></p>
            <ul>
                <li>Print multiple copies</li>
                <li>Store copies in separate physical locations</li>
                <li>Use archival-quality paper and ink</li>
                <li>Consider also storing the digital container file securely</li>
            </ul>
        </div>
        """

        chunk_section = f"""
        <div class="offline-section">
            <h2>📦 Offline Recovery Data</h2>
            {page_count_warning}
            <p>These chunks allow complete recovery without any digital files.</p>
            
            <h3>Recovery Container ({len(chunks)} chunks)</h3>
            {chunk_html}
            
            {"<h3>Header Backup (" + str(len(header_chunks)) + " chunks)</h3>" + header_html if header_chunks else ""}
            
            <div class="instructions">
                <h4>To reconstruct:</h4>
                <ol>
                    <li>Copy all chunks (in any order) to a text file</li>
                    <li>Run: <code>python recovery.py reconstruct chunks.txt</code></li>
                </ol>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{Branding.PRODUCT_NAME} Recovery Kit</title>
    <style>
        @media print {{
            body {{ margin: 0.5in; }}
            .no-print {{ display: none; }}
        }}
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            max-width: 8.5in;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.4;
        }}
        .header {{
            text-align: center;
            border-bottom: 3px solid #c00;
            padding-bottom: 20px;
            margin-bottom: 20px;
        }}
        .header h1 {{
            color: #c00;
            margin-bottom: 5px;
        }}
        .warning {{
            background: #fee;
            border: 2px solid #c00;
            padding: 15px;
            margin: 20px 0;
            border-radius: 5px;
        }}
        .warning h3 {{
            color: #c00;
            margin-top: 0;
        }}
        .phrase-section {{
            background: #f8f8f8;
            border: 2px solid #333;
            padding: 20px;
            margin: 20px 0;
            border-radius: 5px;
        }}
        .phrase-section h2 {{
            margin-top: 0;
            border-bottom: 1px solid #ccc;
            padding-bottom: 10px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        td {{
            border: 1px solid #ccc;
            padding: 8px 12px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 14px;
        }}
        .word-num {{
            color: #666;
            font-size: 12px;
        }}
        .hash {{
            font-family: monospace;
            background: #eee;
            padding: 5px 10px;
            border-radius: 3px;
        }}
        .offline-section {{
            margin-top: 30px;
            page-break-before: always;
        }}
        .chunk {{
            margin: 15px 0;
            border: 1px solid #ddd;
            border-radius: 5px;
            overflow: hidden;
        }}
        .chunk-header {{
            background: #333;
            color: white;
            padding: 8px 12px;
            font-weight: bold;
        }}
        .chunk-data {{
            background: #f5f5f5;
            padding: 10px;
            margin: 0;
            font-size: 10px;
            word-break: break-all;
            white-space: pre-wrap;
        }}
        .instructions {{
            background: #eff;
            border: 1px solid #0aa;
            padding: 15px;
            margin: 20px 0;
            border-radius: 5px;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ccc;
            font-size: 12px;
            color: #666;
        }}
        .qr-section {{
            margin-top: 30px;
            padding: 20px;
            background: #f8f8f8;
            border: 2px solid #333;
            border-radius: 5px;
        }}
        .qr-section h2 {{
            margin-top: 0;
            border-bottom: 1px solid #ccc;
            padding-bottom: 10px;
        }}
        .qr-container {{
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 20px;
            margin: 20px 0;
        }}
        .qr-chunk {{
            text-align: center;
            padding: 10px;
            background: white;
            border: 1px solid #ddd;
            border-radius: 5px;
        }}
        .qr-chunk img {{
            max-width: 150px;
            height: auto;
        }}
        .qr-chunk p {{
            margin: 10px 0 0 0;
            font-size: 12px;
            color: #666;
        }}
        .note {{
            font-size: 12px;
            color: #666;
            margin-top: 15px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔐 SMARTDRIVE RECOVERY KIT</h1>
        <p>Volume: <strong>{volume_name}</strong></p>
        <p>Security Mode: <strong>{mode_desc}</strong></p>
        <p>Generated: {timestamp}</p>
    </div>
    
    <div class="warning">
        <h3>⚠️ CRITICAL SECURITY WARNINGS</h3>
        <ul>
            <li><strong>PRINT THIS PAGE</strong> and store in a secure physical location</li>
            <li><strong>DELETE THE DIGITAL FILE</strong> after printing</li>
            <li><strong>ANYONE WITH THIS PHRASE</strong> can access your encrypted data</li>
            <li><strong>ONE-TIME USE ONLY</strong> - recovery invalidates this kit</li>
            <li><strong>MANDATORY REKEY</strong> - you must change credentials after recovery</li>
        </ul>
    </div>
    
    {gpg_pw_only_section}
    
    <div class="phrase-section">
        <h2>📝 24-Word Recovery Phrase</h2>
        <p>Write down these words <strong>in order</strong>. Each word is important.</p>
        <table>
            {word_table}
        </table>
        <p>Verification hash: <span class="hash">{phrase_hash}</span></p>
        <p><em>This hash can be used to verify you've entered the phrase correctly.</em></p>
    </div>
    
    {qr_section}
    
    {header_qr_section}
    
    {artifact_qr_section}
    
    {chunk_section}
    
    <div class="instructions">
        <h3>📋 Recovery Instructions</h3>
        <ol>
            <li>Install Python 3 and required dependencies</li>
            <li>Run: <code>python recovery.py recover</code></li>
            <li>Enter your 24-word recovery phrase when prompted</li>
            <li>The system will restore your access</li>
            <li><strong>IMMEDIATELY</strong> run <code>python rekey.py</code> to change credentials</li>
        </ol>
        <p><strong>Note:</strong> This recovery kit can only be used ONCE. After successful recovery, 
        you MUST generate a new recovery kit with new credentials.</p>
    </div>
    
    <!-- BUG-20251218-010: Header Restore Guidance Section -->
    <div class="instructions" style="background: #fff8e1; border-color: #ff9800;">
        <h3>🔧 VeraCrypt Header Backup Restoration</h3>
        <p><strong>What is a VeraCrypt header backup?</strong></p>
        <p>The volume header contains encryption keys and metadata. If it becomes corrupted 
        (rare disk errors, interrupted operations), the volume becomes inaccessible even with 
        correct passwords.</p>
        
        <p><strong>When do you need header restoration?</strong></p>
        <ul>
            <li>VeraCrypt reports "Incorrect password or not a VeraCrypt volume"</li>
            <li>Volume fails to mount despite correct credentials</li>
            <li>Disk experienced corruption or bad sectors at the start</li>
        </ul>
        
        <p><strong>How to restore the header (GUI):</strong></p>
        <ol>
            <li>Open VeraCrypt</li>
            <li>Go to <code>Tools → Restore Volume Header</code></li>
            <li>Select "Restore the volume header from an external backup"</li>
            <li>Browse to your <code>header.backup</code> file (in your .smartdrive/recovery folder)</li>
            <li>Enter your volume password when prompted</li>
            <li>Confirm the restoration</li>
        </ol>
        
        <p><strong>How to restore the header (CLI):</strong></p>
        <pre style="background: #f5f5f5; padding: 10px; border-radius: 3px; overflow-x: auto;">veracrypt --restore-headers /path/to/volume.vc --backup-file=/path/to/header.backup</pre>
        
        <div style="background: #ffebee; padding: 10px; margin-top: 10px; border-radius: 3px;">
            <strong>⚠️ Important:</strong> Header backup restoration does NOT require your recovery phrase.
            It only requires the original volume password/keyfile. Only use header restore if the volume 
            itself is corrupted. For credential recovery (lost password/YubiKey), use the recovery phrase above.
        </div>
    </div>
    
    <!-- BUG-20251218-011: Critical Files/Folders Preservation Section -->
    <div class="instructions" style="background: #e8f5e9; border-color: #4caf50;">
        <h3>💾 Critical Files & Folders to Preserve</h3>
        <p><strong>Your .smartdrive folder contains essential security artifacts. Understand what to keep:</strong></p>
        
        <table style="font-size: 12px; margin: 15px 0;">
            <thead>
                <tr style="background: #c8e6c9;">
                    <th style="padding: 8px; text-align: left;">File/Folder</th>
                    <th style="padding: 8px; text-align: left;">Purpose</th>
                    <th style="padding: 8px; text-align: left;">Safe to Back Up?</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><code>config.json</code></td>
                    <td>Drive configuration (paths, settings, mode)</td>
                    <td style="color: green;">✓ Yes - encrypted or non-sensitive</td>
                </tr>
                <tr style="background: #f5f5f5;">
                    <td><code>keys/</code></td>
                    <td>GPG-encrypted keyfile</td>
                    <td style="color: green;">✓ Yes - always encrypted</td>
                </tr>
                <tr>
                    <td><code>recovery/</code></td>
                    <td>Recovery container and header backup</td>
                    <td style="color: green;">✓ Yes - encrypted container</td>
                </tr>
                <tr style="background: #f5f5f5;">
                    <td><code>{FileNames.SEED_GPG}</code> (if GPG_PW_ONLY mode)</td>
                    <td>GPG-encrypted key derivation seed</td>
                    <td style="color: green;">✓ Yes - always encrypted</td>
                </tr>
                <tr>
                    <td><code>scripts/</code></td>
                    <td>{Branding.PRODUCT_NAME} scripts (can be restored from source)</td>
                    <td style="color: blue;">◐ Optional - publicly available</td>
                </tr>
            </tbody>
        </table>
        
        <div style="background: #fff3e0; padding: 10px; margin-top: 10px; border-radius: 3px;">
            <strong>⚠️ What NOT to modify:</strong>
            <ul style="margin: 5px 0;">
                <li>Do NOT edit <code>config.json</code> manually - use {Branding.PRODUCT_NAME} tools</li>
                <li>Do NOT rename or move the <code>.smartdrive</code> folder</li>
                <li>Do NOT delete <code>keys/</code> or <code>recovery/</code> until you've verified backups</li>
            </ul>
        </div>
        
        <div style="background: #e3f2fd; padding: 10px; margin-top: 10px; border-radius: 3px;">
            <strong>💡 Backup Recommendation:</strong>
            <p style="margin: 5px 0;">Back up the entire <code>.smartdrive</code> folder to a secure location (separate from your recovery phrase). 
            The encrypted files cannot be used without your YubiKey/password, so they're safe to store in cloud backup.</p>
        </div>
    </div>
    
    <div class="instructions" style="background: #f0f0f0; border-color: #999;">
        <h3>🔧 Environment Snapshot</h3>
        <p>This kit was generated with the following environment. For best results, use similar versions:</p>
        <table style="font-size: 12px;">
            <tr><td><strong>Python</strong></td><td>{env.get('python_version', 'unknown')}</td></tr>
            <tr><td><strong>OS</strong></td><td>{env.get('os_family', 'unknown')} {env.get('os_version', '')[:30]}</td></tr>
            <tr><td><strong>VeraCrypt</strong></td><td>{env.get('veracrypt_version', 'unknown')}</td></tr>
            <tr><td><strong>Requirements Hash</strong></td><td><code>{env.get('requirements_hash', 'unknown')}</code></td></tr>
            <tr><td><strong>Volume Identity</strong></td><td><code>{volume_identity or 'not recorded'}</code></td></tr>
        </table>
        <p><em>If recovery fails with environment errors, ensure compatible versions are installed.</em></p>
    </div>
    
    <div class="footer">
        <p>{Branding.PRODUCT_NAME} Recovery System • This document is CONFIDENTIAL</p>
        <p>Keep in a secure location separate from your encrypted drive</p>
        <p style="font-size: 10px; color: #999;">Generated: {timestamp} | Volume ID: {volume_identity[:16] if volume_identity else 'N/A'}...</p>
    </div>
</body>
</html>"""

    return html


# ─────────────────────────────────────────────────────────────────────────────
# SETUP INTEGRATION - Direct function call (no subprocess)
# ─────────────────────────────────────────────────────────────────────────────


def _verify_phrase_forgiving(words: list, phrase_hash: str) -> bool:
    """
    Forgivable verification loop - randomly select 3 words to verify.

    Args:
        words: List of 24 words in order
        phrase_hash: Hash for display

    Returns:
        True if all words verified, False if user wants to retry
    """
    # Randomly select 3 distinct indices
    import random

    indices_to_check = random.sample(range(24), 3)
    indices_to_check.sort()

    print(f"\n  Please enter 3 words to verify you recorded them correctly:")
    print()

    for idx in indices_to_check:
        attempts = 0
        while attempts < 3:
            user_word = input(f"  Enter word #{idx+1}: ").strip().lower()
            if user_word == words[idx].lower():
                break
            else:
                attempts += 1
                if attempts < 3:
                    print(f"  ✗ Incorrect. Try again ({3-attempts} attempts remaining)")
                else:
                    print(f"  ✗ Incorrect. Maximum attempts reached for word #{idx+1}")
                    return False

    return True


def generate_recovery_kit_from_setup(config_path: Path, password: str, keyfile_bytes: bytes = None) -> int:
    """
    Generate recovery kit directly from setup (no subprocess, no re-auth).

    Called by setup.py when user opts into recovery generation.
    Uses already-verified credentials from setup context.

    Implements MANDATORY workflow:
    1. Mode selection: Printable (HTML) vs Terminal (manual write-down)
    2. Printable mode: Generate HTML, open browser, verify (forgivable)
    3. Terminal mode: Show phrases, confirm, scrub, verify (forgivable)
    4. Both modes: Create container, export header, update config

    Args:
        config_path: Path to config.json
        password: Already-verified volume password
        keyfile_bytes: Already-decrypted keyfile bytes (or None)

    Returns:
        0 on success, non-zero on failure
    """
    try:
        # Load config
        if not config_path.exists():
            error(f"Config not found: {config_path}")
            return 1

        with open(config_path, "r") as f:
            config = json.load(f)

        volume_path, mount_target = get_volume_info(config)
        mode = config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)

        print("\n" + "=" * 70)
        print(f"  {Branding.PRODUCT_NAME.upper()} RECOVERY KIT GENERATOR")
        print("  (Setup Integration Mode)")
        print("=" * 70 + "\n")

        # Build credentials from setup-provided values (already verified)
        credentials = {
            "volume_path": volume_path,
            "security_mode": mode,
            "mount_password": password,
            "mount_target": mount_target,
            "created_at": utc_timestamp_iso(),
        }

        if keyfile_bytes:
            credentials["keyfile_bytes_b64"] = base64.b64encode(keyfile_bytes).decode("ascii")

        log("Using credentials from setup context (already verified)")

        # Generate BIP39 phrase
        log("Generating recovery phrase...")
        phrase = generate_bip39_phrase()
        phrase_hash = hash_phrase(phrase)
        log(f"Generated 24-word BIP39 phrase ✓")

        # STEP 1: MODE SELECTION (MANDATORY)
        print("\n" + "=" * 70)
        print("  RECOVERY KIT FORMAT")
        print("=" * 70)
        print("\nChoose recovery kit format:")
        print("  [P] Printable (HTML) - Opens in browser, includes QR codes")
        print("  [T] Terminal (manual write-down) - Display in terminal only")
        print("  [A] Abort - Cancel recovery kit generation")
        print()

        while True:
            format_choice = input("  Your choice [P/T/A]: ").strip().upper()
            if format_choice in ["P", "T", "A"]:
                break
            print("  Invalid choice. Please enter P, T, or A.")

        if format_choice == "A":
            print("\n  Recovery kit generation aborted by user.")
            return 1

        # Store choice for verification phase
        is_printable_mode = format_choice == "P"
        html_path = None
        words = phrase.split()

        # STEP 2: PRINTABLE (HTML) MODE
        if is_printable_mode:
            # Generate HTML immediately (before verification)
            log("Generating HTML recovery kit...")
            drive_name = config.get(ConfigKeys.DRIVE_NAME, Branding.PRODUCT_NAME)
            volume_identity = compute_volume_identity(volume_path)

            # Build GPG_PW_ONLY info if applicable
            gpg_pw_only_info = None
            if mode == SecurityMode.GPG_PW_ONLY.value:
                gpg_pw_only_info = {
                    "kdf": config.get("kdf", CryptoParams.KDF_HKDF_SHA256),
                    "salt_b64": config.get("salt_b64", ""),
                    "hkdf_info": config.get("hkdf_info", CryptoParams.HKDF_INFO_DEFAULT),
                }

            html = generate_recovery_html(
                phrase=phrase,
                chunks=None,
                header_chunks=None,
                volume_name=drive_name,
                volume_identity=volume_identity,
                security_mode=mode,
                gpg_pw_only_info=gpg_pw_only_info,
            )

            # SSOT: Save HTML to recovery directory with standard filename
            # BUG-20251219-010 FIX: config_path is .smartdrive/config.json
            # parent is .smartdrive/, parent.parent is launcher root
            launcher_mount = config_path.parent.parent  # Launcher root (H:\)
            recovery_dir = Paths.recovery_dir(launcher_mount)
            recovery_dir.mkdir(parents=True, exist_ok=True)  # Ensure folder exists
            html_path = recovery_dir / f"{Branding.PRODUCT_NAME}_Recovery_Kit.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            log(f"HTML kit saved: {html_path} ✓")

            # Open HTML in browser immediately
            print("\n  Opening recovery kit in browser...")
            if open_html_in_browser(html_path):
                log("Browser opened with recovery kit")
            else:
                print(f"  ⚠️  Could not open browser automatically.")
                print(f"  Please open manually: {html_path}")

            print("\n  Review the recovery kit in your browser.")
            print("  You MUST write down or print the 24-word phrase.")
            input("\n  Press ENTER when you have recorded the phrase...")

        # STEP 3: TERMINAL (MANUAL WRITE-DOWN) MODE
        else:
            # Display phrases in terminal (plaintext allowed temporarily)
            verification_passed = False

            while not verification_passed:
                print("\n" + "=" * 70)
                print("  YOUR 24-WORD RECOVERY PHRASE")
                print("  WRITE THIS DOWN NOW - IT'S YOUR ONLY BACKUP!")
                print("=" * 70 + "\n")

                for i in range(0, 24, 6):
                    row = "  "
                    for j in range(6):
                        idx = i + j
                        row += f"{idx+1:2}. {words[idx]:12}"
                    print(row)

                print("\n" + "-" * 70)
                print(f"  Verification hash: {phrase_hash}")
                print("-" * 70 + "\n")

                # Explicit confirmation step
                print("  Have you written down ALL 24 words?")
                while True:
                    confirm = input(f"  Type {UserInputs.YES} to continue: ").strip().upper()
                    if confirm == UserInputs.YES:
                        break
                    else:
                        print(f"  You must confirm by typing {UserInputs.YES} exactly.")
                        redo = input("  Press ENTER to see phrases again, or type 'abort' to cancel: ").strip().lower()
                        if redo == "abort":
                            error("Verification aborted by user")
                            return 1
                        # Loop back to show phrases again
                        break

                if confirm != UserInputs.YES:
                    continue  # Re-display phrases

                # SCRUBBING PHASE (MANDATORY)
                # Clear terminal (cross-platform)
                if platform.system() == "Windows":
                    os.system("cls")
                else:
                    os.system("clear")

                print("\n" + "=" * 70)
                print("  PHRASE SCRUBBED - NOW VERIFY YOUR WRITTEN COPY")
                print("=" * 70 + "\n")

                # Display obfuscated placeholders
                for i in range(0, 24, 6):
                    row = "  "
                    for j in range(6):
                        idx = i + j
                        row += f"{idx+1:2}. {'*****':12}"
                    print(row)

                print("\n" + "-" * 70)
                print(f"  Verification hash: {phrase_hash}")
                print("-" * 70 + "\n")

                # Verification test (forgivable)
                if _verify_phrase_forgiving(words, phrase_hash):
                    verification_passed = True
                else:
                    print("\n  ✗ Verification failed. You will see the phrases again.")
                    input("  Press ENTER to retry...")
                    # Loop back to beginning (re-display phrases)

        # STEP 4: VERIFICATION (PRINTABLE MODE) - Same logic, no phrase display
        if is_printable_mode:
            verification_passed = False

            while not verification_passed:
                # No phrase display - user has HTML
                print("\n  Now verify you have recorded the phrase correctly.")

                if _verify_phrase_forgiving(words, phrase_hash):
                    verification_passed = True
                else:
                    print("\n  ✗ Verification failed.")
                    retry_choice = input("  Re-open HTML in browser? [yes/no]: ").strip().lower()
                    if retry_choice == "yes" and html_path:
                        if not open_html_in_browser(html_path):
                            print(f"  Could not open browser. Path: {html_path}")
                    input("  Press ENTER to retry verification...")

        log("Phrase verification successful ✓")
        print("  ✓ All words verified correctly!")

        # STEP 5: Create container (SSOT: use Paths.recovery_dir)
        log("Creating encrypted recovery container...")
        # BUG-20251219-010 FIX: config_path is .smartdrive/config.json
        # parent is .smartdrive/, parent.parent is launcher root
        launcher_mount = config_path.parent.parent  # Launcher root (H:\)
        recovery_dir = Paths.recovery_dir(launcher_mount)
        recovery_dir.mkdir(parents=True, exist_ok=True)  # Ensure folder exists
        smartdrive_dir = config_path.parent  # .smartdrive directory

        container_path = recovery_dir / "recovery_container.bin"
        header_path = recovery_dir / "header_backup.hdr"

        # BUG-20251219-001c FIX: Add volume identity and environment snapshot to credentials
        # This ensures parity with cmd_generate() - credentials stored in container
        # must include binding info for recovery verification
        volume_identity = compute_volume_identity(volume_path)
        env_snapshot = get_environment_snapshot()
        credentials["volume_id"] = volume_identity
        credentials["environment"] = env_snapshot
        log(f"Volume identity: {volume_identity[:16]}...")

        try:
            container_bytes = create_container(credentials, phrase)
            save_container(container_bytes, container_path)
            log(f"Container saved: {container_path} ✓")
        except RecoveryContainerError as e:
            error(f"Failed to create recovery container: {e}")
            return 1

        # Export header
        log("Exporting VeraCrypt header backup...")

        temp_keyfile = None
        if keyfile_bytes:
            temp_dir = get_ram_temp_dir()
            temp_keyfile = temp_dir / f"kf_{secrets.token_hex(8)}.tmp"
            temp_keyfile.write_bytes(keyfile_bytes)

        try:
            success, used_gui = export_header(
                volume_path=volume_path,
                output_path=header_path,
                password=password,
                keyfile_path=temp_keyfile,
                allow_gui_fallback=True,
                security_mode=mode,  # BUG-20251218-006: Pass mode for hardware key enforcement
            )
            if used_gui:
                log("Header backup guidance provided via GUI (CLI unsupported on this platform)")
            else:
                log(f"Header backup saved: {header_path} ✓")
        except VeraCryptError as e:
            error(f"Failed to export header: {e}")
            if container_path.exists():
                container_path.unlink()
            return 1
        finally:
            if temp_keyfile and temp_keyfile.exists():
                secure_delete(temp_keyfile)

        # Update config
        # BUG-20251220-010 + BUG-20251220-012 FIX: Include ALL required fields for recovery state
        # Must match cmd_generate() config structure for GUI to correctly display status
        log("Updating configuration...")
        # Note: volume_identity already computed earlier (BUG-20251219-001c fix)

        config[RECOVERY_CONFIG_KEY] = {
            "enabled": True,
            "used": False,
            "state": RECOVERY_STATE_ENABLED,  # BUG-20251220-012: Required for GUI status display
            "phrase_hash": phrase_hash,
            "container_path": str(container_path),  # BUG-20251220-010: Required for recovery lookup
            "header_path": str(header_path),
            "volume_identity": volume_identity,
            "created_at": utc_timestamp_iso(),
        }

        # BUG-20251219-001c FIX: Use atomic config save for safety
        try:
            save_config_atomic(config)
            log("Configuration updated ✓")
        except Exception as e:
            error(f"Failed to update config: {e}")
            return 1

        # BUG-20251219-001c FIX: Collect and copy mode-specific artifacts
        # This ensures parity with cmd_generate() - artifacts like seed.gpg, keyfile.vc.gpg
        # are copied to recovery directory for offline recovery
        log("Collecting mode-appropriate artifacts...")
        artifacts, artifact_qr_chains = collect_mode_artifacts(config, smartdrive_dir)
        if artifacts:
            log(f"Saving {len(artifacts)} artifacts to recovery directory...")
            copy_artifacts_to_recovery_dir(artifacts, recovery_dir)

        # BUG-20251219-001c FIX: Add audit logging for consistency with cmd_generate
        audit_log(
            "GENERATE_KIT_FROM_SETUP",
            details={
                "volume_identity": volume_identity[:16],
                "mode": mode,
            },
        )

        # For terminal mode, HTML was not generated yet - generate it now for record
        if not is_printable_mode and not html_path:
            log("Generating HTML recovery kit for archival...")
            drive_name = config.get(ConfigKeys.DRIVE_NAME, Branding.PRODUCT_NAME)

            gpg_pw_only_info = None
            if mode == SecurityMode.GPG_PW_ONLY.value:
                gpg_pw_only_info = {
                    "kdf": config.get("kdf", CryptoParams.KDF_HKDF_SHA256),
                    "salt_b64": config.get("salt_b64", ""),
                    "hkdf_info": config.get("hkdf_info", CryptoParams.HKDF_INFO_DEFAULT),
                }

            # BUG-20251219-001c FIX: Include environment snapshot and artifact QR chains
            # for parity with cmd_generate()
            html = generate_recovery_html(
                phrase=phrase,
                chunks=None,
                header_chunks=None,
                volume_name=drive_name,
                volume_identity=volume_identity,
                environment=env_snapshot,
                security_mode=mode,
                gpg_pw_only_info=gpg_pw_only_info,
                artifact_qr_chains=artifact_qr_chains if artifact_qr_chains else None,
            )

            # SSOT: Use same recovery_dir path (already created earlier)
            html_path = recovery_dir / f"{Branding.PRODUCT_NAME}_Recovery_Kit.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            log(f"HTML kit saved: {html_path} ✓")

        print("\n" + "=" * 70)
        print("  RECOVERY KIT GENERATED SUCCESSFULLY")
        print("=" * 70)
        print(f"\n  Files created:")
        print(f"    - {container_path}")
        print(f"    - {header_path}")
        if html_path:
            print(f"    - {html_path}")
        if artifacts:
            for artifact_name in artifacts:
                print(f"    - {recovery_dir / artifact_name}")
        print("\n  IMPORTANT: Store your 24-word phrase securely!")
        if is_printable_mode:
            print("             Print or save the HTML file to a secure location.")
        print("=" * 70 + "\n")

        return 0

    except Exception as e:
        error(f"Recovery kit generation failed: {e}")
        return 1


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE COMMAND
# ─────────────────────────────────────────────────────────────────────────────


def cmd_generate(args):
    """
    Generate a recovery kit.

    Flow:
    1. Authenticate (verify we have valid credentials)
    2. Generate BIP39 phrase
    3. Verify user has recorded phrase
    4. Create encrypted recovery container
    5. Export VeraCrypt header backup
    6. Write config atomically
    7. Generate printable HTML kit
    8. Open HTML in browser
    """
    config = load_config()
    volume_path, mount_target = get_volume_info(config)

    print("\n" + "=" * 70)
    print(f"  {Branding.PRODUCT_NAME.upper()} RECOVERY KIT GENERATOR")
    print("=" * 70 + "\n")

    # BUG-20251219-004: Enforce single-shot generation by default
    # Check if recovery already exists and enforce --force for regeneration
    recovery_config = config.get(RECOVERY_CONFIG_KEY, {})
    force_regenerate = getattr(args, "force", False) if args else False

    if recovery_config.get("enabled") and not recovery_config.get("used"):
        if not force_regenerate:
            error("An active recovery kit already exists!")
            print("\n" + "-" * 70)
            print("SECURITY: Recovery kit generation is single-shot by default.")
            print("-" * 70)
            print("\nOptions:")
            print("  1. Use 'python recovery.py recover' to use the existing kit")
            print("  2. Run 'python recovery.py generate --force' to regenerate")
            print("     WARNING: This will invalidate the existing kit!")
            print("-" * 70)
            audit_log("GENERATE_BLOCKED", details={"reason": "active_kit_exists", "force": False})
            return
        else:
            # --force provided: require explicit confirmation and audit
            warn("An active recovery kit already exists!")
            print("\n" + "=" * 70)
            print("  ⚠️  FORCED REGENERATION WARNING")
            print("=" * 70)
            print("\nYou are about to generate a NEW recovery kit.")
            print("The EXISTING kit will be PERMANENTLY INVALIDATED.")
            print("\nType 'REGENERATE' to confirm (anything else aborts):\n")

            confirm = input("Confirm: ").strip()
            if confirm != "REGENERATE":
                log("Forced regeneration aborted by user.")
                audit_log("GENERATE_ABORTED", details={"reason": "user_cancelled_force"})
                return

            # Audit the forced regeneration
            audit_log(
                "GENERATE_FORCE_CONFIRMED",
                details={
                    "previous_created_at": recovery_config.get("created_at"),
                    "previous_phrase_hash": recovery_config.get("phrase_hash", "")[:16] + "...",
                },
            )
            log("Forced regeneration confirmed - proceeding...")

    # Step 1: Authenticate
    log("Step 1/7: Authenticating...")
    credentials = authenticate_for_generate(config)
    log("Authentication complete ✓")

    # Step 2: Generate BIP39 phrase
    log("Step 2/7: Generating recovery phrase...")
    phrase = generate_bip39_phrase()
    phrase_hash = hash_phrase(phrase)
    log(f"Generated 24-word BIP39 phrase ✓")

    # CHG-20251218-001: Ask user preference for recovery phrase display
    # Before showing sensitive phrases, ask if they want a printable HTML kit
    print("\n" + "=" * 70)
    print("  RECOVERY PHRASE DISPLAY OPTIONS")
    print("=" * 70)
    print("\n  Your 24-word recovery phrase has been generated.")
    print("  You MUST record this phrase - it's your ONLY backup!")
    print("\n  Choose how to view your recovery phrase:")
    print("\n    [P] Generate PRINTABLE HTML kit (recommended for secure storage)")
    print("        - Opens in browser, print and store in safe location")
    print("        - Phrase will NOT be shown in this terminal")
    print("\n    [T] Display in TERMINAL (for manual transcription)")
    print("        - You must write down all 24 words before continuing")
    print("        - Terminal will be CLEARED before verification test")
    print()

    use_printable_kit = None
    while use_printable_kit is None:
        choice = input("  Choose [P]rintable kit or [T]erminal display: ").strip().upper()
        if choice == "P":
            use_printable_kit = True
        elif choice == "T":
            use_printable_kit = False
        else:
            print("  Please enter P or T")

    words = phrase.split()

    if use_printable_kit:
        # BUG-20251218-008: Generate printable HTML IMMEDIATELY when [P] selected
        # User must be able to read/print their phrases BEFORE verification
        print("\n  [OK] Printable kit selected. Generating HTML recovery kit...")
        print("       Phrase will NOT be shown in this terminal.")

        # Generate a preliminary HTML kit with phrase only (no container/header yet)
        # Full kit with all artifacts will be regenerated at step 7
        config = load_config()
        drive_name = config.get(ConfigKeys.DRIVE_NAME, Branding.PRODUCT_NAME)
        mode = config.get(ConfigKeys.MODE, SecurityMode.PW_ONLY.value)

        # Build GPG_PW_ONLY info if applicable
        preliminary_gpg_info = None
        if mode == SecurityMode.GPG_PW_ONLY.value:
            preliminary_gpg_info = {
                "kdf": config.get("kdf", CryptoParams.KDF_HKDF_SHA256),
                "salt_b64": config.get("salt_b64", ""),
                "hkdf_info": config.get("hkdf_info", CryptoParams.HKDF_INFO_DEFAULT),
            }

        preliminary_html = generate_recovery_html(
            phrase=phrase,
            chunks=None,
            header_chunks=None,
            volume_name=drive_name,
            volume_identity="(will be computed after verification)",
            security_mode=mode,
            gpg_pw_only_info=preliminary_gpg_info,
            include_qr=True,
        )

        # Determine output location (use temp or recovery dir if available)
        if CONFIG_FILE and CONFIG_FILE.parent.exists():
            preliminary_kit_path = CONFIG_FILE.parent / "recovery_kit_PRELIMINARY.html"
        else:
            import tempfile

            preliminary_kit_path = Path(tempfile.gettempdir()) / "keydrive_recovery_PRELIMINARY.html"

        with open(preliminary_kit_path, "w", encoding="utf-8") as f:
            f.write(preliminary_html)

        log(f"Preliminary HTML kit saved: {preliminary_kit_path}")

        # Open in browser for user to view/print
        print(f"\n  Opening recovery kit in your browser...")
        print(f"  File: {preliminary_kit_path}")
        if not open_html_in_browser(preliminary_kit_path):
            print(f"\n  Please manually open this file in your browser:")
            print(f"  {preliminary_kit_path}")

        print("\n" + "-" * 70)
        print("  IMPORTANT: Print and securely store the recovery kit now!")
        print("  The HTML file will be deleted after verification.")
        print("-" * 70)

        input("\n  Press Enter when you have printed/saved your recovery phrase...")

        # Clean up preliminary file (final version generated at step 7)
        try:
            if preliminary_kit_path.exists():
                preliminary_kit_path.unlink()
                log("Preliminary HTML kit deleted (final version will be generated)")
        except Exception as e:
            warn(f"Could not delete preliminary kit: {e}")

        phrase_displayed_in_terminal = False
    else:
        # User wants terminal display
        phrase_displayed_in_terminal = True
        print("\n" + "=" * 70)
        print("  YOUR 24-WORD RECOVERY PHRASE")
        print("  Write this down CAREFULLY - it's your ONLY backup!")
        print("=" * 70 + "\n")

        for i in range(0, 24, 6):
            row = "  "
            for j in range(6):
                idx = i + j
                row += f"{idx+1:2}. {words[idx]:12}"
            print(row)

        print("\n" + "-" * 70)
        print(f"  Verification hash: {phrase_hash}")
        print("-" * 70 + "\n")

        input("Press Enter when you have written down ALL 24 words...")

    # Step 3: Verify recording (with retry)
    # BUG-20251218-009: Add flexible retry options
    log("Step 3/7: Verifying phrase recording...")

    # BUG-20251218-005: Clear terminal before verification test
    # This ensures previously displayed phrases are not visible during test
    if phrase_displayed_in_terminal:
        print("\n  [SECURITY] Clearing terminal before verification test...")
        print("             You must enter words from your WRITTEN notes.")
        input("  Press Enter to clear terminal and begin verification...")
        clear_terminal()

    # Verification loop with flexible options
    verification_passed = False
    while not verification_passed:
        print("\n" + "=" * 70)
        print("  RECOVERY PHRASE VERIFICATION")
        print("=" * 70)
        print(f"\n  Verification hash (for reference): {phrase_hash}")
        print("  (Use this hash to verify you've entered the phrase correctly later)")
        print()

        if verify_phrase_recording(phrase):
            log("Phrase verified ✓")
            verification_passed = True
            break
        else:
            # BUG-20251218-009: Offer flexible retry options
            print("\n" + "-" * 70)
            print("  Verification FAILED. Please check your written/printed phrase.")
            print("-" * 70)
            print("\n  Options:")
            print("    [R] Retry verification (try again)")
            print("    [S] Show phrase again (re-display)")
            print("    [C] Change storage method (switch between printable/terminal)")
            print("    [A] Abort (cancel recovery kit generation)")
            print()

            retry_choice = input("  Choose [R/S/C/A]: ").strip().upper()

            if retry_choice == "R":
                # Simply retry - loop continues
                print("\n  Retrying verification...")
                continue

            elif retry_choice == "S":
                # Re-display the phrase
                if use_printable_kit:
                    # Regenerate and open HTML
                    print("\n  Regenerating printable recovery kit...")
                    preliminary_html = generate_recovery_html(
                        phrase=phrase,
                        chunks=None,
                        header_chunks=None,
                        volume_name=drive_name,
                        volume_identity="(will be computed after verification)",
                        security_mode=mode,
                        gpg_pw_only_info=preliminary_gpg_info if "preliminary_gpg_info" in dir() else None,
                        include_qr=True,
                    )
                    preliminary_kit_path = (
                        CONFIG_FILE.parent / "recovery_kit_PRELIMINARY.html"
                        if CONFIG_FILE
                        else Path(tempfile.gettempdir()) / "keydrive_recovery_PRELIMINARY.html"
                    )
                    with open(preliminary_kit_path, "w", encoding="utf-8") as f:
                        f.write(preliminary_html)
                    if not open_html_in_browser(preliminary_kit_path):
                        print(f"\n  Please open: {preliminary_kit_path}")
                    input("\n  Press Enter when ready to retry verification...")
                else:
                    # Show in terminal again
                    print("\n" + "=" * 70)
                    print("  YOUR 24-WORD RECOVERY PHRASE")
                    print("  Write this down CAREFULLY - it's your ONLY backup!")
                    print("=" * 70 + "\n")
                    for i in range(0, 24, 6):
                        row = "  "
                        for j in range(6):
                            idx = i + j
                            row += f"{idx+1:2}. {words[idx]:12}"
                        print(row)
                    print("\n" + "-" * 70)
                    print(f"  Verification hash: {phrase_hash}")
                    print("-" * 70 + "\n")
                    input("Press Enter when you have written down ALL 24 words...")
                    # Clear before retry
                    print("\n  [SECURITY] Clearing terminal before verification test...")
                    input("  Press Enter to clear and retry verification...")
                    clear_terminal()
                continue

            elif retry_choice == "C":
                # Switch between printable and terminal
                use_printable_kit = not use_printable_kit
                if use_printable_kit:
                    print("\n  Switching to PRINTABLE mode...")
                    # Generate HTML
                    preliminary_html = generate_recovery_html(
                        phrase=phrase,
                        chunks=None,
                        header_chunks=None,
                        volume_name=drive_name if "drive_name" in dir() else Branding.PRODUCT_NAME,
                        volume_identity="(will be computed after verification)",
                        security_mode=mode if "mode" in dir() else None,
                        gpg_pw_only_info=preliminary_gpg_info if "preliminary_gpg_info" in dir() else None,
                        include_qr=True,
                    )
                    preliminary_kit_path = (
                        CONFIG_FILE.parent / "recovery_kit_PRELIMINARY.html"
                        if CONFIG_FILE
                        else Path(tempfile.gettempdir()) / "keydrive_recovery_PRELIMINARY.html"
                    )
                    with open(preliminary_kit_path, "w", encoding="utf-8") as f:
                        f.write(preliminary_html)
                    if not open_html_in_browser(preliminary_kit_path):
                        print(f"\n  Please open: {preliminary_kit_path}")
                    input("\n  Press Enter when you have printed/saved your recovery phrase...")
                    phrase_displayed_in_terminal = False
                else:
                    print("\n  Switching to TERMINAL mode...")
                    print("\n" + "=" * 70)
                    print("  YOUR 24-WORD RECOVERY PHRASE")
                    print("  Write this down CAREFULLY - it's your ONLY backup!")
                    print("=" * 70 + "\n")
                    for i in range(0, 24, 6):
                        row = "  "
                        for j in range(6):
                            idx = i + j
                            row += f"{idx+1:2}. {words[idx]:12}"
                        print(row)
                    print("\n" + "-" * 70)
                    print(f"  Verification hash: {phrase_hash}")
                    print("-" * 70 + "\n")
                    input("Press Enter when you have written down ALL 24 words...")
                    print("\n  [SECURITY] Clearing terminal before verification test...")
                    input("  Press Enter to clear and retry verification...")
                    clear_terminal()
                    phrase_displayed_in_terminal = True
                continue

            elif retry_choice == "A":
                error("Verification aborted by user.")
                sys.exit(1)
            else:
                print("  Invalid option. Please choose R, S, C, or A.")
                continue

    # Clean up any preliminary HTML after successful verification
    try:
        preliminary_kit_path = (
            CONFIG_FILE.parent / "recovery_kit_PRELIMINARY.html"
            if CONFIG_FILE
            else Path(tempfile.gettempdir()) / "keydrive_recovery_PRELIMINARY.html"
        )
        if preliminary_kit_path.exists():
            preliminary_kit_path.unlink()
    except:
        pass

    # Determine where to save recovery files
    # If volume is mounted, save there; otherwise use script directory
    if platform.system().lower() == "windows":
        is_mounted = Path(mount_target).exists()
    else:
        is_mounted = os.path.ismount(mount_target)

    if is_mounted:
        recovery_dir = get_recovery_dir(mount_target)
    else:
        # Use local .smartdrive directory as fallback
        # SCRIPT_DIR.parent is already .smartdrive/, so just append "recovery"
        # BUG FIX: Previously used ".smartdrive/recovery" which created double path
        recovery_dir = SCRIPT_DIR.parent / "recovery"

    recovery_dir.mkdir(parents=True, exist_ok=True)

    container_path = get_container_path(recovery_dir)
    header_path = get_header_path(recovery_dir)

    # Step 4: Create recovery container
    log("Step 4/7: Creating encrypted recovery container...")

    try:
        container_bytes = create_container(credentials, phrase)
        save_container(container_bytes, container_path)
        log(f"Container saved: {container_path} ✓")
    except RecoveryContainerError as e:
        error(f"Failed to create recovery container: {e}")
        sys.exit(1)

    # Step 5: Export VeraCrypt header
    log("Step 5/7: Exporting VeraCrypt header backup...")

    # TODO 4: Removed obsolete HEADER BACKUP NOTICE
    # The render_header_export_gui_guide() function provides complete,
    # command-driven guidance with CPW/CKF commands. No duplicate notice needed.

    # Write keyfile to temp location if needed
    temp_keyfile = None
    if "keyfile_bytes_b64" in credentials:
        temp_dir = get_ram_temp_dir()
        temp_keyfile = temp_dir / f"kf_{secrets.token_hex(8)}.tmp"
        temp_keyfile.write_bytes(base64.b64decode(credentials["keyfile_bytes_b64"]))

    try:
        success, used_gui = export_header(
            volume_path=volume_path,
            output_path=header_path,
            password=credentials["mount_password"],
            keyfile_path=temp_keyfile,
            allow_gui_fallback=True,
            security_mode=credentials.get("security_mode"),  # BUG-20251218-006: Pass mode for hardware key enforcement
        )
        if used_gui:
            log("Header backup guidance provided via GUI (CLI unsupported on this platform)")
        else:
            log(f"Header backup saved: {header_path} ✓")
    except VeraCryptError as e:
        error(f"Failed to export header: {e}")
        # Clean up container we just created
        if container_path.exists():
            container_path.unlink()
        sys.exit(1)
    finally:
        if temp_keyfile and temp_keyfile.exists():
            secure_delete(temp_keyfile)

    # Step 6: Update config atomically
    log("Step 6/7: Updating configuration...")

    # Compute volume identity for binding (P1)
    volume_identity = compute_volume_identity(volume_path)
    log(f"Volume identity: {volume_identity[:16]}...")

    # Capture environment snapshot (P1)
    env_snapshot = get_environment_snapshot()

    # Add volume identity to credentials for container storage
    credentials["volume_id"] = volume_identity
    credentials["environment"] = env_snapshot

    config[RECOVERY_CONFIG_KEY] = {
        "enabled": True,
        "used": False,
        "state": RECOVERY_STATE_ENABLED,
        "phrase_hash": phrase_hash,
        "container_path": str(container_path),
        "header_path": str(header_path),
        "volume_identity": volume_identity,
        "created_at": utc_timestamp_iso(),
    }

    try:
        save_config_atomic(config)
        log("Configuration updated ✓")
    except Exception as e:
        error(f"Failed to update config: {e}")
        sys.exit(1)

    # Log generation event (P1 audit)
    audit_log(
        "GENERATE_KIT",
        details={
            "volume_identity": volume_identity[:16],
            "offline_mode": args.offline,
        },
    )

    # Step 7: Generate printable kit
    log("Step 7/7: Generating printable recovery kit...")

    # Collect mode-appropriate artifacts (TODO 4)
    log("Collecting mode-appropriate artifacts...")
    smartdrive_dir = recovery_dir.parent  # recovery_dir is .smartdrive/recovery, parent is .smartdrive
    artifacts, artifact_qr_chains = collect_mode_artifacts(config, smartdrive_dir)

    # Copy artifacts to recovery directory
    if artifacts:
        log(f"Saving {len(artifacts)} artifacts to recovery directory...")
        copy_artifacts_to_recovery_dir(artifacts, recovery_dir)

    # For offline mode, include chunks
    chunks = None
    header_chunks = None
    if args.offline:
        log("Including offline recovery data (chunks)...")
        chunks = chunk_container_for_paper(container_bytes)

        # Also chunk the header backup
        header_bytes = header_path.read_bytes()
        header_chunks = chunk_container_for_paper(header_bytes)

        # Calculate and warn about page count
        total_chunks = len(chunks) + len(header_chunks)
        estimated_pages = max(1, (total_chunks + 2) // 3) + 1

        print("\n" + "=" * 70)
        print("  ⚠️  OFFLINE KIT SIZE WARNING")
        print("=" * 70)
        print(f"\n  Total chunks: {total_chunks}")
        print(f"  Estimated pages: ~{estimated_pages}")
        print("\n  IMPORTANT:")
        print("  • ALL chunks must be present and readable for recovery")
        print("  • A single lost or damaged page makes recovery IMPOSSIBLE")
        print("  • Consider printing multiple copies for redundancy")
        print("  • Store copies in separate physical locations")
        print("=" * 70 + "\n")

    html = generate_recovery_html(
        phrase=phrase,
        chunks=chunks,
        header_chunks=header_chunks,
        volume_name=volume_path,
        volume_identity=volume_identity,
        environment=env_snapshot,
        security_mode=credentials.get("security_mode"),
        gpg_pw_only_info=(
            {
                "kdf": credentials.get("kdf", CryptoParams.KDF_HKDF_SHA256),
                "salt_b64": credentials.get("salt_b64", ""),
                "hkdf_info": credentials.get("hkdf_info", CryptoParams.HKDF_INFO_DEFAULT),
            }
            if credentials.get("security_mode") == SecurityMode.GPG_PW_ONLY.value
            else None
        ),
        artifact_qr_chains=artifact_qr_chains if artifact_qr_chains else None,
    )

    # Save HTML
    kit_path = recovery_dir / f"{Branding.PRODUCT_NAME}_Recovery_Kit.html"
    kit_path.write_text(html, encoding="utf-8")
    log(f"Recovery kit saved: {kit_path}")

    # Open in browser
    # BUG-20251219-011 + BUG-20251221-001 FIX:
    # Use open_html_in_browser() with CREATE_NO_WINDOW on Windows to prevent
    # "syntax error in command line" popups
    log("Opening recovery kit in browser...")
    open_html_in_browser(kit_path)

    # Final instructions
    print("\n" + "=" * 70)
    print("  ✅ RECOVERY KIT GENERATION COMPLETE")
    print("=" * 70 + "\n")
    print("IMPORTANT:")
    print("  1. PRINT the recovery kit that just opened in your browser")
    print("  2. DELETE the digital file after printing")
    print("  3. STORE the printed kit in a secure physical location")
    print("  4. This kit can only be used ONCE")
    print(f"\nRecovery files saved to: {recovery_dir}")
    print("\n" + "=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# PAGINATED RECOVER COMMAND (CHG-20251219-003b)
# ─────────────────────────────────────────────────────────────────────────────


def cmd_recover_paginated(args):
    """
    Paginated recovery flow with [B]ack/[N]ext navigation.

    CHG-20251219-003b: Implements paginated screens that mirror setup pagination
    semantics with these security constraints:
    - Secrets (phrase, password, keyfile) stay IN-MEMORY ONLY
    - Going back past phrase entry page clears phrase from memory
    - Never re-expose secrets - require re-entry instead

    Pages:
    1. PREFLIGHT: Environment verification
    2. CONSENT: Windows security warning (Windows only)
    3. CONFIG_CHECK: Recovery kit state verification
    4. PHRASE_ENTRY: Enter 24-word recovery phrase
    5. PHRASE_VERIFY: Validate phrase hash
    6. CONFIRM: Final one-time use confirmation
    7. DECRYPT_MOUNT: Container decryption and volume mount
    8. COMPLETE: Success summary and rekey prompt
    """
    # ─────────────────────────────────────────────────────────────────────────
    # Setup pagination
    # ─────────────────────────────────────────────────────────────────────────
    pagination = RecoveryPagination()

    # Define pages (content renderers added inline)
    pagination.add_page("preflight", "Environment Verification", "PREFLIGHT", can_go_back=False)
    pagination.add_page("consent", "Security Consent", "CONSENT", can_go_back=True)
    pagination.add_page("config_check", "Recovery Kit Status", "PREFLIGHT", can_go_back=True)
    pagination.add_page("phrase_entry", "Recovery Phrase Entry", "PHRASE", requires_secret_reentry=True)
    pagination.add_page("phrase_verify", "Phrase Verification", "VERIFICATION")
    pagination.add_page("confirm", "Final Confirmation", "CONFIRMATION")
    pagination.add_page("decrypt_mount", "Decrypt & Mount", "MOUNT", can_go_back=False)
    pagination.add_page("complete", "Recovery Complete", "COMPLETE", can_go_back=False)
    pagination.finalize_pages()

    # ─────────────────────────────────────────────────────────────────────────
    # Shared state (secrets stay in local scope only)
    # ─────────────────────────────────────────────────────────────────────────
    phrase = None  # In-memory only, cleared on back navigation
    credentials = None  # Decrypted credentials, in-memory only

    audit_log("RECOVERY_ATTEMPT_START", details={"mode": "paginated"})
    config = load_config()
    volume_path, mount_target = get_volume_info(config)
    recovery_config = config.get(RECOVERY_CONFIG_KEY, {})

    # ─────────────────────────────────────────────────────────────────────────
    # Page loop with navigation
    # ─────────────────────────────────────────────────────────────────────────
    while pagination.current_page_index < len(pagination.pages):
        page = pagination.get_current_page()
        page.render_header()

        # ═══════════════════════════════════════════════════════════════════
        # PAGE: PREFLIGHT
        # ═══════════════════════════════════════════════════════════════════
        if page.page_id == "preflight":
            container_path = Path(recovery_config.get("container_path", ""))
            header_path = Path(recovery_config.get("header_path", ""))

            print("  Checking environment prerequisites...")
            print()

            preflight_ok, issues = run_preflight_checks(
                volume_path=volume_path,
                mount_target=mount_target,
                container_path=container_path if container_path.as_posix() != "." else None,
            )

            if not preflight_ok:
                print("  ❌ Environment check FAILED:\n")
                for issue in issues:
                    print(f"    • {issue}")
                print("\n" + "-" * 60)
                print(RecoveryOutcome.message(RecoveryOutcome.ENVIRONMENT_FAILURE))
                audit_log("RECOVERY_PREFLIGHT_FAILED", RecoveryOutcome.ENVIRONMENT_FAILURE, {"issues": issues})
                sys.exit(1)

            print("  ✓ VeraCrypt installed")
            print("  ✓ Volume path accessible")
            print("  ✓ Recovery container found")
            print("\n  All environment checks passed.")

            pagination.store_result("container_path", container_path)
            pagination.store_result("header_path", header_path)

        # ═══════════════════════════════════════════════════════════════════
        # PAGE: CONSENT (Windows only)
        # ═══════════════════════════════════════════════════════════════════
        elif page.page_id == "consent":
            if platform.system().lower() != "windows":
                # Skip consent page on non-Windows
                pagination.navigate_next()
                continue

            print("  ⚠️  WINDOWS SECURITY WARNING\n")
            print("  VeraCrypt on Windows requires passing the password via command line.")
            print("  This may EXPOSE THE PASSWORD to other local processes.\n")
            print("  Only continue if this system is trusted.\n")

        # ═══════════════════════════════════════════════════════════════════
        # PAGE: CONFIG_CHECK
        # ═══════════════════════════════════════════════════════════════════
        elif page.page_id == "config_check":
            # Check for pending rekey from previous incomplete recovery
            check_pending_rekey(config)

            # Check for incomplete recovery state
            if not check_incomplete_recovery_state(config):
                audit_log("RECOVERY_BLOCKED", RecoveryOutcome.PERMANENT_FAILURE, {"reason": "incomplete_state"})
                sys.exit(1)

            state = recovery_config.get("state", RECOVERY_STATE_ENABLED)

            if state == RECOVERY_STATE_USED or recovery_config.get("used"):
                print("  ❌ This recovery kit has ALREADY BEEN USED.\n")
                print("  Recovery kits are ONE-TIME USE ONLY.")
                print("\n" + "-" * 60)
                print(RecoveryOutcome.message(RecoveryOutcome.PERMANENT_FAILURE))
                audit_log("RECOVERY_BLOCKED", RecoveryOutcome.PERMANENT_FAILURE, {"reason": "already_used"})
                sys.exit(1)

            if not recovery_config.get("enabled") and state != RECOVERY_STATE_ENABLED:
                print("  ❌ Recovery is not enabled for this volume.\n")
                print("  You need to generate a recovery kit first:")
                print("    python recovery.py generate")
                audit_log("RECOVERY_BLOCKED", RecoveryOutcome.ENVIRONMENT_FAILURE, {"reason": "not_enabled"})
                sys.exit(1)

            print("  ✓ Recovery kit is enabled")
            print("  ✓ Recovery kit has not been used")
            print(f"\n  Volume: {volume_path}")
            print(f"  Mount target: {mount_target}")

        # ═══════════════════════════════════════════════════════════════════
        # PAGE: PHRASE_ENTRY
        # ═══════════════════════════════════════════════════════════════════
        elif page.page_id == "phrase_entry":
            # SECURITY: Clear any previous phrase when entering this page
            phrase = None

            print("  Enter your 24-word recovery phrase.\n")
            print("  You can enter all words on one line separated by spaces,")
            print("  or enter them one at a time.\n")

            try:
                phrase_input = input("  Recovery phrase: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n\n" + "-" * 60)
                print(RecoveryOutcome.message(RecoveryOutcome.USER_ABORT))
                audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT, {"reason": "input_cancelled"})
                sys.exit(0)

            words = phrase_input.split()
            while len(words) < 24:
                try:
                    more = input(f"    (have {len(words)}/24 words, continue): ").strip()
                    words.extend(more.split())
                except (KeyboardInterrupt, EOFError):
                    print("\n\n" + "-" * 60)
                    print(RecoveryOutcome.message(RecoveryOutcome.USER_ABORT))
                    audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT)
                    sys.exit(0)

            if len(words) != 24:
                print(f"\n  ❌ Expected 24 words, got {len(words)}")
                print("\n  Please go back and try again.")
                # Stay on this page - user must re-enter
                nav = pagination.prompt_navigation(allow_back=True, custom_prompt="  [B]ack to retry | [Q]uit")
                if nav == "Q":
                    audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT)
                    sys.exit(0)
                continue

            phrase = " ".join(words[:24])

            # Validate BIP39 checksum immediately
            if not verify_bip39_phrase(phrase):
                print("\n  ❌ Invalid recovery phrase (BIP39 checksum failed)")
                print("  Please check that you entered all words correctly.\n")
                phrase = None  # Clear invalid phrase
                nav = pagination.prompt_navigation(allow_back=True, custom_prompt="  [B]ack to retry | [Q]uit")
                if nav == "Q":
                    audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT)
                    sys.exit(0)
                continue

            print("\n  ✓ 24 words entered")
            print("  ✓ BIP39 checksum valid")

        # ═══════════════════════════════════════════════════════════════════
        # PAGE: PHRASE_VERIFY
        # ═══════════════════════════════════════════════════════════════════
        elif page.page_id == "phrase_verify":
            if phrase is None:
                # Phrase was cleared - go back to entry page
                pagination.current_page_index = next(
                    i for i, p in enumerate(pagination.pages) if p.page_id == "phrase_entry"
                )
                continue

            phrase_hash = hash_phrase(phrase)
            expected_hash = recovery_config.get("phrase_hash", "")

            print(f"  Your phrase hash:     {phrase_hash}")
            print(f"  Expected hash:        {expected_hash}\n")

            if phrase_hash != expected_hash:
                print("  ❌ Phrase does NOT match this recovery kit!\n")
                print("  This phrase was not generated for this volume.")
                print("  Please verify you have the correct recovery phrase.\n")
                # SECURITY: Clear phrase and force re-entry
                phrase = None
                audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "phrase_hash_mismatch"})
                nav = pagination.prompt_navigation(
                    allow_back=True, custom_prompt="  [B]ack to re-enter phrase | [Q]uit"
                )
                if nav == "Q":
                    sys.exit(1)
                elif nav == "B":
                    pagination.navigate_back()
                continue

            print("  ✓ Phrase verified for this volume")

        # ═══════════════════════════════════════════════════════════════════
        # PAGE: CONFIRM
        # ═══════════════════════════════════════════════════════════════════
        elif page.page_id == "confirm":
            print("  ⚠️  FINAL CONFIRMATION\n")
            print("  This is a ONE-TIME recovery.")
            print("  If successful, this kit will be PERMANENTLY INVALIDATED.\n")
            print("  Type RECOVER to continue (anything else aborts):\n")

            try:
                confirm = input("  Confirm: ").strip()
            except (KeyboardInterrupt, EOFError):
                confirm = ""

            if confirm != UserInputs.RECOVER:
                print("\n" + "-" * 60)
                print(RecoveryOutcome.message(RecoveryOutcome.USER_ABORT))
                audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT, {"reason": "confirmation_declined"})
                sys.exit(0)

            print("\n  ✓ Confirmation received")

        # ═══════════════════════════════════════════════════════════════════
        # PAGE: DECRYPT_MOUNT
        # ═══════════════════════════════════════════════════════════════════
        elif page.page_id == "decrypt_mount":
            container_path = pagination.get_result("container_path")
            header_path = pagination.get_result("header_path")

            print("  Decrypting recovery container...\n")

            try:
                container_bytes = load_container(container_path)
                credentials = decrypt_container(container_bytes, phrase)
                print("  ✓ Container decrypted\n")
            except RecoveryContainerError as e:
                print(f"  ❌ Failed to decrypt container: {e}\n")
                print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
                audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "decrypt_failed"})
                sys.exit(1)

            # Volume binding verification
            container_volume = credentials.get(ConfigKeys.VOLUME_PATH, "")

            def normalize_path(p):
                return str(Path(p).resolve()).lower() if p else ""

            if container_volume and normalize_path(container_volume) != normalize_path(volume_path):
                print("  ❌ VOLUME PATH MISMATCH!\n")
                print(f"    Expected: {container_volume}")
                print(f"    Got:      {volume_path}")
                audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "path_mismatch"})
                sys.exit(1)

            print("  ✓ Volume binding verified\n")

            # Extract credentials
            password = credentials.get("mount_password")
            keyfile_b64 = credentials.get("keyfile_bytes_b64")

            if not password:
                print("  ❌ Recovery container is missing password!\n")
                audit_log("RECOVERY_FAILED", RecoveryOutcome.PERMANENT_FAILURE, {"reason": "no_password"})
                sys.exit(1)

            # Mount volume
            print("  Mounting volume...")

            temp_keyfile = None
            if keyfile_b64:
                temp_dir = get_ram_temp_dir()
                temp_keyfile = temp_dir / f"kf_{secrets.token_hex(8)}.tmp"
                temp_keyfile.write_bytes(base64.b64decode(keyfile_b64))

            mount_success = False
            header_restored = False

            try:
                success, err = try_mount(
                    volume_path=volume_path,
                    mount_point=mount_target,
                    password=password,
                    keyfile_path=temp_keyfile,
                )
                mount_success = success

                if success:
                    print(f"  ✓ Volume mounted at {mount_target}\n")
                else:
                    print(f"  ❌ Mount failed: {err}\n")
                    print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
                    audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "mount_failed"})

            except HeaderCorruptionError:
                print("  ⚠️  Volume header is CORRUPTED!")
                print("  Attempting header restoration...\n")

                if header_path and header_path.exists():
                    try:
                        restore_header(
                            volume_path=volume_path,
                            header_backup_path=header_path,
                            password=password,
                            keyfile_path=temp_keyfile,
                        )
                        print("  ✓ Header restored\n")
                        header_restored = True

                        success, err = try_mount(
                            volume_path=volume_path,
                            mount_point=mount_target,
                            password=password,
                            keyfile_path=temp_keyfile,
                        )
                        mount_success = success

                        if success:
                            print(f"  ✓ Volume mounted at {mount_target}\n")
                        else:
                            print(f"  ❌ Mount failed after header restore: {err}\n")
                    except VeraCryptError as e:
                        print(f"  ❌ Header restoration failed: {e}\n")
                else:
                    print("  ❌ No header backup available!\n")

            except InvalidCredentialsError:
                print("  ❌ Recovered credentials are invalid!\n")
                audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "invalid_credentials"})

            except VeraCryptError as e:
                print(f"  ❌ VeraCrypt error: {e}\n")
                audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": str(e)})

            finally:
                if temp_keyfile and temp_keyfile.exists():
                    secure_delete(temp_keyfile)

            if not mount_success:
                sys.exit(1)

            # Two-phase commit
            print("  Enforcing one-time use...")

            recovery_config["state"] = RECOVERY_STATE_CONSUMING
            config[RECOVERY_CONFIG_KEY] = recovery_config
            try:
                save_config_atomic(config)
            except Exception:
                pass

            try:
                secure_delete(container_path)
            except Exception:
                try:
                    container_path.unlink()
                except Exception:
                    pass

            config[RECOVERY_CONFIG_KEY] = {
                "enabled": False,
                "used": True,
                "state": RECOVERY_STATE_USED,
                "invalidated_at": utc_timestamp_iso(),
                "header_restored": header_restored,
            }

            config[POST_RECOVERY_KEY] = {
                "rekey_required": True,
                "rekey_completed": False,
                "recovery_completed_at": utc_timestamp_iso(),
            }

            try:
                save_config_atomic(config)
            except Exception:
                pass

            audit_log("RECOVERY_SUCCESS", RecoveryOutcome.SUCCESS, {"header_restored": header_restored})

            # Store for complete page
            pagination.store_result("mount_target", mount_target)
            pagination.store_result("header_restored", header_restored)

        # ═══════════════════════════════════════════════════════════════════
        # PAGE: COMPLETE
        # ═══════════════════════════════════════════════════════════════════
        elif page.page_id == "complete":
            mount_target = pagination.get_result("mount_target")
            header_restored = pagination.get_result("header_restored", False)

            print("  ✅ RECOVERY SUCCESSFUL\n")
            print(f"  Volume mounted at: {mount_target}")
            if header_restored:
                print("\n  ⚠️  Header was corrupted and has been restored.")

            print("\n  " + "-" * 56)
            print("  WHAT HAPPENED:")
            print("    • Your recovery kit has been PERMANENTLY INVALIDATED")
            print("    • The recovery container has been deleted")
            print("    • Your volume is now mounted and accessible")
            print("  " + "-" * 56)

            print("\n  WHAT YOU MUST DO NOW:")
            print("    1. IMMEDIATELY change your credentials (rekey)")
            print("    2. Generate a NEW recovery kit")
            print(f"\n  Audit log: {RECOVERY_LOG_FILE}")

            print("\n" + "=" * 60)
            print("  ⚠️  MANDATORY: CHANGE YOUR CREDENTIALS NOW")
            print("=" * 60 + "\n")

            confirm = input("  Start credential change now? [Y/n]: ")
            if confirm.lower() != "n":
                try:
                    rekey_path = SCRIPT_DIR / "rekey.py"
                    result = subprocess.run([sys.executable, str(rekey_path)], cwd=str(SCRIPT_DIR))

                    if result.returncode == 0:
                        config[POST_RECOVERY_KEY] = {
                            "rekey_required": False,
                            "rekey_completed": True,
                            "completed_at": utc_timestamp_iso(),
                        }
                        save_config_atomic(config)
                        audit_log("REKEY_SUCCESS")
                        print("\n  Don't forget to generate a NEW recovery kit:")
                        print("    python recovery.py generate")
                    else:
                        print("\n  ⚠️  Rekey did not complete. Run 'python rekey.py' manually.")
                        audit_log("REKEY_INCOMPLETE")
                except Exception as e:
                    print(f"\n  ⚠️  Could not start rekey: {e}")
                    audit_log("REKEY_ERROR", details={"error": str(e)})
            else:
                print("\n  ⚠️  YOU SKIPPED CREDENTIAL CHANGE!")
                print("  Run 'python rekey.py' as soon as possible!")
                audit_log("REKEY_SKIPPED")

            return  # Done

        # ═══════════════════════════════════════════════════════════════════
        # NAVIGATION PROMPT
        # ═══════════════════════════════════════════════════════════════════
        # Show navigation prompt for pages that allow it
        if page.page_id not in ("complete", "decrypt_mount"):
            nav = pagination.prompt_navigation()

            if nav == "Q":
                print("\n" + "-" * 60)
                print(RecoveryOutcome.message(RecoveryOutcome.USER_ABORT))
                audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT)
                sys.exit(0)
            elif nav == "B":
                # SECURITY: Clear secrets if going back past phrase entry
                if pagination.pages_requiring_secret_reentry_between(
                    pagination.current_page_index, pagination.current_page_index - 1
                ):
                    phrase = None
                    credentials = None
                pagination.navigate_back()
            else:  # nav == "N"
                pagination.navigate_next()
        else:
            # Auto-advance for non-navigable pages
            pagination.navigate_next()


# ─────────────────────────────────────────────────────────────────────────────
# RECOVER COMMAND
# ─────────────────────────────────────────────────────────────────────────────


def cmd_recover(args):
    """
    Recover access using recovery phrase.

    CHG-20251219-003b: If --paginated flag is set, use paginated navigation mode.

    INVARIANTS:
    - One-time after SUCCESS, not one-time per attempt
    - A failed mount does NOT burn the recovery kit
    - Every failure maps to exactly one RecoveryOutcome
    - Preflight checks run BEFORE any state transition

    Flow:
    1. Load config and run preflight checks (ENVIRONMENT_FAILURE if failed)
    2. Windows security consent (USER_ABORT if declined)
    3. Check for incomplete recovery state
    4. Human confirmation before consumption
    5. Read and validate recovery phrase
    6. Verify phrase hash and volume binding
    7. Decrypt recovery container
    8. Attempt mount with recovered credentials
    9. ONLY ON SUCCESS: Two-phase commit + rekey
    """
    # CHG-20251219-003b: Dispatch to paginated flow if requested
    if getattr(args, "paginated", False):
        return cmd_recover_paginated(args)

    outcome = RecoveryOutcome.TRANSIENT_FAILURE  # Default to safe retry

    # Log attempt start
    audit_log("RECOVERY_ATTEMPT_START")

    config = load_config()
    volume_path, mount_target = get_volume_info(config)
    recovery_config = config.get(RECOVERY_CONFIG_KEY, {})

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 0: PREFLIGHT CHECKS (P0) - Run BEFORE any state transition
    # ═══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 70)
    print(f"  {Branding.PRODUCT_NAME.upper()} RECOVERY MODE")
    print("=" * 70 + "\n")

    log("Running environment preflight checks...")

    container_path = Path(recovery_config.get("container_path", ""))
    header_path = Path(recovery_config.get("header_path", ""))

    preflight_ok, issues = run_preflight_checks(
        volume_path=volume_path,
        mount_target=mount_target,
        container_path=container_path if container_path.as_posix() != "." else None,
    )

    if not preflight_ok:
        print("\n" + "=" * 70)
        print("  ❌ ENVIRONMENT CHECK FAILED")
        print("=" * 70 + "\n")
        print("Recovery cannot proceed due to environment issues:\n")
        for issue in issues:
            print(f"  • {issue}")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.ENVIRONMENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_PREFLIGHT_FAILED", RecoveryOutcome.ENVIRONMENT_FAILURE, {"issues": issues})
        sys.exit(1)

    log("Preflight checks passed ✓")

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1: Platform consent and state checks
    # ═══════════════════════════════════════════════════════════════════════

    # P0: Windows runtime consent for password exposure
    if platform.system().lower() == "windows":
        print("\n" + "=" * 70)
        print("  ⚠️  WINDOWS SECURITY WARNING")
        print("=" * 70 + "\n")
        print("VeraCrypt on Windows requires passing the password via command line.")
        print("This may EXPOSE THE PASSWORD to other local processes.\n")
        print("Only continue if this system is trusted.\n")

        confirm = input("Type YES to continue: ").strip()
        if confirm != UserInputs.YES:
            print("\n" + "-" * 70)
            print(RecoveryOutcome.message(RecoveryOutcome.USER_ABORT))
            print("-" * 70 + "\n")
            audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT, {"reason": "windows_consent_declined"})
            sys.exit(0)

    # Check for pending rekey from previous incomplete recovery
    check_pending_rekey(config)

    # P0: Check for incomplete recovery state (crash between deletion and config update)
    if not check_incomplete_recovery_state(config):
        audit_log("RECOVERY_BLOCKED", RecoveryOutcome.PERMANENT_FAILURE, {"reason": "incomplete_state"})
        sys.exit(1)

    # Check recovery config state
    log("Step 1/9: Checking recovery configuration...")

    state = recovery_config.get("state", RECOVERY_STATE_ENABLED)

    if state == RECOVERY_STATE_USED or recovery_config.get("used"):
        error("This recovery kit has ALREADY BEEN USED.")
        error("Recovery kits are ONE-TIME USE ONLY.")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.PERMANENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_BLOCKED", RecoveryOutcome.PERMANENT_FAILURE, {"reason": "already_used"})
        sys.exit(1)

    if not recovery_config.get("enabled") and state != RECOVERY_STATE_ENABLED:
        error("Recovery is not enabled for this volume.")
        error("You need to generate a recovery kit first: python recovery.py generate")
        audit_log("RECOVERY_BLOCKED", RecoveryOutcome.ENVIRONMENT_FAILURE, {"reason": "not_enabled"})
        sys.exit(1)

    log("Recovery is enabled and unused ✓")

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 2: Collect and validate recovery phrase
    # ═══════════════════════════════════════════════════════════════════════

    log("Step 2/9: Enter your recovery phrase...")

    print("\nEnter your 24-word recovery phrase.")
    print("You can enter all words on one line separated by spaces,")
    print("or enter them one at a time.\n")

    try:
        phrase_input = input("Recovery phrase: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.USER_ABORT))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT, {"reason": "input_cancelled"})
        sys.exit(0)

    # Handle multi-line input
    words = phrase_input.split()
    while len(words) < 24:
        try:
            more = input(f"  (have {len(words)}/24 words, continue): ").strip()
            words.extend(more.split())
        except (KeyboardInterrupt, EOFError):
            print("\n\n" + "-" * 70)
            print(RecoveryOutcome.message(RecoveryOutcome.USER_ABORT))
            print("-" * 70 + "\n")
            audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT)
            sys.exit(0)

    if len(words) != 24:
        error(f"Expected 24 words, got {len(words)}")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "wrong_word_count"})
        sys.exit(1)

    phrase = " ".join(words[:24])

    # Step 3: Validate BIP39 checksum
    log("Step 3/9: Validating phrase...")

    if not verify_bip39_phrase(phrase):
        error("Invalid recovery phrase (BIP39 checksum failed)")
        error("Please check that you entered all words correctly.")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "bip39_checksum_failed"})
        sys.exit(1)

    log("BIP39 checksum valid ✓")

    # Step 4: Verify phrase hash
    log("Step 4/9: Verifying phrase matches this volume...")

    phrase_hash = hash_phrase(phrase)
    expected_hash = recovery_config.get("phrase_hash", "")

    if phrase_hash != expected_hash:
        error("Phrase does not match the recovery kit for this volume!")
        error(f"Expected hash: {expected_hash}")
        error(f"Got hash:      {phrase_hash}")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "phrase_hash_mismatch"})
        sys.exit(1)

    log("Phrase verified for this volume ✓")

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: HUMAN CONFIRMATION BEFORE CONSUMPTION (P1)
    # ═══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 70)
    print("  ⚠️  FINAL CONFIRMATION")
    print("=" * 70 + "\n")
    print("This is a ONE-TIME recovery.")
    print("If successful, this kit will be PERMANENTLY INVALIDATED.\n")
    print("Type RECOVER to continue (anything else aborts):\n")

    try:
        confirm = input("Confirm: ").strip()
    except (KeyboardInterrupt, EOFError):
        confirm = ""

    if confirm != UserInputs.RECOVER:
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.USER_ABORT))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_CANCELLED", RecoveryOutcome.USER_ABORT, {"reason": "confirmation_declined"})
        sys.exit(0)

    print()  # Blank line

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 4: Locate and decrypt container
    # ═══════════════════════════════════════════════════════════════════════

    log("Step 5/9: Locating recovery container...")

    if not container_path.exists():
        error(f"Recovery container not found: {container_path}")
        error("\nIf you have paper backup chunks, run:")
        error("  python recovery.py reconstruct <chunks.txt>")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.ENVIRONMENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.ENVIRONMENT_FAILURE, {"reason": "container_not_found"})
        sys.exit(1)

    log(f"Container found: {container_path} ✓")

    log("Step 6/9: Decrypting recovery container...")

    try:
        container_bytes = load_container(container_path)
        credentials = decrypt_container(container_bytes, phrase)
        log("Container decrypted successfully ✓")
    except RecoveryContainerError as e:
        error(f"Failed to decrypt container: {e}")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "decrypt_failed"})
        sys.exit(1)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 5: Volume binding verification (P1 - strengthened)
    # ═══════════════════════════════════════════════════════════════════════

    container_volume = credentials.get(ConfigKeys.VOLUME_PATH, "")
    container_volume_id = credentials.get("volume_id", "")
    expected_volume_id = recovery_config.get("volume_identity", "")

    # Normalize paths for comparison
    def normalize_path(p):
        return str(Path(p).resolve()).lower() if p else ""

    # Check path binding
    if container_volume and normalize_path(container_volume) != normalize_path(volume_path):
        error("VOLUME PATH MISMATCH!")
        error(f"This recovery kit was generated for: {container_volume}")
        error(f"Current target volume is:            {volume_path}")
        error("\nThis recovery kit cannot be used on a different volume.")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "path_mismatch"})
        sys.exit(1)

    # Check volume identity binding (P1 - strengthened)
    if container_volume_id and expected_volume_id:
        id_match, id_msg = verify_volume_identity(
            expected_id=container_volume_id,
            volume_path=volume_path,
            header_backup_path=header_path,
        )
        if not id_match:
            error("VOLUME IDENTITY MISMATCH!")
            error(id_msg)
            error("\nThis recovery kit may be for a different volume.")
            print("\n" + "-" * 70)
            print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
            print("-" * 70 + "\n")
            audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "identity_mismatch"})
            sys.exit(1)
        log(id_msg)

    log("Volume binding verified ✓")

    # Extract credentials
    password = credentials.get("mount_password")
    keyfile_b64 = credentials.get("keyfile_bytes_b64")

    if not password:
        error("Recovery container is missing password!")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.PERMANENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.PERMANENT_FAILURE, {"reason": "no_password_in_container"})
        sys.exit(1)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 6: Mount volume
    # ═══════════════════════════════════════════════════════════════════════

    log("Step 7/9: Mounting volume with recovered credentials...")

    # Write keyfile to temp if needed
    temp_keyfile = None
    if keyfile_b64:
        temp_dir = get_ram_temp_dir()
        temp_keyfile = temp_dir / f"kf_{secrets.token_hex(8)}.tmp"
        temp_keyfile.write_bytes(base64.b64decode(keyfile_b64))

    mount_success = False
    header_restored = False

    try:
        success, err = try_mount(
            volume_path=volume_path,
            mount_point=mount_target,
            password=password,
            keyfile_path=temp_keyfile,
        )
        mount_success = success

        if success:
            log(f"Volume mounted at {mount_target} ✓")
        else:
            error(f"Mount failed: {err}")
            print("\n" + "-" * 70)
            print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
            print("-" * 70 + "\n")
            audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "mount_failed"})

    except HeaderCorruptionError:
        warn("Volume header is CORRUPTED!")
        log("Attempting header restoration...")

        if not header_path.exists():
            error(f"Header backup not found: {header_path}")
            error("Cannot recover from header corruption without backup!")
            print("\n" + "-" * 70)
            print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
            print("-" * 70 + "\n")
            audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "header_corrupt_no_backup"})
            sys.exit(1)

        try:
            restore_header(
                volume_path=volume_path,
                header_backup_path=header_path,
                password=password,
                keyfile_path=temp_keyfile,
            )
            log("Header restored successfully ✓")
            header_restored = True

            # Retry mount
            success, err = try_mount(
                volume_path=volume_path,
                mount_point=mount_target,
                password=password,
                keyfile_path=temp_keyfile,
            )
            mount_success = success

            if success:
                log(f"Volume mounted at {mount_target} ✓")
            else:
                error(f"Mount failed after header restore: {err}")
                print("\n" + "-" * 70)
                print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
                print("-" * 70 + "\n")
                audit_log(
                    "RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "mount_failed_after_restore"}
                )

        except VeraCryptError as e:
            error(f"Header restoration failed: {e}")
            print("\n" + "-" * 70)
            print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
            print("-" * 70 + "\n")
            audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "header_restore_failed"})
            sys.exit(1)

    except InvalidCredentialsError:
        error("Recovered credentials are invalid!")
        error("This should not happen - the recovery container may be corrupted.")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": "invalid_credentials"})
        sys.exit(1)

    except VeraCryptError as e:
        error(f"VeraCrypt error: {e}")
        print("\n" + "-" * 70)
        print(RecoveryOutcome.message(RecoveryOutcome.TRANSIENT_FAILURE))
        print("-" * 70 + "\n")
        audit_log("RECOVERY_FAILED", RecoveryOutcome.TRANSIENT_FAILURE, {"reason": f"veracrypt_error: {e}"})
        sys.exit(1)

    finally:
        if temp_keyfile and temp_keyfile.exists():
            secure_delete(temp_keyfile)

    if not mount_success:
        sys.exit(1)

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 7: TWO-PHASE COMMIT (P0) - Crash-safe state transitions
    # ═══════════════════════════════════════════════════════════════════════

    log("Step 8/9: Enforcing one-time use (two-phase commit)...")

    # Phase 1: Transition to "consuming" state
    recovery_config["state"] = RECOVERY_STATE_CONSUMING
    config[RECOVERY_CONFIG_KEY] = recovery_config
    try:
        save_config_atomic(config)
        log("Phase 1: Marked as consuming ✓")
    except Exception as e:
        warn(f"Failed to mark consuming state: {e}")

    # Phase 2: Delete container
    try:
        secure_delete(container_path)
        log("Phase 2: Recovery container permanently deleted ✓")
    except Exception as e:
        warn(f"Could not securely delete container: {e}")
        try:
            container_path.unlink()
            log("Phase 2: Recovery container deleted (standard) ✓")
        except Exception as e2:
            warn(f"Could not delete container: {e2}")
            warn("SECURITY: Manually delete the recovery container!")

    # Phase 3: Transition to "used" state
    config[RECOVERY_CONFIG_KEY] = {
        "enabled": False,
        "used": True,
        "state": RECOVERY_STATE_USED,
        "invalidated_at": utc_timestamp_iso(),
        "header_restored": header_restored,
    }

    config[POST_RECOVERY_KEY] = {
        "rekey_required": True,
        "rekey_completed": False,
        "recovery_completed_at": utc_timestamp_iso(),
    }

    try:
        save_config_atomic(config)
        log("Phase 3: Configuration updated ✓")
    except Exception as e:
        warn(f"Failed to update config: {e}")

    # Log success
    audit_log("RECOVERY_SUCCESS", RecoveryOutcome.SUCCESS, {"header_restored": header_restored})

    # ═══════════════════════════════════════════════════════════════════════
    # STEP 8: SUCCESS EPILOGUE (P1)
    # ═══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 70)
    print("  ✅ RECOVERY SUCCESSFUL")
    print("=" * 70 + "\n")
    print(f"Volume mounted at: {mount_target}")
    if header_restored:
        print("\n⚠️  Header was corrupted and has been restored from backup.")

    print("\n" + "-" * 70)
    print("WHAT HAPPENED:")
    print("  • Your recovery kit has been PERMANENTLY INVALIDATED")
    print("  • The recovery container has been deleted")
    print("  • Your volume is now mounted and accessible")
    print("-" * 70)

    print("\nWHAT YOU MUST DO NOW:")
    print("  1. IMMEDIATELY change your credentials (rekey)")
    print("  2. Generate a NEW recovery kit")
    print("  3. Check recovery.log for audit trail")
    print(f"\nAudit log: {RECOVERY_LOG_FILE}")

    # Step 9: Force rekey with tracking
    log("Step 9/9: Credential change...")
    print("\n" + "=" * 70)
    print("  ⚠️  MANDATORY: CHANGE YOUR CREDENTIALS NOW")
    print("=" * 70 + "\n")

    confirm = input("Start credential change now? [Y/n]: ")
    if confirm.lower() != "n":
        log("Starting rekey process...")

        try:
            rekey_path = SCRIPT_DIR / "rekey.py"
            result = subprocess.run(
                [sys.executable, str(rekey_path)],
                cwd=str(SCRIPT_DIR),
            )

            if result.returncode != 0:
                warn("Rekey process did not complete successfully!")
                warn("Run 'python rekey.py' manually as soon as possible.")
                audit_log("REKEY_INCOMPLETE")
            else:
                config[POST_RECOVERY_KEY] = {
                    "rekey_required": False,
                    "rekey_completed": True,
                    "completed_at": utc_timestamp_iso(),
                }
                save_config_atomic(config)
                log("Credential change complete ✓")
                audit_log("REKEY_SUCCESS")
                print("\nDon't forget to generate a NEW recovery kit:")
                print("  python recovery.py generate")

        except Exception as e:
            warn(f"Could not start rekey: {e}")
            warn("Run 'python rekey.py' manually as soon as possible.")
            audit_log("REKEY_ERROR", details={"error": str(e)})
    else:
        warn("\n⚠️  YOU SKIPPED CREDENTIAL CHANGE!")
        warn("Run 'python rekey.py' as soon as possible!")
        audit_log("REKEY_SKIPPED")


# ─────────────────────────────────────────────────────────────────────────────
# RECONSTRUCT COMMAND
# ─────────────────────────────────────────────────────────────────────────────


def cmd_reconstruct(args):
    """
    Reconstruct recovery files from paper chunks.

    This is for offline-complete recovery when digital files are lost
    but paper backup with encoded chunks exists.

    Flow:
    1. Read chunks from file
    2. Validate ordering and hashes
    3. Rebuild files to .smartdrive/recovery/
    """
    config = load_config()
    volume_path, mount_target = get_volume_info(config)

    print("\n" + "=" * 70)
    print(f"  {Branding.PRODUCT_NAME.upper()} OFFLINE RECONSTRUCTION")
    print("=" * 70 + "\n")

    chunks_file = Path(args.chunks_file)
    if not chunks_file.exists():
        error(f"Chunks file not found: {chunks_file}")
        sys.exit(1)

    log(f"Reading chunks from: {chunks_file}")

    # Read all chunks from file
    # Each chunk should be on its own line, format: SDRC:v1:INDEX/TOTAL:HASH:DATA:CRC
    with open(chunks_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse chunks - look for lines starting with SDRC:
    container_chunks = []
    header_chunks = []

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("SDRC:"):
            # Determine if it's a container or header chunk based on context
            # For now, assume all are container chunks unless file has sections
            container_chunks.append(line)

    if not container_chunks:
        error("No valid chunks found in file!")
        error("Chunks should start with 'SDRC:v1:'")
        sys.exit(1)

    log(f"Found {len(container_chunks)} chunks")

    # Reconstruct container
    log("Reconstructing recovery container...")

    try:
        container_bytes = reconstruct_from_chunks(container_chunks)
        log("Container reconstructed successfully ✓")
    except RecoveryContainerError as e:
        error(f"Failed to reconstruct container: {e}")
        sys.exit(1)

    # Determine recovery directory
    if platform.system().lower() == "windows":
        is_mounted = Path(mount_target).exists()
    else:
        is_mounted = os.path.ismount(mount_target)

    if is_mounted:
        recovery_dir = get_recovery_dir(mount_target)
    else:
        # SCRIPT_DIR.parent is already .smartdrive/, so just append "recovery"
        # BUG FIX: Previously used ".smartdrive/recovery" which created double path
        recovery_dir = SCRIPT_DIR.parent / "recovery"

    recovery_dir.mkdir(parents=True, exist_ok=True)
    container_path = get_container_path(recovery_dir)

    # Save reconstructed container
    save_container(container_bytes, container_path)
    log(f"Container saved: {container_path}")

    # Update config with container path
    recovery_config = config.get(RECOVERY_CONFIG_KEY, {})
    recovery_config["container_path"] = str(container_path)
    config[RECOVERY_CONFIG_KEY] = recovery_config

    try:
        save_config_atomic(config)
    except Exception as e:
        warn(f"Could not update config: {e}")

    print("\n" + "=" * 70)
    print("  ✅ RECONSTRUCTION COMPLETE")
    print("=" * 70 + "\n")
    print(f"Recovery container saved to: {container_path}")
    print("\nYou can now run: python recovery.py recover")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description=f"{Branding.PRODUCT_NAME} Recovery System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  generate    Create a new recovery kit with encrypted credentials
  recover     Restore access using your 24-word recovery phrase
  reconstruct Rebuild recovery files from paper backup chunks

Examples:
  python recovery.py generate           # Create recovery kit
  python recovery.py generate --offline # Include paper-encodable chunks
  python recovery.py recover            # Use recovery phrase to restore access
  python recovery.py reconstruct chunks.txt  # Rebuild from paper backup
        """,
    )

    # Global --config option for all commands
    parser.add_argument(
        "--config", "-c", type=Path, metavar="PATH", help="Absolute path to config.json (propagated from caller)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Status command - for import verification
    status_parser = subparsers.add_parser(
        "status", help="Verify module imports and show environment status (for setup verification)"
    )

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate a new recovery kit")
    gen_parser.add_argument("--offline", action="store_true", help="Include chunk data for paper-only reconstruction")
    gen_parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration even if active kit exists (requires explicit confirmation)",
    )

    # Recover command
    rec_parser = subparsers.add_parser("recover", help="Recover access using recovery phrase")
    rec_parser.add_argument(
        "--paginated",
        action="store_true",
        help="CHG-20251219-003b: Enable paginated navigation with [B]ack/[N]ext controls",
    )

    # Reconstruct command
    recon_parser = subparsers.add_parser("reconstruct", help="Reconstruct recovery files from paper chunks")
    recon_parser.add_argument("chunks_file", help="Path to file containing paper backup chunks")

    args = parser.parse_args()

    # Override global CONFIG_FILE if --config provided
    global CONFIG_FILE
    if args.config:
        config_path = Path(args.config).resolve()
        if config_path.exists():
            CONFIG_FILE = config_path
            print(f"[recovery] Using explicit config: {CONFIG_FILE}")
        else:
            print(f"[ERROR] Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to command handler
    if args.command == "status":
        # Simple status check - if we got here, imports worked
        print("recovery.py import verification: OK")
        print(f"  VERSION: {VERSION}")
        print(f"  ConfigKeys: {ConfigKeys is not None}")
        print(f"  SecurityMode: {SecurityMode is not None}")
        print(f"  Limits: {Limits is not None}")
        print(f"  Paths: {Paths is not None}")
        sys.exit(0)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "recover":
        cmd_recover(args)
    elif args.command == "reconstruct":
        cmd_reconstruct(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Cancelled by user]")
        wait_before_exit("Press Enter to close...")
        sys.exit(130)
    except SystemExit as e:
        # If exiting with error code, give user time to read messages
        if e.code and e.code != 0:
            wait_before_exit("Press Enter to close...")
        raise
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}", file=sys.stderr)
        wait_before_exit("Press Enter to close...")
        sys.exit(1)
