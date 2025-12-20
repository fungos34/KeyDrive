"""
Output Formatting SSOT Module

Provides width-safe, ASCII-safe console output formatting functions.
All UI string formatting must use these functions to ensure:
1. ASCII-safe rendering in broken consoles (elevated PowerShell)
2. Consistent width handling across platforms
3. Proper text wrapping for long messages

ARCHITECTURE CONSTRAINTS (from AGENT_ARCHITECTURE.md):
- Use ConsoleStyle from core/constants.py for symbols
- Maximum line width: 70 characters (fits 80-col terminals with margin)
- All user-facing strings must go through format functions
- No raw emoji/unicode in format strings - use ConsoleStyle symbols

Usage:
    from core.formatting import Formatter
    from core.constants import ConsoleStyle
    
    style = ConsoleStyle.detect()
    fmt = Formatter(style)
    
    fmt.header("PHASE 1: VERIFICATION")
    fmt.success("Verification complete")
    fmt.warning("No backup found")
    fmt.error("Critical failure")
    fmt.info("Additional information")
    fmt.box(["Line 1", "Line 2"])  # Draws bordered box
"""

from __future__ import annotations

import os
import shutil
import textwrap
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

# Import ConsoleStyle - this module extends its functionality
try:
    from core.constants import ConsoleStyle
except ImportError:
    # Fallback for standalone testing
    class ConsoleStyle:
        UNICODE = "unicode"
        ASCII = "ascii"

        def __init__(self, mode=None):
            self._mode = mode or self.ASCII

        @classmethod
        def detect(cls):
            return cls()

        def symbol(self, name):
            return f"[{name}]"

        @property
        def SUCCESS(self):
            return "[OK]"

        @property
        def FAILURE(self):
            return "[X]"

        @property
        def WARNING(self):
            return "[!]"

        @property
        def INFO(self):
            return "[i]"


# =============================================================================
# Constants
# =============================================================================

# Maximum line width for console output
MAX_LINE_WIDTH = 70

# Minimum sane terminal width
MIN_TERMINAL_WIDTH = 40

# Default terminal width fallback
DEFAULT_TERMINAL_WIDTH = 80


@dataclass
class FormatterConfig:
    """Configuration for Formatter instance."""

    # Maximum line width (0 = auto-detect from terminal)
    max_width: int = MAX_LINE_WIDTH

    # Indent for wrapped continuation lines
    wrap_indent: int = 4

    # Enable color output (requires colorama on Windows)
    use_color: bool = False

    # Prefix for continuation lines
    continuation_prefix: str = "  "

    # Box padding (spaces inside box borders)
    box_padding: int = 1


@dataclass
class OutputLine:
    """A formatted output line with metadata."""

    text: str
    line_type: str = "normal"  # normal, header, success, error, warning, info
    indent: int = 0


# =============================================================================
# Terminal Width Detection
# =============================================================================


def get_terminal_width() -> int:
    """
    Get the current terminal width, with fallback.

    Returns:
        Terminal width in characters, minimum MIN_TERMINAL_WIDTH
    """
    try:
        # shutil.get_terminal_size() is cross-platform
        size = shutil.get_terminal_size((DEFAULT_TERMINAL_WIDTH, 24))
        width = size.columns
        # Ensure minimum width
        return max(width, MIN_TERMINAL_WIDTH)
    except Exception:
        return DEFAULT_TERMINAL_WIDTH


def get_effective_width(max_width: int = MAX_LINE_WIDTH) -> int:
    """
    Get effective width for output, respecting terminal and max_width.

    Args:
        max_width: Maximum allowed width (0 = use terminal width)

    Returns:
        Effective width for text formatting
    """
    terminal_width = get_terminal_width()
    if max_width <= 0:
        return terminal_width
    return min(max_width, terminal_width)


# =============================================================================
# Text Wrapping Utilities
# =============================================================================


def wrap_text(
    text: str,
    width: int = MAX_LINE_WIDTH,
    initial_indent: str = "",
    subsequent_indent: str = "",
    preserve_paragraphs: bool = True,
) -> List[str]:
    """
    Wrap text to specified width with proper indentation.

    Args:
        text: Text to wrap
        width: Maximum line width
        initial_indent: Prefix for first line
        subsequent_indent: Prefix for continuation lines
        preserve_paragraphs: Keep paragraph breaks (double newlines)

    Returns:
        List of wrapped lines
    """
    if not text:
        return []

    lines = []

    if preserve_paragraphs:
        # Split on paragraph breaks
        paragraphs = text.split("\n\n")
        for i, para in enumerate(paragraphs):
            # Normalize whitespace within paragraph
            para = " ".join(para.split())
            if para:
                wrapped = textwrap.wrap(
                    para,
                    width=width,
                    initial_indent=initial_indent if i == 0 else "",
                    subsequent_indent=subsequent_indent,
                    break_long_words=True,
                    break_on_hyphens=True,
                )
                lines.extend(wrapped)
            if i < len(paragraphs) - 1:
                lines.append("")  # Paragraph separator
    else:
        # Simple wrap
        text = " ".join(text.split())
        lines = textwrap.wrap(
            text,
            width=width,
            initial_indent=initial_indent,
            subsequent_indent=subsequent_indent,
            break_long_words=True,
            break_on_hyphens=True,
        )

    return lines


