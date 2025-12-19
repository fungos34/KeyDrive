"""
CLI Output Formatting Module (SSOT)

This module provides consistent, ASCII-safe terminal output formatting.
Per AGENT_ARCHITECTURE.md, elevated PowerShell consoles on Windows can
break UTF-8 encoding, so we provide safe fallbacks.

Usage:
    from cli_output import CLIOutput
    
    out = CLIOutput.detect()
    out.info("Operation completed")
    out.warn("Potential issue")
    out.error("Failed!")
    out.section("HEADER TEXT")
    out.step(1, 5, "Doing something")
"""

import os
import sys
import shutil
from typing import Optional, Callable


class CLIOutput:
    """
    SSOT for consistent CLI output formatting.
    
    Features:
    - Width-aware line wrapping
    - ASCII-safe mode for broken consoles
    - Consistent [INFO]/[WARN]/[ERROR] prefixes
    - Step counters for multi-step operations
    """
    
    # Unicode symbols (preferred)
    UNICODE_SYMBOLS = {
        'info': '✓',
        'warn': '⚠️',
        'error': '❌',
        'bullet': '•',
        'section': '═',
        'separator': '─',
        'arrow': '→',
    }
    
    # ASCII fallbacks (for broken consoles)
    ASCII_SYMBOLS = {
        'info': '[OK]',
        'warn': '[!!]',
        'error': '[XX]',
        'bullet': '*',
        'section': '=',
        'separator': '-',
        'arrow': '->',
    }
    
    def __init__(self, use_unicode: bool = True, width: int = 70, indent: int = 2):
        """
        Initialize CLI output formatter.
        
        Args:
            use_unicode: Use Unicode symbols (True) or ASCII fallback (False)
            width: Target line width for formatting
            indent: Left margin indent (spaces)
        """
        self.use_unicode = use_unicode
        self.width = width
        self.indent = indent
        self._symbols = self.UNICODE_SYMBOLS if use_unicode else self.ASCII_SYMBOLS
        self._prefix = ' ' * indent
        
    @classmethod
    def detect(cls, width: Optional[int] = None) -> 'CLIOutput':
        """
        Auto-detect console capabilities and return appropriate formatter.
        
        Checks for:
        - Windows elevated PowerShell (often breaks UTF-8)
        - Terminal width
        - PYTHONIOENCODING
        
        Returns:
            CLIOutput instance configured for current console
        """
        # Detect terminal width
        if width is None:
            try:
                term_size = shutil.get_terminal_size()
                width = min(term_size.columns, 80)
            except:
                width = 70
        
        # Detect Unicode safety
        use_unicode = True
        
        # Windows check - elevated PowerShell often has broken UTF-8
        if sys.platform == 'win32':
            # Check for elevated prompt (admin)
            import ctypes
            try:
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                if is_admin:
                    # Check if console can handle UTF-8
                    try:
                        test = '✓'
                        if sys.stdout.encoding and 'utf' not in sys.stdout.encoding.lower():
                            use_unicode = False
                    except:
                        use_unicode = False
            except:
                pass
        
        # Check PYTHONIOENCODING
        io_encoding = os.environ.get('PYTHONIOENCODING', '')
        if io_encoding and 'utf' not in io_encoding.lower():
            use_unicode = False
            
        return cls(use_unicode=use_unicode, width=width)
    
    @property
    def sym(self) -> dict:
        """Get current symbol set."""
        return self._symbols
    
    def _print(self, msg: str, file=None):
        """Print with safe encoding fallback."""
        try:
            print(msg, file=file or sys.stdout)
        except UnicodeEncodeError:
            # Fallback to ASCII if encoding fails
            safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
            print(safe_msg, file=file or sys.stdout)
    
    def info(self, message: str, prefix: str = None):
        """Print info message."""
        sym = prefix or self._symbols['info']
        self._print(f"{self._prefix}{sym} {message}")
    
    def warn(self, message: str, prefix: str = None):
        """Print warning message."""
        sym = prefix or self._symbols['warn']
        self._print(f"{self._prefix}{sym} {message}")
    
    def error(self, message: str, prefix: str = None):
        """Print error message."""
        sym = prefix or self._symbols['error']
        self._print(f"{self._prefix}{sym} {message}", file=sys.stderr)
    
    def log(self, message: str):
        """Print plain log message with indent."""
        self._print(f"{self._prefix}{message}")
    
    def bullet(self, message: str):
        """Print bullet point."""
        self._print(f"{self._prefix}{self._symbols['bullet']} {message}")
    
    def step(self, current: int, total: int, message: str):
        """Print step progress (e.g., Step 3/7: Verifying...)."""
        self._print(f"{self._prefix}Step {current}/{total}: {message}")
    
    def section(self, title: str, width: int = None):
        """Print section header."""
        w = width or self.width
        sep = self._symbols['section']
        self._print("")
        self._print(sep * w)
        self._print(f"  {title}")
        self._print(sep * w)
    
    def separator(self, width: int = None):
        """Print horizontal separator line."""
        w = width or self.width
        self._print(self._symbols['separator'] * w)
    
    def blank(self):
        """Print blank line."""
        self._print("")
    
    def boxed(self, lines: list, width: int = None):
        """
        Print content in a box.
        
        Args:
            lines: List of strings to display
            width: Box width (default: self.width)
        """
        w = width or self.width
        h = self._symbols['separator']
        
        self._print(f"+{h * (w - 2)}+")
        for line in lines:
            # Truncate or pad to fit
            line_content = line[:w - 4]
            padding = w - 4 - len(line_content)
            self._print(f"| {line_content}{' ' * padding} |")
        self._print(f"+{h * (w - 2)}+")
    
    def table(self, headers: list, rows: list, col_widths: list = None):
        """
        Print simple table.
        
        Args:
            headers: Column header strings
            rows: List of row tuples
            col_widths: Optional column widths
        """
        if not col_widths:
            # Auto-calculate based on content
            col_widths = [
                max(len(str(headers[i])), max(len(str(row[i])) for row in rows) if rows else 0)
                for i in range(len(headers))
            ]
        
        # Header
        header_line = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
        self._print(f"{self._prefix}{header_line}")
        
        sep_line = "-+-".join("-" * w for w in col_widths)
        self._print(f"{self._prefix}{sep_line}")
        
        # Rows
        for row in rows:
            row_line = " | ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(row))
            self._print(f"{self._prefix}{row_line}")


# Module-level convenience functions
_default_output = None

def get_output() -> CLIOutput:
    """Get or create default CLIOutput instance."""
    global _default_output
    if _default_output is None:
        _default_output = CLIOutput.detect()
    return _default_output

def info(msg: str): get_output().info(msg)
def warn(msg: str): get_output().warn(msg)
def error(msg: str): get_output().error(msg)
def log(msg: str): get_output().log(msg)
def step(current: int, total: int, msg: str): get_output().step(current, total, msg)
def section(title: str): get_output().section(title)
def separator(): get_output().separator()
