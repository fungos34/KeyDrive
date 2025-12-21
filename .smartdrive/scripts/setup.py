#!/usr/bin/env python3
"""
KeyDrive Setup Wizard

Automated setup for encrypted external drives with YubiKey + VeraCrypt:
- Detect and select external drive
- Partition drive (KeyDrive + PAYLOAD)
- Create VeraCrypt encrypted volume
- Add YubiKey protection
- Copy scripts and generate config

[!] WARNING: This script performs DESTRUCTIVE operations!
All data on the selected drive will be permanently erased.

Dependencies:
- Python 3.7+
- gpg in PATH with YubiKeys configured
- VeraCrypt installed
- Administrator/root privileges

Usage:
    python setup.py              # Interactive wizard
    python setup.py --help       # Show options
"""

import base64
import ctypes
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from getpass import getpass
from pathlib import Path
from typing import Optional

# =============================================================================
# Core module imports - SINGLE SOURCE OF TRUTH
# =============================================================================
_script_dir = Path(__file__).resolve().parent

# Determine execution context (deployed vs development)
# Note: ".smartdrive" literal used here because FileNames not yet imported
if _script_dir.parent.name == ".smartdrive":
    # Deployed on drive: .smartdrive/scripts/setup.py
    # DEPLOY_ROOT = .smartdrive/, add to path for 'from core.x import y'
    _deploy_root = _script_dir.parent
    _project_root = _deploy_root.parent  # drive root
    if str(_deploy_root) not in sys.path:
        sys.path.insert(0, str(_deploy_root))
else:
    # Development: scripts/setup.py at repo root
    _project_root = _script_dir.parent

if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.config import write_config_atomic

# Import configuration constants (legacy - for file names)
from core.constants import Branding, ConfigKeys, CryptoParams, Defaults, FileNames, Prompts, UserInputs
from core.filesystems import FS, launcher_fs_spec
from core.limits import Limits
from core.modes import _SECRETS_AVAILABLE  # Module-level flag (not Enum attribute)
from core.modes import SECURITY_MODE_DISPLAY, SecurityMode, VolumeIdentifier, VolumeIdentifierKind
from core.paths import DEPLOYED_SCRIPTS_DIR, Paths, normalize_mount_letter
from core.platform import get_instantiation_drive, get_os_drive, get_platform, is_drive_protected
from core.platform import is_windows as _is_windows
from core.platform import windows_create_shortcut, windows_refresh_explorer, windows_set_attributes
from core.safety import (
    DiskIdentity,
    DiskSnapshot,
    PartitionRef,
    SafetyValidationResult,
    SetupSafetyPolicy,
    SetupType,
    detect_source_disk,
    get_disk_snapshot_windows,
    get_target_disk_identity_windows,
    resolve_launcher_partition_windows,
    resolve_payload_partition_windows,
)
from core.version import VERSION

# Fallback to FileNames from core - SSOT branding from Branding class
BAT_LAUNCHER_NAME = FileNames.BAT_LAUNCHER
GUI_BAT_LAUNCHER_NAME = FileNames.GUI_BAT_LAUNCHER
SH_LAUNCHER_NAME = FileNames.SH_LAUNCHER
GUI_EXE_NAME = FileNames.GUI_EXE
README_NAME = FileNames.README
GUI_README_NAME = FileNames.GUI_README
README_PDF_NAME = FileNames.README_PDF
GUI_README_PDF_NAME = FileNames.GUI_README_PDF
PRODUCT_NAME = Branding.PRODUCT_NAME  # SSOT: Never hardcode product name

# Import render_vc_guide from SSOT (veracrypt_cli.py)
from veracrypt_cli import render_vc_guide

# =============================================================================
# Path assertion (uses core.paths)
# =============================================================================


def assert_deployed_scripts_exist(launcher_path: Path) -> None:
    """Assert all required scripts exist. Raises RuntimeError if any missing."""
    Paths.assert_required_scripts_exist(launcher_path)


# Setup state tracking for honest completion status (P1-1)
class SetupState:
    """Track critical failures and warnings during setup."""

    critical_failures: list = []
    warnings: list = []
    cli_verified: bool = False
    verification_overridden: bool = False
    integrity_signed: bool = False
    recovery_requested: bool = False
    recovery_generated: bool = False

    # P0: Target disk identity persistence (prevents identity loss mid-setup)
    target_disk_unique_id: str = ""
    target_disk_number: int = None
    target_disk_name: str = ""

    @classmethod
    def reset(cls):
        cls.critical_failures = []
        cls.warnings = []
        cls.cli_verified = False
        cls.verification_overridden = False
        cls.integrity_signed = False
        cls.recovery_requested = False
        cls.recovery_generated = False
        cls.target_disk_unique_id = ""
        cls.target_disk_number = None
        cls.target_disk_name = ""

    @classmethod
    def set_target_disk(cls, unique_id: str, disk_number: int, name: str):
        """
        Persist target disk identity for use throughout setup.

        Called immediately after disk selection. All subsequent operations
        should reference these values instead of the ephemeral selected_drive dict.
        """
        cls.target_disk_unique_id = unique_id or ""
        cls.target_disk_number = disk_number
        cls.target_disk_name = name or ""
        log(f"Target disk identity set: #{disk_number} '{name}' UniqueId={unique_id[:20] if unique_id else 'N/A'}...")

    @classmethod
    def get_target_disk_number(cls) -> int:
        """Get the persisted target disk number."""
        return cls.target_disk_number

    @classmethod
    def add_critical(cls, msg: str):
        cls.critical_failures.append(msg)

    @classmethod
    def add_warning(cls, msg: str):
        cls.warnings.append(msg)

    @classmethod
    def has_critical_failures(cls) -> bool:
        return len(cls.critical_failures) > 0


# =============================================================================
# TODO 0: Setup Flow Trace (Breadcrumb Logger)
# =============================================================================


def setup_flow_trace(checkpoint: str, context: dict | None = None) -> None:
    """
    Log a sanitized breadcrumb for control flow debugging.

    TODO 0 Guardrail: Proves where control flow goes and why it exits/hangs.

    Args:
        checkpoint: Human-readable checkpoint name (e.g., "MANUAL_LOOP_ENTER")
        context: Optional dict of sanitized context (no secrets!)
    """
    timestamp = time.strftime("%H:%M:%S")
    safe_context = ""
    if context:
        # Sanitize context - never log passwords or secrets
        safe_items = []
        for k, v in context.items():
            if k.lower() in ("password", "secret", "seed", "key"):
                safe_items.append(f"{k}=<REDACTED>")
            elif isinstance(v, str) and len(v) > 50:
                safe_items.append(f"{k}={v[:20]}...{v[-10:]}")
            else:
                safe_items.append(f"{k}={v}")
        safe_context = f" | {', '.join(safe_items)}"

    log(f"[FLOW_TRACE] {timestamp} {checkpoint}{safe_context}")


# =============================================================================
# CHG-20251218-002: Setup Pagination System - State Machine Implementation
# =============================================================================


class SetupPhase:
    """Enumeration of setup phases for state machine."""

    PREFLIGHT = 0
    DRIVE_SELECTION = 1
    PARTITION_SIZE = 2
    SECURITY_CONFIG = 3
    REVIEW_CONFIRM = 4
    EXECUTION = 5
    SUMMARY = 6
    COMPLETE = 7
    CANCELLED = -1
    ERROR = -2


class PagedSetupState:
    """
    Holds all state for the paged setup flow.

    CHG-20251218-002: Enables [B]ack navigation by preserving state per phase.
    CHG-20251219-001: Includes log preservation for later review.
    """

    def __init__(self):
        # Phase tracking
        self.current_phase = SetupPhase.PREFLIGHT
        self.phase_completed = set()

        # CHG-20251219-001: Log preservation - categorized by phase
        self.logs: dict[str, list[str]] = {
            "preflight": [],
            "drive_selection": [],
            "partition_size": [],
            "security_config": [],
            "yubikey_verification": [],
            "review_confirm": [],
            "partitioning": [],
            "veracrypt_creation": [],
            "deployment": [],
            "summary": [],
        }
        self.current_log_phase = "preflight"

        # System info (set during preflight)
        self.system = None
        self.vc_exe = None
        self.project_root = None
        self.scripts_dir = None

        # Phase 1: Drive Selection results
        self.drives = None
        self.selected_drive = None
        self.drive_id = None
        self.drive_name = None
        self.drive_size = None
        self.disk_number = None
        self.launcher_label = None

        # Phase 2: Partition Size results
        self.launcher_size = CryptoParams.LAUNCHER_PARTITION_SIZE_MB

        # Phase 3: Security Config results
        self.fingerprints = []
        self.security_mode = None
        self.mount_letter = "V"
        self.user_preferred_mount_letter = "V"

        # Phase 4: YubiKey Verification
        self.yubikeys_verified = False
        self.verification_overridden = False  # BUG-013: Track if user skipped verification

        # Phase 5: Review (no persistent state, just confirmation)
        self.confirmed = False
        self.partition_done = False  # Set True after ERASE triggers partitioning

        # Phase 6+: Execution results
        self.launcher_mount = None
        self.payload_device = None
        self.password = None
        self.use_keyfile = False
        self.use_gpg = False
        self.tmp_keyfile = None
        self.tmp_encrypted = None
        self.salt = None
        self.session_seed_gpg_path = None
        self.session_salt_b64 = None
        self.session_hkdf_info = None
        self.deployment_done = False

        # Phase 8: Post-setup actions (recovery tracking + in-memory keyfile bytes)
        self.recovery_generated = False
        self.keyfile_bytes = None  # bytes or None; required for recovery kit without re-auth

    def clear_from_phase(self, phase: int):
        """Clear all state from a phase onwards (for re-running)."""
        phases_to_clear = [p for p in self.phase_completed if p >= phase]
        for p in phases_to_clear:
            self.phase_completed.discard(p)

        # Clear phase-specific data
        if phase <= SetupPhase.DRIVE_SELECTION:
            self.selected_drive = None
            self.drive_id = None
            self.drive_name = None
            self.drive_size = None
            self.disk_number = None
            self.launcher_label = None
        if phase <= SetupPhase.PARTITION_SIZE:
            self.launcher_size = CryptoParams.LAUNCHER_PARTITION_SIZE_MB
        if phase <= SetupPhase.SECURITY_CONFIG:
            self.fingerprints = []
            self.security_mode = None
            self.mount_letter = Defaults.WINDOWS_MOUNT_LETTER
        if phase <= SetupPhase.REVIEW_CONFIRM:
            self.confirmed = False
            self.partition_done = False
        if phase <= SetupPhase.EXECUTION:
            self.launcher_mount = None
            self.payload_device = None