def truncate_with_ellipsis(text: str, max_length: int) -> str:
    """
    Truncate text with ellipsis if too long.

    Args:
        text: Text to truncate
        max_length: Maximum length including ellipsis

    Returns:
        Truncated text with "..." if needed
    """
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return text[: max_length - 3] + "..."


def center_text(text: str, width: int, fill_char: str = " ") -> str:
    """
    Center text within specified width.

    Args:
        text: Text to center
        width: Total width
        fill_char: Character to use for padding

    Returns:
        Centered text
    """
    if len(text) >= width:
        return text
    padding = width - len(text)
    left_pad = padding // 2
    right_pad = padding - left_pad
    return fill_char * left_pad + text + fill_char * right_pad


# =============================================================================
# Box Drawing
# =============================================================================


def draw_box(
    lines: List[str], style: ConsoleStyle, width: int = 0, title: Optional[str] = None, padding: int = 1
) -> List[str]:
    """
    Draw a box around text lines.

    Args:
        lines: Lines to put in box
        style: ConsoleStyle for box characters
        width: Box width (0 = auto from content)
        title: Optional title for top border
        padding: Internal padding (spaces)

    Returns:
        List of lines forming the box
    """
    if not lines:
        return []

    # Get box characters from style
    h = style.symbol("BOX_H")
    v = style.symbol("BOX_V")
    tl = style.symbol("BOX_TL")
    tr = style.symbol("BOX_TR")
    bl = style.symbol("BOX_BL")
    br = style.symbol("BOX_BR")

    # Calculate width
    content_width = max(len(line) for line in lines)
    if width <= 0:
        width = content_width + (padding * 2) + 2  # +2 for borders

    inner_width = width - 2  # Minus border characters

    result = []

    # Top border with optional title
    if title:
        title_text = f" {title} "
        title_len = len(title_text)
        left_border = (inner_width - title_len) // 2
        right_border = inner_width - title_len - left_border
        result.append(tl + h * left_border + title_text + h * right_border + tr)
    else:
        result.append(tl + h * inner_width + tr)

    # Content lines
    for line in lines:
        padded = line.ljust(inner_width - padding)[: inner_width - padding]
        result.append(v + " " * padding + padded + " " * (inner_width - padding - len(padded)) + v)

    # Bottom border
    result.append(bl + h * inner_width + br)

    return result


# =============================================================================
# Formatter Class
# =============================================================================


