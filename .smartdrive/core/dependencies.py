# core/dependencies.py - SINGLE SOURCE OF TRUTH for dependency checking
"""
Dependency checking and installation guidance for KeyDrive.

CHG-20251229-001: Provides clear OS-specific error messages and remediation hints
when dependencies are missing.

This module checks for:
- System tools: GPG, VeraCrypt
- Python packages: PyQt6, cryptography, markdown, etc.

Dependencies are checked at startup before GUI initialization.
"""

import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


def _get_platform_name() -> str:
    """Get platform name without importing the platform module.

    This avoids shadowing issues with core/platform.py.
    """
    # sys.platform is always available and doesn't require imports
    plat = sys.platform.lower()
    if plat.startswith("win"):
        return "Windows"
    elif plat.startswith("darwin"):
        return "Darwin"
    elif plat.startswith("linux"):
        return "Linux"
    else:
        return plat.capitalize()


@dataclass
class DependencyInfo:
    """Information about a dependency and how to install it."""

    name: str
    required_for: str  # e.g., "GUI", "encryption", "YubiKey"
    install_windows: str  # Windows installation instructions
    install_linux: str  # Linux installation instructions (Debian/Ubuntu)
    install_macos: str  # macOS installation instructions
    url: Optional[str] = None  # Download URL for more info


# Required Python packages for GUI operation
REQUIRED_PYTHON_PACKAGES = {
    "PyQt6": DependencyInfo(
        name="PyQt6",
        required_for="GUI",
        install_windows="pip install PyQt6",
        install_linux="pip install PyQt6",
        install_macos="pip install PyQt6",
        url="https://pypi.org/project/PyQt6/",
    ),
    "cryptography": DependencyInfo(
        name="cryptography",
        required_for="encryption",
        install_windows="pip install cryptography",
        install_linux="pip install cryptography",
        install_macos="pip install cryptography",
        url="https://pypi.org/project/cryptography/",
    ),
    "markdown": DependencyInfo(
        name="markdown",
        required_for="recovery kit generation",
        install_windows="pip install markdown",
        install_linux="pip install markdown",
        install_macos="pip install markdown",
        url="https://pypi.org/project/Markdown/",
    ),
    "reportlab": DependencyInfo(
        name="reportlab",
        required_for="PDF generation",
        install_windows="pip install reportlab",
        install_linux="pip install reportlab",
        install_macos="pip install reportlab",
        url="https://pypi.org/project/reportlab/",
    ),
    "argon2-cffi": DependencyInfo(
        name="argon2-cffi",
        required_for="password hashing",
        install_windows="pip install argon2-cffi",
        install_linux="pip install argon2-cffi",
        install_macos="pip install argon2-cffi",
        url="https://pypi.org/project/argon2-cffi/",
    ),
    "mnemonic": DependencyInfo(
        name="mnemonic",
        required_for="recovery phrase generation",
        install_windows="pip install mnemonic",
        install_linux="pip install mnemonic",
        install_macos="pip install mnemonic",
        url="https://pypi.org/project/mnemonic/",
    ),
    "qrcode": DependencyInfo(
        name="qrcode",
        required_for="QR code generation",
        install_windows="pip install qrcode",
        install_linux="pip install qrcode",
        install_macos="pip install qrcode",
        url="https://pypi.org/project/qrcode/",
    ),
    "pillow": DependencyInfo(
        name="Pillow",
        required_for="image processing",
        install_windows="pip install pillow",
        install_linux="pip install pillow",
        install_macos="pip install pillow",
        url="https://pypi.org/project/Pillow/",
    ),
    "colorama": DependencyInfo(
        name="colorama",
        required_for="terminal colors",
        install_windows="pip install colorama",
        install_linux="pip install colorama",
        install_macos="pip install colorama",
        url="https://pypi.org/project/colorama/",
    ),
}

# Required system tools
REQUIRED_SYSTEM_TOOLS = {
    "veracrypt": DependencyInfo(
        name="VeraCrypt",
        required_for="volume encryption",
        install_windows="Download from https://www.veracrypt.fr/en/Downloads.html\nInstall the full or portable version.",
        install_linux="Ubuntu/Debian: sudo apt install veracrypt\nFedora: sudo dnf install veracrypt\nArch: yay -S veracrypt",
        install_macos="brew install --cask veracrypt\nOr download from https://www.veracrypt.fr/en/Downloads.html",
        url="https://www.veracrypt.fr/en/Downloads.html",
    ),
    "gpg": DependencyInfo(
        name="GnuPG (GPG)",
        required_for="YubiKey and encryption key management",
        install_windows="Download Gpg4win from https://gpg4win.org/download.html\nInstall and run Kleopatra to initialize.",
        install_linux="Ubuntu/Debian: sudo apt install gnupg\nFedora: sudo dnf install gnupg2",
        install_macos="brew install gnupg\nOr install GPG Suite from https://gpgtools.org/",
        url="https://gnupg.org/",
    ),
}