def clear_terminal() -> None:
    """
    Clear the terminal screen.

    CHG-20251218-002: Used for page navigation to provide clean screens.
    BUG-20251219-002: Preserve scrollback on Windows to maintain consistency.

    Uses platform-appropriate method:
    - Windows: ANSI escape codes (preserves scrollback better than cls)
    - Unix: clear command or ANSI escape codes

    SECURITY NOTE: This is called between sensitive screens to prevent
    shoulder-surfing, but should not disrupt the terminal session.

    BUG-20251221-022 FIX: Replaced os.system() calls with subprocess.run()
    to prevent "syntax error in command line" popups on Windows.
    """
    if platform.system().lower() == "windows":
        # BUG-20251219-002 FIX: Use ANSI escape codes instead of cls
        # cls creates a new buffer which can resize/lose scrollback in some terminals
        # ANSI codes work better in modern terminals (Windows Terminal, PowerShell 7)
        try:
            # Check if ANSI is supported (Windows 10+)
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # Enable virtual terminal processing
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            if mode.value & 0x0004:
                # ANSI supported - use escape codes
                print("\033[2J\033[H", end="", flush=True)
                return
        except Exception:
            pass
        # BUG-20251221-022/024: Use subprocess with CREATE_NO_WINDOW to prevent popups
        subprocess.run(
            ["cmd", "/c", "cls"],
            shell=False,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        # BUG-20251221-022: Use subprocess instead of os.system() to prevent issues
        result = subprocess.run(["clear"], shell=False, check=False)
        if result.returncode != 0:
            # ANSI escape code fallback
            print("\033[2J\033[H", end="")


def detect_recovery_generated(launcher_root: Path) -> bool:
    """Detect whether a recovery kit exists on the deployed drive.

    SSOT: Uses core.paths.Paths.recovery_dir() for location.
    File names from FileNames class (SSOT).

    Consider 'generated' if:
    - {PRODUCT_NAME}_Recovery_Kit.html exists, OR
    - both recovery_container.bin and header_backup.hdr exist.
    """
    try:
        recovery_dir = Paths.recovery_dir(launcher_root)
        html = recovery_dir / f"{Branding.PRODUCT_NAME}{FileNames.RECOVERY_KIT_HTML_SUFFIX}"
        container = recovery_dir / FileNames.RECOVERY_CONTAINER_BIN
        header = recovery_dir / FileNames.RECOVERY_HEADER_HDR
        return html.exists() or (container.exists() and header.exists())
    except Exception:
        return False


def open_folder_cli(path: Path) -> bool:
    """Open a directory in the system file manager (CLI-safe; no Qt imports).

    BUG-20251221-022 FIX: Use subprocess with CREATE_NO_WINDOW on Windows
    instead of os.startfile() to prevent "syntax error in command line" popups.

    Returns True on success, False on failure.
    """
    try:
        if not isinstance(path, Path):
            path = Path(path)
        if not path.exists():
            print(f"  [!] Path does not exist: {path}")
            return False

        plat = get_platform()
        if plat == "windows":
            # BUG-20251221-022: Use explorer.exe via subprocess instead of os.startfile()
            # os.startfile() can trigger "syntax error in command line" popups
            subprocess.run(
                ["explorer", str(path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
        elif plat == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
        return True
    except Exception as e:
        print(f"  [!] Could not open folder: {e}")
        return False


def render_page_header(phase_num: int, total_phases: int, title: str, phase_name: str):
    """
    Render a page header with phase info and [X/Y] indicator.

    CHG-20251218-002: Header format requirement.
    """
    clear_terminal()
    print("=" * 70)
    print(f"  {Branding.PRODUCT_NAME.upper()} SETUP")
    print(f"  Phase: {phase_name}")
    print(f"  [{phase_num}/{total_phases}] {title}")
    print("=" * 70)
    print()


def prompt_navigation(
    phase_num: int, total_phases: int, can_go_back: bool = True, can_rerun: bool = False, auto_next: bool = False
) -> str:
    f"""
    Display navigation options and get user choice.

    CHG-20251218-002: [B]ack/[N]ext navigation.

    Returns: '{UserInputs.BACK}' (back), '{UserInputs.NEXT}' (next), '{UserInputs.RETRY}' (rerun), '{UserInputs.QUIT}' (quit)
    """
    if auto_next:
        return UserInputs.NEXT

    print()
    print("  " + "-" * 66)

    options = []
    valid = [UserInputs.NEXT, UserInputs.QUIT]

    if can_go_back and phase_num > 1:
        options.append(f"[{UserInputs.BACK}] Back")
        valid.append(UserInputs.BACK)
    options.append(f"[{UserInputs.NEXT}] Next")
    if can_rerun:
        options.append(f"[{UserInputs.RETRY}] Rerun")
        valid.append(UserInputs.RETRY)
    options.append(f"[{UserInputs.QUIT}] Quit")

    print(f"  Navigation: {' | '.join(options)}")

    while True:
        choice = input("  Your choice: ").strip().upper()
        if choice in valid:
            return choice
        if choice == UserInputs.BACK and UserInputs.BACK not in valid:
            print("  Cannot go back from this page.")
        else:
            print(f"  Invalid. Choose: {', '.join(valid)}")


class SetupPage:
    """Represents a single setup page with header, content, and navigation."""

    def __init__(
        self,
        page_id: str,
        title: str,
        phase: str,
        page_number: int,
        total_pages: int,
        content_renderer: callable = None,
        can_go_back: bool = True,
        can_rerun: bool = False,
    ):
        self.page_id = page_id
        self.title = title
        self.phase = phase
        self.page_number = page_number
        self.total_pages = total_pages
        self.content_renderer = content_renderer
        self.can_go_back = can_go_back
        self.can_rerun = can_rerun
        self.result = None  # Store result of page execution

    def render_header(self) -> None:
        """Render the page header with title, phase, and page number."""
        clear_terminal()
        print("=" * 70)
        print(f"  {Branding.PRODUCT_NAME.upper()} SETUP")
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
        if self.can_rerun:
            options.append("[R]erun this step")
        options.append("[Q]uit")
        return " | ".join(options)


class SetupPagination:
    """
    Manages page-based navigation for setup flow.

    CHG-20251218-002: Implements discrete pages with header, [B]ack/[N]ext navigation.
    """

    PHASES = {
        "START": "Drive Selection & Partitioning",
        "SECURITY": "Security Configuration",
        "VERACRYPT": "VeraCrypt Volume Setup",
        "VERIFICATION": "Setup Verification",
        "DEPLOYMENT": "Script Deployment",
        "SUMMARY": "Setup Complete",
    }

    def __init__(self):
        self.pages: list[SetupPage] = []
        self.current_page_index = 0
        self.page_results = {}  # Store results by page_id

    def add_page(
        self,
        page_id: str,
        title: str,
        phase: str,
        content_renderer: callable = None,
        can_go_back: bool = True,
        can_rerun: bool = False,
    ) -> SetupPage:
        """Add a page to the setup flow."""
        page = SetupPage(
            page_id=page_id,
            title=title,
            phase=phase,
            page_number=len(self.pages) + 1,
            total_pages=0,  # Will be updated after all pages added
            content_renderer=content_renderer,
            can_go_back=can_go_back,
            can_rerun=can_rerun,
        )
        self.pages.append(page)
        return page

    def finalize_pages(self) -> None:
        """Update total_pages after all pages have been added."""
        total = len(self.pages)
        for page in self.pages:
            page.total_pages = total

    def get_current_page(self) -> SetupPage:
        """Get the current page."""
        return self.pages[self.current_page_index]

    def navigate_back(self) -> bool:
        """Go to the previous page. Returns False if at first page."""
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
        """Store a result for a page (for use by later pages)."""
        self.page_results[page_id] = result

    def get_result(self, page_id: str, default=None) -> any:
        """Get a stored result from a previous page."""
        return self.page_results.get(page_id, default)

    def render_navigation_prompt(self) -> str:
        """Show navigation options and get user choice."""
        page = self.get_current_page()
        print()
        print("  " + "-" * 66)
        print(f"  Navigation: {page.get_navigation_options()}")

        valid_choices = ["N", "Q"]
        if page.can_go_back and self.current_page_index > 0:
            valid_choices.append("B")
        if page.can_rerun:
            valid_choices.append("R")

        while True:
            choice = input("  Choice: ").strip().upper()
            if choice in valid_choices:
                return choice
            print(f"  Invalid. Choose from: {', '.join(valid_choices)}")


def show_setup_success_screen(
    launcher_mount: Path,
    target_drive: str,
    use_gpg: bool,
    use_keyfile: bool,
    fingerprints: list,
    recovery_generated: bool,
) -> str:
    """
    Display comprehensive setup success screen with next actions menu.

    CHG-20251218-003: Clean, cohesive final screen with clear action explanations.
    CHG-20251221-022: Added [S] Sign option for explicit script signing choice.

    Returns: User's menu choice ('M', 'G', 'P', 'R', 'S', 'Q')
    """
    # Determine security mode
    if use_gpg:
        security_mode = f"YubiKey 2FA ({len(fingerprints)} key{'s' if len(fingerprints) > 1 else ''})"
        hardware_keys = f"[OK] YubiKey fingerprints: {', '.join(fp[:8] + '...' for fp in fingerprints)}"
    elif use_keyfile:
        security_mode = "Password + Keyfile"
        hardware_keys = "[X] No hardware keys configured"
    else:
        security_mode = "Password only"
        hardware_keys = "[X] No hardware keys configured"

    # Recovery kit status
    recovery_status = "[OK] Generated" if recovery_generated else "[X] Not generated"

    # Signing availability
    signing_available = fingerprints and len(fingerprints) > 0

    # Clear screen for final summary
    clear_terminal()

    print("=" * 70)
    print("  +===============================================================+")
    print("  |               SETUP COMPLETE                                  |")
    print("  +===============================================================+")
    print("=" * 70)
    print()

    # Configuration summary
    print("  CONFIGURATION SUMMARY")
    print("  " + "-" * 66)
    print(f"  Target Drive:        {target_drive}")
    print(f"  {Branding.PRODUCT_NAME} Partition: {launcher_mount}")
    print(f"  Security Mode:       {security_mode}")
    print(f"  Hardware Keys:       {hardware_keys}")
    print(f"  Recovery Kit:        {recovery_status}")
    print("  " + "-" * 66)
    print()

    # Security warnings if applicable
    if not use_gpg and not use_keyfile:
        print("  [!] WARNING: Password-only mode is less secure.")
        print("      Consider upgrading to YubiKey for hardware-based 2FA.")
        print()
    elif use_keyfile and not use_gpg:
        print("  [!] WARNING: Keyfile is stored without hardware protection.")
        print("      Consider upgrading to YubiKey for stronger security.")
        print()

    if not recovery_generated:
        print("  [!] CRITICAL: No recovery kit generated yet.")
        print("      Without it, losing your password means PERMANENT data loss!")
        print()

    # Actions menu - single cohesive block
    print("  " + "=" * 66)
    print("  CHOOSE YOUR NEXT ACTION")
    print("  " + "=" * 66)
    print()

    # [M] Mount
    print("    [M] MOUNT NOW")
    print(f"        Target: {launcher_mount}")
    print("        Attempts to mount the encrypted VeraCrypt volume.")
    print("        Use this to verify your setup works correctly.")
    print()

    # [G] Open GUI
    print("    [G] OPEN VERACRYPT GUI")
    print("        Opens the VeraCrypt graphical interface.")
    print("        For manual operations or troubleshooting.")
    print()

    # [P] Recovery kit
    if recovery_generated:
        print("    [P] OPEN RECOVERY KIT LOCATION")
        print("        Opens the folder containing your recovery files.")
        print("        Store these securely - they are your safety net.")
    else:
        print("    [P] GENERATE RECOVERY KIT (RECOMMENDED)")
        print(f"        Target: {launcher_mount}")
        print("        Creates a 24-word recovery phrase and header backup.")
        print("        STRONGLY RECOMMENDED - your only recovery option.")
    print()

    # [R] Rekey
    print("    [R] REKEY (CHANGE CREDENTIALS)")
    print("        Launches the credential change flow (password / keyfile rotation).")
    print("        Use this if you want to rotate secrets after initial setup.")
    print()

    # [S] Sign (CHG-20251221-022)
    if signing_available:
        print("    [S] SIGN DEPLOYED SCRIPTS")
        print("        Signs the deployed scripts with your GPG key for integrity verification.")
        print("        RECOMMENDED for tamper detection on future runs.")
    else:
        print("    [S] SIGN DEPLOYED SCRIPTS (UNAVAILABLE)")
        print("        Script signing requires GPG keys to be configured.")
        print("        You can sign scripts later from the main CLI menu.")
    print()

    # [T] Test (CHG-20251221-023)
    print("    [T] RUN VERIFICATION TESTS")
    print("        Runs the pytest test suite to verify deployment integrity.")
    print("        Informational only - failures do not affect deployment.")
    print()

    # [Q] Quit
    print("    [Q] QUIT")
    print("        Exit setup. You can mount later using:")
    if platform.system() == "Windows":
        print(f"        Double-click {FileNames.BAT_LAUNCHER} (from {launcher_mount})")
    else:
        print(f"        Run ./{FileNames.SH_LAUNCHER} (from {launcher_mount})")
    print()

    print("  " + "-" * 66)

    # Interactive menu - include S only if signing is available, T always available
    valid_choices = ["M", "G", "P", "R", "T", "Q"]
    if signing_available:
        valid_choices.insert(4, "S")  # Insert S before T

    while True:
        choice = input(f"  Your choice [{'/'.join(valid_choices)}]: ").strip().upper()
        if choice in valid_choices:
            return choice
        elif choice == "S" and not signing_available:
            print("  Script signing is not available (no GPG keys configured).")
        else:
            print(f"  Invalid choice. Please enter {', '.join(valid_choices[:-1])}, or {valid_choices[-1]}.")


def replace_markdown_variables(markdown_content: str) -> str:
    """
    Replace variable placeholders in markdown content with actual values from variables.py.
    Variables are in the format {VARIABLE_NAME}.
    This allows variables.py to be the single point of change for product customization.
    """
    try:
        # Import variables module
        import os
        import sys
        from pathlib import Path

        # Add project root to path to import variables.py
        project_root = Path(__file__).resolve().parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        import variables

        # Create a dictionary of all variables for replacement
        replacements = {}

        # Get all uppercase attributes from variables module
        for attr_name in dir(variables):
            if not attr_name.startswith("_") and attr_name.isupper():
                attr_value = getattr(variables, attr_name)
                if isinstance(attr_value, str):
                    replacements[attr_name] = attr_value

        # Replace variables in markdown content
        result = markdown_content
        for var_name, var_value in replacements.items():
            placeholder = f"{{{var_name}}}"
            result = result.replace(placeholder, var_value)

        return result

    except ImportError as e:
        log(f"Warning: Could not import variables.py for variable replacement: {e}")
        return markdown_content
    except Exception as e:
        log(f"Warning: Failed to replace variables: {e}")
        return markdown_content


def generate_pdf_from_markdown(markdown_path: Path, output_path: Path) -> bool:
    """
    Generate PDF from Markdown file using markdown + reportlab.
    Replaces variables in the markdown content before conversion.
    Returns True if successful, False otherwise.
    """
    try:
        # Import PDF libraries
        import markdown
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        # Read markdown content
        with open(markdown_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        # Replace variables in markdown content
        md_content = replace_markdown_variables(md_content)

        # Convert markdown to HTML
        html_content = markdown.markdown(md_content, extensions=["tables", "fenced_code"])

        # Create PDF document
        doc = SimpleDocTemplate(str(output_path), pagesize=letter)
        styles = getSampleStyleSheet()

        # Create custom styles
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Heading1"],
            fontSize=18,
            spaceAfter=30,
            textColor=colors.darkblue,
        )

        heading_style = ParagraphStyle(
            "CustomHeading",
            parent=styles["Heading2"],
            fontSize=14,
            spaceAfter=20,
            textColor=colors.darkgreen,
        )

        code_style = ParagraphStyle(
            "CustomCode",
            parent=styles["Normal"],
            fontName="Courier",
            fontSize=10,
            backColor=colors.lightgrey,
            borderPadding=5,
            leftIndent=20,
        )

        # Simple HTML to Platypus conversion (basic implementation)
        story = []
        lines = html_content.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Basic HTML tag parsing
            if line.startswith("<h1>") and line.endswith("</h1>"):
                text = line[4:-5]
                story.append(Paragraph(text, title_style))
                story.append(Spacer(1, 12))
            elif line.startswith("<h2>") and line.endswith("</h2>"):
                text = line[4:-5]
                story.append(Paragraph(text, heading_style))
                story.append(Spacer(1, 8))
            elif line.startswith("<h3>") and line.endswith("</h3>"):
                text = line[4:-5]
                story.append(Paragraph(text, styles["Heading3"]))
                story.append(Spacer(1, 6))
            elif line.startswith("<p>") and line.endswith("</p>"):
                text = line[3:-4]
                story.append(Paragraph(text, styles["Normal"]))
                story.append(Spacer(1, 6))
            elif line.startswith("<code>") and line.endswith("</code>"):
                text = line[6:-7]
                story.append(Paragraph(text, code_style))
                story.append(Spacer(1, 4))
            elif line.startswith("<pre><code>") and line.endswith("</code></pre>"):
                text = line[11:-12]
                story.append(Paragraph(text, code_style))
                story.append(Spacer(1, 8))
            elif line.startswith("<ul>") or line.startswith("<ol>"):
                # Skip list tags for now
                continue
            elif line.startswith("<li>") and line.endswith("</li>"):
                text = "- " + line[4:-5]
                story.append(Paragraph(text, styles["Normal"]))
                story.append(Spacer(1, 3))
            elif "</ul>" in line or "</ol>" in line:
                story.append(Spacer(1, 6))
            else:
                # Plain text or unhandled tags
                if line and not line.startswith("<"):
                    story.append(Paragraph(line, styles["Normal"]))
                    story.append(Spacer(1, 4))

        # Build PDF
        doc.build(story)
        return True

    except ImportError as e:
        log(f"Warning: PDF generation libraries not available: {e}")
        log("Install with: pip install markdown reportlab")
        return False
    except Exception as e:
        log(f"Warning: Failed to generate PDF: {e}")
        return False


def get_ram_temp_dir():
    """Get a RAM-backed temp directory if available, else system temp.

    SSOT: Uses Paths class constants for platform-specific paths.
    """
    if platform.system() == "Linux":
        ram_dir = Path(Paths.LINUX_RAM_TEMP)
        if ram_dir.exists() and os.access(ram_dir, os.W_OK):
            return ram_dir
    elif platform.system() == "Darwin":  # macOS
        ram_dir = Path(Paths.MACOS_RAM_TEMP)
        if ram_dir.exists() and os.access(ram_dir, os.W_OK):
            return ram_dir
    # Windows or fallback
    return Path(tempfile.gettempdir())


# =============================================================================
# GUI Guidance Renderer - IMPORTED from veracrypt_cli.py (SSOT)
# See: from veracrypt_cli import render_vc_guide (above)
# =============================================================================


# =============================================================================
# P0-3: YubiKey Detection with Hard Stop and Fingerprint Verification
# =============================================================================


class CardIdentity:
    """Identity information from an inserted smart card."""

    def __init__(
        self,
        serial: str | None = None,
        enc_fpr: str | None = None,
        sig_fpr: str | None = None,
        auth_fpr: str | None = None,
    ):
        self.serial = serial  # Card serial number (e.g., "34397658")
        self.enc_fpr = enc_fpr  # Encryption subkey fingerprint (40 hex)
        self.sig_fpr = sig_fpr  # Signature subkey fingerprint (40 hex)
        self.auth_fpr = auth_fpr  # Authentication subkey fingerprint (40 hex)

    def __repr__(self):
        return f"CardIdentity(serial={self.serial}, enc_fpr={self.enc_fpr[:16] if self.enc_fpr else None}...)"

    def matches(self, expected_fpr: str, expected_serial: str | None = None) -> bool:
        """
        Check if this card matches expected identity.

        P0-3 Protocol:
        1. If expected_serial is provided, compare serial first (most reliable)
        2. Then compare enc_fpr (encryption subkey fingerprint)
        3. Also check if expected_fpr is a primary key that owns this card's subkey

        Args:
            expected_fpr: Expected fingerprint (could be primary or subkey)
            expected_serial: Expected card serial (if known)

        Returns:
            True if identity matches
        """
        expected_normalized = expected_fpr.replace(" ", "").upper() if expected_fpr else ""

        log(f"[DEBUG] CardIdentity.matches() expected_fpr={expected_normalized[:16]}..., serial={expected_serial}")
        log(f"[DEBUG]   card: serial={self.serial}, enc_fpr={self.enc_fpr[:16] if self.enc_fpr else 'None'}...")

        # Serial match is authoritative
        if expected_serial and self.serial:
            if self.serial == expected_serial:
                log("[DEBUG]   MATCH: Serial match")
                return True

        # Direct fingerprint match (encryption subkey)
        if self.enc_fpr and expected_normalized:
            if self.enc_fpr == expected_normalized:
                log("[DEBUG]   MATCH: Direct enc_fpr match")
                return True
            # Prefix match for abbreviated fingerprints
            if self.enc_fpr.startswith(expected_normalized) or expected_normalized.startswith(self.enc_fpr):
                log("[DEBUG]   MATCH: Prefix enc_fpr match")
                return True

        # Check if expected_fpr is a primary key fingerprint
        # In this case, we need to verify if the card's subkeys belong to that primary
        # This is more complex - for now, also check sig_fpr as it might be the primary key slot
        if self.sig_fpr and expected_normalized:
            if self.sig_fpr == expected_normalized or self.sig_fpr.startswith(expected_normalized):
                log("[DEBUG]   MATCH: sig_fpr match")
                return True

        # P0-3: Try to resolve primary key -> subkey relationship
        # If expected_fpr is a primary key, check if our enc_fpr is its subkey
        if expected_normalized and self.enc_fpr:
            try:
                primary_of_subkey = _get_primary_key_for_subkey(self.enc_fpr)
                if primary_of_subkey and primary_of_subkey.upper() == expected_normalized:
                    log(f"[DEBUG]   MATCH: enc_fpr belongs to primary {expected_normalized[:16]}...")
                    return True
            except Exception as e:
                log(f"[DEBUG]   Primary key lookup failed: {e}")

        log("[DEBUG]   NO MATCH")
        return False


def _get_primary_key_for_subkey(subkey_fpr: str) -> str | None:
    """
    Resolve which primary key owns a given subkey.

    Uses: gpg --with-colons --list-keys <subkey_fpr>

    Returns:
        Primary key fingerprint (40 hex) or None if not found
    """
    try:
        # GPG can look up by subkey fingerprint
        result = subprocess.run(
            ["gpg", "--with-colons", "--list-keys", subkey_fpr], capture_output=True, text=True, timeout=5
        )

        if result.returncode != 0:
            return None

        # Parse output - first fpr: line is the primary key
        for line in result.stdout.splitlines():
            if line.startswith("fpr:"):
                parts = line.split(":")
                if len(parts) > 9:
                    return parts[9].upper()

        return None
    except Exception:
        return None


def get_inserted_card_identity() -> CardIdentity | None:
    """
    Get complete identity information from the currently inserted smart card.

    Uses gpg --with-colons --card-status for deterministic parsing.

    P0-3: Returns CardIdentity with:
    - serial: Card serial number
    - enc_fpr: Encryption subkey fingerprint (40 hex)
    - sig_fpr: Signature subkey fingerprint (40 hex)
    - auth_fpr: Authentication subkey fingerprint (40 hex)

    Returns None if no card is inserted or parsing fails.

    BUG-20251218-007 FIX: Add --no-tty to prevent terminal hang on repeated calls.
    """
    try:
        result = subprocess.run(
            ["gpg", "--no-tty", "--with-colons", "--card-status"],
            capture_output=True,
            text=True,
            timeout=Limits.GPG_CARD_STATUS_TIMEOUT,
        )

        if result.returncode != 0:
            return None

        serial = None
        fingerprints = []  # Will collect [sig_fpr, enc_fpr, auth_fpr] in order

        for line in result.stdout.split("\n"):
            parts = line.split(":")
            if not parts:
                continue

            record_type = parts[0]

            # serial:34397658:
            if record_type == "serial" and len(parts) > 1:
                serial = parts[1].strip()

            # fpr:SIG_FPR:ENC_FPR:AUTH_FPR:
            # The fingerprints are colon-separated after "fpr:"
            elif record_type == "fpr" and len(parts) > 1:
                # Collect all non-empty fingerprint fields
                for i in range(1, min(4, len(parts))):
                    fpr = parts[i].strip().upper()
                    if fpr and len(fpr) >= 32:  # Valid fingerprint
                        fingerprints.append(fpr)

        # Assign fingerprints: order is sig, enc, auth
        sig_fpr = fingerprints[0] if len(fingerprints) > 0 else None
        enc_fpr = fingerprints[1] if len(fingerprints) > 1 else None
        auth_fpr = fingerprints[2] if len(fingerprints) > 2 else None

        if not serial and not enc_fpr:
            return None

        return CardIdentity(serial=serial, enc_fpr=enc_fpr, sig_fpr=sig_fpr, auth_fpr=auth_fpr)
    except Exception as e:
        log(f"[DEBUG] get_inserted_card_identity failed: {e}")
        return None


def get_inserted_card_fingerprint() -> str | None:
    """
    Get the encryption key fingerprint of the currently inserted YubiKey/smart card.

    LEGACY WRAPPER: For backward compatibility. Use get_inserted_card_identity() for
    full identity information.

    Returns the encryption fingerprint (no spaces, uppercase) or None if:
    - No card is inserted
    - Cannot read card status
    - No encryption key fingerprint found
    """
    identity = get_inserted_card_identity()
    return identity.enc_fpr if identity else None


def detect_yubikey() -> bool:
    """
    Detect if a YubiKey is present and accessible for GPG operations.
    Returns True if YubiKey is detected, False otherwise.

    BUG-20251218-007 FIX: Add --no-tty to prevent terminal hang on repeated calls.
    """
    try:
        # Try gpg --card-status which requires YubiKey presence
        # BUG-20251218-007: --no-tty prevents gpg from waiting on TTY input
        result = subprocess.run(
            ["gpg", "--no-tty", "--card-status"], capture_output=True, text=True, timeout=Limits.GPG_CARD_STATUS_TIMEOUT
        )
        return result.returncode == 0 and "serial number" in result.stdout.lower()
    except Exception:
        return False


def detect_yubikey_with_fingerprint(
    expected_fpr: str, expected_serial: str | None = None
) -> tuple[bool, CardIdentity | None]:
    """
    Detect if the CORRECT YubiKey is inserted (matching expected identity).

    P0-3 Protocol:
    1. Get full card identity (serial + fingerprints) using --with-colons
    2. Match by serial (if provided) - most reliable
    3. Match by encryption subkey fingerprint
    4. Also check if expected_fpr is a primary key that owns this card's subkeys

    Args:
        expected_fpr: The expected fingerprint (could be primary or enc subkey)
        expected_serial: Expected card serial (if known) - most reliable match

    Returns:
        (is_correct: bool, card_identity: CardIdentity | None)
        - (True, identity) if correct key is inserted
        - (False, identity) if wrong key is inserted
        - (False, None) if no key is inserted

    P0-3: Security requirement - must verify the EXACT key requested is present.
    """
    identity = get_inserted_card_identity()

    if identity is None:
        return (False, None)

    # Use CardIdentity.matches() for comprehensive comparison
    if identity.matches(expected_fpr, expected_serial):
        return (True, identity)

    return (False, identity)


def require_yubikey(operation: str, max_attempts: int = 3) -> bool:
    """
    Require YubiKey presence for an operation. Loops up to max_attempts.
    Returns True if YubiKey detected, False if user exhausted attempts.

    This is a HARD GATE for YubiKey-required modes.
    """
    for attempt in range(1, max_attempts + 1):
        if detect_yubikey():
            return True

        print(f"\n[!] YubiKey not detected. Attempt {attempt}/{max_attempts}.")
        print(f"    Insert YubiKey and press Enter to retry...")

        if attempt < max_attempts:
            input()
        else:
            print(f"\n[X] YubiKey required for {operation} but not detected after {max_attempts} attempts.")
            return False

    return False


def verify_yubikey_decryption(encrypted_file: Path, key_label: str = "YubiKey") -> bool:
    """
    Verify that the current YubiKey can decrypt an encrypted file.
    Returns True if decryption succeeds, False otherwise.

    This is used to verify EACH hardware key can access the encrypted seed/keyfile.
    """
    if not encrypted_file.exists():
        log(f"Cannot verify {key_label}: encrypted file not found")
        return False

    try:
        # BUG-20251219-001 FIX: Add --no-tty to prevent terminal hang
        result = subprocess.run(
            ["gpg", "--no-tty", "--decrypt", "--quiet", str(encrypted_file)],
            capture_output=True,
            timeout=Limits.GPG_DECRYPT_TIMEOUT,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log(f"Decryption verification timed out for {key_label}")
        return False
    except Exception as e:
        log(f"Decryption verification failed for {key_label}: {e}")
        return False


def verify_all_yubikeys(
    encrypted_file: Path, fingerprints: list, max_attempts_per_key: int = 3, verbose: bool = True
) -> tuple:
    """
    Verify EACH configured YubiKey can decrypt the encrypted file.
    Prompts user to insert each key in turn.

    Args:
        encrypted_file: Path to GPG-encrypted test file
        fingerprints: List of GPG key fingerprints to verify
        max_attempts_per_key: Number of attempts before failing a key
        verbose: If False, suppress header/intro text (for use within page functions)

    Returns (success: bool, verified_keys: list, failed_keys: list)

    SECURITY (P0-3):
    - Both keys MUST work for setup to succeed.
    - Uses gpg --with-colons for deterministic identity parsing.
    - Verifies by card serial (if known) or encryption subkey fingerprint.
    - Rejects wrong keys explicitly (prevents using any key instead of the requested one).
    """
    verified_keys = []
    failed_keys = []

    # BUG-20251219-002: Only print header if verbose=True (avoid duplicates when page already printed header)
    if verbose:
        print("\n" + "=" * 70)
        print("  HARDWARE KEY VERIFICATION")
        print("=" * 70)
        print(f"\n  You configured {len(fingerprints)} hardware key(s).")
        print("  Each key will be verified to ensure backup access works.")
        print("  P0-3: Identity verified via serial number and/or encryption fingerprint.\n")

    for idx, fpr in enumerate(fingerprints, 1):
        key_label = f"Key #{idx} ({fpr[:8]}...)"
        print(f"\n  [{idx}/{len(fingerprints)}] Verifying {key_label}")
        print("-" * 50)

        for attempt in range(1, max_attempts_per_key + 1):
            print(f"\n  Insert {key_label} and press Enter...")
            input()

            # P0-3: Check if CORRECT YubiKey is present using full identity
            is_correct, identity = detect_yubikey_with_fingerprint(fpr)

            if identity is None:
                print(f"  [!] No YubiKey detected. Attempt {attempt}/{max_attempts_per_key}")
                if attempt == max_attempts_per_key:
                    print(f"  [X] Could not detect {key_label}")
                    failed_keys.append(fpr)
                continue

            if not is_correct:
                # P0-3: Wrong key inserted - explicit rejection with identity info
                print(f"  [!] WRONG KEY inserted!")
                print(f"      Expected: {fpr[:16]}...")
                print(
                    f"      Inserted: serial={identity.serial or 'N/A'}, enc_fpr={identity.enc_fpr[:16] if identity.enc_fpr else 'N/A'}..."
                )
                print(f"      Attempt {attempt}/{max_attempts_per_key}")
                if attempt == max_attempts_per_key:
                    print(f"  [X] Could not verify {key_label} - wrong key inserted")
                    failed_keys.append(fpr)
                continue

            # Correct key detected - verify it can decrypt
            enc_display = identity.enc_fpr[:16] if identity.enc_fpr else "N/A"
            print(f"  [+] Correct key detected: serial={identity.serial or 'N/A'}, enc={enc_display}...")
            print(f"  Testing decryption with {key_label}...")
            print("  (You may be prompted for PIN)")

            if verify_yubikey_decryption(encrypted_file, key_label):
                print(f"  [OK] {key_label} verified successfully!")
                verified_keys.append(fpr)
                break
            else:
                print(f"  [!] Decryption failed. Attempt {attempt}/{max_attempts_per_key}")
                if attempt == max_attempts_per_key:
                    print(f"  [X] {key_label} could not decrypt the file")
                    failed_keys.append(fpr)

    print("\n" + "=" * 70)
    print("  VERIFICATION SUMMARY")
    print("=" * 70)
    print(f"\n  Verified: {len(verified_keys)}/{len(fingerprints)} keys")

    if failed_keys:
        print(f"  Failed:   {len(failed_keys)} keys")
        for fpr in failed_keys:
            print(f"    - {fpr[:16]}...")

    success = len(failed_keys) == 0
    return success, verified_keys, failed_keys


def list_signing_keys() -> list:
    """
    Enumerate available GPG keys that can sign.

    Returns list of dicts: [{fingerprint, uid, algo, capabilities}]
    Only includes keys with signing capability ('S' in capabilities).
    """
    signing_keys = []

    try:
        result = subprocess.run(
            ["gpg", "--list-secret-keys", "--with-colons"],
            capture_output=True,
            text=True,
            timeout=Limits.GPG_CARD_STATUS_TIMEOUT,
        )

        if result.returncode != 0:
            return []

        # Parse colon-delimited output
        # sec:u:4096:1:KEYID:...:u:::scESC:
        # fpr:::::::::FINGERPRINT:
        # uid:u::::...:User Name <email>:
        current_key = {}

        for line in result.stdout.split("\n"):
            parts = line.split(":")
            if not parts:
                continue

            record_type = parts[0]

            if record_type in ("sec", "ssb"):
                # Secret key or subkey
                if current_key and current_key.get("can_sign"):
                    signing_keys.append(current_key)

                capabilities = parts[11] if len(parts) > 11 else ""
                algo = parts[3] if len(parts) > 3 else ""
                key_size = parts[2] if len(parts) > 2 else ""

                # Check for signing capability
                can_sign = "s" in capabilities.lower() or "S" in capabilities

                current_key = {
                    "fingerprint": "",
                    "uid": "",
                    "algo": f"{algo}/{key_size}",
                    "capabilities": capabilities,
                    "can_sign": can_sign,
                }

            elif record_type == "fpr" and current_key:
                current_key["fingerprint"] = parts[9] if len(parts) > 9 else ""

            elif record_type == "uid" and current_key and not current_key.get("uid"):
                current_key["uid"] = parts[9] if len(parts) > 9 else ""

        # Don't forget the last key
        if current_key and current_key.get("can_sign"):
            signing_keys.append(current_key)

        # Deduplicate by fingerprint
        seen = set()
        unique_keys = []
        for key in signing_keys:
            fpr = key.get("fingerprint", "")
            if fpr and fpr not in seen:
                seen.add(fpr)
                unique_keys.append(key)

        return unique_keys

    except Exception as e:
        log(f"Error listing signing keys: {e}")
        return []


def select_signing_key(available_keys: list) -> str:
    """
    Let user select a signing key if multiple are available.

    Args:
        available_keys: List from list_signing_keys()

    Returns:
        Selected fingerprint, or empty string if user skipped/none available
    """
    if not available_keys:
        print("\n  [!] No signing keys found.")
        print("  You can skip signing or configure GPG keys later.")
        skip = input("  Skip signing? [Y/n]: ").strip().lower()
        return "" if skip != "n" else ""

    if len(available_keys) == 1:
        # Auto-select the only key
        key = available_keys[0]
        short_fpr = key["fingerprint"][-8:] if key["fingerprint"] else "unknown"
        uid = key.get("uid", "Unknown")[:40]
        print(f"\n  Using signing key: {short_fpr} ({uid})")
        return key["fingerprint"]

    # Multiple keys - let user choose
    print("\n  Multiple signing keys available:")
    print("  " + "-" * 60)

    for idx, key in enumerate(available_keys, 1):
        fpr = key.get("fingerprint", "")
        short_fpr = fpr[-8:] if fpr else "unknown"
        uid = key.get("uid", "Unknown")[:40]
        algo = key.get("algo", "")
        print(f"  [{idx}] {short_fpr}  {uid}")
        if algo:
            print(f"      Algorithm: {algo}")

    print(f"  [S] Skip signing")
    print()

    while True:
        choice = input(f"  Select key [1-{len(available_keys)}/S]: ").strip()

        if choice.upper() == "S":
            return ""

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(available_keys):
                selected = available_keys[idx]
                print(f"  [OK] Selected: {selected['fingerprint'][-8:]}")
                return selected["fingerprint"]
        except ValueError:
            pass

        print(f"  Invalid choice. Enter 1-{len(available_keys)} or S to skip.")


# =============================================================================
# P1-2: Clipboard Utilities (Password not printed to terminal)
# =============================================================================


def clipboard_available() -> bool:
    """Check if clipboard operations are available."""
    system = platform.system().lower()
    if "windows" in system:
        return True  # Windows always has clipboard via ctypes
    elif "darwin" in system:
        return shutil.which("pbcopy") is not None
    else:
        return shutil.which("xclip") is not None or shutil.which("xsel") is not None


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to system clipboard.
    Returns True on success, False on failure.
    """
    system = platform.system().lower()

    try:
        if "windows" in system:
            # Windows: use ctypes
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32

            # Open clipboard
            if not user32.OpenClipboard(None):
                return False

            try:
                user32.EmptyClipboard()

                # Encode text as UTF-16 (Windows clipboard format)
                text_bytes = text.encode("utf-16-le") + b"\x00\x00"

                # Allocate global memory
                h_mem = kernel32.GlobalAlloc(0x0042, len(text_bytes))  # GMEM_MOVEABLE | GMEM_ZEROINIT
                if not h_mem:
                    return False

                # Lock and copy
                p_mem = kernel32.GlobalLock(h_mem)
                if not p_mem:
                    kernel32.GlobalFree(h_mem)
                    return False

                ctypes.memmove(p_mem, text_bytes, len(text_bytes))
                kernel32.GlobalUnlock(h_mem)

                # Set clipboard data (CF_UNICODETEXT = 13)
                user32.SetClipboardData(13, h_mem)
                return True
            finally:
                user32.CloseClipboard()

        elif "darwin" in system:
            # macOS: use pbcopy
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(input=text.encode("utf-8"))
            return proc.returncode == 0

        else:
            # Linux: try xclip or xsel
            if shutil.which("xclip"):
                proc = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"))
                return proc.returncode == 0
            elif shutil.which("xsel"):
                proc = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"))
                return proc.returncode == 0
            return False

    except Exception as e:
        log(f"Clipboard error: {e}")
        return False


def clear_clipboard() -> bool:
    """Clear the system clipboard."""
    return copy_to_clipboard("")


def password_to_clipboard_with_timeout(password: str, timeout_seconds: int = 60, wait_for_enter: bool = True) -> bool:
    """
    Copy password to clipboard and clear after user presses Enter.

    Args:
        password: The password to copy
        timeout_seconds: Fallback timeout if user doesn't press Enter
        wait_for_enter: If True, prompt user to press Enter to clear clipboard

    Returns True if successfully copied.
    """
    if not clipboard_available():
        return False

    if not copy_to_clipboard(password):
        return False

    print(f"\n🔑 Password copied to clipboard.")
    print(f"   Paste it into VeraCrypt when prompted.")

    if wait_for_enter:
        print(f"   Press Enter when done to clear clipboard (auto-clears in {timeout_seconds}s).")
        # Use a simple blocking approach - user presses Enter when done
        import threading

        cleared = threading.Event()

        def auto_clear():
            if not cleared.wait(timeout_seconds):
                clear_clipboard()
                # Don't print - user may have moved on

        timer = threading.Thread(target=auto_clear, daemon=True)
        timer.start()

        try:
            input()  # Wait for Enter
            cleared.set()
            clear_clipboard()
            print("   [OK] Clipboard cleared.")
        except (EOFError, KeyboardInterrupt):
            cleared.set()
            clear_clipboard()
    else:
        print(f"   Clipboard will auto-clear in {timeout_seconds}s.\n")

    return True


def secure_delete(file_path, passes=3):
    """Securely delete a file by overwriting with random data."""
    if not file_path.exists():
        return
    try:
        file_size = file_path.stat().st_size
        with open(file_path, "wb") as f:
            for _ in range(passes):
                f.write(os.urandom(file_size))
                f.flush()
                os.fsync(f.fileno())
        os.unlink(file_path)
    except Exception as e:
        # Fallback to regular delete
        try:
            os.unlink(file_path)
        except:
            pass
        log(f"Warning: Could not securely delete {file_path}: {e}")


def derive_password_from_seed(seed: bytes, salt: bytes = None) -> str:
    """
    Derive a high-entropy password from a seed using PBKDF2.
    Returns a base64-encoded string suitable for VeraCrypt password.
    """
    import base64
    import hashlib

    if salt is None:
        # Use a fixed salt for deterministic derivation
        salt = SALT_PREFIX.encode("utf-8")

    # PBKDF2 with high iteration count
    iterations = 100000
    key_length = 32  # 256 bits

    derived = hashlib.pbkdf2_hmac("sha256", seed, salt, iterations, key_length)

    # Encode as base64 for printable password
    return base64.b64encode(derived).decode("ascii")


def generate_seed() -> bytes:
    """Generate a cryptographically secure random seed."""
    return secrets.token_bytes(32)  # 256-bit seed


# =============================================================================
# Constants
# =============================================================================

# Default KeyDrive partition size

# VERSION is imported from core.version above


# =============================================================================
# Utility Functions
# =============================================================================

# CHG-20251219-001: Global state reference for log preservation
_active_setup_state: "PagedSetupState | None" = None


def _redact_secrets(msg: str) -> str:
    """Redact potential secrets from log messages."""
    import re

    # Redact anything that looks like a password prompt result or key material
    msg = re.sub(r"(password|secret|seed|key|pin)\s*[:=]\s*\S+", r"\1=<REDACTED>", msg, flags=re.IGNORECASE)
    # Redact base64-looking strings over 20 chars (potential keys)
    msg = re.sub(r"[A-Za-z0-9+/=]{20,}", "<REDACTED_B64>", msg)
    return msg


def log(msg: str) -> None:
    """Log a message and optionally preserve it for later review."""
    print(f"[{PRODUCT_NAME}] {msg}")
    # CHG-20251219-001: Preserve log if state is active
    if _active_setup_state is not None:
        safe_msg = _redact_secrets(msg)
        phase = _active_setup_state.current_log_phase
        if phase in _active_setup_state.logs:
            _active_setup_state.logs[phase].append(f"[LOG] {safe_msg}")


def error(msg: str) -> None:
    """Log an error and optionally preserve it for later review."""
    print(f"[ERROR] {msg}", file=sys.stderr)
    # CHG-20251219-001: Preserve log if state is active
    if _active_setup_state is not None:
        safe_msg = _redact_secrets(msg)
        phase = _active_setup_state.current_log_phase
        if phase in _active_setup_state.logs:
            _active_setup_state.logs[phase].append(f"[ERROR] {safe_msg}")


def warn(msg: str) -> None:
    """Log a warning and optionally preserve it for later review."""
    print(f"[WARNING] {msg}")
    # CHG-20251219-001: Preserve log if state is active
    if _active_setup_state is not None:
        safe_msg = _redact_secrets(msg)
        phase = _active_setup_state.current_log_phase
        if phase in _active_setup_state.logs:
            _active_setup_state.logs[phase].append(f"[WARN] {safe_msg}")


def show_log_review(state: "PagedSetupState") -> None:
    """
    CHG-20251219-001: Display preserved logs for operator review.
    CHG-20251219-002: Navigation loop - return to menu after viewing, explicit [Q] to exit.

    Shows a menu to select a phase and view its logs.
    After viewing logs, returns to the log review menu (not setup summary).
    """
    phase_names = {
        "preflight": "Pre-flight Checks",
        "drive_selection": "Drive Selection",
        "partition_size": "Partition Size",
        "security_config": "Security Configuration",
        "yubikey_verification": "YubiKey Verification",
        "review_confirm": "Review & Confirm",
        "partitioning": "Partitioning",
        "veracrypt_creation": "VeraCrypt Creation",
        "deployment": "Deployment",
        "summary": "Summary",
    }

    # Navigation loop
    while True:
        clear_terminal()
        print("=" * 70)
        print(f"  {Branding.PRODUCT_NAME.upper()} SETUP - LOG REVIEW")
        print("=" * 70)
        print("\n  Select a phase to review its logs:\n")

        # Build phase list with log counts
        phases_with_logs = []
        for idx, (phase_id, phase_name) in enumerate(phase_names.items(), 1):
            log_count = len(state.logs.get(phase_id, []))
            if log_count > 0:
                phases_with_logs.append((phase_id, phase_name, log_count))
                print(f"  [{idx}] {phase_name} ({log_count} entries)")

        if not phases_with_logs:
            print("  (No logs recorded yet)")
            print("\n  Press Enter to return...")
            input()
            return

        print(f"\n  [A] Show ALL logs")
        print(f"  [Q] Return to setup summary")

        choice = input("\n  Your choice: ").strip().upper()

        if choice == "Q":
            return
        elif choice == "A":
            # Show all logs
            clear_terminal()
            print("=" * 70)
            print("  ALL SETUP LOGS")
            print("=" * 70)
            for phase_id, phase_name, _ in phases_with_logs:
                print(f"\n  --- {phase_name} ---")
                for entry in state.logs[phase_id]:
                    print(f"    {entry}")
            print("\n  Press Enter to return to log review menu...")
            input()
            # Loop continues - return to menu
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(phases_with_logs):
                phase_id, phase_name, _ = phases_with_logs[idx]
                clear_terminal()
                print("=" * 70)
                print(f"  LOGS: {phase_name.upper()}")
                print("=" * 70)
                for entry in state.logs[phase_id]:
                    print(f"  {entry}")
                print("\n  Press Enter to return to log review menu...")
                input()
                # Loop continues - return to menu
            else:
                print("  Invalid choice. Enter a number, A, or Q.")
        else:
            print("  Invalid choice. Enter a number, A, or Q.")


def have(cmd: str) -> bool:
    """Check if a command is available in PATH."""
    return shutil.which(cmd) is not None


def is_admin() -> bool:
    """Check if running with administrator privileges."""
    system = platform.system().lower()
    if "windows" in system:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False
    else:
        return os.geteuid() == 0


def run_cmd(args, *, check=True, capture_output=True, text=True, input_text=None, timeout=None):
    """Run a subprocess command."""
    try:
        result = subprocess.run(
            args,
            check=check,
            capture_output=capture_output,
            text=text,
            input=input_text,
            timeout=timeout,
            encoding="cp1252" if text else None,
            errors="replace" if text else None,
        )
        return result
    except subprocess.CalledProcessError as e:
        error_details = []
        if e.stdout:
            error_details.append(f"stdout: {e.stdout}")
        if e.stderr:
            error_details.append(f"stderr: {e.stderr}")
        error_msg = "\n".join(error_details) if error_details else f"exit code {e.returncode}"
        raise RuntimeError(f"Command failed: {' '.join(str(a) for a in args)}\n{error_msg}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out: {' '.join(str(a) for a in args)}")


def confirm_destructive(prompt: str, confirm_word: str = None) -> bool:
    """
    Require user to type exact confirmation word for destructive operations.
    Returns True only if exact match. Loops until ERASE or CANCEL.
    """
    if confirm_word is None:
        confirm_word = UserInputs.ERASE

    print(f"\n{'='*60}")
    print(f"[!] {prompt}")
    print(f"{'='*60}")

    while True:
        print(f"\n  Type '{confirm_word}' to proceed with data destruction.")
        print(f"  Type 'CANCEL' to abort safely (no changes will be made).")
        print()
        response = input("> ").strip()

        if response == confirm_word:
            return True
        elif response == "CANCEL":
            print("\n[OK] Cancelled. No changes were made to any drive.")
            return False
        else:
            print(f"\n[X] Invalid input. You entered: '{response}'")
            print(f"   Expected exactly '{confirm_word}' or 'CANCEL'.")


# =============================================================================
# Drive Detection
# =============================================================================


def get_drives_windows() -> list[dict]:
    """Get list of drives on Windows with detailed info including UniqueId."""
    drives = []
    try:
        # Get disk info via PowerShell (include ALL disks, even system)
        # Include UniqueId for persistent identification (P0 safety)
        ps_script = """
        Get-Disk | ForEach-Object {
            $disk = $_
            $partitions = Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue | ForEach-Object {
                @{
                    Number = $_.PartitionNumber
                    Size = [math]::Round($_.Size / 1GB, 2)
                    DriveLetter = $_.DriveLetter
                    Type = $_.Type
                }
            }
            @{
                Number = $disk.Number
                Name = $disk.FriendlyName
                Bus = $disk.BusType.ToString()
                SizeGB = [math]::Round($disk.Size / 1GB, 2)
                PartitionStyle = $disk.PartitionStyle.ToString()
                IsSystem = $disk.IsSystem
                IsBoot = $disk.IsBoot
                UniqueId = $disk.UniqueId
                SerialNumber = $disk.SerialNumber
                Partitions = @($partitions)
            }
        } | ConvertTo-Json -Depth 3
        """
        result = run_cmd(["powershell", "-NoProfile", "-Command", ps_script], check=True)

        data = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(data, dict):
            data = [data]

        for disk in data:
            drives.append(
                {
                    "number": disk["Number"],
                    "name": disk["Name"],
                    "bus": disk["Bus"],
                    "size_gb": disk["SizeGB"],
                    "partition_style": disk["PartitionStyle"],
                    "is_system": disk.get("IsSystem", False),
                    "is_boot": disk.get("IsBoot", False),
                    "unique_id": disk.get("UniqueId", ""),  # Persistent identifier
                    "serial_number": disk.get("SerialNumber", ""),
                    "partitions": disk.get("Partitions") or [],
                }
            )
    except Exception as e:
        error(f"Failed to list drives: {e}")

    return drives


def get_drives_unix() -> list[dict]:
    """Get list of drives on Linux/macOS with detailed info."""
    drives = []
    system = platform.system().lower()

    try:
        if "darwin" in system:
            # macOS
            result = run_cmd(["diskutil", "list", "-plist"], check=True)
            import plistlib

            data = plistlib.loads(result.stdout.encode())
            # Parse macOS disk info...
            for disk_id in data.get("AllDisksAndPartitions", []):
                if disk_id.get("Content") == "GUID_partition_scheme":
                    drives.append(
                        {
                            "name": disk_id.get("DeviceIdentifier", "?"),
                            "size_gb": disk_id.get("Size", 0) / (1024**3),
                            "bus": "unknown",
                            "is_system": disk_id.get("DeviceIdentifier") == "disk0",
                        }
                    )
        else:
            # Linux
            result = run_cmd(["lsblk", "-d", "-o", "NAME,SIZE,TYPE,TRAN,MODEL", "-J"], check=True)
            data = json.loads(result.stdout)

            for device in data.get("blockdevices", []):
                if device.get("type") == "disk":
                    name = f"{Paths.LINUX_DEV_PREFIX}{device['name']}"
                    is_system = device["name"] in ["sda", "nvme0n1", "vda"]
                    drives.append(
                        {
                            "name": name,
                            "model": device.get("model", "Unknown"),
                            "size": device.get("size", "?"),
                            "bus": device.get("tran", "?"),
                            "is_system": is_system,
                        }
                    )
    except Exception as e:
        error(f"Failed to list drives: {e}")

    return drives


def display_drives(drives: list[dict], system: str) -> None:
    """Display drives in a formatted table."""
    print("\n" + "=" * 70)
    print("  AVAILABLE DRIVES")
    print("=" * 70)

    # Sort drives by number/name for consistent display
    if "windows" in system:
        sorted_drives = sorted(drives, key=lambda d: d.get("number", 0))
        print(f"{'[#]':<6} {'Name':<28} {'Size':<10} {'Bus':<8} {'Status'}")
        print("-" * 70)

        for d in sorted_drives:
            status_parts = []
            if d.get("is_system") or d.get("is_boot"):
                status_parts.append("[X] SYSTEM")
            elif d["bus"] in ["USB", "7"]:  # 7 = USB in some versions
                status_parts.append("[OK] External")

            if d["partitions"]:
                letters = [p.get("DriveLetter") for p in d["partitions"] if p.get("DriveLetter")]
                if letters:
                    status_parts.append(f"[{', '.join(letters)}:]")

            status = " ".join(status_parts)
            num_display = f"[{d['number']}]"
            print(f"{num_display:<6} {d['name'][:28]:<28} {d['size_gb']:<10.1f} {d['bus']:<8} {status}")
    else:
        sorted_drives = sorted(drives, key=lambda d: d.get("name", ""))
        print(f"{'[Device]':<15} {'Model':<25} {'Size':<10} {'Bus':<8} {'Status'}")
        print("-" * 70)

        for d in sorted_drives:
            status = "[X] SYSTEM" if d.get("is_system") else "[OK] External" if d.get("bus") == "usb" else ""
            # BUG-20251219-009 FIX: Handle None model value (key exists but value is None)
            # d.get("model", fallback) returns None if key exists with None value
            model = (d.get("model") or d.get("name") or "?")[:25]
            print(f"[{d['name']:<13}] {model:<25} {d.get('size', '?'):<10} {d.get('bus', '?'):<8} {status}")

    print("=" * 70)


def select_drive(drives: list[dict], system: str) -> dict | None:
    """Let user select a drive. Returns selected drive or None.

    SAFETY: This function blocks selection of:
    1. OS drives (is_system/is_boot flag from PowerShell/lsblk)
    2. The instantiation drive (where this script is running from)

    Per FEATURE_FLOWS.md CHG-20251221-040, this is CRITICAL safety logic.
    """
    # Get protected drive identifiers
    os_drive = get_os_drive()
    inst_drive = get_instantiation_drive()

    def _is_protected_drive(drive: dict) -> tuple[bool, str]:
        """Check if drive is protected. Returns (is_protected, reason)."""
        # Check OS/boot flags (from PowerShell Get-Disk or lsblk)
        if drive.get("is_system") or drive.get("is_boot"):
            return True, "system_boot"

        # Check against detected OS drive
        if os_drive:
            if "windows" in system.lower():
                # On Windows, compare drive letters
                partitions = drive.get("partitions", [])
                for part in partitions:
                    part_letter = part.get("DriveLetter", "")
                    if part_letter and f"{part_letter}:" == os_drive:
                        return True, "os_drive"
            else:
                # On Unix, compare device names
                if drive.get("name") == os_drive:
                    return True, "os_drive"

        # Check against instantiation drive (CRITICAL: prevent repartitioning running instance)
        if inst_drive:
            if "windows" in system.lower():
                partitions = drive.get("partitions", [])
                for part in partitions:
                    part_letter = part.get("DriveLetter", "")
                    if part_letter and f"{part_letter}:" == inst_drive:
                        return True, "instantiation_drive"
            else:
                if drive.get("name") == inst_drive:
                    return True, "instantiation_drive"

        return False, ""

    # Filter out protected drives for selection
    safe_drives = []
    protected_drives = []

    for d in drives:
        is_protected, reason = _is_protected_drive(d)
        if is_protected:
            d["_protection_reason"] = reason  # Tag for display
            protected_drives.append(d)
        else:
            safe_drives.append(d)

    # Legacy compatibility: also track system_drives for display
    system_drives = [d for d in drives if d.get("is_system") or d.get("is_boot")]

    if not safe_drives:
        error("No external drives detected!")
        print("Please connect an external USB drive and try again.")
        if inst_drive:
            print(f"\n[INFO] Detected instantiation drive: {inst_drive}")
            print("       (Cannot repartition the drive running this script)")
        return None

    display_drives(drives, system)

    print("\n[!] WARNING: Protected drives are shown but CANNOT be selected:")
    print("    - System/Boot drives: Running your operating system")
    if inst_drive:
        print(f"    - Instantiation drive ({inst_drive}): Running this setup script")
    print("    Only external drives can be configured.\n")

    while True:
        if "windows" in system:
            choice = input("Enter disk NUMBER to configure (or 'q' to quit): ").strip()
            if choice.lower() == "q":
                return None

            try:
                disk_num = int(choice)
                selected = next((d for d in safe_drives if d["number"] == disk_num), None)
                if selected:
                    return selected
                else:
                    # Check if they tried to select a protected drive
                    protected = next((d for d in protected_drives if d["number"] == disk_num), None)
                    if protected:
                        reason = protected.get("_protection_reason", "system")
                        if reason == "instantiation_drive":
                            error(f"Cannot select instantiation drive! This drive is running the setup script.")
                        elif reason == "os_drive":
                            error("Cannot select OS drive! This drive is running your operating system.")
                        else:
                            error("Cannot select system/boot drive! Choose an external drive.")
                    else:
                        error(f"Disk {disk_num} not found.")
            except ValueError:
                error("Please enter a valid disk number.")
        else:
            choice = input("Enter device path to configure (or 'q' to quit): ").strip()
            if choice.lower() == "q":
                return None

            selected = next((d for d in safe_drives if d["name"] == choice), None)
            if selected:
                return selected
            else:
                protected = next((d for d in protected_drives if d["name"] == choice), None)
                if protected:
                    reason = protected.get("_protection_reason", "system")
                    if reason == "instantiation_drive":
                        error(f"Cannot select {choice}! This drive is running the setup script.")
                    elif reason == "os_drive":
                        error(f"Cannot select {choice}! This drive is running your operating system.")
                    else:
                        error(f"Cannot select {choice}! This is a system drive.")
                else:
                    error(f"Device {choice} not found.")


# =============================================================================
# GPG/YubiKey Functions
# =============================================================================


def get_available_fingerprints() -> list[tuple[str, str]]:
    """Get available GPG key fingerprints."""
    try:
        result = run_cmd(["gpg", "--list-keys", "--with-colons"], check=True)

        fingerprints = []
        current_fpr = None

        for line in result.stdout.splitlines():
            parts = line.split(":")
            if parts[0] == "fpr":
                current_fpr = parts[9]
            elif parts[0] == "uid" and current_fpr:
                uid = parts[9]
                fingerprints.append((current_fpr, uid))
                current_fpr = None

        return fingerprints
    except:
        return []


def prompt_for_fingerprints(available: list[tuple[str, str]]) -> tuple[list[str], str]:
    """Prompt user to select YubiKey fingerprints and mode. Returns (fingerprints, mode)."""
    selected = []
    mode_name = SecurityMode.PW_ONLY.value  # default

    print("\n" + "=" * 60)
    print("  SECURITY MODE SELECTION")
    print("=" * 60)
    print(
        f"""
Choose your security level:

  [1] Password + YubiKey (Recommended)
      Keyfile encrypted to hardware token(s)
      Requires: Password + YubiKey + PIN
      
  [2] GPG Password-Only (New!)
      Password derived from GPG-encrypted seed
      Requires: YubiKey + PIN only (no manual password)
      
  [3] Password + Plain Keyfile
      Unencrypted keyfile stored on {Branding.PRODUCT_NAME}
      Requires: Password + keyfile present
      
  [4] Password Only
      No keyfile, just VeraCrypt password
      Requires: Password only
"""
    )

    while True:
        mode = input("Select security mode [1/2/3/4]: ").strip()
        if mode in ("1", "2", "3", "4"):
            break
        print("Please enter 1, 2, 3, or 4.")

    if mode == "4":
        # Password-only mode
        print("\n  ℹ️  Password-only mode selected.")
        print("     Your drive will be protected by password alone.")
        return [], SecurityMode.PW_ONLY.value

    if mode == "3":
        # Plain keyfile mode
        print("\n  ℹ️  Plain keyfile mode selected.")
        print("     A keyfile will be generated but NOT encrypted.")
        print("     Store the keyfile securely (separate from the drive).")
        return ["PLAIN_KEYFILE"], SecurityMode.PW_KEYFILE.value

    if mode == "2":
        # GPG password-only mode
        print("\n  ℹ️  GPG password-only mode selected.")
        print("     A random seed will be encrypted to your YubiKey(s).")
        print("     VeraCrypt password will be derived automatically.")
        print("     Requires: YubiKey + PIN only")
        mode_name = SecurityMode.GPG_PW_ONLY.value
        # Continue to fingerprint selection below

    if mode == "1":
        # YubiKey keyfile mode
        mode_name = SecurityMode.PW_GPG_KEYFILE.value
        # Continue to fingerprint selection below
    print("\n" + "-" * 60)
    print("  SELECT YUBIKEY(S)")
    print("-" * 60)
    print("Select YubiKey(s) to encrypt the keyfile to.")
    print("Recommend: Select MAIN + BACKUP keys.\n")

    if available:
        for i, (fpr, uid) in enumerate(available, 1):
            formatted = " ".join([fpr[j : j + 4] for j in range(0, len(fpr), 4)])
            print(f"  [{i}] {formatted}")
            print(f"      {uid}")
        print(f"  [m] Enter fingerprint manually")
        print(f"  [d] Done selecting\n")

        while True:
            choice = input("Select [1-9/m/d]: ").strip().lower()

            if choice == "d":
                if not selected:
                    print("Please select at least one key.")
                    continue
                break
            elif choice == "m":
                fpr = input("Enter 40-char fingerprint: ").strip().replace(" ", "").upper()
                if len(fpr) == 40 and all(c in "0123456789ABCDEF" for c in fpr):
                    if fpr not in selected:
                        selected.append(fpr)
                        log(f"Added: {fpr[:16]}...")
                else:
                    error("Invalid fingerprint format.")
            elif choice.isdigit() and 1 <= int(choice) <= len(available):
                fpr = available[int(choice) - 1][0]
                if fpr not in selected:
                    selected.append(fpr)
                    log(f"Added: {fpr[:16]}...")
            else:
                print("Invalid selection.")
    else:
        print("No GPG keys found in keyring.")
        print("Enter fingerprints manually.\n")

        while True:
            fpr = input("Enter fingerprint (or 'd' when done): ").strip()
            if fpr.lower() == "d":
                if selected:
                    break
                print("Please enter at least one fingerprint.")
                continue

            fpr = fpr.replace(" ", "").upper()
            if len(fpr) == 40 and all(c in "0123456789ABCDEF" for c in fpr):
                if fpr not in selected:
                    selected.append(fpr)
                    log(f"Added: {fpr[:16]}...")
            else:
                error("Invalid fingerprint (must be 40 hex characters).")

    return selected, mode_name


# =============================================================================
# Security Mode Verification Matrix (SSOT)
# =============================================================================


@dataclass
class SecurityModePrerequisites:
    """
    Prerequisites for a security mode to succeed during setup.

    This is the SINGLE SOURCE OF TRUTH for what each mode requires.
    Setup verification checks these before attempting mount.
    """

    mode: str
    requires_password: bool
    requires_keyfile: bool
    requires_yubikey: bool
    requires_gpg_decrypt: bool
    description: str
    verification_command_hint: str

    def check_prerequisites(
        self, password_set: bool, keyfile_path: Path | None, yubikey_available: bool
    ) -> tuple[bool, list[str]]:
        """
        Check if prerequisites are met for this mode.

        Returns:
            Tuple of (all_met: bool, missing_items: list[str])
        """
        missing = []

        if self.requires_password and not password_set:
            missing.append("Password not set")

        if self.requires_keyfile:
            if keyfile_path is None:
                missing.append("Keyfile path not configured")
            elif not Path(keyfile_path).exists():
                missing.append(f"Keyfile not found at {keyfile_path}")

        if self.requires_yubikey and not yubikey_available:
            missing.append("YubiKey not detected - insert and retry")

        return (len(missing) == 0, missing)


# SSOT: All supported security modes and their requirements
SECURITY_MODE_MATRIX = {
    SecurityMode.PW_ONLY.value: SecurityModePrerequisites(
        mode=SecurityMode.PW_ONLY.value,
        requires_password=True,
        requires_keyfile=False,
        requires_yubikey=False,
        requires_gpg_decrypt=False,
        description="Password only - no keyfile or hardware token",
        verification_command_hint="veracrypt /volume <device> /letter Z /password <pw> /silent /quit",
    ),
    SecurityMode.PW_KEYFILE.value: SecurityModePrerequisites(
        mode=SecurityMode.PW_KEYFILE.value,
        requires_password=True,
        requires_keyfile=True,
        requires_yubikey=False,
        requires_gpg_decrypt=False,
        description="Password + plain keyfile",
        verification_command_hint="veracrypt /volume <device> /letter Z /password <pw> /keyfiles <keyfile> /silent /quit",
    ),
    SecurityMode.PW_GPG_KEYFILE.value: SecurityModePrerequisites(
        mode=SecurityMode.PW_GPG_KEYFILE.value,
        requires_password=True,
        requires_keyfile=True,
        requires_yubikey=True,
        requires_gpg_decrypt=True,
        description="Password + GPG-encrypted keyfile (YubiKey decryption)",
        verification_command_hint=f"1. gpg --decrypt {FileNames.KEYFILE_GPG} > keyfile.vc\n"
        "2. veracrypt /volume <device> /letter Z /password <pw> /keyfiles keyfile.vc /silent /quit",
    ),
    SecurityMode.GPG_PW_ONLY.value: SecurityModePrerequisites(
        mode=SecurityMode.GPG_PW_ONLY.value,
        requires_password=False,  # Password is derived, not manual
        requires_keyfile=False,
        requires_yubikey=True,
        requires_gpg_decrypt=True,
        description="GPG-derived password (YubiKey + PIN only)",
        verification_command_hint=f"1. gpg --decrypt {FileNames.SEED_GPG} | derive password\n"
        "2. veracrypt /volume <device> /letter Z /password <derived> /silent /quit",
    ),
}


def get_mode_prerequisites(security_mode: str) -> SecurityModePrerequisites | None:
    """Get the prerequisites for a security mode."""
    return SECURITY_MODE_MATRIX.get(security_mode)


def verify_mode_prerequisites_or_prompt_manual(
    security_mode: str, password_set: bool, keyfile_path: Path | None, yubikey_available: bool
) -> tuple[bool, bool]:
    """
    Verify prerequisites for the security mode. If verification fails,
    offer explicit manual verification branch.

    Returns:
        Tuple of (can_proceed: bool, manual_verification_done: bool)
    """
    prereqs = get_mode_prerequisites(security_mode)
    if not prereqs:
        log(f"Warning: Unknown security mode '{security_mode}', skipping prerequisite check")
        return (True, False)

    all_met, missing = prereqs.check_prerequisites(password_set, keyfile_path, yubikey_available)

    if all_met:
        log(f"[OK] All prerequisites met for {prereqs.description}")
        return (True, False)

    # Prerequisites not met - offer manual verification
    print("\n" + "=" * 70)
    print("  VERIFICATION PREREQUISITES NOT MET")
    print("=" * 70)
    print(f"\n  Security Mode: {prereqs.description}")
    print("\n  Missing prerequisites:")
    for item in missing:
        print(f"    - {item}")

    print("\n  To verify manually, you can use:")
    print(f"    {prereqs.verification_command_hint}")

    print("\n  Options:")
    print("    [R] Retry - Check prerequisites again")
    print("    [M] Manual - Continue with manual verification")
    print("    [A] Abort - Exit setup")

    while True:
        choice = input("\n  Your choice [R/M/A]: ").strip().upper()
        if choice == "R":
            # Re-check (caller should re-detect yubikey etc.)
            return (False, False)
        elif choice == "M":
            print("\n  Continuing with manual verification...")
            print("  You will need to verify the mount works yourself.")
            return (True, True)
        elif choice == "A":
            print("\n  Setup aborted.")
            return (False, False)
        print("  Please enter R, M, or A.")


# =============================================================================
# Partitioning Functions
# =============================================================================


def check_disk_ready_windows(disk_number: int) -> bool:
    """
    BUG-20251220-002: Check if a disk is ready for I/O operations on Windows.

    Uses diskpart to verify the disk exists and is accessible.
    Returns True if disk is ready, False otherwise.
    """
    try:
        # Use diskpart to query disk status
        script = f"""select disk {disk_number}
detail disk
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(script)
            script_path = f.name

        try:
            result = subprocess.run(
                ["diskpart", "/s", script_path],
                capture_output=True,
                text=True,
                encoding="cp1252",
                errors="replace",
                timeout=Limits.POWERSHELL_QUICK_TIMEOUT,
            )

            # Check if diskpart succeeded and didn't report device not ready
            if result.returncode == 0:
                output_lower = result.stdout.lower()
                # Look for common "not ready" indicators
                if "nicht bereit" in output_lower or "not ready" in output_lower:
                    return False
                # Look for "fehler" (error) indicators
                if "fehler" in output_lower and "ger„t" in output_lower:
                    return False
                return True
            return False
        finally:
            try:
                os.unlink(script_path)
            except:
                pass
    except Exception:
        return False


def partition_drive_windows(disk_number: int, launcher_size_mb: int, launcher_label: str) -> tuple[str, str]:
    """
    Partition a drive on Windows using diskpart.
    Creates: LAUNCHER (size launcher_size_mb) + PAYLOAD (rest of disk)
    Formats LAUNCHER using CryptoParams.LAUNCHER_FILESYSTEM_ID (SSOT via core/filesystems.py)
    Returns: (launcher_drive_letter, payload_device_path)
    """
    # BUG-20251220-002: Check device readiness before partitioning
    log(f"Checking if disk {disk_number} is ready...")
    max_retries = Limits.DISKPART_DEVICE_READY_MAX_RETRIES
    retry_delay = Limits.DISKPART_DEVICE_READY_RETRY_DELAY_SECONDS

    for attempt in range(1, max_retries + 1):
        if check_disk_ready_windows(disk_number):
            log(f"[OK] Disk {disk_number} is ready")
            break

        if attempt < max_retries:
            print(f"\n⚠️  Device not ready yet (attempt {attempt}/{max_retries})... waiting {retry_delay} seconds...")
            print("   Press Ctrl+C to cancel if the device will not become ready.")
            try:
                time.sleep(retry_delay)
            except KeyboardInterrupt:
                print("\n\n[!] Cancelled by user")
                raise RuntimeError("Device readiness check cancelled by user")
        else:
            # All retries exhausted
            error("Device is not ready after multiple attempts!")
            print("\n❌ The drive could not be accessed. Common causes:")
            print("   • Drive was recently inserted and is still initializing")
            print("   • Drive is faulty or not fully connected")
            print("   • Windows has not finished enumerating the drive")
            print("\n💡 Troubleshooting steps:")
            print("   1. Remove and reinsert the drive, then run setup again")
            print("   2. Check Windows Disk Management (diskmgmt.msc) to verify the disk appears")
            print("   3. Try a different USB port or cable")
            raise RuntimeError(f"Disk {disk_number} is not ready for partitioning")

    log(f"Partitioning disk {disk_number}...")

    spec = launcher_fs_spec(CryptoParams)
    if not spec.windows_diskpart_fs:
        raise RuntimeError(f"Launcher filesystem '{spec.id}' not supported on Windows (diskpart)")

    diskpart_script = f"""select disk {disk_number}
clean
create partition primary size={launcher_size_mb}
format fs={spec.windows_diskpart_fs} label="{launcher_label}" quick
assign
create partition primary
"""

    # Write script to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(diskpart_script)
        script_path = f.name

    try:
        # Run diskpart with real-time output streaming
        log("Running diskpart (this may take 30-60 seconds for disk operations)...")
        log("Progress will be shown below:")
        print()

        # Use Popen for real-time output streaming
        process = subprocess.Popen(
            ["diskpart", "/s", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="cp1252",
            errors="replace",
        )

        stdout_lines = []
        timeout_seconds = 120
        start_time = time.time()

        # Read output in real-time
        while True:
            # Check for timeout
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                process.kill()
                error(f"Diskpart timed out after {timeout_seconds} seconds")
                raise RuntimeError("Diskpart operation timed out")

            line = process.stdout.readline()
            if not line:
                # Process finished
                break

            # Show progress in real-time
            line = line.rstrip()
            if line:
                print(f"  {line}")
                stdout_lines.append(line)

        # Wait for process to complete
        returncode = process.wait(timeout=5)
        stdout = "\n".join(stdout_lines)

        # Check for errors in diskpart output
        if returncode != 0 or (stdout and "error" in stdout.lower()):
            error("Diskpart failed!")
            print(f"\nDiskpart output:\n{stdout}")
            raise RuntimeError("Diskpart partitioning failed - see output above")

        print()
        log("[OK] Partitioning complete")

        # Wait for Windows to recognize new partitions
        time.sleep(3)

        # Discover launcher drive letter + payload partition number
        ps_script = f"""
        $partitions = Get-Partition -DiskNumber {disk_number} | Sort-Object PartitionNumber
        $launcher = $partitions | Where-Object {{ $_.PartitionNumber -eq 1 }}
        $payload = $partitions | Where-Object {{ $_.PartitionNumber -ne 1 -and -not $_.IsHidden }} |
                   Sort-Object Size -Descending | Select-Object -First 1
        @{{
            SmartDriveLetter = $launcher.DriveLetter
            PayloadPartitionNumber = if ($payload) {{ $payload.PartitionNumber }} else {{ 2 }}
        }} | ConvertTo-Json
        """

        result = run_cmd(["powershell", "-NoProfile", "-Command", ps_script])
        info = json.loads(result.stdout)

        smartdrive_letter = info.get("SmartDriveLetter", "") or ""
        payload_partition = info.get("PayloadPartitionNumber", 2)

        # Device path for VeraCrypt (note: Harddisk numbering may differ on some systems)
        payload_device = f"\\Device\\Harddisk{disk_number}\\Partition{payload_partition}"

        return smartdrive_letter, payload_device

    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def partition_drive_unix(device: str, launcher_size_mb: int, launcher_label: str) -> tuple[str, str]:
    """
    Partition a drive on Unix/Linux using parted.
    Creates: LAUNCHER (size launcher_size_mb) + PAYLOAD (rest of disk)
    Formats LAUNCHER using CryptoParams.LAUNCHER_FILESYSTEM_ID (SSOT via core/filesystems.py)
    Returns: (launcher_mount_point, payload_device)
    """
    log(f"Partitioning {device}...")

    # Create GPT partition table
    run_cmd(["parted", "-s", device, "mklabel", "gpt"], check=True)

    # Create LAUNCHER partition (no FS hint; mkfs happens explicitly via SSOT)
    run_cmd(["parted", "-s", device, "mkpart", "primary", "1MiB", f"{launcher_size_mb + 1}MiB"], check=True)

    # Create PAYLOAD partition (rest of disk)
    run_cmd(["parted", "-s", device, "mkpart", "primary", f"{launcher_size_mb + 1}MiB", "100%"], check=True)

    # Determine partition names
    if "nvme" in device or "mmcblk" in device:
        launcher_dev = f"{device}p1"
        payload_dev = f"{device}p2"
    else:
        launcher_dev = f"{device}1"
        payload_dev = f"{device}2"

    # Wait for kernel to recognize partitions
    time.sleep(1)

    # Format LAUNCHER partition using SSOT FS spec
    spec = launcher_fs_spec(CryptoParams)
    if not spec.unix_mkfs_cmd:
        raise RuntimeError(f"Launcher filesystem '{spec.id}' not supported on Unix")

    run_cmd([*spec.unix_mkfs_cmd, launcher_label, launcher_dev], check=True)

    log("[OK] Partitioning complete")

    # Mount LAUNCHER temporarily
    mount_point = f"{Paths.LINUX_MNT_PREFIX}{launcher_label}"
    os.makedirs(mount_point, exist_ok=True)
    run_cmd(["mount", launcher_dev, mount_point], check=True)

    return mount_point, payload_dev


# =============================================================================
# VeraCrypt Functions
# =============================================================================


def find_veracrypt_windows() -> Path | None:
    """Find VeraCrypt.exe on Windows using core.paths."""
    # First check PATH
    vc_which = shutil.which(Paths.VERACRYPT_EXE_NAME)
    if vc_which:
        return Path(vc_which)

    # Use centralized path from core.paths
    try:
        vc_path = Paths.veracrypt_exe()
        if vc_path and vc_path.exists():
            return vc_path
    except RuntimeError:
        pass
    return None


def build_veracrypt_mount_cmd_windows(
    vc_exe: Path, volume: str, mount_letter: str, password: str, *, keyfile: Path = None, read_only: bool = True
) -> list:
    """
    Build VeraCrypt mount command for WINDOWS ONLY.

    MANDATORY RULES:
    - Returns argv LIST ONLY (for subprocess.run with shell=False)
    - Uses ONLY Windows flags (/volume, /letter, /password, /quit, /silent)
    - NEVER uses Linux flags (--text, --password, etc.)
    - All Path→str conversion happens inside this function
    - No empty arguments in returned list

    Args:
        vc_exe: Path to VeraCrypt.exe
        volume: Volume path (drive letter like "E:" or volume GUID)
        mount_letter: Target mount letter (e.g., "Z" or "Z:")
        password: Volume password (passed as-is, subprocess handles escaping)
        keyfile: Optional keyfile path
        read_only: If True, mount as read-only (for verification)

    Returns:
        List[str] - argv for subprocess.run(args, shell=False)

    Raises:
        ValueError: If mount_letter is invalid
    """
    # Normalize mount letter via SSOT helper
    letter = normalize_mount_letter(mount_letter)

    # Build argv with ONLY Windows flags
    args = [str(vc_exe), "/volume", volume, "/letter", letter, "/password", password, "/quit", "/silent"]

    # Add keyfile if provided
    if keyfile and keyfile.exists():
        args.extend(["/keyfile", str(keyfile)])

    # Validate: no empty arguments
    for i, arg in enumerate(args):
        if not arg:
            raise ValueError(f"Empty argument at position {i} in VeraCrypt command")

    return args


def log_veracrypt_invocation(args: list, cwd: str = None):
    """
    Log VeraCrypt command invocation with password sanitized.

    MANDATORY: Called before every subprocess.run() for VeraCrypt.
    """
    # Sanitize password in argv
    sanitized = []
    skip_next = False
    for arg in args:
        if skip_next:
            sanitized.append("<PW>")
            skip_next = False
        elif arg == "/password":
            sanitized.append(arg)
            skip_next = True
        else:
            sanitized.append(arg)

    log(f"VeraCrypt invocation:")
    log(f"  argv: {sanitized}")
    log(f"  argc: {len(args)}")
    log(f"  cwd: {cwd or os.getcwd()}")
    log(f"  shell: False (mandatory)")


class VolumeResolutionError(Exception):
    r"""
    Failed to resolve a volume device path to a usable format.

    Per AGENT_ARCHITECTURE.md Section 2.5: Device paths (\Device\Harddisk)
    MUST be resolved to GUID or drive letter. Never return unresolved paths.
    """

    pass


# =============================================================================
# SINGLE SOURCE OF TRUTH: Mount Verification
# =============================================================================


@dataclass
class MountVerificationResult:
    """
    Result of a mount verification check.

    Use this structured result instead of simple bool/str returns.
    """

    success: bool
    mount_point: Optional[str] = None  # Confirmed mount letter/path
    volume_identifier: Optional[VolumeIdentifier] = None
    error_message: Optional[str] = None
    diagnostic_info: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success


def log_pre_mount_diagnostic(
    disk_number: Optional[int],
    payload_device: str,
    security_mode: str,
    has_keyfile: bool,
    preferred_letter: Optional[str] = None,
) -> dict:
    """
    Log comprehensive pre-mount diagnostic snapshot.

    Call this BEFORE every mount attempt to aid troubleshooting.
    Uses the SSOT DiskSnapshot from core.safety for partition resolution.

    Args:
        disk_number: Windows disk number (None for Unix)
        payload_device: Device path or volume identifier
        security_mode: SecurityMode value being used
        has_keyfile: Whether a keyfile is being used
        preferred_letter: Candidate mount letter (Windows only)

    Returns:
        Dict of diagnostic info for inclusion in error reports
    """
    log("=" * 60)
    log("PRE-MOUNT DIAGNOSTIC SNAPSHOT")
    log("=" * 60)

    diagnostics = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": get_platform(),
        "disk_number": disk_number,
        "payload_device": payload_device,
        "security_mode": security_mode,
        "has_keyfile": has_keyfile,
        "preferred_letter": preferred_letter,
    }

    log(f"  Platform: {diagnostics['platform']}")
    log(f"  Disk Number: {disk_number}")
    log(f"  Payload Device: {payload_device}")
    log(f"  Security Mode: {security_mode}")
    log(f"  Has Keyfile: {has_keyfile}")

    if "windows" in get_platform():
        log(f"  Preferred Letter: {preferred_letter}")

        # Use SSOT DiskSnapshot for comprehensive disk state
        if disk_number is not None:
            try:
                snapshot = get_disk_snapshot_windows(disk_number)
                if snapshot:
                    # Log the full snapshot
                    snapshot.log()

                    # Store snapshot info in diagnostics
                    diagnostics["disk_snapshot"] = {
                        "disk_unique_id": snapshot.disk_identity.unique_id,
                        "disk_bus_type": snapshot.disk_identity.bus_type,
                        "partition_count": len(snapshot.partitions),
                        "partitions": [p.to_log_dict() for p in snapshot.partitions],
                        "launcher_partition": (
                            snapshot.launcher_partition.partition_number if snapshot.launcher_partition else None
                        ),
                        "payload_partition": (
                            snapshot.payload_partition.partition_number if snapshot.payload_partition else None
                        ),
                    }
                else:
                    log("  [DiskSnapshot: Failed to query]")
                    diagnostics["disk_snapshot_error"] = "Query failed"
            except Exception as e:
                log(f"  [DiskSnapshot query failed: {e}]")
                diagnostics["disk_snapshot_error"] = str(e)

    log("=" * 60)
    return diagnostics


def verify_mount_operation(
    vc_exe: Path,
    payload_device: str,
    password: str,
    keyfile_path: Optional[Path],
    security_mode: str,
    disk_number: Optional[int] = None,
    preferred_letter: str = "Z",
    log_diagnostics: bool = True,
) -> MountVerificationResult:
    """
    SINGLE SOURCE OF TRUTH for mount verification.

    This function handles ALL SecurityMode variants and provides:
    - Pre-mount diagnostic logging
    - Volume resolution
    - Mount attempt
    - Post-mount confirmation

    ALL mount verification in setup should use this function.

    Args:
        vc_exe: Path to VeraCrypt executable
        payload_device: Device path or identifier
        password: VeraCrypt password
        keyfile_path: Path to keyfile (if any)
        security_mode: SecurityMode enum value
        disk_number: Windows disk number (required for volume resolution)
        preferred_letter: Candidate mount letter (Windows only)
        log_diagnostics: Whether to log pre-mount diagnostics

    Returns:
        MountVerificationResult with success status and confirmed mount point
    """
    system = get_platform()
    has_keyfile = keyfile_path is not None and Path(keyfile_path).exists()

    # Step 1: Log pre-mount diagnostics
    if log_diagnostics:
        diagnostics = log_pre_mount_diagnostic(
            disk_number=disk_number,
            payload_device=payload_device,
            security_mode=security_mode,
            has_keyfile=has_keyfile,
            preferred_letter=preferred_letter if "windows" in system else None,
        )
    else:
        diagnostics = {}

    # Step 2: Windows volume resolution
    volume_identifier = None
    temp_letter = None

    if "windows" in system:
        if disk_number is None:
            return MountVerificationResult(
                success=False,
                error_message="Windows mount requires disk_number for volume resolution",
                diagnostic_info=diagnostics,
            )

        # Refresh volume enumeration
        log("Step 1: Refreshing Windows volume enumeration...")
        refresh_windows_volume_enumeration(disk_number, timeout_seconds=10)

        # Resolve to usable format
        log("Step 2: Resolving volume target...")
        try:
            volume_identifier, temp_letter = resolve_volume_target_windows(payload_device, disk_number)
            log(f"Volume identifier confirmed: {volume_identifier}")
        except VolumeResolutionError as e:
            return MountVerificationResult(success=False, error_message=str(e), diagnostic_info=diagnostics)

        # Build mount command with resolved volume
        volume_target = volume_identifier.to_veracrypt_arg()
        args = build_veracrypt_mount_cmd(
            vc_exe, volume_target, preferred_letter, password, keyfile_path, is_windows=True
        )
    else:
        # Unix: use device path directly
        volume_target = payload_device
        args = ["veracrypt", "--text", "--non-interactive", "--mount", volume_target]
        if password:
            args.extend(["--password", password])
        if keyfile_path:
            args.extend(["--keyfiles", str(keyfile_path)])

    # Step 3: Execute mount
    log("Step 3: Executing mount command...")
    log_veracrypt_invocation(args)

    try:
        result = subprocess.run(args, capture_output=True, timeout=Limits.VERACRYPT_MOUNT_TIMEOUT)
    except subprocess.TimeoutExpired:
        if temp_letter:
            remove_temp_drive_letter(temp_letter)
        return MountVerificationResult(
            success=False,
            error_message=f"Mount timed out after {Limits.VERACRYPT_MOUNT_TIMEOUT}s",
            diagnostic_info=diagnostics,
        )
    except Exception as e:
        if temp_letter:
            remove_temp_drive_letter(temp_letter)
        return MountVerificationResult(
            success=False, error_message=f"Mount exception: {e}", diagnostic_info=diagnostics
        )

    # Clean up temp letter
    if temp_letter:
        remove_temp_drive_letter(temp_letter)

    # Step 4: Verify mount success
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore") if result.stderr else ""
        return MountVerificationResult(
            success=False,
            error_message=f"VeraCrypt returned {result.returncode}: {stderr[:200]}",
            diagnostic_info=diagnostics,
        )

    # Step 5: Confirm mount letter/path
    log("Step 4: Confirming mount binding...")

    if "windows" in system:
        # Verify preferred letter is actually bound
        mount_path = Path(f"{preferred_letter}:\\")
        if mount_path.exists():
            log(f"[OK] Mount CONFIRMED at {preferred_letter}:")
            return MountVerificationResult(
                success=True,
                mount_point=preferred_letter,
                volume_identifier=volume_identifier,
                diagnostic_info=diagnostics,
            )
        else:
            # Windows may have used a different letter - scan for it
            for letter in "ZYXWVUTSRQPONMLKJIHGFED":
                try:
                    test_path = Path(f"{letter}:\\")
                    if test_path.exists() and letter != preferred_letter:
                        # Found a different mount - might be ours
                        # TODO: Add more verification (e.g., check for VeraCrypt signature)
                        log(f"Mount at unexpected letter: {letter}: (expected {preferred_letter}:)")
                except Exception:
                    pass

            return MountVerificationResult(
                success=False,
                error_message=f"Mount command succeeded but {preferred_letter}: not confirmed",
                diagnostic_info=diagnostics,
            )
    else:
        # Unix: mount succeeded if returncode is 0
        # TODO: Add actual mount point discovery for Unix
        return MountVerificationResult(success=True, mount_point=volume_target, diagnostic_info=diagnostics)


def refresh_windows_volume_enumeration(
    disk_number: int, timeout_seconds: int = 10, partition_number: int = None
) -> bool:
    """
    Trigger Windows to re-enumerate volumes after partition creation.

    MANDATORY POST-SETUP STEP (TODO 4):
    After manual VeraCrypt creation, Windows may not immediately expose
    the new volume. This function attempts to refresh the enumeration.

    Args:
        disk_number: Disk number to refresh
        timeout_seconds: Max time to wait for volume to appear
        partition_number: Specific partition to check (if None, uses find_payload_partition_number)

    Returns:
        True if volume became visible, False if still not visible
    """
    log("Refreshing Windows volume enumeration...")

    # Determine partition number if not provided (NO HARDCODED 2)
    if partition_number is None:
        try:
            partition_number = find_payload_partition_number(disk_number, launcher_partition=1)
        except RuntimeError as e:
            log(f"  - Could not determine payload partition: {e}")
            partition_number = 2  # Fallback only if discovery fails

    # Method 1: Update-HostStorageCache (most reliable)
    try:
        ps_refresh = """
        Update-HostStorageCache -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
        """
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_refresh], capture_output=True, timeout=5)
        log("  - Update-HostStorageCache executed")
    except Exception as e:
        log(f"  - Update-HostStorageCache failed: {e}")

    # Method 2: Re-scan disk
    try:
        ps_rescan = f"""
        $disk = Get-Disk -Number {disk_number} -ErrorAction SilentlyContinue
        if ($disk) {{
            Update-Disk -Number {disk_number} -ErrorAction SilentlyContinue
        }}
        """
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_rescan], capture_output=True, timeout=5)
        log("  - Update-Disk executed")
    except Exception as e:
        log(f"  - Update-Disk failed: {e}")

    # Wait and poll for volume to appear
    import time

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        # Check if payload partition has a volume (using discovered partition_number)
        try:
            ps_check = f"""
            $part = Get-Partition -DiskNumber {disk_number} -PartitionNumber {partition_number} -ErrorAction SilentlyContinue
            if ($part) {{
                $vol = Get-Volume -Partition $part -ErrorAction SilentlyContinue
                if ($vol) {{
                    if ($part.DriveLetter) {{
                        Write-Output "LETTER:$($part.DriveLetter)"
                    }} elseif ($vol.UniqueId) {{
                        Write-Output "GUID:$($vol.UniqueId)"
                    }} else {{
                        Write-Output "PARTITION_EXISTS"
                    }}
                }} else {{
                    Write-Output "NO_VOLUME"
                }}
            }} else {{
                Write-Output "NO_PARTITION"
            }}
            """
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_check],
                capture_output=True,
                text=True,
                timeout=Limits.POWERSHELL_QUICK_TIMEOUT,
            )
            output = result.stdout.strip()

            if output.startswith("LETTER:") or output.startswith("GUID:"):
                log(f"  - Volume enumerated: {output}")
                return True
            elif output == "PARTITION_EXISTS":
                log("  - Partition exists but no volume identifier yet")
        except Exception:
            pass

        time.sleep(1)

    log(f"  - Volume not enumerated after {timeout_seconds}s")
    return False