class Formatter:
    """
    Console output formatter with width-safe, ASCII-safe rendering.

    Usage:
        style = ConsoleStyle.detect()
        fmt = Formatter(style)

        fmt.header("PHASE 1: VERIFICATION")
        fmt.success("Task completed successfully")
        fmt.warning("Backup not found, proceeding anyway")
        fmt.error("Critical error occurred")

        # Multi-line wrapped output
        fmt.paragraph("This is a very long message that will be automatically "
                     "wrapped to fit within the terminal width...")

        # Boxed content
        fmt.box(["Important:", "- Item 1", "- Item 2"])

        # Section divider
        fmt.divider()
    """

    def __init__(
        self, style: ConsoleStyle = None, config: FormatterConfig = None, output: Callable[[str], None] = None
    ):
        """
        Initialize formatter.

        Args:
            style: ConsoleStyle instance (auto-detected if None)
            config: FormatterConfig (defaults if None)
            output: Output function (print if None)
        """
        self.style = style or ConsoleStyle.detect()
        self.config = config or FormatterConfig()
        self._output = output or print
        self._effective_width = get_effective_width(self.config.max_width)

    def _print(self, text: str = "") -> None:
        """Print a line using configured output."""
        self._output(text)

    def _wrap(self, text: str, prefix: str = "") -> List[str]:
        """Wrap text with prefix for first line."""
        prefix_len = len(prefix)
        return wrap_text(text, width=self._effective_width, initial_indent=prefix, subsequent_indent=" " * prefix_len)

    # =========================================================================
    # Output Methods
    # =========================================================================

    def raw(self, text: str) -> None:
        """Print raw text without formatting."""
        self._print(text)

    def blank(self, count: int = 1) -> None:
        """Print blank lines."""
        for _ in range(count):
            self._print("")

    def divider(self, char: str = None, width: int = None) -> None:
        """Print a horizontal divider line."""
        char = char or self.style.symbol("SECTION_SEP")
        width = width or self._effective_width
        self._print(char * width)

    def double_divider(self, width: int = None) -> None:
        """Print a double-line divider."""
        char = self.style.symbol("MENU_DOUBLE")
        width = width or self._effective_width
        self._print(char * width)

    def header(self, text: str, char: str = None) -> None:
        """
        Print a section header with border.

        Format:
            ======================================
              HEADER TEXT
            ======================================
        """
        char = char or self.style.symbol("MENU_DOUBLE")
        width = self._effective_width

        self._print(char * width)
        self._print(center_text(text, width))
        self._print(char * width)

    def subheader(self, text: str) -> None:
        """Print a sub-header."""
        self.divider()
        self._print(f"  {text}")
        self.divider()

    def phase(self, num: int, total: int, title: str) -> None:
        """
        Print a phase header.

        Format:
            ======================================
              PHASE 1/3: TITLE
            ======================================
        """
        self.header(f"PHASE {num}/{total}: {title}")

    def success(self, text: str) -> None:
        """Print a success message."""
        prefix = f"{self.style.SUCCESS} "
        for line in self._wrap(text, prefix):
            self._print(line)

    def error(self, text: str) -> None:
        """Print an error message."""
        prefix = f"{self.style.FAILURE} "
        for line in self._wrap(text, prefix):
            self._print(line)

    def warning(self, text: str) -> None:
        """Print a warning message."""
        prefix = f"{self.style.WARNING} "
        for line in self._wrap(text, prefix):
            self._print(line)

    def info(self, text: str) -> None:
        """Print an info message."""
        prefix = f"{self.style.INFO} "
        for line in self._wrap(text, prefix):
            self._print(line)

    def bullet(self, text: str, char: str = "-") -> None:
        """Print a bullet point."""
        prefix = f"  {char} "
        for line in self._wrap(text, prefix):
            self._print(line)

    def numbered(self, num: int, text: str) -> None:
        """Print a numbered item."""
        prefix = f"  {num}. "
        for line in self._wrap(text, prefix):
            self._print(line)

    def key_value(self, key: str, value: str, separator: str = ": ") -> None:
        """Print a key-value pair."""
        line = f"{key}{separator}{value}"
        if len(line) > self._effective_width:
            self._print(f"{key}{separator}")
            for wrapped in self._wrap(str(value), "    "):
                self._print(wrapped)
        else:
            self._print(line)

    def paragraph(self, text: str) -> None:
        """Print a paragraph with word wrapping."""
        for line in self._wrap(text):
            self._print(line)

    def indented(self, text: str, indent: int = 4) -> None:
        """Print indented text."""
        prefix = " " * indent
        for line in self._wrap(text, prefix):
            self._print(line)

    def code_line(self, code: str) -> None:
        """Print a code/command line with proper handling."""
        if len(code) > self._effective_width:
            self._print(truncate_with_ellipsis(code, self._effective_width))
        else:
            self._print(code)

    def box(self, lines: List[str], title: Optional[str] = None, width: int = 0) -> None:
        """
        Print text in a bordered box.

        Args:
            lines: Lines to put in box
            title: Optional title
            width: Box width (0 = auto)
        """
        box_lines = draw_box(
            lines, self.style, width=width or self._effective_width, title=title, padding=self.config.box_padding
        )
        for line in box_lines:
            self._print(line)

    def table(self, headers: List[str], rows: List[List[str]], col_widths: List[int] = None) -> None:
        """
        Print a simple table.

        Args:
            headers: Column headers
            rows: Table rows
            col_widths: Column widths (auto if None)
        """
        if not headers and not rows:
            return

        # Calculate column widths
        num_cols = len(headers) if headers else (len(rows[0]) if rows else 0)
        if not col_widths:
            col_widths = [0] * num_cols
            if headers:
                for i, h in enumerate(headers):
                    col_widths[i] = max(col_widths[i], len(str(h)))
            for row in rows:
                for i, cell in enumerate(row[:num_cols]):
                    col_widths[i] = max(col_widths[i], len(str(cell)))

        # Check if fits
        total_width = sum(col_widths) + (num_cols - 1) * 3  # " | " separators
        if total_width > self._effective_width:
            # Scale down columns
            scale = (self._effective_width - (num_cols - 1) * 3) / sum(col_widths)
            col_widths = [max(3, int(w * scale)) for w in col_widths]

        sep = self.style.symbol("BOX_V")

        # Header
        if headers:
            header_cells = [str(h).ljust(col_widths[i])[: col_widths[i]] for i, h in enumerate(headers)]
            self._print(f" {sep} ".join(header_cells))
            self.divider()

        # Rows
        for row in rows:
            cells = [str(c).ljust(col_widths[i])[: col_widths[i]] for i, c in enumerate(row[:num_cols])]
            self._print(f" {sep} ".join(cells))

    # =========================================================================
    # Compound Layouts
    # =========================================================================

    def status_line(self, label: str, status: str, ok: bool = True) -> None:
        """
        Print a status line with alignment.

        Format: "Label..................... [OK]"
        """
        sym = self.style.SUCCESS if ok else self.style.FAILURE
        status_part = f" {status} {sym}"
        available = self._effective_width - len(status_part)

        if len(label) > available - 3:
            label = truncate_with_ellipsis(label, available - 3)

        dots = "." * (available - len(label))
        self._print(f"{label}{dots}{status_part}")

    def progress_section(
        self,
        title: str,
        items: List[Tuple[str, bool]],  # (description, success)
    ) -> None:
        """
        Print a progress section with checkmarks.

        Args:
            title: Section title
            items: List of (description, success) tuples
        """
        self.subheader(title)
        for desc, success in items:
            sym = self.style.SUCCESS if success else self.style.FAILURE
            self._print(f"  {sym} {desc}")
        self.blank()

    def summary_box(self, title: str, entries: List[Tuple[str, str]], success: bool = True) -> None:  # (key, value)
        """
        Print a summary box with key-value pairs.

        Args:
            title: Box title
            entries: List of (key, value) tuples
            success: Overall success status
        """
        sym = self.style.SUCCESS if success else self.style.FAILURE

        lines = []
        for key, value in entries:
            lines.append(f"{key}: {value}")

        self.box(lines, title=f"{sym} {title}")