# GPG-mode specific dependencies (only required when using GPG/YubiKey modes)
GPG_MODE_DEPENDENCIES = {
    "scdaemon": DependencyInfo(
        name="scdaemon (GPG SmartCard Daemon)",
        required_for="YubiKey/SmartCard communication in GPG modes",
        install_windows="Included with Gpg4win. If missing, reinstall Gpg4win from https://gpg4win.org/",
        install_linux="Ubuntu/Debian: sudo apt install scdaemon pcscd\nFedora: sudo dnf install pcsc-lite pcsc-lite-ccid gnupg2-smime\nArch: sudo pacman -S pcsclite ccid",
        install_macos="brew install gnupg\n(scdaemon is included with gnupg on macOS)",
        url="https://gnupg.org/",
    ),
    "pcscd": DependencyInfo(
        name="pcscd (PC/SC Smart Card Daemon)",
        required_for="SmartCard/YubiKey hardware communication",
        install_windows="Included with Windows. If issues, check 'Smart Card' service in services.msc",
        install_linux="Ubuntu/Debian: sudo apt install pcscd\nThen start: sudo systemctl enable --now pcscd",
        install_macos="brew install pcsc-lite\n(Usually pre-installed on macOS)",
        url="https://pcsclite.apdu.fr/",
    ),
}


def is_package_installed(package_name: str) -> bool:
    """
    Check if a Python package is installed.

    Args:
        package_name: Name of the package to check

    Returns:
        True if package is installed, False otherwise
    """
    # Handle special cases where import name differs from package name
    import_names = {
        "argon2-cffi": "argon2",
        "pillow": "PIL",
        "PyQt6": "PyQt6.QtCore",  # Check a submodule to ensure Qt is actually available
    }

    import_name = import_names.get(package_name, package_name)

    try:
        spec = importlib.util.find_spec(import_name)
        return spec is not None
    except (ModuleNotFoundError, ValueError):
        return False


def is_tool_installed(tool_name: str) -> bool:
    """
    Check if a system tool is available in PATH.

    Args:
        tool_name: Name of the tool to check (e.g., "gpg", "veracrypt")

    Returns:
        True if tool is found in PATH, False otherwise
    """
    # Special case for VeraCrypt on Windows - use centralized path detection
    if tool_name == "veracrypt" and _get_platform_name() == "Windows":
        # Check PATH first
        if shutil.which("veracrypt") or shutil.which("VeraCrypt"):
            return True

        # Use Paths SSOT for common installation paths
        try:
            from core.paths import Paths

            vc_path = Paths.veracrypt_exe()
            if vc_path and vc_path.exists():
                return True
        except (ImportError, RuntimeError):
            pass

        return False

    return shutil.which(tool_name) is not None


def get_platform_instructions(dep: DependencyInfo) -> str:
    """
    Get OS-appropriate installation instructions.

    Args:
        dep: DependencyInfo for the dependency

    Returns:
        Installation instructions string for current platform
    """
    system = _get_platform_name()

    if system == "Windows":
        return dep.install_windows
    elif system == "Darwin":
        return dep.install_macos
    else:  # Linux and others
        return dep.install_linux


def check_python_packages(packages: List[str] = None) -> Tuple[List[str], List[DependencyInfo]]:
    """
    Check which Python packages are missing.

    Args:
        packages: List of package names to check. If None, checks all required packages.

    Returns:
        Tuple of (list of missing package names, list of DependencyInfo for missing packages)
    """
    if packages is None:
        packages = list(REQUIRED_PYTHON_PACKAGES.keys())

    missing_names = []
    missing_infos = []

    for pkg_name in packages:
        if not is_package_installed(pkg_name):
            missing_names.append(pkg_name)
            if pkg_name in REQUIRED_PYTHON_PACKAGES:
                missing_infos.append(REQUIRED_PYTHON_PACKAGES[pkg_name])

    return missing_names, missing_infos