# =============================================================================
# Payload Partition Discovery (SSOT for partition number)
# =============================================================================


def find_payload_partition_number(disk_number: int, launcher_partition: int = 1) -> int:
    """
    Find the payload partition number by exclusion.

    Per AGENT_ARCHITECTURE.md Section 2.5: NO HARDCODED PARTITION NUMBERS.
    The payload partition is the one that is NOT the launcher partition.

    This function handles:
    - Standard 2-partition layout (launcher=1, payload=2)
    - Future multi-partition layouts
    - Recovery/hidden partitions

    Args:
        disk_number: Windows disk number
        launcher_partition: Known launcher partition number (default 1)

    Returns:
        Partition number of the payload partition

    Raises:
        RuntimeError: If payload partition cannot be determined
    """
    try:
        ps_script = f"""
        $partitions = Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue
        if ($partitions) {{
            $partitions | Sort-Object PartitionNumber | ForEach-Object {{
                @{{
                    Number = $_.PartitionNumber
                    Size = [math]::Round($_.Size / 1GB, 2)
                    Type = $_.Type
                    IsHidden = $_.IsHidden
                    DriveLetter = $_.DriveLetter
                }}
            }} | ConvertTo-Json -Depth 2
        }} else {{
            "[]"
        }}
        """
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=Limits.POWERSHELL_QUICK_TIMEOUT,
        )

        data = json.loads(result.stdout) if result.stdout.strip() else []
        if isinstance(data, dict):
            data = [data]  # Single partition case

        # Filter out the launcher partition and find the largest remaining
        # The payload partition is typically the largest non-launcher partition
        candidates = [
            p
            for p in data
            if p["Number"] != launcher_partition and not p.get("IsHidden", False)  # Skip hidden partitions
        ]

        if not candidates:
            raise RuntimeError(
                f"No payload partition found on disk {disk_number}. "
                f"Expected at least 2 partitions, launcher is partition {launcher_partition}."
            )

        # Return the largest candidate (by size)
        payload = max(candidates, key=lambda p: p.get("Size", 0))
        log(f"Payload partition discovered: #{payload['Number']} ({payload.get('Size', '?')} GB)")
        return payload["Number"]

    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse partition info: {e}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timeout querying partitions on disk {disk_number}")


