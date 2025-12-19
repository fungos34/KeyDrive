#!/usr/bin/env python3
"""
SmartDrive Manager - Unified CLI Interface
==========================================

Context-aware menu that detects whether it's running from:
- LAUNCHER partition (external drive) → Mount/Unmount/Rekey
- SYSTEM drive (development/setup) → Setup wizard/Recovery tools

Author: SmartDrive Project
License: MIT
"""

import json
import os
import sys
import subprocess
import platform
import urllib.request
import urllib.error
import hashlib
import secrets
from pathlib import Path

# Import update functionality
try:
    from update import update_deployment_drive
except ImportError:
    # Fallback if update.py not available
    def update_deployment_drive(*args, **kwargs):
        print("❌ Update functionality not available (update.py missing)")
        return False

# ============================================================
# CONFIGURATION
# ============================================================

SCRIPT_DIR = Path(__file__).parent.resolve()

# Detect if running from .smartdrive/ (deployed) or scripts/ (development)
# In deployed mode: SCRIPT_DIR is .smartdrive/scripts/, parent is .smartdrive/
# In dev mode: SCRIPT_DIR is scripts/, parent is project root
if SCRIPT_DIR.parent.name == ".smartdrive":
    # Deployed on external drive
    SMARTDRIVE_DIR = SCRIPT_DIR.parent
    KEYS_DIR = SMARTDRIVE_DIR / "keys"
    INTEGRITY_DIR = SMARTDRIVE_DIR / "integrity"
else:
    # Development environment - check for .smartdrive or fall back to old structure
    if (SCRIPT_DIR.parent / ".smartdrive").exists():
        SMARTDRIVE_DIR = SCRIPT_DIR.parent / ".smartdrive"
        KEYS_DIR = SMARTDRIVE_DIR / "keys"
        INTEGRITY_DIR = SMARTDRIVE_DIR / "integrity"
    else:
        # Legacy structure (scripts/ and keys/ at root)
        SMARTDRIVE_DIR = SCRIPT_DIR.parent
        KEYS_DIR = SMARTDRIVE_DIR / "keys"
        INTEGRITY_DIR = SMARTDRIVE_DIR  # integrity files at root in legacy mode

CONFIG_FILE = SCRIPT_DIR / "config.json"

# ============================================================
# DISPLAY HELPERS
# ============================================================