# =============================================================================
# Module-level convenience functions
# =============================================================================

# Default formatter instance (lazy initialized)
_default_formatter: Optional[Formatter] = None


def get_formatter() -> Formatter:
    """Get or create default formatter."""
    global _default_formatter
    if _default_formatter is None:
        _default_formatter = Formatter()
    return _default_formatter


def reset_formatter() -> None:
    """Reset default formatter (for testing or reconfiguration)."""
    global _default_formatter
    _default_formatter = None


# Convenience wrappers
def header(text: str) -> None:
    """Print header using default formatter."""
    get_formatter().header(text)


def success(text: str) -> None:
    """Print success message using default formatter."""
    get_formatter().success(text)


def error(text: str) -> None:
    """Print error message using default formatter."""
    get_formatter().error(text)


def warning(text: str) -> None:
    """Print warning message using default formatter."""
    get_formatter().warning(text)


def info(text: str) -> None:
    """Print info message using default formatter."""
    get_formatter().info(text)


# =============================================================================
# Testing
# =============================================================================

if __name__ == "__main__":
    # Demo output
    style = ConsoleStyle.detect()
    fmt = Formatter(style)

    print(f"Detected style: {style.mode}")
    print(f"Terminal width: {get_terminal_width()}")
    print(f"Effective width: {get_effective_width()}")
    print()

    fmt.header("FORMATTING DEMO")
    fmt.blank()

    fmt.phase(1, 3, "VERIFICATION")
    fmt.success("All checks passed successfully")
    fmt.warning("No backup found, proceeding without backup")
    fmt.error("Critical error: file not found")
    fmt.info("Additional information about the process")
    fmt.blank()

    fmt.subheader("BULLET LIST")
    fmt.bullet("First item in the list")
    fmt.bullet(
        "Second item with a much longer description that will need "
        "to be wrapped across multiple lines to fit the terminal width"
    )
    fmt.bullet("Third item")
    fmt.blank()

    fmt.subheader("KEY-VALUE PAIRS")
    fmt.key_value("Drive", "D:")
    fmt.key_value("Volume Size", "1.0 GB")
    fmt.key_value("Security Mode", "GPG + Password + YubiKey Hardware Auth")
    fmt.blank()

    fmt.subheader("BOXED CONTENT")
    fmt.box(
        [
            "IMPORTANT NOTICE",
            "",
            "This is critical information that",
            "should be highlighted to the user.",
        ],
        title="WARNING",
    )
    fmt.blank()

    fmt.subheader("STATUS LINES")
    fmt.status_line("Checking prerequisites", "PASS", True)
    fmt.status_line("Verifying signature", "PASS", True)
    fmt.status_line("Checking backup", "SKIP", False)
    fmt.blank()

    fmt.subheader("SUMMARY")
    fmt.summary_box(
        "Setup Complete",
        [
            ("Drive", "D:"),
            ("Mount Point", "V:"),
            ("Security", "GPG + Password"),
            ("Status", "Ready to use"),
        ],
        success=True,
    )