def resolve_volume_target_windows(payload_device: str, disk_number: int = None) -> tuple:
    """
    Resolve a volume target to a usable format for VeraCrypt CLI.

    MANDATORY (Per AGENT_ARCHITECTURE.md Section 2.5):
    VeraCrypt CLI on Windows cannot use \\Device\\Harddisk paths.
    Must resolve to drive letter or volume GUID.

    NEVER returns a device path as "resolved" - that is a bug.
    NEVER logs "Resolved volume target: <device_path>".

    Args:
        payload_device: The device path (may be \\Device\\Harddisk format)

        disk_number: Optional disk number for partition lookup

    Returns:
        (volume_identifier: VolumeIdentifier, temp_letter_assigned: str or None)
        - volume_identifier: CONFIRMED identifier (drive_letter or volume_guid)
        - temp_letter_assigned: If a temp letter was assigned, return it for cleanup

    Raises:
        VolumeResolutionError: If device path cannot be resolved to letter/GUID
    """
    # Track what we tried for error message
    resolution_attempts = []

    # Step 1: If already has a drive letter format, validate and return
    if len(payload_device) <= 3 and payload_device[0].isalpha():
        letter = payload_device.rstrip(":").upper()
        # Verify the letter actually exists
        if Path(f"{letter}:\\").exists():
            vid = VolumeIdentifier.from_drive_letter(letter, resolution_method="input_validated")
            log(f"Volume identifier confirmed: {vid}")
            return (vid, None)
        else:
            resolution_attempts.append(f"input letter '{letter}:' does not exist")

    # Step 2: Parse device path
    is_device_path = payload_device.startswith("\\Device\\") or payload_device.startswith("\\\\.\\PhysicalDrive")

    if not is_device_path and disk_number is None:
        # Not a device path and no disk number - can't resolve
        raise VolumeResolutionError(
            f"Cannot resolve '{payload_device}': not a valid device path and no disk number provided."
        )

    # Step 2.5: Determine payload partition number dynamically (NO HARDCODED 2)
    payload_partition_num = None
    if disk_number is not None:
        try:
            payload_partition_num = find_payload_partition_number(disk_number, launcher_partition=1)
            log(f"Using payload partition #{payload_partition_num} on disk {disk_number}")
        except RuntimeError as e:
            resolution_attempts.append(f"payload partition discovery: {e}")

    # Step 3: Try to find existing drive letter for this partition
    if disk_number is not None and payload_partition_num is not None:
        try:
            ps_script = f"""
            $partition = Get-Partition -DiskNumber {disk_number} -PartitionNumber {payload_partition_num} -ErrorAction SilentlyContinue
            if ($partition -and $partition.DriveLetter) {{
                $partition.DriveLetter
            }}
            """
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=Limits.POWERSHELL_QUICK_TIMEOUT,
            )
            letter = result.stdout.strip()
            if letter and len(letter) == 1 and letter.isalpha():
                # Verify the letter exists
                if Path(f"{letter}:\\").exists():
                    vid = VolumeIdentifier.from_drive_letter(letter, resolution_method="partition_query")
                    log(f"Volume identifier confirmed: {vid}")
                    return (vid, None)
                else:
                    resolution_attempts.append(f"partition has letter '{letter}' but path doesn't exist")
            else:
                resolution_attempts.append("existing drive letter: partition has no letter assigned")
        except Exception as e:
            resolution_attempts.append(f"existing drive letter query: {e}")

    # Step 4: Try volume GUID path
    if disk_number is not None and payload_partition_num is not None:
        try:
            ps_script = f"""
            $partition = Get-Partition -DiskNumber {disk_number} -PartitionNumber {payload_partition_num} -ErrorAction SilentlyContinue
            if ($partition) {{
                $volume = Get-Volume -Partition $partition -ErrorAction SilentlyContinue
                if ($volume -and $volume.UniqueId) {{
                    $volume.UniqueId
                }}
            }}
            """
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=Limits.POWERSHELL_QUICK_TIMEOUT,
            )
            guid_path = result.stdout.strip()
            if guid_path and guid_path.startswith("\\\\?\\Volume{"):
                vid = VolumeIdentifier.from_volume_guid(guid_path, resolution_method="volume_query")
                log(f"Volume identifier confirmed: {vid}")
                return (vid, None)
            else:
                resolution_attempts.append("volume GUID: partition has no GUID assigned")
        except Exception as e:
            resolution_attempts.append(f"volume GUID query: {e}")

    # Step 5: Try to assign a temporary drive letter
    if disk_number is not None and payload_partition_num is not None:
        temp_letter = assign_temp_drive_letter(disk_number, payload_partition_num)
        if temp_letter:
            # Verify assignment succeeded
            if Path(f"{temp_letter}:\\").exists():
                vid = VolumeIdentifier.from_drive_letter(temp_letter, resolution_method="temp_assignment")
                log(f"Volume identifier confirmed (temporary): {vid}")
                return (vid, temp_letter)
            else:
                resolution_attempts.append(f"temp letter '{temp_letter}' assigned but path doesn't exist")
                remove_temp_drive_letter(temp_letter)
        else:
            resolution_attempts.append("temp drive letter assignment: failed to assign any letter")

    # MANDATORY: Never return a device path as "resolved" - that's a bug
    # Per AGENT_ARCHITECTURE.md Section 2.5: If CLI feature unavailable,
    # fall back to documented guidance, don't silently fail
    error_details = (
        "\n".join(f"  - {a}" for a in resolution_attempts) if resolution_attempts else "  - no resolution attempts made"
    )
    raise VolumeResolutionError(
        f"Cannot resolve device path to drive letter or volume GUID.\n"
        f"\n"
        f"Device: {payload_device}\n"
        f"Disk number: {disk_number}\n"
        f"\n"
        f"Resolution attempts:\n"
        f"{error_details}\n"
        f"\n"
        f"GUIDANCE:\n"
        f"Windows has not exposed this partition as a mountable volume.\n"
        f"This typically happens immediately after VeraCrypt GUI creates a volume.\n"
        f"\n"
        f"TO FIX:\n"
        f"1. Open Disk Management (diskmgmt.msc)\n"
        f"2. Find the partition on Disk {disk_number}\n"
        f"3. Right-click -> 'Change Drive Letter and Paths...'\n"
        f"4. Assign any available letter (e.g., Z:)\n"
        f"5. Re-run this operation\n"
    )


