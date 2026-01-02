#!/usr/bin/env python3
"""
Bootstrap Dependencies for KeyDrive

CHG-20251229-002: Platform-independent dependency installation.

This script checks for required Python packages and offers to install
them from the bundled requirements.txt if missing. If dependencies are
missing, it creates a virtual environment and installs all packages there.

Design:
- Auto-creates .smartdrive/.venv if dependencies missing
- Installs from bundled requirements.txt into venv
- Works with system Python as fallback
- Provides clear OS-specific messages
- Non-interactive mode for automated deployments
- Returns exit code 0 if all deps installed, 1 if missing and not installed

Usage:
    python bootstrap_dependencies.py           # Interactive mode
    python bootstrap_dependencies.py --check   # Check only, no install
    python bootstrap_dependencies.py --auto    # Auto-install if missing
    python bootstrap_dependencies.py --venv    # Force venv creation even if deps exist
"""

import subprocess
import sys
import venv
from pathlib import Path

# Import SSOT constants - must be available before venv is created
try:
    from core.limits import Limits

    IMPORT_CHECK_TIMEOUT = Limits.POWERSHELL_QUICK_TIMEOUT
except ImportError:
    # Fallback if core modules not available yet (first bootstrap)
    IMPORT_CHECK_TIMEOUT = 10

# Minimum required Python packages to check before full requirements install
# These are the critical packages needed to even show a GUI error message
CRITICAL_PACKAGES = [
    ("PyQt6", "PyQt6.QtCore"),  # (package_name, import_name)
]

# Full package list for checking (import_name may differ from package_name)
REQUIRED_PACKAGES = [
    ("PyQt6", "PyQt6.QtCore"),
    ("cryptography", "cryptography"),
    ("markdown", "markdown"),
    ("reportlab", "reportlab"),
    ("argon2-cffi", "argon2"),
    ("mnemonic", "mnemonic"),
    ("qrcode", "qrcode"),
    ("pillow", "PIL"),
    ("colorama", "colorama"),
]


def get_platform_name() -> str:
    """Get platform name without external imports."""
    plat = sys.platform.lower()
    if plat.startswith("win"):
        return "Windows"
    elif plat.startswith("darwin"):
        return "macOS"
    elif plat.startswith("linux"):
        return "Linux"
    return plat.capitalize()


def is_package_installed(import_name: str) -> bool:
    """Check if a package can be imported."""
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


def check_packages() -> tuple[list[str], list[str]]:
    """
    Check which packages are missing.

    Returns:
        Tuple of (installed_packages, missing_packages)
    """
    installed = []
    missing = []

    for package_name, import_name in REQUIRED_PACKAGES:
        if is_package_installed(import_name):
            installed.append(package_name)
        else:
            missing.append(package_name)

    return installed, missing


def find_requirements_txt() -> Path | None:
    """Find the requirements.txt file in the expected location."""
    # Script is at .smartdrive/scripts/bootstrap_dependencies.py
    script_dir = Path(__file__).resolve().parent
    smartdrive_dir = script_dir.parent  # .smartdrive

    # Check for requirements.txt in .smartdrive root
    req_path = smartdrive_dir / "requirements.txt"
    if req_path.exists():
        return req_path

    return None


def _get_os_venv_dir_name() -> str:
    """
    Get the OS-specific venv directory name for the current platform.

    BUG-20260102-012: Returns .venv-win, .venv-linux, or .venv-mac based on OS.
    """
    platform = get_platform_name()
    if platform == "Windows":
        return ".venv-win"
    elif platform == "macOS":
        return ".venv-mac"
    else:  # Linux and other Unix-like
        return ".venv-linux"


def get_venv_path() -> Path:
    """
    Get the path to the venv directory.

    BUG-20260102-012: Uses OS-specific venv name, falls back to legacy .venv.
    """
    script_dir = Path(__file__).resolve().parent
    smartdrive_dir = script_dir.parent  # .smartdrive

    # Try OS-specific venv first
    os_venv_name = _get_os_venv_dir_name()
    os_venv_path = smartdrive_dir / os_venv_name
    if os_venv_path.exists():
        return os_venv_path

    # Fall back to legacy .venv
    legacy_venv_path = smartdrive_dir / ".venv"
    if legacy_venv_path.exists():
        return legacy_venv_path

    # Return OS-specific path for new venv creation
    return os_venv_path