def clear_screen():
    """Clear terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def get_drive_metadata() -> dict:
    """
    Load drive metadata from config.json.
    Returns dict with drive info for display.
    """
    metadata = {
        "drive_name": None,
        "security_mode": None,
        "volume_path": None,
        "mount_target": None,
        "last_password_change": None,
        "setup_date": None,
        "version": None,
        "last_updated": None,
        "keyfile_fingerprints": None,
    }
    
    if not CONFIG_FILE.exists():
        return metadata
    
    try:
        import json
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        
        # Drive name (user-defined label)
        metadata["drive_name"] = cfg.get("drive_name", None)
        
        # Security mode
        mode = cfg.get("security_mode", "")
        if not mode:
            # Detect from keyfile config
            if cfg.get("encrypted_keyfile"):
                mode = "yubikey"
            elif cfg.get("keyfile"):
                mode = "keyfile"
            else:
                mode = "password"
        metadata["security_mode"] = mode
        
        # Volume path and mount target
        system = platform.system().lower()
        if system == "windows":
            metadata["volume_path"] = cfg.get("windows", {}).get("volume_path", "")
            metadata["mount_target"] = cfg.get("windows", {}).get("mount_letter", "V") + ":"
        else:
            metadata["volume_path"] = cfg.get("unix", {}).get("volume_path", "")
            metadata["mount_target"] = cfg.get("unix", {}).get("mount_point", "")
        
        # Timestamps
        metadata["last_password_change"] = cfg.get("last_password_change")
        metadata["setup_date"] = cfg.get("setup_date")
        metadata["version"] = cfg.get("version")
        metadata["last_updated"] = cfg.get("last_updated")
        
        # YubiKey fingerprints (if stored)
        metadata["keyfile_fingerprints"] = cfg.get("keyfile_fingerprints")
        
    except Exception:
        pass
    
    return metadata

def get_security_mode_display(mode: str) -> str:
    """Get display string for security mode."""
    modes = {
        "yubikey": "🔐 YubiKey + Password",
        "keyfile": "🔑 Keyfile + Password", 
        "password": "🔒 Password Only"
    }
    return modes.get(mode, f"❓ {mode}")

def print_banner():
    """Print the SmartDrive banner."""
    print()
    print("═" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║                    SmartDrive Manager                         ║")
    print("  ║         Encrypted External Drive with YubiKey 2FA             ║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("═" * 70)

def print_drive_info():
    """Print drive metadata panel."""
    metadata = get_drive_metadata()
    
    if not any(metadata.values()):
        return  # No config, skip
    
    # Check recovery status
    recovery_info = None
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            recovery_info = cfg.get("recovery", {})
        except:
            pass
    
    print()
    print("┌" + "─" * 68 + "┐")
    
    # Drive name or default
    drive_name = metadata["drive_name"] or "Unnamed Drive"
    print(f"│  📀 {drive_name:<63}│")
    
    print("├" + "─" * 68 + "┤")
    
    # Security mode
    if metadata["security_mode"]:
        mode_str = get_security_mode_display(metadata["security_mode"])
        print(f"│  Security: {mode_str:<56}│")
    
    # Recovery status
    if recovery_info:
        if recovery_info.get("enabled"):
            recovery_date = recovery_info.get("created_date", "Unknown")
            recovery_text = f"Recovery: ✅ Enabled (created {recovery_date[:10]})"
            print(f"│  {recovery_text:<66}│")
            
            # Show recovery events if any
            events = recovery_info.get("recovery_events", [])
            if events:
                last_event = events[-1]
                event_date = last_event.get("date", "Unknown")
                event_reason = last_event.get("reason", "Unknown")
                warning_text = f"⚠️  Recovery used on {event_date[:10]} ({event_reason})"
                print(f"│  {warning_text:<66}│")
        else:
            print(f"│  {'Recovery: ❌ Not enabled':<66}│")
    
    # Mount target
    if metadata["mount_target"]:
        print(f"│  Mounts to: {metadata['mount_target']:<55}│")
    
    # Last password change (if tracked)
    if metadata["last_password_change"]:
        # Calculate days since change
        try:
            from datetime import datetime
            last_change = datetime.fromisoformat(metadata["last_password_change"])
            days_ago = (datetime.now() - last_change).days
            if days_ago > 90:
                status = f"⚠️  {days_ago} days ago (consider rotating)"
            else:
                status = f"✓ {days_ago} days ago"
            print(f"│  Password changed: {status:<48}│")
        except:
            print(f"│  Password changed: {metadata['last_password_change']:<48}│")
    
    # Setup date
    if metadata["setup_date"]:
        print(f"│  Setup date: {metadata['setup_date']:<54}│")
    
    # Version
    if metadata["version"]:
        version_str = f"v{metadata['version']}"
        if metadata["last_updated"]:
            version_str += f" (updated {metadata['last_updated'][:10]})"
        print(f"│  Version: {version_str:<57}│")
    
    print("└" + "─" * 68 + "┘")

def print_status(context: str, is_mounted: bool = None):
    """Print current status."""
    print()
    if context == "LAUNCHER":
        # Show drive info panel
        print_drive_info()
        
        # Mount status
        print()
        if is_mounted is True:
            print("  Status: 🔓 Volume MOUNTED")
        elif is_mounted is False:
            print("  Status: 🔒 Volume NOT mounted")
        else:
            print("  Status: ❓ Volume status unknown")
    else:
        print("  Mode: 🖥️  System/Development")
    print()

def print_menu_launcher():
    """Print menu for LAUNCHER context."""
    print("┌" + "─" * 68 + "┐")
    print("│  SMARTDRIVE - External Drive Menu" + " " * 33 + "│")
    print("├" + "─" * 68 + "┤")
    print("│" + " " * 68 + "│")
    print("│  [1] 🔓 Mount encrypted volume" + " " * 37 + "│")
    print("│  [2] 🔒 Unmount volume" + " " * 45 + "│")
    print("│  [3] 🔑 Change password / Rotate keyfile" + " " * 27 + "│")
    print("│  [4] 🛠️  Keyfile utilities" + " " * 41 + "│")
    print("│  [5] ℹ️  Show configuration & status" + " " * 31 + "│")
    print("│  [6] 🆘 Recovery Kit (emergency access)" + " " * 28 + "│")
    print("│  [7] ✍️  Sign scripts (create integrity signature)" + " " * 16 + "│")
    print("│  [8] 🔍 Verify script integrity (GPG signature)" + " " * 20 + "│")
    print("│  [9] � Generate challenge hash (remote verification)" + " " * 13 + "│")
    print("│  [10] �📖 Help / Documentation" + " " * 38 + "│")
    print("│" + " " * 68 + "│")
    print("│  [0] ❌ Exit" + " " * 55 + "│")
    print("│" + " " * 68 + "│")
    print("└" + "─" * 68 + "┘")

def print_menu_system():
    """Print menu for SYSTEM context."""
    print("┌" + "─" * 68 + "┐")
    print("│  SMARTDRIVE - System/Setup Menu" + " " * 35 + "│")
    print("├" + "─" * 68 + "┤")
    print("│" + " " * 68 + "│")
    print("│  [1] 🆕 Setup new encrypted drive" + " " * 34 + "│")
    print("│  [2] 🛠️  Keyfile utilities (create/backup/recover)" + " " * 19 + "│")
    print("│  [3] ✍️  Sign scripts (create integrity signature)" + " " * 18 + "│")
    print("│  [4] 📖 Help / Open documentation" + " " * 34 + "│")
    print("│  [5] 📦 Update deployment drive" + " " * 34 + "│")
    print("│" + " " * 68 + "│")
    print("│  [0] ❌ Exit" + " " * 55 + "│")
    print("│" + " " * 68 + "│")
    print("└" + "─" * 68 + "┘")

def print_keyfile_menu():
    """Print keyfile utilities submenu."""
    print()
    print("┌" + "─" * 68 + "┐")
    print("│  KEYFILE UTILITIES" + " " * 49 + "│")
    print("├" + "─" * 68 + "┤")
    print("│" + " " * 68 + "│")
    print("│  [1] 🔐 Create new keyfile (encrypted to YubiKeys)" + " " * 18 + "│")
    print("│  [2] 🔓 Decrypt keyfile (for recovery/migration)" + " " * 20 + "│")
    print("│  [3] 🔒 Encrypt existing file to YubiKeys" + " " * 27 + "│")
    print("│" + " " * 68 + "│")
    print("│  [0] ↩️  Back to main menu" + " " * 42 + "│")
    print("│" + " " * 68 + "│")
    print("└" + "─" * 68 + "┘")

# ============================================================
# CONTEXT DETECTION
# ============================================================

def detect_context() -> str:
    """
    Detect whether we're running from LAUNCHER or SYSTEM.
    
    LAUNCHER: config.json exists AND keys folder with .gpg file nearby
    SYSTEM: Otherwise (development/setup environment)
    """
    # Check for LAUNCHER indicators
    config_exists = CONFIG_FILE.exists()
    keys_exists = KEYS_DIR.exists()
    has_encrypted_keyfile = False
    
    if keys_exists:
        gpg_files = list(KEYS_DIR.glob("*.gpg"))
        has_encrypted_keyfile = len(gpg_files) > 0
    
    # LAUNCHER context: has config and/or encrypted keyfile
    if config_exists and (has_encrypted_keyfile or keys_exists):
        return "LAUNCHER"
    
    # Check if we have setup.py (indicates SYSTEM/dev context)
    setup_exists = (SCRIPT_DIR / "setup.py").exists()
    if setup_exists and not config_exists:
        return "SYSTEM"
    
    # Default: if config exists, assume LAUNCHER
    if config_exists:
        return "LAUNCHER"
    
    return "SYSTEM"

def check_mount_status() -> bool:
    """
    Check if the volume is currently mounted.
    Returns True if mounted, False if not, None if unknown.
    """
    if not CONFIG_FILE.exists():
        return None
    
    try:
        import json
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        
        system = platform.system().lower()
        
        if system == "windows":
            mount_letter = cfg.get("windows", {}).get("mount_letter", "V")
            drive_path = Path(f"{mount_letter}:/")
            return drive_path.exists() and drive_path.is_dir()
        else:
            mount_point = cfg.get("unix", {}).get("mount_point", "")
            if mount_point:
                mount_path = Path(mount_point).expanduser()
                # Check if something is mounted there
                if mount_path.exists():
                    # On Unix, check if it's a mount point
                    try:
                        result = subprocess.run(
                            ["mountpoint", "-q", str(mount_path)],
                            capture_output=True
                        )
                        return result.returncode == 0
                    except FileNotFoundError:
                        # mountpoint command not available, check if dir has content
                        return any(mount_path.iterdir())
            return False
    except Exception:
        return None

# ============================================================
# ACTION HANDLERS
# ============================================================

def run_script(script_name: str, args: list = None):
    """Run a Python script from the scripts directory."""
    script_path = SCRIPT_DIR / script_name
    
    if not script_path.exists():
        print(f"\n❌ Error: Script not found: {script_path}")
        input("\nPress Enter to continue...")
        return False
    
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    
    print(f"\n{'─' * 70}")
    print(f"Running: {script_name}")
    print("─" * 70 + "\n")
    
    try:
        result = subprocess.run(cmd, cwd=str(SCRIPT_DIR))
        print("\n" + "─" * 70)
        if result.returncode == 0:
            print(f"✓ {script_name} completed successfully")
        else:
            print(f"⚠️ {script_name} exited with code {result.returncode}")
        print("─" * 70)
    except KeyboardInterrupt:
        print("\n\n⚠️ Operation cancelled by user")
    except Exception as e:
        print(f"\n❌ Error running {script_name}: {e}")
    
    input("\nPress Enter to continue...")
    return True

def show_config_status():
    """Display current configuration and status."""
    clear_screen()
    print_banner()
    print("\n" + "─" * 70)
    print("  CONFIGURATION & STATUS")
    print("─" * 70 + "\n")
    
    # Context
    context = detect_context()
    print(f"  Context:      {context}")
    print(f"  Script dir:   {SCRIPT_DIR}")
    print(f"  Keys dir:     {KEYS_DIR}")
    print()
    
    # Config file
    cfg = {}
    if CONFIG_FILE.exists():
        print(f"  ✓ Config:     {CONFIG_FILE.name}")
        try:
            import json
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            
            # Drive name
            drive_name = cfg.get("drive_name")
            if drive_name:
                print(f"    Name:       {drive_name}")
            else:
                print(f"    Name:       Not set (use option below to set)")
            
            # Security mode
            security_mode = cfg.get("security_mode", "unknown")
            mode_display = get_security_mode_display(security_mode)
            print(f"    Security:   {mode_display}")
            
            # Setup date
            setup_date = cfg.get("setup_date")
            if setup_date:
                print(f"    Setup:      {setup_date}")
            
            # Last password change
            last_pw = cfg.get("last_password_change")
            if last_pw:
                try:
                    from datetime import datetime
                    last_change = datetime.strptime(last_pw, "%Y-%m-%d")
                    days_ago = (datetime.now() - last_change).days
                    if days_ago > 90:
                        print(f"    Password:   {last_pw} (⚠️ {days_ago} days - consider rotating)")
                    else:
                        print(f"    Password:   {last_pw} ({days_ago} days ago)")
                except:
                    print(f"    Password:   {last_pw}")
            
            print()
            
            system = platform.system().lower()
            if system == "windows":
                vol_path = cfg.get("windows", {}).get("volume_path", "Not set")
                mount_letter = cfg.get("windows", {}).get("mount_letter", "V")
                print(f"    Volume:     {vol_path}")
                print(f"    Mount:      {mount_letter}:")
            else:
                vol_path = cfg.get("unix", {}).get("volume_path", "Not set")
                mount_point = cfg.get("unix", {}).get("mount_point", "Not set")
                print(f"    Volume:     {vol_path}")
                print(f"    Mount:      {mount_point}")
            
            keyfile = cfg.get("encrypted_keyfile", "")
            if keyfile:
                print(f"    Keyfile:    {keyfile} (GPG encrypted)")
            else:
                plain_keyfile = cfg.get("keyfile", "")
                if plain_keyfile:
                    print(f"    Keyfile:    {plain_keyfile} (plain)")
                else:
                    print(f"    Keyfile:    None (password-only mode)")
        except Exception as e:
            print(f"    ⚠️ Error reading config: {e}")
    else:
        print(f"  ✗ Config:     Not found")
    
    print()
    
    # Encrypted keyfile
    if KEYS_DIR.exists():
        gpg_files = list(KEYS_DIR.glob("*.gpg"))
        if gpg_files:
            print(f"  ✓ Keyfiles:   {len(gpg_files)} encrypted keyfile(s)")
            for gpg in gpg_files:
                print(f"                - {gpg.name}")
        else:
            print(f"  ✗ Keyfiles:   No encrypted keyfiles found")
    else:
        print(f"  ✗ Keys dir:   Not found")
    
    print()
    
    # Mount status
    is_mounted = check_mount_status()
    if is_mounted is True:
        print(f"  ✓ Volume:     MOUNTED")
    elif is_mounted is False:
        print(f"  ✗ Volume:     Not mounted")
    else:
        print(f"  ? Volume:     Status unknown")
    
    print("\n" + "─" * 70)
    
    # Option to set drive name
    if CONFIG_FILE.exists():
        print("\n  [N] Set/change drive name")
        print("  [Enter] Back to menu")
        choice = input("\n  > ").strip().lower()
        
        if choice == 'n':
            set_drive_name()
    else:
        input("\nPress Enter to continue...")

def set_drive_name():
    """Set or change the drive name in config."""
    import json
    
    if not CONFIG_FILE.exists():
        print("\n  ❌ No config.json found")
        input("\n  Press Enter to continue...")
        return
    
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        
        current_name = cfg.get("drive_name", "")
        print(f"\n  Current name: {current_name or '(not set)'}")
        print("  Enter new name (or press Enter to cancel):")
        new_name = input("  > ").strip()
        
        if new_name:
            cfg["drive_name"] = new_name
            with open(CONFIG_FILE, 'w') as f:
                json.dump(cfg, f, indent=2)
            print(f"\n  ✓ Drive name set to: {new_name}")
        else:
            print("\n  Cancelled.")
    except Exception as e:
        print(f"\n  ❌ Error: {e}")
    
    input("\n  Press Enter to continue...")

# ============================================================
# README DOCUMENTATION VIEWER
# ============================================================

# Try to import Rich for beautiful markdown rendering
RICH_AVAILABLE = False
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    pass

def find_readme() -> Path:
    """Find README.md in project structure."""
    # Try various locations
    candidates = [
        SCRIPT_DIR.parent / "README.md",  # Standard location
        SCRIPT_DIR / "README.md",          # In scripts folder
        Path.cwd() / "README.md",          # Current directory
        Path.cwd().parent / "README.md",   # Parent directory
    ]
    
    for path in candidates:
        if path.exists():
            return path
    return None

def show_documentation_rich(readme_path: Path):
    """Display README.md using Rich library for beautiful rendering."""
    console = Console()
    
    try:
        with open(readme_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        console.print(f"[red]Error reading README: {e}[/red]")
        input("\nPress Enter to continue...")
        return
    
    # Split into sections for paginated viewing
    sections = []
    current_section = []
    current_title = "Introduction"
    
    for line in content.split('\n'):
        if line.startswith('## '):
            if current_section:
                sections.append((current_title, '\n'.join(current_section)))
            current_title = line[3:].strip()
            current_section = [line]
        else:
            current_section.append(line)
    
    if current_section:
        sections.append((current_title, '\n'.join(current_section)))
    
    current_idx = 0
    
    while True:
        console.clear()
        
        # Header
        console.print(Panel(
            Text("📖 SmartDrive Documentation", justify="center", style="bold cyan"),
            style="cyan"
        ))
        
        if sections:
            title, section_content = sections[current_idx]
            
            # Section indicator
            console.print(f"\n[dim]Section {current_idx + 1} of {len(sections)}[/dim]")
            console.print()
            
            # Render markdown
            md = Markdown(section_content)
            console.print(md)
        
        # Navigation footer
        console.print("\n" + "─" * 70)
        console.print("[bold]Navigation:[/bold]")
        nav_options = []
        if current_idx > 0:
            nav_options.append("[b] Previous section")
        if current_idx < len(sections) - 1:
            nav_options.append("[Enter/n] Next section")
        nav_options.append("[t] Table of contents")
        nav_options.append("[q] Quit")
        console.print("  " + "  │  ".join(nav_options))
        console.print("─" * 70)
        
        choice = input("  > ").strip().lower()
        
        if choice == 'q':
            break
        elif choice == 'b' and current_idx > 0:
            current_idx -= 1
        elif choice == 't':
            show_toc_rich(console, sections)
            # Let user jump to a section
            try:
                jump = input("\n  Jump to section (1-{}) or Enter to cancel: ".format(len(sections))).strip()
                if jump.isdigit():
                    idx = int(jump) - 1
                    if 0 <= idx < len(sections):
                        current_idx = idx
            except:
                pass
        elif choice in ('', 'n') and current_idx < len(sections) - 1:
            current_idx += 1

def show_toc_rich(console, sections: list):
    """Show table of contents with Rich."""
    console.clear()
    console.print(Panel(
        Text("📑 Table of Contents", justify="center", style="bold cyan"),
        style="cyan"
    ))
    console.print()
    
    for i, (title, _) in enumerate(sections, 1):
        console.print(f"  [bold cyan]{i:2}.[/bold cyan] {title}")
    
    console.print("\n" + "─" * 70)

def format_markdown_line(line: str, in_code_block: bool, in_table: bool) -> tuple:
    """
    Format a single markdown line for terminal display (fallback mode).
    Returns (formatted_line, in_code_block, in_table).
    """
    import re
    stripped = line.rstrip()
    
    # Code block handling
    if stripped.startswith("```"):
        if in_code_block:
            return ("  └" + "─" * 66 + "┘", False, in_table)
        else:
            lang = stripped[3:].strip() or "code"
            return ("  ┌" + f"─ {lang} " + "─" * (64 - len(lang)) + "┐", True, in_table)
    
    if in_code_block:
        # Inside code block - show with indent and border
        content = line.rstrip()[:64]
        return (f"  │ {content:<64} │", True, in_table)
    
    # Table detection
    if "|" in stripped and stripped.startswith("|"):
        return (f"  {stripped}", in_code_block, True)
    elif in_table and not stripped.startswith("|") and stripped:
        in_table = False
    
    # Headers
    if stripped.startswith("# "):
        title = stripped[2:]
        return ("\n" + "═" * 70 + f"\n  {title.upper()}\n" + "═" * 70, in_code_block, in_table)
    elif stripped.startswith("## "):
        title = stripped[3:]
        return ("\n" + "─" * 70 + f"\n  {title}\n" + "─" * 70, in_code_block, in_table)
    elif stripped.startswith("### "):
        title = stripped[4:]
        return (f"\n  ▸ {title}\n", in_code_block, in_table)
    elif stripped.startswith("#### "):
        title = stripped[5:]
        return (f"\n    ▹ {title}", in_code_block, in_table)
    
    # Horizontal rules
    if stripped in ("---", "***", "___"):
        return ("\n" + "─" * 70 + "\n", in_code_block, in_table)
    
    # List items
    if stripped.startswith("- "):
        return (f"    • {stripped[2:]}", in_code_block, in_table)
    if stripped.startswith("* "):
        return (f"    • {stripped[2:]}", in_code_block, in_table)
    
    # Numbered lists
    for i in range(1, 10):
        if stripped.startswith(f"{i}. "):
            return (f"    {i}. {stripped[3:]}", in_code_block, in_table)
    
    # Bold and emphasis (simple replacement)
    result = stripped
    # **bold** → BOLD
    result = re.sub(r'\*\*([^*]+)\*\*', lambda m: m.group(1).upper(), result)
    # *italic* → _italic_
    result = re.sub(r'\*([^*]+)\*', r'_\1_', result)
    # `code` → [code]
    result = re.sub(r'`([^`]+)`', r'[\1]', result)
    
    # Regular paragraph
    if result:
        return (f"  {result}", in_code_block, in_table)
    else:
        return ("", in_code_block, in_table)

def show_documentation_fallback(readme_path: Path):
    """Display README.md with basic formatting (no Rich library)."""
    try:
        with open(readme_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"\n  Error reading README: {e}")
        input("\n  Press Enter to continue...")
        return
    
    # Format all lines
    formatted_lines = []
    in_code_block = False
    in_table = False
    
    for line in lines:
        formatted, in_code_block, in_table = format_markdown_line(line, in_code_block, in_table)
        if formatted:
            formatted_lines.append(formatted)
    
    # Pagination
    terminal_height = 30  # Approximate lines per page
    total_lines = len(formatted_lines)
    current_line = 0
    
    while current_line < total_lines:
        clear_screen()
        print("═" * 70)
        print("  📖 SmartDrive Documentation")
        if not RICH_AVAILABLE:
            print("  [Tip: Install 'rich' package for better rendering: pip install rich]")
        print("═" * 70)
        
        # Show a page of content
        page_end = min(current_line + terminal_height - 6, total_lines)
        for i in range(current_line, page_end):
            print(formatted_lines[i])
        
        # Navigation footer
        print("\n" + "─" * 70)
        progress = f"Line {current_line + 1}-{page_end} of {total_lines}"
        print(f"  {progress}")
        print("  [Enter] Next page  [b] Back  [q] Quit  [t] Table of contents")
        print("─" * 70)
        
        choice = input("  > ").strip().lower()
        
        if choice == 'q':
            break
        elif choice == 'b':
            current_line = max(0, current_line - terminal_height + 6)
        elif choice == 't':
            show_table_of_contents(formatted_lines)
            current_line = 0  # Reset to start after TOC
        else:
            current_line = page_end

def show_documentation():
    """Display README.md - uses Rich if available, otherwise fallback."""
    readme_path = find_readme()
    
    if not readme_path:
        clear_screen()
        print_banner()
        print("\n" + "─" * 70)
        print("  README NOT FOUND")
        print("─" * 70 + "\n")
        print("  Could not find README.md in the expected locations.")
        print("\n  Searched in:")
        print(f"    • {SCRIPT_DIR.parent / 'README.md'}")
        print(f"    • {SCRIPT_DIR / 'README.md'}")
        print(f"    • {Path.cwd() / 'README.md'}")
        input("\n  Press Enter to continue...")
        return
    
    if RICH_AVAILABLE:
        show_documentation_rich(readme_path)
    else:
        show_documentation_fallback(readme_path)

def show_table_of_contents(lines: list):
    """Show a table of contents extracted from headers (fallback mode)."""
    clear_screen()
    print("═" * 70)
    print("  📑 TABLE OF CONTENTS")
    print("═" * 70 + "\n")
    
    toc = []
    for i, line in enumerate(lines):
        if line.strip().startswith("═") and i + 1 < len(lines):
            # Main header (##)
            next_line = lines[i + 1].strip()
            if next_line and not next_line.startswith("═") and not next_line.startswith("─"):
                toc.append(f"  {next_line}")
        elif line.strip().startswith("  ▸ "):
            # Subheader (###)
            toc.append(f"    {line.strip()}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_toc = []
    for item in toc:
        if item not in seen:
            seen.add(item)
            unique_toc.append(item)
    
    for item in unique_toc[:40]:  # Limit to 40 items
        print(item)
    
    if len(unique_toc) > 40:
        print(f"\n  ... and {len(unique_toc) - 40} more sections")
    
    print("\n" + "─" * 70)
    input("  Press Enter to return to documentation...")

def show_help():
    """Display help - either README or basic help."""
    readme_path = find_readme()
    
    if readme_path:
        # Show full README with pagination
        show_documentation()
    else:
        # Fallback to basic help
        clear_screen()
        print_banner()
        print("\n" + "─" * 70)
        print("  HELP & DOCUMENTATION")
        print("─" * 70 + "\n")
        
        print("""
  SmartDrive creates encrypted external drives with optional YubiKey 2FA.

  SECURITY MODES:
  ───────────────
  • Password-only:     VeraCrypt password protection
  • Plain keyfile:     Password + unencrypted keyfile
  • YubiKey + GPG:     Password + YubiKey-encrypted keyfile (recommended)

  TYPICAL WORKFLOW:
  ─────────────────
  1. Run setup.py to prepare a new external drive
  2. Use mount.py to mount the encrypted volume
  3. Use unmount.py when done
  4. Use rekey.py to change password or rotate keyfiles

  FILES:
  ──────
  • config.json        Volume path and mount settings
  • keyfile.vc.gpg     GPG-encrypted keyfile (if using YubiKey mode)
  
  For full documentation, see README.md in the project root.