def assign_temp_drive_letter(disk_number: int, partition_number: int = None) -> str:
    """
    Assign a temporary drive letter to a partition.

    Args:
        disk_number: Windows disk number
        partition_number: Partition number to assign letter to.
                         If None, uses find_payload_partition_number() to discover it.

    Returns the assigned letter or None on failure.
    """
    if disk_number is None:
        return None

    # Determine partition number if not provided (NO HARDCODED 2)
    if partition_number is None:
        try:
            partition_number = find_payload_partition_number(disk_number, launcher_partition=1)
        except RuntimeError as e:
            log(f"Cannot assign temp letter: {e}")
            return None

    # Find an available letter (start from Y, go backwards)
    for letter in "YXWVUTSRQPONMLKJIHG":
        try:
            # Check if letter is in use
            check = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Test-Path '{letter}:'"],
                capture_output=True,
                text=True,
                timeout=Limits.PROCESS_CHECK_TIMEOUT,
            )
            if "True" in check.stdout:
                continue  # Letter in use

            # Assign the letter using discovered partition number
            ps_script = f"""
            $partition = Get-Partition -DiskNumber {disk_number} -PartitionNumber {partition_number} -ErrorAction Stop
            Set-Partition -InputObject $partition -NewDriveLetter '{letter}' -ErrorAction Stop
            Write-Output '{letter}'
            """
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=Limits.POWERSHELL_ASSIGN_LETTER_TIMEOUT,
            )
            if result.returncode == 0 and letter in result.stdout:
                log(f"Assigned temporary drive letter: {letter}:")
                return letter
        except Exception:
            continue

    return None


def remove_temp_drive_letter(letter: str):
    """
    Remove a temporarily assigned drive letter.
    """
    if not letter:
        return
    try:
        ps_script = f"""
        $volume = Get-Volume -DriveLetter '{letter}' -ErrorAction SilentlyContinue
        if ($volume) {{
            Remove-PartitionAccessPath -DriveLetter '{letter}' -ErrorAction SilentlyContinue
        }}
        """
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=Limits.POWERSHELL_QUICK_TIMEOUT,
        )
        log(f"Removed temporary drive letter: {letter}:")
    except Exception as e:
        warn(f"Could not remove temp drive letter {letter}: {e}")


def build_veracrypt_dismount_cmd_windows(vc_exe: Path, mount_letter: str) -> list:
    """
    Build VeraCrypt dismount command for WINDOWS ONLY.

    MANDATORY RULES:
    - Returns argv LIST ONLY
    - Uses ONLY Windows flags (/dismount, /letter, /quit, /silent)
    - NEVER uses Linux flags

    Args:
        vc_exe: Path to VeraCrypt.exe
        mount_letter: Mounted drive letter (e.g., "Z" or "Z:")

    Returns:
        List[str] - argv for subprocess.run(args, shell=False)
    """
    letter = normalize_mount_letter(mount_letter)
    return [str(vc_exe), "/dismount", letter, "/quit", "/silent"]


# Legacy wrapper for compatibility during transition
def build_veracrypt_mount_cmd(
    vc_exe: Path, volume_path: str, mount_point: str, password: str, keyfile_path: Path = None, is_windows: bool = True
) -> list:
    """DEPRECATED: Use build_veracrypt_mount_cmd_windows instead."""
    if is_windows:
        return build_veracrypt_mount_cmd_windows(vc_exe, volume_path, mount_point, password, keyfile=keyfile_path)
    else:
        # Unix path - not the focus of P0-A fix
        return ["veracrypt", "--text", "--non-interactive", "--mount", volume_path, mount_point, "--password", password]


def build_veracrypt_dismount_cmd(vc_exe: Path, mount_point: str, is_windows: bool = True) -> list:
    """DEPRECATED: Use build_veracrypt_dismount_cmd_windows instead."""
    if is_windows:
        return build_veracrypt_dismount_cmd_windows(vc_exe, mount_point)
    else:
        return ["veracrypt", "--text", "--dismount", mount_point]


def create_veracrypt_volume_windows(
    vc_exe: Path,
    device_path: str,
    password: str,
    keyfile_path: Path | None = None,
    size_mb: int | None = None,
    security_mode: str = SecurityMode.PW_ONLY.value,
    session_seed_gpg_path: Path | None = None,
    session_salt_b64: str | None = None,
    session_hkdf_info: str | None = None,
) -> bool:
    """
    Create a VeraCrypt volume on Windows.

    Returns:
        bool: True if volume was created successfully
    """
    log(f"Creating VeraCrypt volume on {device_path}...")

    # VeraCrypt CLI (Format.exe) does NOT support partition/device encryption reliably.
    # It only works well for file containers with explicit size.
    # For partition encryption, we MUST use the GUI.

    # Check if this is a device path (partition encryption) vs file container
    is_device = (
        device_path.startswith("\\Device\\") or device_path.startswith("\\\\.\\") or device_path.startswith("\\\\?\\")
    )

    if is_device:
        # Device/partition encryption - go directly to GUI
        log("Partition encryption requires VeraCrypt GUI...")
        return create_veracrypt_volume_gui(
            vc_exe,
            device_path,
            password,
            keyfile_path,
            security_mode,
            session_seed_gpg_path,
            session_salt_b64,
            session_hkdf_info,
        )

    # File container - CLI works fine
    log("Creating file container via CLI...")

    # Use centralized executable name from Paths
    format_exe = vc_exe.parent / Paths.VERACRYPT_FORMAT_EXE_NAME
    if not format_exe.exists():
        format_exe = vc_exe

    args = [
        str(format_exe),
        "/create",
        device_path,
        "/password",
        password,
        "/encryption",
        "AES",
        "/hash",
        "SHA-512",
        "/filesystem",
        "exFAT",
        "/quick",
        "/silent",
    ]

    if size_mb:
        args.extend(["/size", f"{size_mb}M"])

    if keyfile_path:
        args.extend(["/keyfile", str(keyfile_path)])

    try:
        # VeraCrypt volume creation can take a while
        result = run_cmd(args, check=False, timeout=600)

        # Check output for success or known issues
        output = (result.stdout or "") + (result.stderr or "")

        if result.returncode == 0 and "error" not in output.lower():
            log("\u2713 VeraCrypt volume created successfully")
            return True  # CLI success
        else:
            # CLI often fails for device encryption - fall back to GUI
            if output:
                log(f"CLI output: {output[:200]}...")
            log("CLI volume creation failed, opening GUI...")
            return create_veracrypt_volume_gui(vc_exe, device_path, password, keyfile_path, security_mode)
    except Exception as e:
        error(f"VeraCrypt volume creation failed: {e}")
        # Try GUI as last resort
        return create_veracrypt_volume_gui(vc_exe, device_path, password, keyfile_path, security_mode)