def check_system_tools(tools: List[str] = None) -> Tuple[List[str], List[DependencyInfo]]:
    """
    Check which system tools are missing.

    Args:
        tools: List of tool names to check. If None, checks all required tools.

    Returns:
        Tuple of (list of missing tool names, list of DependencyInfo for missing tools)
    """
    if tools is None:
        tools = list(REQUIRED_SYSTEM_TOOLS.keys())

    missing_names = []
    missing_infos = []

    for tool_name in tools:
        if not is_tool_installed(tool_name):
            missing_names.append(tool_name)
            if tool_name in REQUIRED_SYSTEM_TOOLS:
                missing_infos.append(REQUIRED_SYSTEM_TOOLS[tool_name])

    return missing_names, missing_infos


def check_gpg_mode_dependencies() -> Tuple[bool, str, List[DependencyInfo]]:
    """
    Check dependencies specific to GPG/YubiKey modes.

    BUG-20260102-014: Provides detailed error messages when scdaemon or pcscd
    are missing, which are required for YubiKey/SmartCard communication.

    Returns:
        Tuple of (all_ok: bool, error_message: str, missing_deps: List[DependencyInfo])
    """
    import subprocess

    system = _get_platform_name()
    missing_deps = []
    issues = []

    # Check if GPG can communicate with smartcard
    try:
        result = subprocess.run(
            ["gpg", "--no-tty", "--card-status"],
            capture_output=True,
            timeout=10,
        )
        stderr = result.stderr.decode("utf-8", errors="replace").lower()

        if result.returncode != 0:
            # Analyze the specific error
            if "no smartcard daemon" in stderr or "scdaemon" in stderr:
                issues.append("scdaemon (GPG SmartCard Daemon) is not installed or not running")
                missing_deps.append(GPG_MODE_DEPENDENCIES["scdaemon"])

            elif "no card" in stderr:
                # Card not present - this is expected if YubiKey not inserted
                # Not a dependency issue
                pass

            elif "ipc connect call failed" in stderr or "can't connect" in stderr:
                # Agent communication issue - may need restart
                issues.append("GPG agent communication failed. Try: gpgconf --kill gpg-agent")

            elif system == "Linux":
                # On Linux, check if pcscd is running
                pcscd_result = subprocess.run(
                    ["systemctl", "is-active", "pcscd"],
                    capture_output=True,
                    timeout=5,
                )
                if pcscd_result.returncode != 0:
                    issues.append("pcscd (PC/SC Smart Card Daemon) service is not running")
                    missing_deps.append(GPG_MODE_DEPENDENCIES["pcscd"])

    except FileNotFoundError:
        issues.append("GPG is not installed")
        missing_deps.append(REQUIRED_SYSTEM_TOOLS["gpg"])
    except subprocess.TimeoutExpired:
        issues.append("GPG is unresponsive (timed out)")
    except Exception as e:
        issues.append(f"Error checking GPG: {e}")

    # On Linux, also check if scdaemon binary exists
    if system == "Linux" and not shutil.which("scdaemon"):
        if "scdaemon" not in [d.name for d in missing_deps]:
            issues.append("scdaemon binary not found in PATH")
            missing_deps.append(GPG_MODE_DEPENDENCIES["scdaemon"])

    if not issues:
        return True, "", []

    # Format error message
    lines = [
        "=" * 70,
        "GPG/YUBIKEY DEPENDENCY CHECK FAILED",
        "=" * 70,
        "",
        "Issues detected:",
    ]
    for issue in issues:
        lines.append(f"  • {issue}")

    if missing_deps:
        lines.append("")
        lines.append("To fix, install the following:")
        lines.append("-" * 40)
        for dep in missing_deps:
            lines.append(f"\n{dep.name}:")
            lines.append(f"  {get_platform_instructions(dep)}")

    lines.append("")
    lines.append("=" * 70)

    return False, "\n".join(lines), missing_deps