def get_venv_python() -> Path | None:
    """Get the Python executable path in the venv."""
    venv_path = get_venv_path()
    if not venv_path.exists():
        return None

    platform = get_platform_name()
    if platform == "Windows":
        python_path = venv_path / "Scripts" / "python.exe"
    else:
        python_path = venv_path / "bin" / "python"

    return python_path if python_path.exists() else None


def create_venv(verbose: bool = True) -> bool:
    """
    Create a virtual environment at .smartdrive/{os-specific-venv}.

    BUG-20260102-012: Creates OS-specific venv directory.

    Args:
        verbose: Print progress messages

    Returns:
        True if venv created successfully, False otherwise
    """
    venv_path = get_venv_path()

    if venv_path.exists():
        if verbose:
            print(f"   ℹ️  Venv already exists at {venv_path}")
        return True

    if verbose:
        print(f"\n🔧 Creating virtual environment at {venv_path}...")

    try:
        # Create venv with pip enabled
        venv.create(venv_path, with_pip=True, upgrade_deps=True)
        if verbose:
            print(f"   ✓ Virtual environment created")
        return True
    except Exception as e:
        if verbose:
            print(f"   ❌ Failed to create venv: {e}")
        return False


def install_into_venv(requirements_path: Path, verbose: bool = True) -> bool:
    """
    Install packages from requirements.txt into the venv.

    Args:
        requirements_path: Path to requirements.txt
        verbose: Show installation output

    Returns:
        True if installation succeeded, False otherwise
    """
    venv_python = get_venv_python()
    if not venv_python:
        if verbose:
            print("   ❌ Venv Python not found")
        return False

    if verbose:
        print(f"\n📦 Installing dependencies into venv...")
        print(f"   Using: {venv_python}")
        print("=" * 60)

    try:
        cmd = [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "-r",
            str(requirements_path),
        ]

        if verbose:
            subprocess.run(cmd, check=True)
        else:
            subprocess.run(cmd, check=True, capture_output=True, text=True)

        if verbose:
            print("=" * 60)
            print("✅ Dependencies installed into venv!")

        return True

    except subprocess.CalledProcessError as e:
        if verbose:
            print(f"\n❌ Installation failed with error code {e.returncode}")
            if hasattr(e, "stderr") and e.stderr:
                print(f"Error: {e.stderr}")
        return False
    except FileNotFoundError:
        if verbose:
            print("\n❌ pip not found in venv.")
        return False


def check_venv_packages() -> tuple[list[str], list[str]]:
    """
    Check which packages are installed in the venv.

    Returns:
        Tuple of (installed_packages, missing_packages)
    """
    venv_python = get_venv_python()
    if not venv_python:
        return [], [pkg[0] for pkg in REQUIRED_PACKAGES]

    installed = []
    missing = []

    for package_name, import_name in REQUIRED_PACKAGES:
        # Check if package can be imported using venv python
        try:
            result = subprocess.run(
                [str(venv_python), "-c", f"import {import_name}"],
                capture_output=True,
                text=True,
                timeout=IMPORT_CHECK_TIMEOUT,
            )
            if result.returncode == 0:
                installed.append(package_name)
            else:
                missing.append(package_name)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            missing.append(package_name)

    return installed, missing

    return None


def install_from_requirements(requirements_path: Path, verbose: bool = True) -> bool:
    """
    Install packages from requirements.txt using pip.

    Args:
        requirements_path: Path to requirements.txt
        verbose: Show installation output

    Returns:
        True if installation succeeded, False otherwise
    """
    if verbose:
        print(f"\n📦 Installing dependencies from {requirements_path}...")
        print("=" * 60)

    try:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "-r",
            str(requirements_path),
        ]

        if verbose:
            result = subprocess.run(cmd, check=True)
        else:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)

        if verbose:
            print("=" * 60)
            print("✅ Dependencies installed successfully!")

        return True

    except subprocess.CalledProcessError as e:
        if verbose:
            print(f"\n❌ Installation failed with error code {e.returncode}")
            if e.stderr:
                print(f"Error: {e.stderr}")
        return False
    except FileNotFoundError:
        if verbose:
            print("\n❌ pip not found. Please ensure Python is properly installed.")
        return False