def create_veracrypt_volume_gui(
    vc_exe: Path,
    device_path: str,
    password: str,
    keyfile_path: Path | None = None,
    security_mode: str = SecurityMode.PW_ONLY.value,
    session_seed_gpg_path: Path | None = None,
    session_salt_b64: str | None = None,
    session_hkdf_info: str | None = None,
) -> bool:
    f"""
    Guide user through VeraCrypt GUI volume creation.

    Uses render_vc_guide() for a scannable, copy-friendly format.
    Per AGENT_ARCHITECTURE.md Section 2.4: Manual steps acknowledged, not hidden.

    SECURITY (per AGENT_ARCHITECTURE.md Section 7 & 10.3):
    - Secrets are NOT printed to terminal
    - Use {UserInputs.COPY_PASSWORD}/{UserInputs.COPY_KEY_FILE}/{UserInputs.COPY_DEVICE_PATH} commands to copy on demand
    - Clipboard-first with auto-clear timeout

    P0-1 FIX: Returns bool explicitly:
    - True (MANUAL_DONE): User completed volume creation (typed YES)
    - False (MANUAL_ABORT): User aborted or error occurred (typed NO or exception)

    Args:
        vc_exe: Path to VeraCrypt executable
        device_path: Device path for volume creation
        password: Volume password (or pre-derived for GPG_PW_ONLY)
        keyfile_path: Optional keyfile path
        security_mode: Security mode (PW_ONLY, PW_KEYFILE, etc.)
        session_seed_gpg_path: Optional temp {FileNames.SEED_GPG} path (setup workflow)
        session_salt_b64: Optional salt for HKDF (setup workflow)
        session_hkdf_info: Optional HKDF info string (setup workflow)

    Returns:
        bool: True if user completed volume creation (MANUAL_DONE),
              False if user aborted or error occurred (MANUAL_ABORT)
    """
    log("[DEBUG] create_veracrypt_volume_gui: ENTERED")

    # Import SecretProvider for on-demand secret access
    global _SECRETS_AVAILABLE
    try:
        from core.secrets import ClipboardUnavailableError, SecretProvider

        _SECRETS_AVAILABLE = True
    except ImportError:
        _SECRETS_AVAILABLE = False

    # Build copyable values block - NEVER include secrets
    # Device path is masked to prevent shoulder-surfing; use CDP to copy
    device_display = device_path[:20] + "..." if len(device_path) > 20 else device_path
    copy_values = {
        "Device": f"{device_display} (use {UserInputs.COPY_DEVICE_PATH} to copy full path)",
    }

    # DO NOT add password to copy_values - use CPW command instead
    # DO NOT add keyfile path - use CKF command instead

    # Build warnings
    warnings = [
        "All existing data on this device will be PERMANENTLY ERASED!",
    ]
    if security_mode == SecurityMode.PW_GPG_KEYFILE.value and not keyfile_path:
        warnings.append("Do NOT add a keyfile in VeraCrypt! YubiKey protection added later.")

    # Build steps list
    steps = [
        "Click 'Create Volume'",
        "Select 'Encrypt a non-system partition/drive' -> Next",
        "Select 'Standard VeraCrypt volume' -> Next",
        {
            "text": f"Click 'Select Device' and choose your device (type {UserInputs.COPY_DEVICE_PATH} to copy path):",
            "substeps": [f"Type {UserInputs.COPY_DEVICE_PATH} below to copy device path to clipboard"],
        },
        {
            "text": "Select 'Create encrypted volume and format it'",
            "substeps": ["NOT 'Encrypt partition in place'!"],
        },
        f"Choose encryption: {CryptoParams.VERACRYPT_ENCRYPTION} and {CryptoParams.VERACRYPT_HASH} -> Next",
        "Verify the volume size is correct -> Next",
    ]

    # Password step - always via command, never printed
    if security_mode == SecurityMode.GPG_PW_ONLY.value:
        steps.append(
            {
                "text": f"Enter the password (type {UserInputs.COPY_PASSWORD} to copy to clipboard):",
                "substeps": [
                    f"Type {UserInputs.COPY_PASSWORD} below to copy the derived password",
                    "Paste it into VeraCrypt (Ctrl+V)",
                    "You'll need this password again during verification",
                ],
            }
        )
    else:
        pw_step = {"text": "Enter your password"}
        if keyfile_path:
            pw_step["substeps"] = [
                "Check 'Use keyfiles', then 'Keyfiles...'",
                "In the Context Menug, click 'Add Files...'",
                f"Type {UserInputs.COPY_KEY_FILE} to copy keyfile path, then paste in file browser and 'Open'.",
                "The Keyfile should now be listed.",
                "Confirm the Context Menu with 'OK'. -> Next",
            ]
        steps.append(pw_step)

    steps.extend(
        [
            "Select 'Yes' for large files support",
            "(relevant for the applied File System in the next step) -> Next",
            {
                "text": "Choose filesystem and format options:",
                "substeps": [
                    f"Filesystem: {CryptoParams.LAUNCHER_FILESYSTEM} ({CryptoParams.LAUNCHER_FILESYSTEM_CAPABILITIES})",
                    "Enable 'Quick Format' (faster, fine for new drives)",
                ],
            },
            "Move mouse randomly until the bar is full",
            "Click 'Format' and confirm the warning",
            "Wait for 'Format Complete' message, then click OK",
            "Exit VeraCrypt (setup will attempt automated mounting next)",
        ]
    )

    # Notes
    notes = [
        f"{CryptoParams.VERACRYPT_ENCRYPTION} with {CryptoParams.VERACRYPT_HASH} is recommended for security",
        f"{CryptoParams.VERACRYPT_FILESYSTEM} {CryptoParams.VERACRYPT_FILESYSTEM_CAPABILITIES}",
        "Setup will attempt automated mounting after creation",
        f"SECURITY: Secrets only copied on demand via {UserInputs.COPY_PASSWORD}/{UserInputs.COPY_KEY_FILE} commands",
    ]

    # Render the guide
    render_vc_guide(
        "MANUAL VERACRYPT VOLUME CREATION",
        steps,
        copy_values=copy_values,
        warnings=warnings,
        notes=notes,
    )

    # Print command reference
    print("\n  " + "=" * 60)
    print("  ON-DEMAND COPY COMMANDS (type anytime):")
    print(f"    {UserInputs.COPY_PASSWORD}  = Copy Password to clipboard")
    if keyfile_path:
        print(f"    {UserInputs.COPY_KEY_FILE}  = Copy Keyfile path to clipboard")
    print(f"    {UserInputs.COPY_DEVICE_PATH}  = Copy Device path to clipboard")
    print("")
    print("  SECURITY: Secrets are NOT printed. Use commands to copy.")
    print("  " + "=" * 60)

    # Create SecretProvider for on-demand access
    secrets_provider = None
    if _SECRETS_AVAILABLE:
        try:
            from core.secrets import SecretProvider

            # Build session overrides for setup workflow
            session_overrides = {}
            if security_mode == SecurityMode.GPG_PW_ONLY.value and session_seed_gpg_path:
                session_overrides[ConfigKeys.SEED_GPG_PATH] = str(session_seed_gpg_path)
                if session_salt_b64:
                    session_overrides[ConfigKeys.SALT_B64] = session_salt_b64
                if session_hkdf_info:
                    session_overrides[ConfigKeys.HKDF_INFO] = session_hkdf_info

            secrets_provider = SecretProvider(
                security_mode=SecurityMode(security_mode),
                volume_path=device_path,
                user_password=password if security_mode != SecurityMode.GPG_PW_ONLY.value else None,
                keyfile_plain_path=keyfile_path if security_mode == SecurityMode.PW_KEYFILE.value else None,
            )

            # Apply session overrides
            if session_overrides:
                if ConfigKeys.SEED_GPG_PATH in session_overrides:
                    secrets_provider.seed_gpg_path = Path(session_overrides[ConfigKeys.SEED_GPG_PATH])
                if ConfigKeys.SALT_B64 in session_overrides:
                    secrets_provider.salt_b64 = session_overrides[ConfigKeys.SALT_B64]
                if ConfigKeys.HKDF_INFO in session_overrides:
                    secrets_provider.hkdf_info = session_overrides[ConfigKeys.HKDF_INFO]

            # For GPG_PW_ONLY, DON'T store pre-derived password (violates decrypt-on-demand)
            # The SecretProvider will derive it when CPW is called
        except Exception as e:
            log(f"Warning: Could not create SecretProvider: {e}")

    input("\n  Press Enter to open VeraCrypt...")

    try:
        # TODO 0: Flow trace at GUI launch
        setup_flow_trace("MANUAL_GUI_ENTER", {"device_path": device_path, "security_mode": security_mode})

        # On Windows: CREATE_NO_WINDOW prevents unexpected GUI popups from capability probes
        if "windows" in platform.system().lower():
            subprocess.Popen([str(vc_exe)], creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen([str(vc_exe)])
        print("\n  [OK] VeraCrypt GUI opened. Complete the volume creation.")
        print("     Setup will attempt automated mounting afterward.")

        # Command loop for on-demand secret access
        setup_flow_trace("MANUAL_LOOP_ENTER", {"has_secrets_provider": secrets_provider is not None})
        log(
            f"[DEBUG] Entered command loop ({UserInputs.COPY_PASSWORD}/{UserInputs.COPY_KEY_FILE}/{UserInputs.COPY_DEVICE_PATH}/{UserInputs.YES}/{UserInputs.NO})"
        )
        print(
            f"\n  Commands: {UserInputs.COPY_PASSWORD} (password), {UserInputs.COPY_KEY_FILE} (keyfile), {UserInputs.COPY_DEVICE_PATH} (device path), {UserInputs.YES} (done), {UserInputs.NO} (abort)"
        )
        while True:
            response = input("  > ").strip().upper()
            setup_flow_trace("MANUAL_LOOP_CMD", {"cmd": response})
            log(f"[DEBUG] Command received: {response}")

            # Handle on-demand secret commands
            if response in {UserInputs.COPY_PASSWORD, UserInputs.COPY_KEY_FILE, UserInputs.COPY_DEVICE_PATH}:
                if secrets_provider:
                    secrets_provider.handle_command(response)
                elif response == UserInputs.COPY_PASSWORD:
                    # Fallback: use clipboard directly (NON-BLOCKING in command loop)
                    if clipboard_available():
                        password_to_clipboard_with_timeout(password, timeout_seconds=120, wait_for_enter=False)
                    else:
                        print("  [!] Clipboard unavailable. Cannot copy password.")
                        print(f"      Type {UserInputs.PRINT_PASSWORD} if you must see the password (not recommended).")
                elif response == UserInputs.COPY_DEVICE_PATH:
                    if clipboard_available():
                        copy_to_clipboard(device_path)
                        print(f"  [OK] Device path copied: {device_path}")
                    else:
                        print(f"  Device path: {device_path}")
                elif response == UserInputs.COPY_KEY_FILE:
                    if keyfile_path:
                        if clipboard_available():
                            copy_to_clipboard(str(keyfile_path))
                            print(f"  [OK] Keyfile path copied: {keyfile_path}")
                        else:
                            print(f"  Keyfile path: {keyfile_path}")
                    else:
                        print("  [!] No keyfile configured for this mode.")
                continue

            # Handle PRINTPW for clipboard-unavailable fallback (explicit opt-in)
            if response == UserInputs.PRINT_PASSWORD:
                print("\n  " + "!" * 60)
                print("  WARNING: Printing password to terminal (shoulder-surfing risk)")
                print("  " + "!" * 60)
                confirm = input(f"  Type '{UserInputs.CONFIRM}' to confirm: ").strip()
                if confirm == UserInputs.CONFIRM:
                    print(f"\n  Password: {password}\n")
                else:
                    print("  Cancelled - password not shown.")
                continue

            # Handle completion
            if response == UserInputs.YES:
                setup_flow_trace("MANUAL_LOOP_YES", {"returning": True})
                log(f"[DEBUG] {UserInputs.YES} received - exiting command loop")
                # Clean up secrets (fire-and-forget, exceptions must NOT affect return)
                if secrets_provider:
                    try:
                        secrets_provider.cleanup()
                        log("[DEBUG] Cleanup complete")
                    except Exception as cleanup_err:
                        log(f"[DEBUG] Cleanup error (non-fatal): {cleanup_err}")
                setup_flow_trace("MANUAL_LOOP_EXIT", {"result": "MANUAL_DONE"})
                log("[DEBUG] Returning MANUAL_DONE (True)")
                return True
            elif response == UserInputs.NO:
                setup_flow_trace("MANUAL_LOOP_NO", {"returning": False})
                log(f"[DEBUG] {UserInputs.NO} received - exiting command loop")
                if secrets_provider:
                    try:
                        secrets_provider.cleanup()
                        log("[DEBUG] Cleanup complete")
                    except Exception as cleanup_err:
                        log(f"[DEBUG] Cleanup error (non-fatal): {cleanup_err}")
                log("[DEBUG] Returning MANUAL_ABORT (False)")
                return False

            print(
                f"  Commands: {UserInputs.COPY_PASSWORD} (password), {UserInputs.COPY_KEY_FILE} (keyfile), {UserInputs.COPY_DEVICE_PATH} (device path), {UserInputs.YES} (done), {UserInputs.NO} (abort)"
            )
    except Exception as e:
        if secrets_provider:
            secrets_provider.cleanup()
        error(f"Failed to open VeraCrypt: {e}")
        return False


def create_veracrypt_volume_unix(device: str, password: str, keyfile_path: Path | None = None) -> bool:
    """Create a VeraCrypt volume on Linux/macOS."""
    log(f"Creating VeraCrypt volume on {device}...")

    args = [
        "veracrypt",
        "--text",
        "--create",
        device,
        "--password",
        password,
        "--encryption",
        "AES",
        "--hash",
        "SHA-512",
        "--filesystem",
        "exfat",
        "--quick",
        "--non-interactive",
    ]

    if keyfile_path:
        args.extend(["--keyfiles", str(keyfile_path)])

    try:
        run_cmd(args, check=True, timeout=600)
        log("[OK] VeraCrypt volume created successfully")
        return True
    except Exception as e:
        error(f"VeraCrypt volume creation failed: {e}")
        return False


def try_auto_mount_volume(
    vc_exe: Path,
    device: str,
    password: str,
    keyfile_path: Path | None,
    disk_num: int,
    preferred_letter: str = (
        Defaults.WINDOWS_MOUNT_LETTER if "windows" in platform.system().lower() else Defaults.UNIX_MOUNT_POINT
    ),
    security_mode: str = None,
) -> tuple[bool, str | None]:
    """
    Attempt automated CLI mounting of a newly created volume.

    This is the PRIMARY method for mounting after volume creation.
    Manual GUI mounting is only a BACKUP if this fails.

    IMPORTANT: This function delegates to verify_mount_operation() which is
    the SSOT for all mount operations. This ensures consistent mount logic
    and diagnostic logging across all setup phases.

    Mount-letter lifecycle:
    1. preferred_letter is a CANDIDATE, not confirmed
    2. verify_mount_operation() handles volume resolution and mount
    3. Only the CONFIRMED letter from MountVerificationResult is returned

    Args:
        vc_exe: Path to VeraCrypt executable
        device: Volume device path
        password: Volume password
        keyfile_path: Path to keyfile (if used)
        disk_num: Disk number for volume resolution on Windows
        preferred_letter: CANDIDATE drive letter (Windows only)
        security_mode: SecurityMode value (e.g. GPG_PW_ONLY) - if None, inferred from keyfile

    Returns:
        Tuple of (success: bool, confirmed_mount_letter: str | None)
        - success: True if volume was mounted successfully
        - confirmed_mount_letter: CONFIRMED letter if mounted on Windows, None on Unix or if failed
    """
    log("Attempting automated volume mount via verify_mount_operation()...")

    # Use provided security mode, or infer from keyfile presence (legacy behavior)
    if security_mode is None:
        security_mode = SecurityMode.PW_KEYFILE.value if keyfile_path else SecurityMode.PW_ONLY.value

    # Use the SSOT verify_mount_operation for consistent mount logic
    result = verify_mount_operation(
        vc_exe=vc_exe,
        payload_device=device,
        password=password,
        keyfile_path=keyfile_path,
        security_mode=security_mode,
        disk_number=disk_num,
        preferred_letter=preferred_letter,
        log_diagnostics=True,  # Always log for traceability
    )

    if result.success:
        log(f"[OK] Mount verified successfully at {result.mount_point}")
        return (True, result.mount_point)
    else:
        log(f"Mount verification failed: {result.error_message}")
        # Log detailed diagnostic info
        if result.diagnostic_info:
            log("Diagnostic snapshot available - see logs for details")
        return (False, None)


def prompt_manual_gui_mount(
    preferred_letter: str = (
        Defaults.WINDOWS_MOUNT_LETTER if "windows" in platform.system().lower() else Defaults.UNIX_MOUNT_POINT
    ),
    password: str = None,
    security_mode: str = None,
    vc_exe: Path = None,
    volume_path: str = None,
    session_overrides: dict = None,
) -> str | None:
    """
    Fallback: Prompt user to mount volume manually via VeraCrypt GUI.
    Only called when automated mounting fails.

    SECURITY (per AGENT_ARCHITECTURE.md Section 7 & 10.3):
    - Secrets are NOT printed to terminal
    - Use CPW command to copy password on demand
    - Clipboard-first with auto-clear timeout
    - GPG_PW_ONLY mode MUST use SecretProvider for hardware key enforcement

    Args:
        preferred_letter: Suggested drive letter for mounting
        password: Volume password (for non-GPG modes; ignored for GPG_PW_ONLY)
        vc_exe: Path to VeraCrypt executable (to auto-start GUI)
        security_mode: Security mode to provide appropriate instructions
        volume_path: Path to the volume (for SecretProvider)
        session_overrides: Session overrides for SecretProvider (GPG_PW_ONLY)

    Returns:
        Mount letter/path if user successfully mounts, None if user declines or fails.
    """
    print("\n" + "=" * 70)
    print("  AUTOMATED MOUNT FAILED")
    print("=" * 70)
    print("\n  The system could not mount the volume automatically.")
    print("  This can happen if:")
    print("    - The volume is on a device that requires special resolution")
    print("    - VeraCrypt CLI has compatibility issues")
    print("\n  Would you like to mount the volume manually via VeraCrypt GUI?")
    print("  (Required for setup to complete icon/label and verification steps)")
    print()

    while True:
        choice = (
            input(f"  Mount manually via GUI? [{UserInputs.YES.lower()}/{UserInputs.NO.lower()}]: ").strip().lower()
        )
        if choice == UserInputs.YES.lower():
            break
        elif choice == UserInputs.NO.lower():
            warn("User declined manual mounting - setup may be incomplete")
            return None
        print(f"  Please type '{UserInputs.YES.lower()}' or '{UserInputs.NO.lower()}'")

    # Auto-start VeraCrypt GUI if available
    system = get_platform()
    if "windows" in system and vc_exe and vc_exe.exists():
        try:
            print("\n  Starting VeraCrypt GUI...")
            # Start VeraCrypt GUI without waiting (non-blocking)
            subprocess.Popen(
                [str(vc_exe)], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            time.sleep(1)  # Brief pause to let GUI start
            print("  VeraCrypt GUI started.")
        except Exception as e:
            log(f"Could not auto-start VeraCrypt: {e}")
            print("  [X] Could not auto-start VeraCrypt. Please open it manually.")

    # Print command reference for on-demand secret access
    print("\n  " + "=" * 60)
    print("  ON-DEMAND COPY COMMANDS:")
    if security_mode == SecurityMode.GPG_PW_ONLY.value:
        print(f"    {UserInputs.COPY_PASSWORD}  = Copy Password to clipboard (GPG-derived)")
    else:
        print(f"    {UserInputs.COPY_PASSWORD}  = Copy Password to clipboard")
    print("")
    print("  SECURITY: Secrets are NOT printed. Use commands to copy.")
    print("  " + "=" * 60)

    # Show GUI mount instructions
    print("\n  MANUAL MOUNT INSTRUCTIONS:")
    print("  1. Open VeraCrypt")
    print(f"  2. Select drive letter {preferred_letter}:")
    print("  3. Click 'Select Device' and choose your volume")
    print("  4. Type CPW below to copy password, then paste in VeraCrypt")
    print("  5. Click 'Mount'")
    print()

    # Command loop for on-demand secret access
    log(f"[DEBUG] Entered manual mount command loop ({UserInputs.COPY_PASSWORD}/{UserInputs.YES}/{UserInputs.NO})")
    print(
        f"  Commands: {UserInputs.COPY_PASSWORD} (password), {UserInputs.YES} (mount succeeded), {UserInputs.NO} (failed/cancel)"
    )

    # Create SecretProvider for GPG_PW_ONLY mode (BUG-20251218-006 fix)
    # This enforces hardware key presence before decrypting secrets
    secrets_provider = None
    if security_mode == SecurityMode.GPG_PW_ONLY.value and _SECRETS_AVAILABLE:
        try:
            from core.secrets import SecretProvider

            secrets_provider = SecretProvider(
                security_mode=SecurityMode(security_mode),
                volume_path=volume_path or "",
                user_password=None,  # GPG_PW_ONLY uses derived password
            )
            # Apply session overrides (seed_gpg_path, salt_b64, hkdf_info)
            if session_overrides:
                if ConfigKeys.SEED_GPG_PATH in session_overrides:
                    secrets_provider.seed_gpg_path = Path(session_overrides[ConfigKeys.SEED_GPG_PATH])
                if ConfigKeys.SALT_B64 in session_overrides:
                    secrets_provider.salt_b64 = session_overrides[ConfigKeys.SALT_B64]
                if ConfigKeys.HKDF_INFO in session_overrides:
                    secrets_provider.hkdf_info = session_overrides[ConfigKeys.HKDF_INFO]
            log("[DEBUG] SecretProvider created for GPG_PW_ONLY mode")
        except Exception as e:
            log(f"Warning: Could not create SecretProvider: {e}")
            secrets_provider = None

    while True:
        response = input("  > ").strip().upper()
        log(f"[DEBUG] Command received: {response}")

        # Handle CPW command (NON-BLOCKING in command loop)
        # BUG-20251218-006: GPG_PW_ONLY mode MUST use SecretProvider for hardware key enforcement
        if response == UserInputs.COPY_PASSWORD:
            if secrets_provider:
                # GPG_PW_ONLY: Use SecretProvider (enforces YubiKey presence)
                secrets_provider.handle_command(response)
            elif password:
                # Non-GPG modes: Use password directly
                if clipboard_available():
                    password_to_clipboard_with_timeout(password, timeout_seconds=120, wait_for_enter=False)
                else:
                    print("  [!] Clipboard unavailable.")
                    print(f"      Type {UserInputs.PRINT_PASSWORD} if you must see the password (not recommended).")
            else:
                print("  [!] No password available.")
            continue

        # Handle PRINTPW for clipboard-unavailable fallback (explicit opt-in)
        # NOT available for GPG_PW_ONLY mode (must use SecretProvider with hardware key)
        if response == UserInputs.PRINT_PASSWORD:
            if secrets_provider:
                print(f"  [!] {UserInputs.PRINT_PASSWORD} not available in {SecurityMode(security_mode)} mode.")
                print(
                    f"      Use {UserInputs.COPY_PASSWORD} to copy password (might require hardware key for authentication)."
                )
                continue
            print("\n  " + "!" * 60)
            print("  WARNING: Printing password to terminal (shoulder-surfing risk)")
            print("  " + "!" * 60)
            confirm = input(f"  Type '{UserInputs.CONFIRM}' to confirm: ").strip()
            if confirm == UserInputs.CONFIRM and password:
                print(f"\n  Password: {password}\n")
            else:
                print("  Cancelled - password not shown.")
            continue

        # Handle completion
        if response == UserInputs.YES:
            log(f"[DEBUG] {UserInputs.YES} received in manual mount loop - prompting for drive letter")
            # Clean up SecretProvider
            if secrets_provider:
                try:
                    secrets_provider.cleanup()
                except Exception:
                    pass
            system = get_platform()
            if "windows" in system:
                while True:
                    mount_letter = (
                        input(f"\n  What drive letter did you mount to? (e.g., '{preferred_letter}'): ").strip().upper()
                    )
                    if mount_letter and len(mount_letter) == 1 and mount_letter.isalpha():
                        # Verify it exists
                        if Path(f"{mount_letter}:\\").exists():
                            log(f"[DEBUG] Drive letter {mount_letter}: confirmed - exiting manual mount loop")
                            log(f"[OK] User confirmed manual mount to {mount_letter}:")
                            clear_clipboard()  # Clean up
                            return mount_letter
                        else:
                            print(f"  Drive {mount_letter}: does not appear to be accessible. Try again.")
                    else:
                        print("  Please enter a single drive letter (A-Z)")
            else:
                mount_path = input("\n  What path did you mount to?: ").strip()
                if mount_path and Path(mount_path).exists():
                    log(f"[OK] User confirmed manual mount to {mount_path}")
                    clear_clipboard()  # Clean up
                    return mount_path
                else:
                    print("  Mount path does not exist. Try again.")
            continue

        if response == UserInputs.NO:
            warn("User failed to mount volume manually")
            # Clean up SecretProvider
            if secrets_provider:
                try:
                    secrets_provider.cleanup()
                except Exception:
                    pass
            clear_clipboard()  # Clean up
            return None

        print(
            f"  Commands: {UserInputs.COPY_PASSWORD} (password), {UserInputs.YES} (mount succeeded), {UserInputs.NO} (failed/cancel)"
        )


# =============================================================================
# Keyfile & Encryption
# =============================================================================


def generate_keyfile() -> bytes:
    """Generate random keyfile data."""
    return secrets.token_bytes(CryptoParams.KEYFILE_SIZE)


def encrypt_keyfile_to_yubikeys(keyfile_data: bytes, fingerprints: list[str], output_path: Path) -> bool:
    """Encrypt keyfile to multiple YubiKey recipients."""
    log("Encrypting keyfile to YubiKeys...")
    log("(You may be prompted for YubiKey PIN/touch)")

    args = ["gpg", "--encrypt", "--armor", "--output", str(output_path)]
    for fpr in fingerprints:
        args.extend(["--recipient", fpr])

    try:
        # GPG reads from stdin for encryption
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(input=keyfile_data)

        if proc.returncode != 0:
            raise RuntimeError(stderr.decode())

        log(f"[OK] Encrypted keyfile: {output_path}")
        return True
    except Exception as e:
        error(f"Keyfile encryption failed: {e}")
        return False


def set_drive_icon(launcher_path: Path, drive_letter: str, icon_type: str = "launcher") -> None:
    """Set a custom drive icon using desktop.ini (requires System attribute).

    Args:
        launcher_path: Root path of the drive to set icon for
        drive_letter: Drive letter (e.g., "F")
        icon_type: "launcher" for KeyDrive launcher partition (LOGO_key.ico fallback to LOGO_main.ico)
                   "veracrypt" for VeraCrypt volume (LOGO_drive.ico fallback to LOGO_mounted.ico)
    """
    if not _is_windows():
        return  # Only for Windows

    try:
        # Create desktop.ini for custom drive icon
        desktop_ini = launcher_path / "desktop.ini"

        # Always reference deployed static directory (.smartdrive/static) for launcher drive icon
        deployed_static = Paths.smartdrive_dir(launcher_path) / Paths.STATIC_SUBDIR

        if icon_type == "veracrypt":
            preferred = FileNames.ICON_VERACRYPT_VOLUME
            fallback = FileNames.ICON_MOUNTED
        else:
            preferred = FileNames.ICON_LAUNCHER_DRIVE
            fallback = FileNames.ICON_MAIN

        icon_filename = preferred if (deployed_static / preferred).exists() else fallback

        icon_rel = Path(Paths.SMARTDRIVE_DIR_NAME) / Paths.STATIC_SUBDIR / icon_filename
        icon_path = icon_rel.as_posix().replace("/", "\\")

        ini_content = f"""[.ShellClassInfo]
IconFile={icon_path}
IconIndex=0

[ViewState]
Mode=
Vid=
FolderType=Generic
"""

        with open(desktop_ini, "w", encoding="utf-8") as f:
            f.write(ini_content)

        # CRITICAL: Set required attributes for drive icon to work
        # desktop.ini must be System+Hidden, folder must be System
        try:
            windows_set_attributes(desktop_ini, hidden=True, system=True, timeout_s=float(Limits.PROCESS_CHECK_TIMEOUT))
            windows_set_attributes(launcher_path, system=True, timeout_s=float(Limits.PROCESS_CHECK_TIMEOUT))
            windows_refresh_explorer(timeout_s=float(Limits.PROCESS_CHECK_TIMEOUT))
            log(f"[OK] Created desktop.ini with System attributes for {drive_letter}: ({icon_type} icon)")
        except Exception as attr_err:
            log(f"[OK] Created desktop.ini for {drive_letter}: (attributes may need manual setup)")
            warn(f"Could not set attributes: {attr_err}")
    except Exception as e:
        warn(f"Could not create desktop.ini: {e}")


def set_drive_label(launcher_path: Path, label: str) -> None:
    """Set the Windows volume label for the launcher drive (best-effort).

    Uses SetVolumeLabelW to avoid shelling out. No-op on non-Windows.
    """
    if not _is_windows():
        return

    drive_root = launcher_path.drive
    if not drive_root:
        warn("Could not set drive label: launcher path missing drive root")
        return

    drive_spec = drive_root if drive_root.endswith("\\") else f"{drive_root}\\"
    try:
        kernel32 = ctypes.windll.kernel32
        success = kernel32.SetVolumeLabelW(ctypes.c_wchar_p(drive_spec), ctypes.c_wchar_p(label))
        if success == 0:
            err = ctypes.GetLastError()
            warn(f"Could not set drive label (error {err})")
        else:
            log(f"[OK] Set drive label to {label}")
    except Exception as e:
        warn(f"Could not set drive label: {e}")


def _write_macos_command_launcher(launcher_path: Path) -> Path:
    """Create a macOS-clickable .command launcher at drive root.

    Note: On Windows, chmod may not be supported on the target filesystem; creation is still useful.
    """
    command_name = f"{Branding.PRODUCT_NAME}.command"
    command_path = launcher_path / command_name
    sh_name = FileNames.SH_LAUNCHER

    content = "#!/bin/bash\n" 'cd "$(dirname "$0")"\n' f"chmod +x './{sh_name}' 2>/dev/null || true\n" f"./{sh_name}\n"
    command_path.write_text(content, encoding="utf-8", newline="\n")
    return command_path


def _ensure_clean_root_entrypoints(launcher_path: Path, *, repo_root: Path, target_scripts: Path) -> None:
    """Enforce deployed root structure: only OS entry points at drive root.

    Root files after this step:
    - Windows: <Product>.lnk
    - Linux: {FileNames.SH_LAUNCHER}
    - macOS: <Product>.command
    """
    # Ensure .smartdrive is hidden on Windows (dot-prefix is not hidden on Windows)
    smartdrive_dir = Paths.smartdrive_dir(launcher_path)
    if _is_windows() and smartdrive_dir.exists():
        windows_set_attributes(smartdrive_dir, hidden=True)

    # Linux/macOS entrypoint: prefer repo's canonical shell launcher
    sh_src = repo_root / FileNames.SH_LAUNCHER
    sh_dst = launcher_path / FileNames.SH_LAUNCHER
    if sh_src.exists():
        shutil.copy2(sh_src, sh_dst)
    else:
        # Minimal fallback - construct path from SSOT constants
        gui_path = f"{Paths.SMARTDRIVE_DIR_NAME}/{Paths.SCRIPTS_SUBDIR}/gui.py"
        sh_dst.write_text(
            f"#!/bin/bash\n" f'cd "$(dirname "$0")"\n' f"python3 {gui_path}\n",
            encoding="utf-8",
            newline="\n",
        )

    # macOS clickable entrypoint
    _write_macos_command_launcher(launcher_path)

    # Windows entrypoint: create .lnk (taskbar icon uses shortcut + exe icon)
    if _is_windows():
        shortcut_name = Path(FileNames.BAT_LAUNCHER).with_suffix(".lnk").name
        shortcut_path = launcher_path / shortcut_name

        icon_path = Paths.icon_main(launcher_path)

        exe_target = target_scripts / FileNames.GUI_EXE
        if exe_target.exists():
            windows_create_shortcut(
                shortcut_path=shortcut_path,
                target_path=exe_target,
                working_dir=launcher_path,
                icon_path=icon_path,
                description=f"{Branding.PRODUCT_NAME} (GUI)",
            )
        else:
            # Best-effort fallback (non-portable): bind to current Python
            pythonw = shutil.which("pythonw")
            python = shutil.which("python")
            python_exe = Path(pythonw or python) if (pythonw or python) else None
            if python_exe:
                launcher_script = target_scripts / "gui_launcher.py"
                windows_create_shortcut(
                    shortcut_path=shortcut_path,
                    target_path=python_exe,
                    arguments=f'"{launcher_script}"',
                    working_dir=launcher_path,
                    icon_path=icon_path,
                    description=f"{Branding.PRODUCT_NAME} (Python)",
                )

    # Remove legacy root artifacts (keep only new entrypoints)
    legacy_root_files = [
        Path(FileNames.BAT_LAUNCHER),
        Path(FileNames.GUI_BAT_LAUNCHER),
        Path(FileNames.VBS_LAUNCHER),
        Path(FileNames.README),
        Path(FileNames.GUI_README),
        Path(FileNames.README_PDF),
        Path(FileNames.GUI_README_PDF),
        Path(FileNames.GUI_EXE),
        Path(FileNames.GUI_BAT_LAUNCHER).with_suffix(".lnk"),
    ]
    # Also remove any legacy Windows lnk that matches the old bat name
    legacy_root_files.append(Path(FileNames.BAT_LAUNCHER).with_suffix(".lnk"))

    for rel in legacy_root_files:
        candidate = launcher_path / rel
        # Preserve the new Windows shortcut if it matches the same name
        if _is_windows() and candidate.name == Path(FileNames.BAT_LAUNCHER).with_suffix(".lnk").name:
            continue
        try:
            if candidate.exists() and candidate.is_file():
                candidate.unlink()
        except Exception:
            pass


# =============================================================================
# Script Deployment
# =============================================================================


# FIRST DEPLOY FUNCTION (LEGACY - uses flat structure, being phased out)
def deploy_scripts(launcher_path: Path, payload_device: str, encrypted_keyfile: Path, mount_letter: str = "V") -> bool:
    """
    Copy scripts and create config on KeyDrive partition.

    LEGACY: This function uses the old flat structure. Use deploy_scripts_extended instead.
    """
    log(f"Deploying scripts to {Branding.PRODUCT_NAME} partition...")

    scripts_dir = Path(__file__).resolve().parent
    smartdrive_root = scripts_dir.parent  # .smartdrive/
    repo_root = smartdrive_root.parent  # repo root for assets

    target_scripts = launcher_path / Paths.SMARTDRIVE_DIR_NAME / Paths.SCRIPTS_SUBDIR
    target_keys = launcher_path / Paths.KEYS_SUBDIR

    # Create directories
    target_scripts.mkdir(parents=True, exist_ok=True)
    target_keys.mkdir(parents=True, exist_ok=True)

    # Copy scripts from .smartdrive/scripts/
    scripts_to_copy = FileNames.COPIED_SCRIPTS_FOR_DEPLOYMENT
    for script in scripts_to_copy:
        src = scripts_dir / script
        if src.exists():
            shutil.copy2(src, target_scripts / script)
            log(f"  Copied {script}")

    # Copy constants.py from repo root to scripts directory
    constants_src = repo_root / "constants.py"
    if constants_src.exists():
        shutil.copy2(constants_src, target_scripts / "constants.py")
        log("  Copied constants.py")

    # Copy variables.py from repo root to scripts directory
    variables_src = repo_root / FileNames.VARIABLES_PY
    if variables_src.exists():
        shutil.copy2(variables_src, target_scripts / FileNames.VARIABLES_PY)
        log("  Copied variables.py")

    # Copy static assets to .smartdrive/static/ (deployed structure - same as update.py)
    # BUG-20251221-041 FIX: static/ is inside .smartdrive/, not at repo root
    static_dir = smartdrive_root / Paths.STATIC_SUBDIR  # .smartdrive/static/
    target_static = launcher_path / Paths.SMARTDRIVE_DIR_NAME / Paths.STATIC_SUBDIR
    if static_dir.exists():
        target_static.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(static_dir, target_static, dirs_exist_ok=True)
        static_files = list(target_static.rglob("*"))
        file_count = sum(1 for f in static_files if f.is_file())
        log(f"  Copied static assets to .smartdrive/static/ ({file_count} files)")
    else:
        warn(f"  Static directory not found at {static_dir}")

    # Copy GUI executable into scripts directory (NOT drive root)
    gui_exe_candidates = [
        repo_root / "dist" / GUI_EXE_NAME,
        repo_root / GUI_EXE_NAME,
    ]
    for candidate in gui_exe_candidates:
        if candidate.exists():
            shutil.copy2(candidate, target_scripts / GUI_EXE_NAME)
            log(f"  Copied {GUI_EXE_NAME} to scripts/ (Windows GUI executable)")
            break

    # Copy docs into .smartdrive/docs/ (drive root must contain entrypoints only)
    docs_dir = Paths.smartdrive_dir(launcher_path) / Paths.DOCUMENTATION_SUBDIR
    docs_dir.mkdir(parents=True, exist_ok=True)
    readme_file = repo_root / README_NAME
    gui_readme_file = repo_root / GUI_README_NAME
    if readme_file.exists():
        shutil.copy2(readme_file, docs_dir / README_NAME)
        log(f"  Copied {README_NAME} to {docs_dir}")
        pdf_path = docs_dir / README_PDF_NAME
        if generate_pdf_from_markdown(readme_file, pdf_path):
            log(f"  Generated {README_PDF_NAME} (PDF documentation)")

    if gui_readme_file.exists():
        shutil.copy2(gui_readme_file, docs_dir / GUI_README_NAME)
        log(f"  Copied {GUI_README_NAME} to {docs_dir}")
        gui_pdf_path = docs_dir / GUI_README_PDF_NAME
        if generate_pdf_from_markdown(gui_readme_file, gui_pdf_path):
            log(f"  Generated {GUI_README_PDF_NAME} (PDF GUI documentation)")

    # Enforce clean root entrypoints
    _ensure_clean_root_entrypoints(launcher_path, repo_root=repo_root, target_scripts=target_scripts)

    # Copy encrypted keyfile
    shutil.copy2(encrypted_keyfile, target_keys / FileNames.KEYFILE_GPG)
    log(f"  Copied {FileNames.KEYFILE_GPG}")

    # Get current date for metadata
    from datetime import datetime

    setup_date = datetime.now().strftime("%Y-%m-%d")

    # Create config.json (atomic write for data integrity) using ConfigKeys (SSOT)
    # In legacy deploy, config goes at launcher_path root
    config = {
        ConfigKeys.SCHEMA_VERSION: 1,
        ConfigKeys.VERSION: VERSION,
        ConfigKeys.MODE: SecurityMode.PW_GPG_KEYFILE.value,  # Legacy deploy uses GPG keyfile mode
        ConfigKeys.SETUP_DATE: setup_date,
        ConfigKeys.LAST_PASSWORD_CHANGE: setup_date,
        ConfigKeys.ENCRYPTED_KEYFILE: str(Path(Paths.KEYS_SUBDIR) / FileNames.KEYFILE_GPG),
        ConfigKeys.WINDOWS: {
            ConfigKeys.VOLUME_PATH: payload_device,
            ConfigKeys.MOUNT_LETTER: mount_letter,
            ConfigKeys.VERACRYPT_PATH: "",
        },
        ConfigKeys.UNIX: {ConfigKeys.VOLUME_PATH: payload_device, ConfigKeys.MOUNT_POINT: "~/veradrive"},
    }

    config_path = launcher_path / FileNames.CONFIG_JSON
    write_config_atomic(config_path, config)
    log("  Created config.json (atomic write)")

    log("[OK] Scripts deployed successfully")
    return True


def deploy_scripts_extended(
    launcher_path: Path,
    payload_device: str,
    encrypted_keyfile: Path = None,
    plain_keyfile: Path = None,
    mount_letter: str = "V",
    use_keyfile: bool = True,
    use_gpg: bool = True,
    security_mode: str = SecurityMode.PW_ONLY.value,
    salt_b64: str = None,
    gpg_fingerprints: list = None,
    verification_overridden: bool = False,  # BUG-013: Track if user skipped verification
    device_info: dict = None,  # BUG-20251221-042: Store device details for recovery kit
) -> bool:
    """
    Copy scripts and create config on KeyDrive partition.
    Supports all security modes: password-only, plain keyfile, GPG-encrypted keyfile, GPG password-only.

    Args:
        gpg_fingerprints: List of GPG key fingerprints used for encryption (for keyfile or seed modes)

    New folder structure:
    LAUNCHER/
    ├── <Product>.lnk        (Windows)
    ├── keydrive.sh          (Linux)
    ├── <Product>.command    (macOS)
    └── .smartdrive/
        ├── scripts/
        ├── keys/
        ├── static/
        ├── docs/
        └── integrity/
    """
    log(f"Deploying scripts to {Branding.PRODUCT_NAME} partition...")

    scripts_dir = Path(__file__).resolve().parent
    smartdrive_root = scripts_dir.parent  # .smartdrive/

    # Determine repo root (parent of .smartdrive for repo assets like KeyDrive.bat)
    # In repo: repo/.smartdrive/scripts/ -> repo
    # On deployed drive: DRIVE:/.smartdrive/scripts/ -> DRIVE:/
    repo_root = smartdrive_root.parent

    # New folder structure: all data under .smartdrive
    target_smartdrive = launcher_path / Paths.SMARTDRIVE_DIR_NAME
    target_scripts = target_smartdrive / Paths.SCRIPTS_SUBDIR
    target_keys = target_smartdrive / Paths.KEYS_SUBDIR
    target_integrity = target_smartdrive / Paths.INTEGRITY_SUBDIR

    # Create directories
    target_scripts.mkdir(parents=True, exist_ok=True)
    target_keys.mkdir(parents=True, exist_ok=True)
    target_integrity.mkdir(parents=True, exist_ok=True)

    # Copy scripts - REQUIRED_SCRIPTS must be present for core functionality
    REQUIRED_SCRIPTS = FileNames.REQUIRED_SCRIPTS_FOR_DEPLOYMENT
    OPTIONAL_SCRIPTS = FileNames.OPTIONAL_SCRIPTS_FOR_DEPLOYMENT
    scripts_to_copy = REQUIRED_SCRIPTS + OPTIONAL_SCRIPTS

    missing_required = []
    for script in scripts_to_copy:
        src = scripts_dir / script
        if src.exists():
            shutil.copy2(src, target_scripts / script)
            log(f"  Copied {script}")
        elif script in REQUIRED_SCRIPTS:
            missing_required.append(script)
            warn(f"  MISSING REQUIRED: {script}")
        else:
            log(f"  Skipped {script} (not found, optional)")

    # Verify all required scripts were deployed
    if missing_required:
        error(f"Deployment failed: missing required scripts: {', '.join(missing_required)}")
        return False

    # Post-deployment verification: check files actually exist on target
    deployment_verified = True
    for script in REQUIRED_SCRIPTS:
        target_file = target_scripts / script
        if not target_file.exists():
            error(f"  Deployment verification failed: {script} not found at {target_file}")
            deployment_verified = False

    if not deployment_verified:
        error("Deployment verification failed - required scripts missing from target")
        return False

    # Copy core/ directory (SSOT modules) to smartdrive directory
    core_src = smartdrive_root / "core"
    target_core = target_smartdrive / "core"
    if core_src.exists() and core_src.is_dir():
        # Remove existing core dir if present to ensure clean copy
        if target_core.exists():
            shutil.rmtree(target_core)
        shutil.copytree(core_src, target_core)
        log("  Copied core/ (SSOT modules)")

        # Verify critical core files
        core_required = FileNames.REQUIRED_CORE_FILES
        for core_file in core_required:
            if not (target_core / core_file).exists():
                error(f"  Core module missing: {core_file}")
                return False
        log("  [OK] Core modules verified")
    else:
        error("Core directory not found - SSOT modules cannot be deployed")
        return False

    # Copy constants.py from repo root to scripts directory (legacy support)
    constants_src = repo_root / "constants.py"
    if constants_src.exists():
        shutil.copy2(constants_src, target_scripts / "constants.py")
        log("  Copied constants.py")

    # Copy variables.py from repo root to scripts directory
    variables_src = repo_root / FileNames.VARIABLES_PY
    if variables_src.exists():
        shutil.copy2(variables_src, target_scripts / FileNames.VARIABLES_PY)
        log("  Copied variables.py")

    # Copy static assets to .smartdrive/static/ (deployed structure - same as update.py)
    # BUG-20251221-041 FIX: static/ is inside .smartdrive/, not at repo root
    static_dir = smartdrive_root / Paths.STATIC_SUBDIR  # .smartdrive/static/
    target_static = launcher_path / Paths.SMARTDRIVE_DIR_NAME / Paths.STATIC_SUBDIR
    if static_dir.exists():
        target_static.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(static_dir, target_static, dirs_exist_ok=True)
        static_files = list(target_static.rglob("*"))
        file_count = sum(1 for f in static_files if f.is_file())
        log(f"  Copied static assets to {target_static} ({file_count} files)")
    else:
        warn(f"  Static directory not found at {static_dir}")

    # Copy GUI executable into .smartdrive/scripts/ (NOT drive root)
    gui_exe_candidates = [
        repo_root / "dist" / GUI_EXE_NAME,
        repo_root / GUI_EXE_NAME,
    ]
    for candidate in gui_exe_candidates:
        if candidate.exists():
            shutil.copy2(candidate, target_scripts / GUI_EXE_NAME)
            log(f"  Copied {GUI_EXE_NAME} to .smartdrive/scripts/ (Windows GUI executable)")
            break

    # Copy docs into .smartdrive/docs/ (drive root must contain entrypoints only)
    docs_dir = target_smartdrive / Paths.DOCUMENTATION_SUBDIR
    docs_dir.mkdir(parents=True, exist_ok=True)
    readme_file = repo_root / README_NAME
    gui_readme_file = repo_root / GUI_README_NAME
    if readme_file.exists():
        shutil.copy2(readme_file, docs_dir / README_NAME)
        log(f"  Copied {README_NAME} to {docs_dir}")
        pdf_path = docs_dir / README_PDF_NAME
        if generate_pdf_from_markdown(readme_file, pdf_path):
            log(f"  Generated {README_PDF_NAME} (PDF documentation)")

    if gui_readme_file.exists():
        shutil.copy2(gui_readme_file, docs_dir / GUI_README_NAME)
        log(f"  Copied {GUI_README_NAME} to {docs_dir}")
        gui_pdf_path = docs_dir / GUI_README_PDF_NAME
        if generate_pdf_from_markdown(gui_readme_file, gui_pdf_path):
            log(f"  Generated {GUI_README_PDF_NAME} (PDF GUI documentation)")

    # Enforce clean root entrypoints
    _ensure_clean_root_entrypoints(launcher_path, repo_root=repo_root, target_scripts=target_scripts)

    # Handle keyfile based on security mode
    keyfile_config = None

    if use_keyfile:
        if use_gpg and encrypted_keyfile:
            # GPG-encrypted keyfile
            shutil.copy2(encrypted_keyfile, target_keys / FileNames.KEYFILE_GPG)
            log(f"  Copied {FileNames.KEYFILE_GPG} (GPG-encrypted)")
            keyfile_config = str(Path(Paths.KEYS_SUBDIR) / FileNames.KEYFILE_GPG)
        elif plain_keyfile:
            # Plain keyfile (not encrypted)
            shutil.copy2(plain_keyfile, target_keys / FileNames.KEYFILE_PLAIN)
            log(f"  Copied {FileNames.KEYFILE_PLAIN} (plain keyfile)")
            keyfile_config = str(Path(Paths.KEYS_SUBDIR) / FileNames.KEYFILE_PLAIN)
    elif security_mode == SecurityMode.GPG_PW_ONLY.value and encrypted_keyfile:
        # GPG password-only mode - encrypted seed
        shutil.copy2(encrypted_keyfile, target_keys / FileNames.SEED_GPG)
        log(f"  Copied {FileNames.SEED_GPG} (GPG-encrypted seed)")
        keyfile_config = None  # No keyfile, password derived
    else:
        log("  No keyfile (password-only mode)")

    # Get current date for metadata
    from datetime import datetime

    setup_date = datetime.now().strftime("%Y-%m-%d")

    # Create config.json with metadata using ConfigKeys (SSOT)
    config = {
        ConfigKeys.SCHEMA_VERSION: 2,  # Increment for gpg_pw_only support
        ConfigKeys.VERSION: VERSION,
        ConfigKeys.DRIVE_NAME: None,  # User can set this later
        ConfigKeys.MODE: security_mode,  # pw_only, pw_keyfile, pw_gpg_keyfile, gpg_pw_only
        ConfigKeys.SETUP_DATE: setup_date,
        ConfigKeys.LAST_PASSWORD_CHANGE: setup_date,  # Initial setup counts as password set
        ConfigKeys.WINDOWS: {
            ConfigKeys.VOLUME_PATH: payload_device,
            ConfigKeys.MOUNT_LETTER: mount_letter,
            ConfigKeys.VERACRYPT_PATH: "",
        },
        ConfigKeys.UNIX: {ConfigKeys.VOLUME_PATH: payload_device, ConfigKeys.MOUNT_POINT: "~/veradrive"},
    }

    # Add mode-specific fields
    if security_mode == SecurityMode.GPG_PW_ONLY.value:
        config.update(
            {
                ConfigKeys.SEED_GPG_PATH: str(Path(Paths.KEYS_SUBDIR) / FileNames.SEED_GPG),
                ConfigKeys.KDF: CryptoParams.KDF_HKDF_SHA256,
                ConfigKeys.SALT_B64: salt_b64 or "",
                ConfigKeys.HKDF_INFO: CryptoParams.HKDF_INFO_DEFAULT,
                ConfigKeys.PW_ENCODING: CryptoParams.PW_ENCODING_DEFAULT,
            }
        )
        # Add GPG fingerprints for GPG-based modes
        if gpg_fingerprints:
            config[ConfigKeys.KEYFILE_FINGERPRINTS] = gpg_fingerprints
    elif keyfile_config:
        config[ConfigKeys.KEYFILE] = keyfile_config
        if use_gpg:
            config[ConfigKeys.ENCRYPTED_KEYFILE] = keyfile_config
            # Add GPG fingerprints for encrypted keyfile mode
            if gpg_fingerprints:
                config[ConfigKeys.KEYFILE_FINGERPRINTS] = gpg_fingerprints

    # BUG-013: Save verification_overridden flag to config
    config[ConfigKeys.VERIFICATION_OVERRIDDEN] = verification_overridden

    # BUG-20251221-042: Store device info for recovery kit display
    if device_info:
        config[ConfigKeys.DEVICE_INFO] = {
            ConfigKeys.DEVICE_NAME: device_info.get("name", "Unknown Device"),
            ConfigKeys.DEVICE_BUS: device_info.get("bus", "Unknown"),
            ConfigKeys.DEVICE_SIZE_GB: device_info.get("size_gb", 0),
            ConfigKeys.DEVICE_UNIQUE_ID: device_info.get("unique_id", ""),
            ConfigKeys.DEVICE_SERIAL: device_info.get("serial_number", ""),
            ConfigKeys.DEVICE_PARTITIONS: device_info.get("partitions", []),
            ConfigKeys.LAUNCHER_PARTITION: str(launcher_path.drive).rstrip(":\\") if launcher_path.drive else "",
        }
        log(f"  Stored device info: {device_info.get('name', 'Unknown')} ({device_info.get('bus', 'Unknown')})")

    # Config lives at .smartdrive/config.json, NOT .smartdrive/scripts/config.json
    # Atomic write for data integrity
    config_path = target_smartdrive / FileNames.CONFIG_JSON
    write_config_atomic(config_path, config)
    log("  Created config.json (atomic write)")

    log("[OK] Scripts deployed successfully")
    return True


def sign_deployed_scripts(launcher_path: Path, gpg_fingerprint: str = None) -> bool:
    """
    Sign deployed scripts with GPG for integrity verification.

    Args:
        launcher_path: Path to KeyDrive partition
        gpg_fingerprint: Optional specific GPG key to use for signing

    Returns:
        True if signing succeeded, False otherwise
    """
    import hashlib

    log("Signing scripts for integrity verification...")

    # New folder structure
    smartdrive_dir = launcher_path / Paths.SMARTDRIVE_DIR_NAME
    target_scripts = smartdrive_dir / Paths.SCRIPTS_SUBDIR
    target_integrity = smartdrive_dir / Paths.INTEGRITY_SUBDIR

    # Ensure integrity directory exists
    target_integrity.mkdir(parents=True, exist_ok=True)

    hash_file = target_integrity / FileNames.HASH_FILE
    sig_file = target_integrity / FileNames.SIGNATURE_FILE

    # Calculate hash of all scripts
    hash_obj = hashlib.sha256()
    scripts = sorted(FileNames.SIGNATURE_HASH_FILES)

    for script_name in scripts:
        script_path = target_scripts / script_name
        if script_path.exists():
            hash_obj.update(script_name.encode("utf-8"))
            with open(script_path, "rb") as f:
                hash_obj.update(f.read())

    script_hash = hash_obj.hexdigest()

    # Write hash file
    with open(hash_file, "w") as f:
        f.write(f"{script_hash}  scripts\n")
    log(f"  Created {hash_file.name}")

    # Sign with GPG
    gpg_cmd = ["gpg", "--detach-sign"]
    if gpg_fingerprint:
        # Use --local-user for explicit key selection (more reliable than --default-key)
        gpg_cmd.extend(["--local-user", gpg_fingerprint])
    gpg_cmd.append(str(hash_file))

    try:
        result = subprocess.run(gpg_cmd, capture_output=True, text=True)

        if result.returncode == 0 and sig_file.exists():
            log(f"  Created {sig_file.name}")
            log("[OK] Scripts signed successfully")
            return True
        else:
            warn(f"GPG signing failed: {result.stderr}")
            return False
    except Exception as e:
        warn(f"Could not sign scripts: {e}")
        return False


def run_post_deployment_tests(launcher_path: Path) -> bool:
    """
    Run the pytest test suite after deployment and display results.

    CHG-20251221-023: Post-setup/update test execution capability.

    Args:
        launcher_path: Path to the deployed KeyDrive partition

    Returns:
        True if all tests passed, False otherwise (informational only)
    """
    import shutil

    print("\n" + "=" * 70)
    print("  POST-DEPLOYMENT VERIFICATION TESTS")
    print("=" * 70 + "\n")

    # Check if pytest is available
    if not shutil.which("pytest") and not _check_pytest_importable():
        print("  [!] pytest is not installed.")
        print("      To enable test verification, install with: pip install pytest")
        print("      Skipping test execution.\n")
        return False

    # Determine tests directory
    smartdrive_dir = launcher_path / Paths.SMARTDRIVE_DIR_NAME
    tests_dir = smartdrive_dir / "tests"

    if not tests_dir.exists():
        # Fallback to repository tests if running from dev environment
        repo_tests = Path(__file__).parent.parent / "tests"
        if repo_tests.exists():
            tests_dir = repo_tests
        else:
            print("  [!] Tests directory not found.")
            print(f"      Expected: {tests_dir}")
            print("      Skipping test execution.\n")
            return False

    print(f"  Running tests from: {tests_dir}")
    print("  " + "-" * 66 + "\n")

    try:
        # Run pytest with verbose output, capturing return code
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(tests_dir), "-v", "--tb=short"],
            cwd=str(smartdrive_dir) if smartdrive_dir.exists() else str(tests_dir.parent),
            check=False,
        )

        print("\n  " + "-" * 66)
        if result.returncode == 0:
            print("  [OK] All tests passed!")
            return True
        elif result.returncode == 1:
            print("  [!] Some tests failed. Review output above.")
            return False
        elif result.returncode == 5:
            print("  [!] No tests were collected.")
            return False
        else:
            print(f"  [!] pytest exited with code {result.returncode}")
            return False

    except Exception as e:
        print(f"  [!] Could not run tests: {e}")
        return False