def format_gpg_error_with_guidance(stderr: str, is_startup_issue: bool = False) -> str:
    """
    Format a GPG error with actionable guidance based on the error type.

    BUG-20260102-014: Provides clear, OS-specific guidance for common GPG errors
    including scdaemon issues, startup delays, and missing keys.

    Args:
        stderr: The stderr output from GPG command
        is_startup_issue: Whether this appears to be a first-run startup issue

    Returns:
        User-friendly error message with resolution steps
    """
    system = _get_platform_name()
    stderr_lower = stderr.lower()

    # Detect specific error types
    if "no smartcard daemon" in stderr_lower or "scdaemon" in stderr_lower:
        if system == "Windows":
            return (
                "🔴 GPG SmartCard Daemon Not Available\n\n"
                "The GPG smartcard daemon (scdaemon) cannot be reached.\n\n"
                "SOLUTIONS:\n"
                "1. Start Kleopatra from the Start Menu (this initializes GPG services)\n"
                "2. If Kleopatra is not installed, install Gpg4win from:\n"
                "   https://gpg4win.org/download.html\n"
                "3. After installing, restart your computer\n\n"
                "If this is the first mount attempt after startup, please wait\n"
                "a moment and try again - GPG services may still be starting."
            )
        elif system == "Linux":
            return (
                "🔴 GPG SmartCard Daemon Not Available\n\n"
                "The scdaemon package is not installed or not running.\n\n"
                "INSTALL (Ubuntu/Debian):\n"
                "  sudo apt install scdaemon pcscd\n"
                "  sudo systemctl enable --now pcscd\n\n"
                "INSTALL (Fedora):\n"
                "  sudo dnf install pcsc-lite gnupg2-smime\n"
                "  sudo systemctl enable --now pcscd\n\n"
                "After installing, unplug and replug your YubiKey."
            )
        else:  # macOS
            return (
                "🔴 GPG SmartCard Daemon Not Available\n\n"
                "SOLUTIONS:\n"
                "1. Install/reinstall GPG:\n"
                "   brew install gnupg\n"
                "2. Or install GPG Suite from https://gpgtools.org/\n"
                "3. Unplug and replug your YubiKey"
            )

    elif "no secret key" in stderr_lower:
        return (
            "🔴 GPG Secret Key Not Found\n\n"
            "GPG cannot find the private key required for decryption.\n\n"
            "POSSIBLE CAUSES:\n"
            "• YubiKey with the correct key is not inserted\n"
            "• Key stubs not present in GPG keyring\n"
            "• Wrong GPG home directory\n\n"
            "SOLUTIONS:\n"
            "1. Insert the correct YubiKey\n"
            "2. Check available keys: gpg --list-secret-keys\n"
            "3. Re-import key stubs: gpg --card-status\n"
            "4. If keys were set up on another machine, import public key first:\n"
            "   gpg --import <your-public-key.asc>\n"
            "   gpg --card-edit  (then type 'fetch' to link key to card)"
        )

    elif "no card" in stderr_lower or "card error" in stderr_lower:
        return (
            "🔴 YubiKey/SmartCard Not Detected\n\n"
            "No YubiKey or SmartCard is detected by GPG.\n\n"
            "SOLUTIONS:\n"
            "1. Insert your YubiKey\n"
            "2. If already inserted, try unplugging and replugging it\n"
            "3. Check the YubiKey LED - it should be blinking during use\n"
            "4. Try a different USB port\n"
            f"5. {'Open Kleopatra to initialize GPG' if system == 'Windows' else 'Run: gpg --card-status'}"
        )

    elif "ipc connect" in stderr_lower or "can't connect" in stderr_lower:
        if is_startup_issue or system == "Windows":
            return (
                "🟡 GPG Agent Starting Up\n\n"
                "GPG services are initializing. This is normal after system startup.\n\n"
                "Please wait a moment and try again.\n\n"
                f"{'If this persists, try opening Kleopatra first.' if system == 'Windows' else 'If this persists, run: gpgconf --kill gpg-agent'}"
            )
        else:
            return (
                "🔴 GPG Agent Communication Failed\n\n"
                "Cannot connect to GPG agent.\n\n"
                "SOLUTIONS:\n"
                "1. Restart GPG agent:\n"
                "   gpgconf --kill gpg-agent\n"
                "2. Then try mounting again\n"
                "3. If issues persist, check GPG logs:\n"
                f"   {'%APPDATA%\\gnupg\\' if system == 'Windows' else '~/.gnupg/'}"
            )

    elif "bad pin" in stderr_lower or "incorrect pin" in stderr_lower:
        return (
            "🔴 Incorrect PIN\n\n"
            "The PIN entered for the YubiKey was incorrect.\n\n"
            "⚠️ WARNING: Multiple incorrect attempts may lock your YubiKey!\n\n"
            "If you've forgotten your PIN:\n"
            "• Use the Admin PIN to reset the User PIN\n"
            "• Default User PIN: 123456\n"
            "• Default Admin PIN: 12345678"
        )

    else:
        # Generic GPG error
        return (
            f"🔴 GPG Decryption Failed\n\n"
            f"Error: {stderr[:200]}{'...' if len(stderr) > 200 else ''}\n\n"
            "GENERAL SOLUTIONS:\n"
            "1. Ensure YubiKey is inserted\n"
            f"2. {'Open Kleopatra' if system == 'Windows' else 'Run: gpg --card-status'}\n"
            "3. Check GPG keys: gpg --list-secret-keys\n"
            "4. Restart GPG agent: gpgconf --kill gpg-agent"
        )