""")
        
        print("─" * 70)
        input("\nPress Enter to continue...")

# ============================================================
# INTEGRITY VERIFICATION (GPG Signature)
# ============================================================

import hashlib
import shutil

def have_gpg() -> bool:
    """Check if GPG is available."""
    return shutil.which("gpg") is not None

def calculate_scripts_hash() -> str:
    """Calculate SHA256 hash of all script files."""
    hash_obj = hashlib.sha256()
    
    # List of scripts to hash (in consistent order)
    # Only include scripts that are deployed to LAUNCHER partition
    # (setup.py is NOT deployed, so it's excluded)
    scripts = sorted([
        "smartdrive.py", "mount.py", "unmount.py", 
        "rekey.py", "keyfile.py"
    ])
    
    for script_name in scripts:
        script_path = SCRIPT_DIR / script_name
        if script_path.exists():
            # Include filename in hash to detect renames
            hash_obj.update(script_name.encode('utf-8'))
            with open(script_path, 'rb') as f:
                hash_obj.update(f.read())
    
    return hash_obj.hexdigest()

def generate_challenge_hash():
    """Generate a salted hash for remote verification."""
    clear_screen()
    print_banner()
    print("\n" + "─" * 70)
    print("  🔐 CHALLENGE HASH GENERATION (Remote Verification)")
    print("─" * 70 + "\n")
    
    print("This generates a salted hash of your ENTIRE scripts directory for secure remote verification.")
    print("The process ensures that:")
    print("• No one can pre-compute the correct hash")
    print("• Tampered scripts cannot generate valid hashes")
    print("• Verification requires manual server interaction")
    print()
    
    # Get salt from user
    print("Enter the salt/challenge from the verification server:")
    salt = input("Salt: ").strip()
    
    if not salt:
        print("\n❌ No salt provided.")
        input("\nPress Enter to continue...")
        return
    
    # Save salt to a file in the scripts directory
    salt_file = SCRIPT_DIR / ".challenge_salt"
    try:
        with open(salt_file, 'w') as f:
            f.write(salt)
        print(f"✅ Salt saved to: {salt_file}")
    except Exception as e:
        print(f"❌ Error saving salt file: {e}")
        input("\nPress Enter to continue...")
        return
    
    # Hash the entire scripts directory INCLUDING the salt file
    try:
        challenge_hash = hash_directory_with_salt(SCRIPT_DIR)
        print("\n" + "═" * 70)
        print("  ✅ DIRECTORY HASH GENERATED")
        print("═" * 70)
        print(f"\nDirectory: {SCRIPT_DIR}")
        print(f"Salt file:  {salt_file}")
        print(f"Result:     {challenge_hash}")
        print()
        print("Submit this result to your verification server:")
        print(f"  {challenge_hash}")
        print()
        print("⚠️  IMPORTANT: The server must hash the same directory")
        print("   with the same salt file to verify.")
        
    except Exception as e:
        print(f"❌ Error generating hash: {e}")
    finally:
        # Clean up salt file
        try:
            if salt_file.exists():
                salt_file.unlink()
                print(f"✅ Salt file cleaned up: {salt_file}")
        except Exception as e:
            print(f"⚠️  Warning: Could not clean up salt file: {e}")
    
    input("\nPress Enter to continue...")

def hash_directory_with_salt(dir_path: Path) -> str:
    """Hash an entire directory recursively, including all files."""
    hash_obj = hashlib.sha256()
    
    # Get all files in sorted order for consistent hashing
    all_files = []
    for root, dirs, files in os.walk(dir_path):
        # Skip certain directories
        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git']]
        for file in files:
            # Skip temporary files and certain extensions
            if not file.startswith('.') or file == '.challenge_salt':
                all_files.append(os.path.join(root, file))
    
    all_files.sort()
    
    for file_path in all_files:
        # Include relative path in hash to detect file moves
        rel_path = os.path.relpath(file_path, dir_path)
        hash_obj.update(rel_path.encode('utf-8'))
        hash_obj.update(b'\x00')  # Separator
        
        try:
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    hash_obj.update(chunk)
        except (OSError, IOError) as e:
            # Skip files that can't be read
            hash_obj.update(f"[ERROR: {e}]".encode('utf-8'))
        
        hash_obj.update(b'\x00')  # File separator
    
    return hash_obj.hexdigest()

def get_hash_file_path() -> Path:
    """Get path to the hash file."""
    return INTEGRITY_DIR / "scripts.sha256"

def get_signature_file_path() -> Path:
    """Get path to the signature file."""
    return INTEGRITY_DIR / "scripts.sha256.sig"

def verify_integrity():
    """Verify script integrity using GPG signature."""
    clear_screen()
    print_banner()
    print("\n" + "─" * 70)
    print("  🔍 SCRIPT INTEGRITY VERIFICATION")
    print("─" * 70 + "\n")
    
    hash_file = get_hash_file_path()
    sig_file = get_signature_file_path()
    
    # Check if signature files exist
    if not hash_file.exists():
        print("  ❌ Hash file not found: scripts.sha256")
        print("     Scripts have not been signed yet.")
        print("\n     To sign scripts, run from System menu or use:")
        print("     gpg --detach-sign scripts.sha256")
        input("\n  Press Enter to continue...")
        return
    
    if not sig_file.exists():
        print("  ❌ Signature file not found: scripts.sha256.sig")
        print("     Scripts have not been signed yet.")
        print("\n     To sign scripts, run from System menu or use:")
        print("     gpg --detach-sign scripts.sha256")
        input("\n  Press Enter to continue...")
        return
    
    if not have_gpg():
        print("  ❌ GPG not found in PATH")
        print("     Cannot verify signature without GPG installed.")
        input("\n  Press Enter to continue...")
        return
    
    print("  Checking integrity...\n")
    
    # Step 1: Verify GPG signature
    print("  Step 1: Verifying GPG signature...")
    signature_time = None
    signer_info = None
    
    try:
        result = subprocess.run(
            ["gpg", "--verify", str(sig_file), str(hash_file)],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("  ✅ GPG signature is VALID")
            # Extract signer info and timestamp from stderr (GPG outputs to stderr)
            for line in result.stderr.split('\n'):
                if 'Good signature' in line:
                    signer_info = line.strip()
                    print(f"     {signer_info}")
                elif 'Signature made' in line:
                    signature_time = line.strip()
                    print(f"     {signature_time}")
                elif 'using' in line and 'key' in line.lower():
                    print(f"     {line.strip()}")
        else:
            print("  ❌ GPG signature is INVALID!")
            print("\n  ⚠️  WARNING: Scripts may have been tampered with!")
            print("     Do NOT use these scripts!")
            print("\n  GPG output:")
            for line in result.stderr.split('\n'):
                if line.strip():
                    print(f"     {line}")
            input("\n  Press Enter to continue...")
            return
    except Exception as e:
        print(f"  ❌ Error verifying signature: {e}")
        input("\n  Press Enter to continue...")
        return
    
    # Step 2: Verify file hashes match
    print("\n  Step 2: Verifying file hashes...")
    
    # Read stored hash
    try:
        with open(hash_file, 'r') as f:
            stored_data = f.read().strip()
        stored_hash = stored_data.split()[0]  # Format: "hash  filename" or just "hash"
    except Exception as e:
        print(f"  ❌ Error reading hash file: {e}")
        input("\n  Press Enter to continue...")
        return
    
    # Calculate current hash
    current_hash = calculate_scripts_hash()
    
    if current_hash == stored_hash:
        print("  ✅ File hashes MATCH")
        print(f"     Hash: {current_hash[:16]}...{current_hash[-16:]}")
    else:
        print("  ❌ File hashes DO NOT MATCH!")
        print("\n  ⚠️  WARNING: Scripts have been modified!")
        print("     Do NOT use these scripts!")
        print(f"\n     Expected: {stored_hash[:32]}...")
        print(f"     Got:      {current_hash[:32]}...")
        input("\n  Press Enter to continue...")
        return
    
        return
    
    # Step 3: Manual salted hash generation for remote verification
    print("\n  Step 3: Manual verification hash generation")
    print("     For secure remote verification, use the 'Generate Challenge Hash' option")
    print("     from the main menu to create a salted hash for server verification.")
    
    # All checks passed
    print("\n" + "═" * 70)
    print("  ✅ INTEGRITY CHECK PASSED")
    print("     Scripts are authentic and unmodified.")
    print("     (Local verification only)")
    print("═" * 70)
    
    # Show timestamp warning
    print("\n" + "─" * 70)
    print("  ⚠️  IMPORTANT: Check the signature timestamp above!")
    print("─" * 70)
    print("""
  A valid signature only proves the scripts were signed by YOUR key.
  If an attacker had access while your YubiKey was plugged in, they
  could have modified scripts AND re-signed them.

  Ask yourself:
  • Does the signature timestamp match when YOU last signed?
  • Has anyone else had access to this drive + your YubiKey?

  PROTECTION: Enable touch requirement for GPG signing:
    ykman openpgp keys set-touch sig on

  This prevents signing without physical touch, even if YubiKey
  is plugged in.