def print_manual_install_instructions(missing: list[str], requirements_path: Path | None):
    """Print OS-specific manual installation instructions."""
    platform = get_platform_name()

    print("\n" + "=" * 60)
    print("MISSING DEPENDENCIES")
    print("=" * 60)
    print(f"\nKeyDrive requires the following Python packages:\n")

    for pkg in missing:
        print(f"  • {pkg}")

    print("\n" + "-" * 60)
    print("INSTALLATION OPTIONS")
    print("-" * 60)

    if requirements_path:
        print(f"\n1. Install all dependencies at once (RECOMMENDED):\n")
        print(f'   pip install -r "{requirements_path}"\n')
    else:
        print(f"\n1. Install missing packages individually:\n")
        packages_str = " ".join(missing)
        print(f"   pip install {packages_str}\n")

    print(f"2. If using a virtual environment, activate it first:\n")
    if platform == "Windows":
        print(f"   .venv\\Scripts\\activate")
    else:
        print(f"   source .venv/bin/activate")

    print("\n" + "-" * 60)

    if platform == "Linux":
        print("Note for Linux users:")
        print("  If pip is not installed: sudo apt install python3-pip")
        print("  For system-wide install: sudo pip install ...")
    elif platform == "macOS":
        print("Note for macOS users:")
        print("  If pip is not installed: python3 -m ensurepip --upgrade")
        print("  Consider using brew: brew install python3")

    print("=" * 60 + "\n")


def main():
    """Main bootstrap function."""
    # Parse arguments
    check_only = "--check" in sys.argv
    auto_install = "--auto" in sys.argv
    force_venv = "--venv" in sys.argv
    quiet = "--quiet" in sys.argv or "-q" in sys.argv

    if not quiet:
        print("🔍 Checking KeyDrive dependencies...")

    # First check if venv exists and has all packages
    venv_python = get_venv_python()
    if venv_python:
        if not quiet:
            print(f"   Found venv at: {get_venv_path()}")
        installed, missing = check_venv_packages()
    else:
        # Fall back to system packages
        installed, missing = check_packages()

    if not quiet:
        print(f"   Installed: {len(installed)}/{len(REQUIRED_PACKAGES)}")
        if installed:
            print(f"   ✓ {', '.join(installed)}")
        if missing:
            print(f"   ✗ Missing: {', '.join(missing)}")

    if not missing and not force_venv:
        if not quiet:
            print("\n✅ All dependencies are installed!")
        return 0

    # Missing packages or force venv - handle based on mode
    requirements_path = find_requirements_txt()

    if check_only:
        print_manual_install_instructions(missing, requirements_path)
        return 1

    if auto_install or force_venv:
        if not requirements_path:
            if not quiet:
                print("\n❌ requirements.txt not found. Cannot auto-install.")
            return 1

        # Create venv if needed
        if not get_venv_python():
            if not create_venv(verbose=not quiet):
                if not quiet:
                    print("\n❌ Failed to create virtual environment.")
                return 1

        # Install into venv
        success = install_into_venv(requirements_path, verbose=not quiet)
        if success:
            # Verify installation
            _, still_missing = check_venv_packages()
            if still_missing:
                if not quiet:
                    print(f"\n⚠️  Some packages still missing: {', '.join(still_missing)}")
                return 1
            if not quiet:
                print(f"\n✅ Virtual environment ready at: {get_venv_path()}")
                platform = get_platform_name()
                if platform == "Windows":
                    print(f"   Activate with: .smartdrive\\.venv\\Scripts\\activate")
                else:
                    print(f"   Activate with: source .smartdrive/.venv/bin/activate")
            return 0
        return 1

    # Interactive mode
    if not requirements_path:
        print_manual_install_instructions(missing, None)
        return 1

    print(f"\n📦 Found requirements.txt at: {requirements_path}")
    print(f"\nKeyDrive will create a virtual environment and install dependencies.")
    print(f"   Location: {get_venv_path()}")

    try:
        response = input("\nCreate venv and install dependencies? [Y/n]: ").strip().lower()
        if response in ("", "y", "yes"):
            # Create venv if needed
            if not get_venv_python():
                if not create_venv(verbose=True):
                    print("\n❌ Failed to create virtual environment.")
                    return 1

            # Install into venv
            success = install_into_venv(requirements_path, verbose=True)
            if success:
                # Verify installation
                _, still_missing = check_venv_packages()
                if still_missing:
                    print(f"\n⚠️  Some packages still missing: {', '.join(still_missing)}")
                    return 1
                print(f"\n✅ Virtual environment ready!")
                print(f"   KeyDrive will automatically use this venv on next launch.")
                return 0
            return 1
        else:
            print("\nInstallation cancelled.")
            print_manual_install_instructions(missing, requirements_path)
            return 1
    except (KeyboardInterrupt, EOFError):
        print("\n\nCancelled.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