def _check_pytest_importable() -> bool:
    """Check if pytest can be imported."""
    try:
        import pytest  # noqa: F401

        return True
    except ImportError:
        return False


# =============================================================================
# Main Wizard
# =============================================================================


def print_banner():
    """Print welcome banner."""
    print("\n" + "=" * 70)
    print("  +" + "=" * 63 + "+")
    print(f"  |           {Branding.PRODUCT_NAME} Setup Wizard v{VERSION}                        |")
    print(f"  |   {Branding.PRODUCT_DESCRIPTION}           |")
    print("  +" + "=" * 63 + "+")
    print("=" * 70)


def print_phase(num: int, total: int, title: str, clear_screen: bool = True):
    """
    Print phase header with optional screen clear.

    CHG-20251218-002: Shows phase + [X/Y] + title format.
    """
    if clear_screen:
        clear_terminal()
    print("=" * 70)
    print(f"  {Branding.PRODUCT_NAME.upper()} SETUP")
    print(f"  [{num}/{total}] {title}")
    print("=" * 70)
    print()


# =============================================================================
# CHG-20251218-002: Paged Setup Implementation
# =============================================================================

TOTAL_SETUP_PAGES = 8
PHASE_NAMES = {
    1: "Drive Selection & Partitioning",
    2: "Security Configuration",
    3: "Hardware Key Verification",
    4: "Review & Confirm",
    5: "VeraCrypt Volume Creation",
    6: "Deployment & Testing",
    7: "Final Deployment",
    8: "Summary",
}


def run_phase_1_drive_selection(state: PagedSetupState) -> tuple:
    """
    Phase 1: Drive Selection

    CHG-20251218-002: Page 1/6 - START phase

    Returns: (success: bool, nav_choice: str)
    """
    state.current_log_phase = "drive_selection"  # CHG-20251219-001
    render_page_header(1, TOTAL_SETUP_PAGES, "DRIVE SELECTION", PHASE_NAMES[1])

    print("⏳ Please wait while available drives are loaded...")

    if "windows" in state.system:
        state.drives = get_drives_windows()
    else:
        state.drives = get_drives_unix()

    if not state.drives:
        error("No drives detected!")
        return False, "Q"

    selected = select_drive(state.drives, state.system)
    if not selected:
        log("Setup cancelled.")
        return False, "Q"

    state.selected_drive = selected

    # Persist target disk identity
    if "windows" in state.system:
        SetupState.set_target_disk(
            unique_id=selected.get("unique_id", ""),
            disk_number=selected.get("number"),
            name=selected.get("name", ""),
        )
        state.disk_number = selected.get("number", 0)
        state.drive_id = f"Disk {selected['number']}"
        state.drive_name = selected["name"]
        state.drive_size = selected["size_gb"]
    else:
        SetupState.set_target_disk(
            unique_id=selected.get("name", ""),
            disk_number=None,
            name=selected.get("model", selected.get("name", "")),
        )
        state.disk_number = 0
        state.drive_id = selected["name"]
        state.drive_name = selected.get("model", state.drive_id)
        state.drive_size = selected.get("size", "?")

    disk_label_num = state.disk_number + 1
    state.launcher_label = f"{PRODUCT_NAME}{disk_label_num}"

    print(f"\n[OK] Selected: {state.drive_id} - {state.drive_name} ({state.drive_size} GB)")

    # Navigation - can go back to cancel, can rerun to re-select
    nav = prompt_navigation(1, TOTAL_SETUP_PAGES, can_go_back=False, can_rerun=True)
    return True, nav


def run_phase_2_partition_size(state: PagedSetupState) -> tuple:
    """
    Phase 2a: Partition Size Configuration

    CHG-20251218-002: Part of Page 2/6 - SECURITY phase (split for granularity)

    Returns: (success: bool, nav_choice: str)
    """
    state.current_log_phase = "partition_size"  # CHG-20251219-001
    render_page_header(2, TOTAL_SETUP_PAGES, "PARTITION SIZE", PHASE_NAMES[2])

    print(f"  Selected Drive: {state.drive_id} - {state.drive_name}")
    print(f"  Drive Size: {state.drive_size} GB")
    print()

    print(f"{Branding.PRODUCT_NAME} partition size (scripts, ~{CryptoParams.LAUNCHER_PARTITION_SIZE_MB}MB recommended)")
    size_input = input(f"Enter size in MB [{CryptoParams.LAUNCHER_PARTITION_SIZE_MB}]: ").strip()
    state.launcher_size = int(size_input) if size_input.isdigit() else CryptoParams.LAUNCHER_PARTITION_SIZE_MB

    print(f"\n[OK] {Branding.PRODUCT_NAME} partition: {state.launcher_size} MB")

    nav = prompt_navigation(2, TOTAL_SETUP_PAGES, can_go_back=True, can_rerun=True)
    return True, nav


def run_phase_3_security_config(state: PagedSetupState) -> tuple:
    """
    Phase 3: Security Configuration (YubiKey, mode selection)

    CHG-20251218-002: Page 2/6 - SECURITY phase (continued)

    Returns: (success: bool, nav_choice: str)
    """
    state.current_log_phase = "security_config"  # CHG-20251219-001
    render_page_header(2, TOTAL_SETUP_PAGES, "SECURITY MODE", PHASE_NAMES[2])

    print(f"  Selected Drive: {state.drive_id}")
    print(f"  {Branding.PRODUCT_NAME} Partition: {state.launcher_size} MB")
    print()

    available_fprs = get_available_fingerprints()
    try:
        fingerprints, security_mode = prompt_for_fingerprints(available_fprs)
        state.fingerprints = fingerprints
        state.security_mode = security_mode

        if security_mode == SecurityMode.PW_KEYFILE.value and fingerprints == ["PLAIN_KEYFILE"]:
            log(f"Selected mode: {security_mode}, plain keyfile (no encryption)")
        else:
            log(f"Selected mode: {security_mode}, fingerprints: {len(fingerprints)}")
    except Exception as e:
        error(f"Error during fingerprint selection: {e}")
        return False, "Q"

    # Mount letter (Windows only)
    if "windows" in state.system:
        letter_input = input(f"\nMount drive letter [{state.mount_letter}]: ").strip().upper()
        if letter_input and len(letter_input) == 1 and letter_input.isalpha():
            state.mount_letter = letter_input
            state.user_preferred_mount_letter = letter_input

    print(f"\n[OK] Security mode: {state.security_mode}")
    if state.fingerprints and state.fingerprints != ["PLAIN_KEYFILE"]:
        print(f"[OK] YubiKey fingerprints: {len(state.fingerprints)}")

    nav = prompt_navigation(2, TOTAL_SETUP_PAGES, can_go_back=True, can_rerun=True)
    return True, nav


def run_phase_4_yubikey_verification(state: PagedSetupState) -> tuple:
    """
    Phase 4: Hardware Key Verification

    CHG-20251218-002: Verify YubiKey access immediately after selection.
    This ensures users possess the keys before proceeding.
    BUG-013 FIX: Verification is now optional - users can skip with [S].

    Returns: (success: bool, nav_choice: str)
    """
    state.current_log_phase = "yubikey_verification"  # CHG-20251219-001
    render_page_header(3, TOTAL_SETUP_PAGES, "HARDWARE KEY VERIFICATION", PHASE_NAMES[3])

    # Only verify for GPG-based modes
    if state.security_mode not in (SecurityMode.GPG_PW_ONLY.value, SecurityMode.PW_GPG_KEYFILE.value):
        print(f"  Security Mode: {state.security_mode}")
        print("  No hardware key verification needed for this mode.\n")
        print("  [OK] Skipping verification (password-only or plain keyfile mode)")
        nav = prompt_navigation(3, TOTAL_SETUP_PAGES, can_go_back=True, can_rerun=False, auto_next=True)
        return True, nav

    # BUG-013 FIX: Offer option to skip verification
    print("  This step verifies your hardware key(s) can decrypt.")
    print("  Verification is RECOMMENDED to prevent locking yourself out.\n")
    print("  [!] Skipping verification means you won't know if the key works")
    print("      until you try to mount the drive.\n")
    print("  " + "-" * 66)
    print("  [C] Continue with verification (RECOMMENDED)")
    print("  [S] Skip verification (EXPERT: at your own risk)")
    print("  [B] Back to key selection")
    print("  [Q] Quit setup")
    print("  " + "-" * 66)

    while True:
        choice = input("  Your choice: ").strip().upper()
        if choice == "S":
            # Skip verification - user takes responsibility
            warn("\n  [!] Verification skipped at user request.")
            print("      You are proceeding without confirming your key works.")
            print("      If the key doesn't work, you will lose access to the drive.\n")
            state.yubikeys_verified = False  # Mark as not verified
            state.verification_overridden = True  # Track that it was skipped
            SetupSessionState.verification_overridden = True
            nav = prompt_navigation(3, TOTAL_SETUP_PAGES, can_go_back=True, can_rerun=False)
            return True, nav
        elif choice == "C":
            # Continue with verification
            break
        elif choice == "B":
            return True, UserInputs.BACK
        elif choice == "Q":
            return False, UserInputs.QUIT
        else:
            print("  Please enter C, S, B, or Q")

    # Check if YubiKey is present
    print("  Checking for YubiKey (required for GPG encryption)...\n")
    if not require_yubikey("GPG operations", max_attempts=Limits.YUBIKEY_MAX_ATTEMPTS):
        error("\n[!] YubiKey not detected")
        print("\n  Your security mode requires a YubiKey.")
        print("  Please ensure your YubiKey is:")
        print("    - Properly inserted into a USB port")
        print("    - Configured with GPG keys (gpg --card-status)")
        print("    - Not in use by another application\n")
        nav = prompt_navigation(3, TOTAL_SETUP_PAGES, can_go_back=True, can_rerun=True)
        if nav == "R":
            return True, "R"  # Retry verification
        return False, nav

    print("  [OK] YubiKey detected\n")

    # Generate test encryption for verification
    print("  Creating test encryption for verification...")
    from crypto_utils import generate_seed

    test_seed = generate_seed()

    tmp_test = get_ram_temp_dir() / f"{FileNames.TMP_FILE_PREFIX}test_{os.urandom(4).hex()}.gpg"
    try:
        gpg_args = ["gpg", "--encrypt", "--armor", "--output", str(tmp_test)]
        for fpr in state.fingerprints:
            gpg_args.extend(["--recipient", fpr])

        proc = subprocess.Popen(gpg_args, stdin=subprocess.PIPE)
        proc.communicate(input=test_seed)
        if proc.returncode != 0:
            raise RuntimeError("Test encryption failed")
        print("  [OK] Test encryption created\n")
    except Exception as e:
        error(f"\n[!] Failed to create test encryption: {e}")
        if tmp_test.exists():
            tmp_test.unlink()
        return False, "Q"

    # Verify all keys can decrypt
    print("  " + "=" * 66)
    print("  VERIFYING HARDWARE KEY ACCESS")
    print("  " + "=" * 66)
    print(f"\n  You configured {len(state.fingerprints)} hardware key(s).")
    if len(state.fingerprints) > 1:
        print("  Each key MUST be verified to ensure backup access works.")
    else:
        print("  The key MUST be verified to ensure you possess it.")
    print("  This prevents locking the drive with keys you don't have.")
    print("  P0-3: Identity verified via serial number and/or encryption fingerprint.\n")

    # BUG-20251219-002: Pass verbose=False to avoid duplicate headers
    success, verified, failed = verify_all_yubikeys(
        tmp_test, state.fingerprints, max_attempts_per_key=Limits.YUBIKEY_MAX_ATTEMPTS, verbose=False
    )

    # Clean up test file
    if tmp_test.exists():
        tmp_test.unlink()

    if not success:
        error(f"\n[!] Verification failed: {len(failed)} key(s) could not decrypt")
        print("\n  All configured hardware keys MUST be able to decrypt.")
        print("  This ensures you have working backup access.")
        print("\n  Possible causes:")
        print("    - Wrong fingerprint selected")
        print("    - Key not configured for encryption")
        print("    - Hardware key malfunction\n")
        nav = prompt_navigation(3, TOTAL_SETUP_PAGES, can_go_back=True, can_rerun=True)
        if nav == "R":
            return True, "R"  # Allow retry
        return False, nav

    print(f"\n  [OK] All {len(state.fingerprints)} hardware key(s) verified!\n")
    state.yubikeys_verified = True

    nav = prompt_navigation(3, TOTAL_SETUP_PAGES, can_go_back=True, can_rerun=False)
    return True, nav


def run_phase_5_review_confirm(state: PagedSetupState) -> tuple:
    """
    Phase 5: Review & Confirm

    CHG-20251218-002: Page 4/8 - REVIEW phase

    CRITICAL: After ERASE confirmation, partitioning happens IMMEDIATELY.
    This is the "point of no return" - drive is wiped right here.

    Returns: (success: bool, nav_choice: str)
    """
    state.current_log_phase = "review_confirm"  # CHG-20251219-001
    render_page_header(4, TOTAL_SETUP_PAGES, "REVIEW & CONFIRM", PHASE_NAMES[4])

    print("The following operations will be performed:\n")
    print(f"  Target Drive:     {state.drive_id} - {state.drive_name}")
    print(f"  Drive Size:       {state.drive_size} GB")
    print(f"  {Branding.PRODUCT_NAME}:         {state.launcher_size} MB ({CryptoParams.LAUNCHER_FILESYSTEM})")

    try:
        payload_size = float(str(state.drive_size).replace("G", "")) - state.launcher_size / 1024
        print(f"  PAYLOAD:          ~{payload_size:.1f} GB (VeraCrypt encrypted)")
    except:
        print(f"  PAYLOAD:          (remaining space, VeraCrypt encrypted)")

    print(f"  Mount Letter:     {state.mount_letter}: (Windows)")

    # Show security mode
    if state.security_mode == SecurityMode.PW_ONLY.value:
        print(f"  Security Mode:    Password Only")
    elif state.security_mode == SecurityMode.PW_KEYFILE.value:
        print(f"  Security Mode:    Password + Plain Keyfile")
    elif state.security_mode == SecurityMode.GPG_PW_ONLY.value:
        print(f"  Security Mode:    GPG Password-Only ({len(state.fingerprints)} key(s))")
    elif state.security_mode == SecurityMode.PW_GPG_KEYFILE.value:
        print(f"  Security Mode:    Password + YubiKey ({len(state.fingerprints)} key(s))")

    print(f"  Password:         (will be prompted during volume creation)")

    print("\n" + "!" * 70)
    print("  [!] WARNING: ALL DATA ON THIS DRIVE WILL BE PERMANENTLY ERASED!")
    print("  [!] This action CANNOT be undone!")
    print("!" * 70)

    # Don't use standard navigation here - need explicit confirmation
    print()
    print("  " + "-" * 66)
    print(
        f"  [{UserInputs.BACK}] Back to change settings | [{UserInputs.CONTINUE}] Confirm and proceed | [{UserInputs.QUIT}] Quit"
    )

    while True:
        choice = input("  Your choice: ").strip().upper()
        if choice == UserInputs.BACK:
            return True, UserInputs.BACK
        elif choice == UserInputs.QUIT:
            log("Setup cancelled by user.")
            return False, UserInputs.QUIT
        elif choice == UserInputs.CONTINUE:
            # Additional confirmation with ERASE keyword
            if confirm_destructive("This will ERASE ALL DATA on the selected drive.", UserInputs.ERASE):
                # =================================================================
                # CRITICAL: ERASE confirmed → Partition drive IMMEDIATELY
                # =================================================================
                state.current_log_phase = "partitioning"  # CHG-20251219-001
                setup_flow_trace("ERASE_CONFIRMED", {"disk": state.drive_id})

                print("\n" + "=" * 70)
                print("  ERASE CONFIRMED - PARTITIONING DRIVE NOW")
                print("=" * 70)

                # Safety validation BEFORE partitioning
                print("\n[Safety Check] Validating target disk...")
                if "windows" in state.system:
                    safety_result = SetupSafetyPolicy.validate_before_partition(
                        script_path=Path(__file__), target_disk_number=state.selected_drive["number"]
                    )
                else:
                    safety_result = SetupSafetyPolicy.validate_before_partition(
                        script_path=Path(__file__), target_device_path=state.selected_drive["name"]
                    )

                if not safety_result:
                    print("\n" + "!" * 70)
                    print(safety_result.format_error())
                    print("!" * 70)
                    error("ABORTING: Safety validation failed!")
                    return False, UserInputs.QUIT

                print("[OK] Safety validation passed\n")

                # Perform partitioning
                setup_flow_trace(
                    "PARTITION_BEGIN", {"disk_number": state.disk_number, "launcher_size": state.launcher_size}
                )
                print("[Partitioning] Creating partitions...")

                try:
                    if "windows" in state.system:
                        smartdrive_letter, payload_device = partition_drive_windows(
                            state.selected_drive["number"], state.launcher_size, state.launcher_label
                        )
                        launcher_mount = Path(f"{smartdrive_letter}:\\")
                    else:
                        launcher_mount, payload_device = partition_drive_unix(
                            state.selected_drive["name"], state.launcher_size, state.launcher_label
                        )
                        launcher_mount = Path(launcher_mount)

                    # Store results in state
                    state.launcher_mount = launcher_mount
                    state.payload_device = payload_device
                    state.partition_done = True
                    state.confirmed = True

                    setup_flow_trace(
                        "PARTITION_DONE",
                        {
                            "launcher_mount": str(launcher_mount),
                            "payload_device": str(payload_device),
                            "disk": state.drive_id,
                        },
                    )

                    print(f"\n[OK] Partitions created successfully!")
                    print(f"     {Branding.PRODUCT_NAME} partition: {launcher_mount}")
                    print(f"     PAYLOAD partition: {payload_device}")

                    # BUG-20251219-004: Pause for operator review after partitioning
                    print("\n" + "=" * 70)
                    print("  PARTITIONING COMPLETE - REVIEW RESULTS")
                    print("=" * 70)
                    print(f"\n  Target Disk:       {state.drive_id}")
                    print(f"  {Branding.PRODUCT_NAME} Mount:   {launcher_mount}")
                    print(f"  {Branding.PRODUCT_NAME} Size:    {state.launcher_size} MB")
                    print(f"  PAYLOAD Partition: {payload_device}")
                    print("\n  The drive has been partitioned. Next step: VeraCrypt volume creation.")
                    print("  [!] No VeraCrypt encryption has been applied yet.\n")

                    # CRITICAL: Wait for operator to explicitly proceed
                    nav = prompt_navigation(4, TOTAL_SETUP_PAGES, can_go_back=False, can_rerun=False, auto_next=False)
                    if nav == UserInputs.QUIT:
                        log("Setup cancelled by user after partitioning.")
                        return False, UserInputs.QUIT
                    return True, nav

                except Exception as e:
                    error(f"\n[X] Partitioning failed: {e}")
                    print("\n  The drive could not be partitioned.")
                    print("  No VeraCrypt volume has been created.")
                    print("  Please check the error above and try again.")
                    return False, UserInputs.QUIT
            else:
                log("Setup cancelled by user.")
                return False, UserInputs.QUIT
        else:
            print(f"  Invalid. Choose {UserInputs.BACK}, {UserInputs.CONTINUE}, or {UserInputs.QUIT}.")