""")
    
    input("  Press Enter to continue...")

def sign_scripts():
    """Sign scripts with GPG (creates hash + signature)."""
    clear_screen()
    print_banner()
    print("\n" + "─" * 70)
    print("  ✍️  SIGN SCRIPTS (Create Integrity Signature)")
    print("─" * 70 + "\n")
    
    if not have_gpg():
        print("  ❌ GPG not found in PATH")
        print("     Cannot sign without GPG installed.")
        input("\n  Press Enter to continue...")
        return
    
    # Ensure integrity directory exists
    INTEGRITY_DIR.mkdir(parents=True, exist_ok=True)
    
    hash_file = get_hash_file_path()
    sig_file = get_signature_file_path()
    
    print("  This will:")
    print("  1. Calculate SHA256 hash of all scripts")
    print("  2. Sign the hash with your GPG key (requires YubiKey if configured)")
    print()
    print(f"  Output files:")
    print(f"    • {hash_file}")
    print(f"    • {sig_file}")
    print()
    
    # Show available GPG keys
    print("  Available GPG signing keys:")
    try:
        result = subprocess.run(
            ["gpg", "--list-secret-keys", "--keyid-format", "LONG"],
            capture_output=True,
            text=True
        )
        
        keys_found = False
        for line in result.stdout.split('\n'):
            if 'sec' in line or 'uid' in line:
                print(f"    {line}")
                keys_found = True
        
        if not keys_found:
            print("    No secret keys found!")
            print("    You need a GPG key to sign scripts.")
            input("\n  Press Enter to continue...")
            return
    except Exception as e:
        print(f"    Error listing keys: {e}")
    
    print()
    confirm = input("  Sign scripts now? [y/N]: ").strip().lower()
    
    if confirm != 'y':
        print("\n  Cancelled.")
        input("\n  Press Enter to continue...")
        return
    
    # Step 1: Calculate and save hash
    print("\n  Step 1: Calculating hash...")
    current_hash = calculate_scripts_hash()
    
    try:
        with open(hash_file, 'w') as f:
            f.write(f"{current_hash}  scripts\n")
        print(f"  ✅ Hash saved: {hash_file.name}")
        print(f"     {current_hash}")
    except Exception as e:
        print(f"  ❌ Error saving hash: {e}")
        input("\n  Press Enter to continue...")
        return
    
    # Step 2: Sign with GPG
    print("\n  Step 2: Signing with GPG...")
    print("  (You may be prompted to insert YubiKey or enter PIN)")
    
    try:
        # Remove old signature if exists
        if sig_file.exists():
            sig_file.unlink()
        
        result = subprocess.run(
            ["gpg", "--detach-sign", str(hash_file)],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and sig_file.exists():
            print(f"  ✅ Signature created: {sig_file.name}")
        else:
            print(f"  ❌ Signing failed!")
            if result.stderr:
                print(f"     {result.stderr}")
            input("\n  Press Enter to continue...")
            return
    except Exception as e:
        print(f"  ❌ Error signing: {e}")
        input("\n  Press Enter to continue...")
        return
    
    # Success
    print("\n" + "═" * 70)
    print("  ✅ SCRIPTS SIGNED SUCCESSFULLY")
    print()
    print("  To verify on any machine with your public key:")
    print("    gpg --verify scripts.sha256.sig scripts.sha256")
    print("═" * 70)
    
    input("\n  Press Enter to continue...")

def keyfile_utilities_menu():
    """Handle keyfile utilities submenu."""
    while True:
        clear_screen()
        print_banner()
        print_keyfile_menu()
        
        choice = input("\n  Select option [0-3]: ").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            run_script("keyfile.py", ["create"])
        elif choice == "2":
            # Ask for file to decrypt
            print("\n  Enter path to encrypted keyfile")
            print("  (or press Enter for default: ../keys/keyfile.vc.gpg)")
            filepath = input("  Path: ").strip()
            if not filepath:
                filepath = str(KEYS_DIR / "keyfile.vc.gpg")
            run_script("keyfile.py", ["decrypt", filepath])
        elif choice == "3":
            print("\n  Enter path to file to encrypt:")
            filepath = input("  Path: ").strip()
            if filepath:
                run_script("keyfile.py", ["encrypt", filepath])
            else:
                print("\n  ⚠️ No file specified")
                input("\n  Press Enter to continue...")
        else:
            print("\n  ⚠️ Invalid option")
            input("\n  Press Enter to continue...")

def recovery_menu():
    """Recovery kit management submenu."""
    while True:
        clear_screen()
        print_banner()
        print("\n" + "─" * 70)
        print("  RECOVERY KIT MANAGEMENT")
        print("─" * 70 + "\n")
        
        # Check current recovery status
        recovery_status = None
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    cfg = json.load(f)
                recovery_status = cfg.get("recovery", {})
            except:
                pass
        
        if recovery_status and recovery_status.get("enabled"):
            print("  Status: ✅ Recovery Kit ENABLED")
            print(f"  Created: {recovery_status.get('created_date', 'Unknown')}")
            events = recovery_status.get("recovery_events", [])
            if events:
                print(f"  Used: {len(events)} time(s)")
                last_event = events[-1]
                print(f"  Last: {last_event.get('date')} - {last_event.get('reason')}")
        else:
            print("  Status: ❌ Recovery Kit NOT enabled")
            print("  ")
            print("  A recovery kit allows emergency access if you lose your")
            print("  YubiKey or password. It's a 24-word phrase that grants")
            print("  ONE-TIME access to your drive.")
        
        print("\n" + "─" * 70)
        print()
        print("  [1] Generate new recovery kit")
        print("  [2] Check recovery status")
        if recovery_status and recovery_status.get("enabled"):
            print("  [3] Use recovery phrase (EMERGENCY)")
        print("  [0] Back to main menu")
        print()
        
        choice = input("  Select option: ").strip()
        
        if choice == "0":
            break
        elif choice == "1":
            run_script("recovery.py", ["generate"])
        elif choice == "2":
            run_script("recovery.py", ["status"])
        elif choice == "3" and recovery_status and recovery_status.get("enabled"):
            print("\n  ⚠️  WARNING: This will use your one-time recovery phrase!")
            print("  Only proceed if you have lost access through normal means.")
            confirm = input("\n  Continue? [y/N]: ").strip().lower()
            if confirm == 'y':
                run_script("recovery.py", ["recover"])
        else:
            print("\n  ⚠️ Invalid option")
            input("\n  Press Enter to continue...")

def update_deployment_drive_menu():
    """Update deployment drive with latest SmartDrive files."""
    print("\n" + "─" * 70)
    print("  UPDATE DEPLOYMENT DRIVE")
    print("─" * 70 + "\n")
    
    print("This will update an external drive with the latest SmartDrive scripts")
    print("and documentation from your development environment.\n")
    
    print("⚠️  IMPORTANT:")
    print("  • User data (keys, recovery kits, integrity files) will NOT be overwritten")
    print("  • Scripts, README, and documentation will be updated")
    print("  • config.json version metadata will be updated to current version")
    print("  • Make sure the target drive is not currently mounted\n")
    
    confirm = input("Continue with update? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("Update cancelled.")
        input("\nPress Enter to continue...")
        return
    
    # Call the update function
    try:
        success = update_deployment_drive()
        if success:
            print("\n✓ Update completed successfully!")
        else:
            print("\n⚠️ Update completed with warnings/errors.")
    except Exception as e:
        print(f"\n❌ Update failed: {e}")
    
    input("\nPress Enter to continue...")

# ============================================================
# MAIN MENU LOOPS
# ============================================================

def main_menu_launcher():
    """Main menu for LAUNCHER context."""
    while True:
        clear_screen()
        is_mounted = check_mount_status()
        print_banner()
        print_status("LAUNCHER", is_mounted)
        print_menu_launcher()
        
        choice = input("\n  Select option [0-10]: ").strip()
        
        if choice == "0":
            print("\n  Goodbye! 👋\n")
            break
        elif choice == "1":
            run_script("mount.py")
        elif choice == "2":
            run_script("unmount.py")
        elif choice == "3":
            run_script("rekey.py")
        elif choice == "4":
            keyfile_utilities_menu()
        elif choice == "5":
            show_config_status()
        elif choice == "6":
            recovery_menu()
        elif choice == "7":
            sign_scripts()
        elif choice == "8":
            verify_integrity()
        elif choice == "9":
            generate_challenge_hash()
        elif choice == "10":
            show_help()
        else:
            print("\n  ⚠️ Invalid option")
            input("\n  Press Enter to continue...")

def main_menu_system():
    """Main menu for SYSTEM context."""
    while True:
        clear_screen()
        print_banner()
        print_status("SYSTEM")
        print_menu_system()
        
        choice = input("\n  Select option [0-5]: ").strip()
        
        if choice == "0":
            print("\n  Goodbye! 👋\n")
            break
        elif choice == "1":
            run_script("setup.py")
        elif choice == "2":
            keyfile_utilities_menu()
        elif choice == "3":
            sign_scripts()
        elif choice == "4":
            show_help()
        elif choice == "5":
            update_deployment_drive_menu()
        else:
            print("\n  ⚠️ Invalid option")
            input("\n  Press Enter to continue...")

# ============================================================
# ENTRY POINT
# ============================================================

def main():
    """Main entry point."""
    try:
        context = detect_context()
        
        if context == "LAUNCHER":
            main_menu_launcher()
        else:
            main_menu_system()
    
    except KeyboardInterrupt:
        print("\n\n  Goodbye! 👋\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)

if __name__ == "__main__":
    main()