def format_dependency_error(missing_packages: List[DependencyInfo], missing_tools: List[DependencyInfo]) -> str:
    """
    Format a user-friendly error message for missing dependencies.

    Args:
        missing_packages: List of missing Python packages
        missing_tools: List of missing system tools

    Returns:
        Formatted error message with installation instructions
    """
    lines = []
    lines.append("=" * 70)
    lines.append("MISSING DEPENDENCIES")
    lines.append("=" * 70)
    lines.append("")
    lines.append("KeyDrive requires the following components that are not installed:")
    lines.append("")

    if missing_tools:
        lines.append("SYSTEM TOOLS:")
        lines.append("-" * 40)
        for tool in missing_tools:
            lines.append(f"\n• {tool.name} (required for {tool.required_for})")
            lines.append(f"  {get_platform_instructions(tool)}")
            if tool.url:
                lines.append(f"  More info: {tool.url}")

    if missing_packages:
        lines.append("")
        lines.append("PYTHON PACKAGES:")
        lines.append("-" * 40)

        # Provide a single pip install command for all missing packages
        pkg_names = [p.name.lower() for p in missing_packages]
        lines.append(f"\nInstall all missing packages with:")
        lines.append(f"  pip install {' '.join(pkg_names)}")
        lines.append("")
        lines.append("Or install from requirements.txt:")
        lines.append("  pip install -r requirements.txt")
        lines.append("")

        for pkg in missing_packages:
            lines.append(f"• {pkg.name} (required for {pkg.required_for})")

    lines.append("")
    lines.append("=" * 70)
    lines.append("After installing the missing components, restart KeyDrive.")
    lines.append("=" * 70)

    return "\n".join(lines)


def check_gui_dependencies(silent: bool = False) -> bool:
    """
    Check all dependencies required for GUI operation.

    Args:
        silent: If True, don't print anything. If False, print error message if deps missing.

    Returns:
        True if all dependencies are available, False otherwise
    """
    # Check critical GUI dependency first
    missing_pkg_names, missing_packages = check_python_packages(["PyQt6"])

    # Check VeraCrypt (critical for operation)
    missing_tool_names, missing_tools = check_system_tools(["veracrypt"])

    # If critical deps are missing, report
    if missing_packages or missing_tools:
        if not silent:
            error_msg = format_dependency_error(missing_packages, missing_tools)
            print(error_msg, file=sys.stderr)
        return False

    return True


def check_all_dependencies(silent: bool = False) -> Tuple[bool, str]:
    """
    Check all dependencies (Python packages and system tools).

    Args:
        silent: If True, don't print anything.

    Returns:
        Tuple of (all_ok: bool, error_message: str)
        If all_ok is True, error_message is empty.
    """
    missing_pkg_names, missing_packages = check_python_packages()
    missing_tool_names, missing_tools = check_system_tools()

    if not missing_packages and not missing_tools:
        return True, ""

    error_msg = format_dependency_error(missing_packages, missing_tools)

    if not silent:
        print(error_msg, file=sys.stderr)

    return False, error_msg


def show_gui_dependency_error() -> None:
    """
    Show a graphical error dialog for missing dependencies.

    This is called when PyQt6 IS available but other dependencies might be missing.
    For the case when PyQt6 itself is missing, we fall back to console output.
    """
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox

        # Create a minimal application just for showing the error
        app = QApplication.instance() or QApplication(sys.argv)

        _, missing_packages = check_python_packages()
        _, missing_tools = check_system_tools()

        # Build a shorter message for the dialog
        parts = []
        if missing_tools:
            parts.append("Missing system tools:\n• " + "\n• ".join(t.name for t in missing_tools))
        if missing_packages:
            parts.append("Missing Python packages:\n• " + "\n• ".join(p.name for p in missing_packages))

        message = "\n\n".join(parts)
        message += "\n\nSee the console/terminal for installation instructions."

        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle("Missing Dependencies")
        msg_box.setText("KeyDrive cannot start due to missing dependencies.")
        msg_box.setInformativeText(message)
        msg_box.exec()

    except ImportError:
        # PyQt6 not available - already printed console message
        pass


if __name__ == "__main__":
    # Test dependency checking
    print("Checking dependencies...\n")

    all_ok, error_msg = check_all_dependencies(silent=True)

    if all_ok:
        print("✓ All dependencies are installed!")
    else:
        print(error_msg)
        sys.exit(1)
        sys.exit(1)