def run_phase_6_veracrypt_creation(state: PagedSetupState) -> tuple:
    """
    Phase 6: VeraCrypt Volume Creation

    CHG-20251218-002: Dedicated page for VeraCrypt volume creation.

    NOTE: Partitioning happens in Phase 5 after ERASE confirmation.
    This phase handles encryption setup and VeraCrypt volume creation only.

    Returns: (success: bool, nav_choice: str)
    """
    state.current_log_phase = "veracrypt_creation"  # CHG-20251219-001
    setup_flow_trace("PHASE6_ENTER", {"partition_done": state.partition_done})

    render_page_header(5, TOTAL_SETUP_PAGES, "VERACRYPT VOLUME CREATION", PHASE_NAMES[5])

    # Check if partitioning was done (should be True from Phase 5)
    if state.partition_done:
        print("  Drive has been partitioned. This phase will:")
        print("    1. Generate encryption keys/passwords")
        print("    2. Create the VeraCrypt encrypted volume")
        print("    3. Attempt to mount the volume for verification\n")
        print(f"  {Branding.PRODUCT_NAME} partition: {state.launcher_mount}")
        print(f"  PAYLOAD partition: {state.payload_device}\n")
    else:
        # Fallback: partition wasn't done (shouldn't happen in normal flow)
        print("  [!] WARNING: Drive not yet partitioned.")
        print("  This phase will:")
        print("    1. Partition the selected drive")
        print("    2. Generate encryption keys/passwords")
        print("    3. Create the VeraCrypt encrypted volume")
        print("    4. Attempt to mount the volume for verification\n")

    print("  ⚠️  This process cannot be interrupted once started.")
    print("  ⚠️  Estimated time: 5-15 minutes depending on drive size.\n")

    # BUG-20251221-023: Add proper input validation loop
    # User must explicitly press C to continue or Q to quit
    while True:
        print(f"  Press [{UserInputs.CONTINUE}] to begin volume creation, or [{UserInputs.QUIT}] to quit...")
        choice = input("  Your choice: ").strip().upper()
        if choice == UserInputs.CONTINUE:
            break  # Proceed with volume creation
        elif choice == UserInputs.QUIT:
            return False, UserInputs.QUIT
        else:
            print(f"  [!] Invalid choice '{choice}'. Please press [{UserInputs.CONTINUE}] or [{UserInputs.QUIT}].\n")

    # Extract state variables
    system = state.system
    selected_drive = state.selected_drive
    disk_number = state.disk_number
    launcher_label = state.launcher_label
    launcher_size = state.launcher_size
    fingerprints = state.fingerprints
    security_mode = state.security_mode
    mount_letter = state.mount_letter
    vc_exe = state.vc_exe
    project_root = state.project_root

    print("\n" + "=" * 70)
    print("  STARTING VERACRYPT VOLUME CREATION")
    print("=" * 70)

    tmp_keyfile = None
    tmp_encrypted = None
    password = None
    salt_b64 = None
    hkdf_info = None

    try:
        # Step 1: Partition drive (SKIP if already done in Phase 5)
        if state.partition_done:
            print("\n[1/4] Partitioning drive... ALREADY DONE ✓")
            print(f"      {Branding.PRODUCT_NAME}: {state.launcher_mount}")
            print(f"      PAYLOAD: {state.payload_device}")
            launcher_mount = state.launcher_mount
            payload_device = state.payload_device
        else:
            # Fallback partitioning (safety net, shouldn't normally execute)
            print("\n[1/4] Partitioning drive...")

            # Safety gate
            print("  [Safety Check] Validating target disk...")
            if "windows" in system:
                safety_result = SetupSafetyPolicy.validate_before_partition(
                    script_path=Path(__file__), target_disk_number=selected_drive["number"]
                )
            else:
                safety_result = SetupSafetyPolicy.validate_before_partition(
                    script_path=Path(__file__), target_device_path=selected_drive["name"]
                )

            if not safety_result:
                print("\n" + "!" * 70)
                print(safety_result.format_error())
                print("!" * 70)
                error("ABORTING: Safety validation failed!")
                return False, UserInputs.QUIT

            print("  [OK] Safety validation passed")

            if "windows" in system:
                smartdrive_letter, payload_device = partition_drive_windows(
                    selected_drive["number"], launcher_size, launcher_label
                )
                launcher_mount = Path(f"{smartdrive_letter}:\\")
            else:
                launcher_mount, payload_device = partition_drive_unix(
                    selected_drive["name"], launcher_size, launcher_label
                )
                launcher_mount = Path(launcher_mount)

            state.launcher_mount = launcher_mount
            state.payload_device = payload_device
            state.partition_done = True
            print(f"[OK] Partitions created")

        # Step 2: Setup encryption
        print("\n[2/4] Setting up encryption...")
        use_keyfile = (
            bool(fingerprints) and fingerprints != ["PLAIN_KEYFILE"] and security_mode != SecurityMode.GPG_PW_ONLY.value
        )
        use_gpg = bool(fingerprints) and fingerprints != ["PLAIN_KEYFILE"]

        state.use_keyfile = use_keyfile
        state.use_gpg = use_gpg

        # Handle GPG-encrypted keyfile mode
        if security_mode == SecurityMode.PW_GPG_KEYFILE.value:
            password = getpass("\n  Enter VeraCrypt password: ")
            password_confirm = getpass("  Confirm password: ")
            if password != password_confirm:
                raise RuntimeError("Passwords do not match")

            tmp_keyfile = get_ram_temp_dir() / f"{FileNames.TMP_FILE_PREFIX}setup_keyfile_{os.urandom(4).hex()}.key"
            tmp_keyfile.write_bytes(os.urandom(64))
            # Capture keyfile bytes for recovery kit generation (no re-auth)
            state.keyfile_bytes = tmp_keyfile.read_bytes()

            tmp_encrypted = get_ram_temp_dir() / f"{FileNames.TMP_FILE_PREFIX}setup_keyfile_{os.urandom(4).hex()}.gpg"
            gpg_args = ["gpg", "--encrypt", "--armor", "--output", str(tmp_encrypted)]
            for fpr in fingerprints:
                gpg_args.extend(["--recipient", fpr])

            with open(tmp_keyfile, "rb") as f:
                proc = subprocess.Popen(gpg_args, stdin=f)
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError("Failed to encrypt keyfile")

            state.tmp_keyfile = tmp_keyfile
            state.tmp_encrypted = tmp_encrypted

        # Handle plain keyfile mode
        elif security_mode == SecurityMode.PW_KEYFILE.value:
            password = getpass("\n  Enter VeraCrypt password: ")
            password_confirm = getpass("  Confirm password: ")
            if password != password_confirm:
                raise RuntimeError("Passwords do not match")

            tmp_keyfile = get_ram_temp_dir() / f"{FileNames.TMP_FILE_PREFIX}setup_keyfile_{os.urandom(4).hex()}.key"
            tmp_keyfile.write_bytes(os.urandom(64))
            # Capture keyfile bytes for recovery kit generation (no re-auth)
            state.keyfile_bytes = tmp_keyfile.read_bytes()
            state.tmp_keyfile = tmp_keyfile

        # Handle GPG password-only mode
        elif security_mode == SecurityMode.GPG_PW_ONLY.value:
            from crypto_utils import derive_veracrypt_password, generate_salt, generate_seed

            seed = generate_seed()
            salt = generate_salt()
            salt_b64 = base64.b64encode(salt).decode("ascii")
            hkdf_info = CryptoParams.HKDF_INFO_DEFAULT

            password = derive_veracrypt_password(seed, salt)
            print(f"  [OK] Derived VeraCrypt password ({len(password)} chars)")

            tmp_seed_gpg = get_ram_temp_dir() / f"{FileNames.TMP_FILE_PREFIX}setup_seed_{os.urandom(4).hex()}.gpg"
            if tmp_seed_gpg.exists():
                tmp_seed_gpg.unlink()

            gpg_args = ["gpg", "--encrypt", "--armor", "--output", str(tmp_seed_gpg)]
            for fpr in fingerprints:
                gpg_args.extend(["--recipient", fpr])

            proc = subprocess.Popen(gpg_args, stdin=subprocess.PIPE)
            proc.communicate(input=seed)
            if proc.returncode != 0:
                raise RuntimeError("GPG encryption failed")

            tmp_encrypted = tmp_seed_gpg
            state.tmp_encrypted = tmp_encrypted
            state.salt = salt_b64
            state.session_seed_gpg_path = str(tmp_seed_gpg)
            state.session_salt_b64 = salt_b64
            state.session_hkdf_info = hkdf_info

        # Handle password-only mode
        else:
            password = getpass("\n  Enter VeraCrypt password: ")
            password_confirm = getpass("  Confirm password: ")
            if password != password_confirm:
                raise RuntimeError("Passwords do not match")

        state.password = password
        print("[OK] Encryption setup complete")

        # Step 3: Create VeraCrypt volume
        print("\n[3/4] Creating VeraCrypt volume...")
        print("       (This may take several minutes...)\n")

        if "windows" in system:
            success = create_veracrypt_volume_windows(
                vc_exe,
                payload_device,
                password,
                tmp_keyfile,
                None,
                security_mode,
                session_seed_gpg_path=tmp_encrypted if security_mode == SecurityMode.GPG_PW_ONLY.value else None,
                session_salt_b64=salt_b64,
                session_hkdf_info=hkdf_info,
            )
        else:
            success = create_veracrypt_volume_unix(payload_device, password, tmp_keyfile)

        if not success:
            raise RuntimeError("VeraCrypt volume creation failed")

        print("[OK] VeraCrypt volume created successfully!")

        # Step 4: Attempt mount
        print("\n[4/4] Attempting to mount volume...")
        auto_mount_success, mount_letter_result = try_auto_mount_volume(
            vc_exe,
            payload_device,
            password,
            tmp_keyfile,
            disk_number,
            preferred_letter=mount_letter,
            security_mode=security_mode,
        )

        if auto_mount_success:
            state.mount_letter = mount_letter_result
            print(f"[OK] Volume mounted to {mount_letter_result}:")
        else:
            print("[!] Automated mount failed - will retry manually later")

        print("\n" + "=" * 70)
        print("  VERACRYPT VOLUME CREATION COMPLETE")
        print("=" * 70)
        print("\n  [OK] Drive partitioned and encrypted successfully!\n")

        nav = prompt_navigation(5, TOTAL_SETUP_PAGES, can_go_back=False, can_rerun=False)
        return True, nav

    except Exception as e:
        error(f"\n[X] Volume creation failed: {e}")
        # Clean up temp files
        if tmp_keyfile and tmp_keyfile.exists():
            tmp_keyfile.unlink()
        if tmp_encrypted and tmp_encrypted.exists():
            tmp_encrypted.unlink()
        return False, "Q"


def run_phase_7_deployment(state: PagedSetupState, *, auto_nav: bool = False) -> tuple:
    """Phase 7: Deployment - now a dedicated page with navigation."""
    state.current_log_phase = "deployment"

    # Bridge variables from paged state
    system = state.system
    launcher_mount = state.launcher_mount
    payload_device = state.payload_device
    tmp_keyfile = state.tmp_keyfile
    tmp_encrypted = state.tmp_encrypted
    fingerprints = state.fingerprints
    security_mode = state.security_mode
    mount_letter = state.mount_letter
    vc_exe = state.vc_exe
    project_root = state.project_root
    use_keyfile = state.use_keyfile
    use_gpg = state.use_gpg

    render_page_header(7, TOTAL_SETUP_PAGES, "DEPLOYMENT", PHASE_NAMES[7])

    print("  Volume created successfully in Phase 6.")
    print("  Now deploying scripts and configuration to the drive...\n")

    setup_flow_trace("DEPLOYMENT_BEGIN", {"launcher_mount": str(launcher_mount)})

    try:
        # Set drive icon and label (Windows only)
        if "windows" in system:
            print("[Deployment] Setting drive icon and label...")
            # set_drive_icon uses SSOT internally for icon paths (FileNames, Paths)
            drive_letter = str(launcher_mount.drive).rstrip(":\\") if launcher_mount.drive else ""
            set_drive_icon(launcher_mount, drive_letter, icon_type="launcher")
            label_to_set = state.launcher_label or Branding.PRODUCT_NAME
            set_drive_label(launcher_mount, label_to_set)
            print(f"  [OK] Drive label: {label_to_set}")

        # Deploy scripts and configuration
        print("[Deployment] Deploying scripts and configuration...")

        encrypted_keyfile_path = tmp_encrypted if tmp_encrypted else None
        plain_keyfile_path = tmp_keyfile if (tmp_keyfile and security_mode == SecurityMode.PW_KEYFILE.value) else None

        deploy_success = deploy_scripts_extended(
            launcher_path=launcher_mount,
            payload_device=str(payload_device),
            encrypted_keyfile=encrypted_keyfile_path,
            plain_keyfile=plain_keyfile_path,
            mount_letter=mount_letter,
            use_keyfile=use_keyfile,
            use_gpg=use_gpg,
            security_mode=security_mode,
            salt_b64=getattr(state, "session_salt_b64", None),
            gpg_fingerprints=fingerprints if fingerprints else None,
            verification_overridden=state.verification_overridden,  # BUG-013
            device_info=state.selected_drive,  # BUG-20251221-042: Store device details
        )

        if not deploy_success:
            error("\n[X] Deployment failed!")
            print("  Scripts could not be deployed to the drive.")
            print("  The VeraCrypt volume was created but setup is incomplete.")
            setup_flow_trace("DEPLOYMENT_ERROR", {"error": "deploy_scripts_extended returned False"})
            return False, "Q"

        print("[OK] Scripts deployed successfully!")

        # Verify deployment - check critical files exist
        print("[Deployment] Verifying deployment...")
        target_smartdrive = launcher_mount / Paths.SMARTDRIVE_DIR_NAME
        target_scripts = target_smartdrive / Paths.SCRIPTS_SUBDIR
        target_config = target_smartdrive / FileNames.CONFIG_JSON

        deployment_verified = True
        required_items = [
            (target_smartdrive, "directory"),
            (target_scripts, "directory"),
            (target_config, "file"),
            (target_scripts / FileNames.MOUNT_PY, "file"),
            (target_scripts / FileNames.UNMOUNT_PY, "file"),
            (target_scripts / FileNames.RECOVERY_PY, "file"),
        ]

        for item_path, item_type in required_items:
            if item_type == "directory":
                if not item_path.is_dir():
                    error(f"  [X] Missing directory: {item_path}")
                    deployment_verified = False
            else:
                if not item_path.is_file():
                    error(f"  [X] Missing file: {item_path}")
                    deployment_verified = False

        if not deployment_verified:
            error("\n[X] Deployment verification failed!")
            print("  Some required files are missing from the deployed drive.")
            setup_flow_trace("DEPLOYMENT_ERROR", {"error": "deployment verification failed"})
            return False, UserInputs.QUIT

        print("[OK] Deployment verified - all required files present")

        # CHG-20251221-022: Signing moved to post-deployment menu
        # Users now have explicit choice whether to sign scripts after setup

        setup_flow_trace(
            "DEPLOYMENT_DONE",
            {
                "launcher_mount": str(launcher_mount),
                "config_exists": target_config.is_file(),
                "scripts_deployed": (target_scripts / FileNames.MOUNT_PY).is_file(),
            },
        )

        # Clean up temporary files
        print("[Deployment] Cleaning up temporary files...")
        if tmp_keyfile and tmp_keyfile.exists():
            tmp_keyfile.unlink()
            print("  [OK] Removed temp keyfile")
        if tmp_encrypted and tmp_encrypted.exists():
            tmp_encrypted.unlink()
            print("  [OK] Removed temp encrypted file")

        state.deployment_done = True

        print("\n" + "=" * 70)
        print("  [PHASE 7 COMPLETE: DEPLOYMENT SUCCESSFUL]")
        print("=" * 70)
        print(f"\n  {Branding.PRODUCT_NAME} partition:  {launcher_mount}")
        print(f"  PAYLOAD partition: {payload_device}")
        print(f"  VeraCrypt mount:   {mount_letter}:")
        print("\n  Deployed files:")
        print(f"    {target_smartdrive}")
        print(f"    {target_scripts}")
        print(f"    {target_config}")

        if auto_nav:
            return True, UserInputs.NEXT

        nav = prompt_navigation(7, TOTAL_SETUP_PAGES, can_go_back=False, can_rerun=False, auto_next=False)
        return True, nav

    except Exception as e:
        error(f"\n[X] Deployment failed with error: {e}")
        setup_flow_trace("DEPLOYMENT_ERROR", {"error": str(e)})
        return False, UserInputs.QUIT


def run_phase_8_summary(state: PagedSetupState, *, auto_exit: bool = False) -> int:
    """Phase 8: Summary and interactive next-steps menu.

    If auto_exit=True: print summary and exit (no prompts).
    Else: show interactive menu with Mount/GUI/Recovery/Rekey/Quit options.
    """
    state.current_log_phase = "summary"

    # If auto_exit, preserve old behavior
    if auto_exit:
        render_page_header(8, TOTAL_SETUP_PAGES, "SUMMARY", PHASE_NAMES[8])
        launcher_mount = state.launcher_mount
        payload_device = state.payload_device
        mount_letter = state.mount_letter
        print("  SETUP COMPLETE")
        print("\n  Your drive has been created successfully!")
        print(f"\n  {Branding.PRODUCT_NAME} partition:  {launcher_mount}")
        print(f"  PAYLOAD partition: {payload_device}")
        print(f"  VeraCrypt mount:   {mount_letter}:")
        return 0

    # Interactive mode: show next-steps menu
    launcher_mount = state.launcher_mount
    payload_device = state.payload_device
    mount_letter = state.mount_letter

    # Preconditions
    if not launcher_mount:
        error("Internal error: launcher_mount is None")
        return 1

    scripts_dir = launcher_mount / Paths.SMARTDRIVE_DIR_NAME / Paths.SCRIPTS_SUBDIR
    config_path = launcher_mount / Paths.SMARTDRIVE_DIR_NAME / FileNames.CONFIG_JSON

    if not scripts_dir.exists():
        error(f"Scripts directory not found: {scripts_dir}")
        return 1
    if not config_path.exists():
        error(f"Config file not found: {config_path}")
        return 1

    setup_flow_trace("POST_SETUP_MENU_SHOWN", {"launcher_mount": str(launcher_mount)})

    # Import helpers (avoid top-level import to keep CLI-only)
    # Recovery import may fail if optional dependencies not installed
    try:
        from recovery import generate_recovery_kit_from_setup

        recovery_available = True
    except ImportError:
        recovery_available = False
        generate_recovery_kit_from_setup = None

    from veracrypt_cli import open_veracrypt_gui

    # Action dispatch loop
    while True:
        # Detect recovery status
        recovery_generated = detect_recovery_generated(launcher_mount) or state.recovery_generated

        # Show menu
        choice = show_setup_success_screen(
            launcher_mount=launcher_mount,
            target_drive=(
                str(state.selected_drive)
                if hasattr(state, "selected_drive") and state.selected_drive
                else str(payload_device)
            ),
            use_gpg=state.use_gpg,
            use_keyfile=state.use_keyfile,
            fingerprints=state.fingerprints if state.fingerprints else [],
            recovery_generated=recovery_generated,
        )

        setup_flow_trace("POST_SETUP_ACTION", {"action": choice})

        # Dispatch actions
        if choice == UserInputs.MOUNT:
            # Mount
            print("\n  [ACTION] Mounting drive...")
            try:
                # Build mount command (pass password for non-GPG_PW_ONLY modes)
                cmd = [sys.executable, str(scripts_dir / FileNames.MOUNT_PY), "--config", str(config_path)]
                if state.security_mode != SecurityMode.GPG_PW_ONLY.value and state.password:
                    cmd.extend(["--password", state.password])
                result = subprocess.run(cmd, cwd=str(scripts_dir))
                if result.returncode == 0:
                    print("  [OK] Mount completed")
                else:
                    print(f"  [!] Mount exited with code {result.returncode}")
            except Exception as e:
                print(f"  [!] Mount failed: {e}")
            print("\n  Press Enter to return to menu...")
            input()

        elif choice == UserInputs.GUI:
            # Open GUI
            print("\n  [ACTION] Opening VeraCrypt GUI...")
            if open_veracrypt_gui():
                print("  [OK] VeraCrypt GUI opened")
            else:
                print("  [!] Could not open VeraCrypt GUI")
            print("\n  Press Enter to return to menu...")
            input()

        elif choice == UserInputs.RECOVERY:
            # Recovery kit
            if recovery_generated:
                # Open recovery directory
                print("\n  [ACTION] Opening recovery kit location...")
                recovery_dir = Paths.recovery_dir(launcher_mount)
                if open_folder_cli(recovery_dir):
                    print(f"  [OK] Opened: {recovery_dir}")
                print("\n  Press Enter to return to menu...")
                input()
            else:
                # Generate recovery kit
                print("\n  [ACTION] Generating recovery kit...")
                if not recovery_available:
                    print("  [!] Recovery kit generation unavailable: missing dependencies")
                    print("      Install with: pip install mnemonic argon2-cffi")
                else:
                    try:
                        rc = generate_recovery_kit_from_setup(
                            config_path=config_path, password=state.password, keyfile_bytes=state.keyfile_bytes
                        )
                        if rc == 0:
                            state.recovery_generated = True
                            print("  [OK] Recovery kit generated successfully")
                        else:
                            print(f"  [!] Recovery kit generation exited with code {rc}")
                    except Exception as e:
                        print(f"  [!] Recovery kit generation failed: {e}")
                print("\n  Press Enter to return to menu...")
                input()

        elif choice == UserInputs.REKEY:
            # Rekey
            print("\n  [ACTION] Launching rekey flow...")
            try:
                subprocess.run([sys.executable, str(scripts_dir / FileNames.REKEY_PY)], cwd=str(scripts_dir))
                print("  [OK] Rekey completed")
            except Exception as e:
                print(f"  [!] Rekey failed: {e}")
            print("\n  Press Enter to return to menu...")
            input()

        elif choice == "S":
            # CHG-20251221-022: Sign deployed scripts (separate from deployment)
            print("\n  [ACTION] Signing deployed scripts...")
            if state.fingerprints and len(state.fingerprints) > 0:
                sign_result = sign_deployed_scripts(launcher_mount, state.fingerprints[0])
                if sign_result:
                    print("  [OK] Scripts signed successfully")
                    print("      Integrity verification will now pass on future runs.")
                else:
                    print("  [!] Script signing failed")
                    print("      You can try again later from the main CLI menu.")
            else:
                print("  [!] Script signing not available (no GPG keys configured)")
            print("\n  Press Enter to return to menu...")
            input()

        elif choice == "T":
            # CHG-20251221-023: Run verification tests
            run_post_deployment_tests(launcher_mount)
            print("\n  Press Enter to return to menu...")
            input()

        elif choice == UserInputs.EXIT:
            # Quit - show log review option and exit
            print("\n  " + "-" * 66)
            print(f"  [{UserInputs.LOGS}] Review setup logs | [Enter] Exit")
            log_choice = input("  Your choice: ").strip().upper()
            if log_choice == UserInputs.LOGS:
                show_log_review(state)
            return 0


def main_paged() -> int:
    """
    CHG-20251218-002: Main setup function with page-based navigation.
    CHG-20251219-001: Includes log preservation for later review.

    Implements [B]ack/[N]ext navigation between setup phases.
    """
    global _active_setup_state

    print_banner()

    state = PagedSetupState()
    state.system = platform.system().lower()

    # CHG-20251219-001: Set global state for log preservation
    _active_setup_state = state

    # ==========================================================================
    # Pre-flight checks (not paginated - must pass before setup)
    # ==========================================================================

    print("\nChecking requirements...\n")

    if not is_admin():
        error("This script requires administrator/root privileges!")
        if "windows" in state.system:
            print("\nRight-click and 'Run as Administrator', or run from elevated PowerShell.")
        else:
            print("\nRun with: sudo python setup.py")
        return 1
    log("[OK] Running with administrator privileges")

    if not have("gpg"):
        error("gpg not found! Please install GnuPG.")
        return 1
    log("[OK] GPG available")

    if "windows" in state.system:
        state.vc_exe = find_veracrypt_windows()
        if not state.vc_exe:
            error("VeraCrypt not found! Please install from veracrypt.fr")
            return 1
        log(f"[OK] VeraCrypt found: {state.vc_exe}")
    else:
        if not have("veracrypt"):
            error("veracrypt not found in PATH!")
            return 1
        state.vc_exe = Path(shutil.which("veracrypt"))
        log("[OK] VeraCrypt available")

    state.scripts_dir = Path(__file__).resolve().parent
    if state.scripts_dir.parent.name == Paths.SMARTDRIVE_DIR_NAME:
        state.project_root = state.scripts_dir.parent.parent
    else:
        state.project_root = state.scripts_dir.parent

    print("\n  Press Enter to begin setup...")
    input()

    # ==========================================================================
    # Paged Setup Flow with [B]ack/[N]ext Navigation
    # ==========================================================================

    current_phase = 1  # Start at phase 1

    while True:
        if current_phase == 1:
            # Phase 1: Drive Selection
            success, nav = run_phase_1_drive_selection(state)
            if not success:
                # BUG-20251220-001: Return proper exit code based on failure vs user quit
                return 0 if nav == "Q" else 1
            if nav == "Q":
                # User quit without failure
                return 0
            if nav == "R":
                state.clear_from_phase(SetupPhase.DRIVE_SELECTION)
                continue  # Re-run phase 1
            current_phase = 2

        elif current_phase == 2:
            # Phase 2a: Partition Size
            success, nav = run_phase_2_partition_size(state)
            if not success:
                return 0 if nav == "Q" else 1
            if nav == "Q":
                return 0
            if nav == "B":
                state.clear_from_phase(SetupPhase.DRIVE_SELECTION)
                current_phase = 1
                continue
            if nav == "R":
                continue  # Re-run phase 2
            current_phase = 3

        elif current_phase == 3:
            # Phase 3: Security Configuration
            success, nav = run_phase_3_security_config(state)
            if not success:
                return 0 if nav == "Q" else 1
            if nav == "Q":
                return 0
            if nav == "B":
                state.clear_from_phase(SetupPhase.PARTITION_SIZE)
                current_phase = 2
                continue
            if nav == "R":
                state.clear_from_phase(SetupPhase.SECURITY_CONFIG)
                continue  # Re-run phase 3
            current_phase = 4

        elif current_phase == 4:
            # Phase 4: Hardware Key Verification
            success, nav = run_phase_4_yubikey_verification(state)
            if not success:
                return 0 if nav == "Q" else 1
            if nav == "Q":
                return 0
            if nav == "B":
                state.clear_from_phase(SetupPhase.SECURITY_CONFIG)
                current_phase = 3
                continue
            if nav == "R":
                continue  # Re-run phase 4
            current_phase = 5

        elif current_phase == 5:
            # Phase 5: Review & Confirm
            success, nav = run_phase_5_review_confirm(state)
            if not success:
                return 0 if nav == "Q" else 1
            if nav == "Q":
                return 0
            if nav == "B":
                # Can go back to verification
                current_phase = 4
                continue
            # After confirmation, proceed to VeraCrypt creation
            current_phase = 6

        elif current_phase == 6:
            # Phase 6: VeraCrypt Volume Creation (point of no return)
            success, nav = run_phase_6_veracrypt_creation(state)
            if not success:
                return 0 if nav == "Q" else 1
            if nav == "Q":
                return 0
            # After successful volume creation, proceed to deployment
            current_phase = 7

        elif current_phase == 7:
            # Phase 7: Deployment (now paged)
            success, nav = run_phase_7_deployment(state)
            if not success:
                return 0 if nav == "Q" else 1
            if nav == "Q":
                return 0
            current_phase = 8

        elif current_phase == 8:
            # Phase 8: Summary
            return run_phase_8_summary(state)


def run_execution_phases(state: PagedSetupState) -> int:
    """
    Run final deployment phases (non-navigable after volume creation).

    BUG-20251219-003: Ensures deployment is not skipped after VeraCrypt setup.
    These are the final deployment and finalization steps after VeraCrypt volume
    has been successfully created in Phase 6.
    """
    # Allow non-paged execution to reuse deployment + summary flow
    success, _ = run_phase_7_deployment(state, auto_nav=True)
    if not success:
        return 1
    return run_phase_8_summary(state, auto_exit=True)


if __name__ == "__main__":
    try:
        sys.exit(main_paged())
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user (Ctrl+C)")
        sys.exit(1)
