"""Reusable UI components for Memex CLI."""

from enum import Enum
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli import __version__
from cli.display.colors import COLORS, STYLES

console = Console()


class StatusIndicator(Enum):
    """Status indicators for visual display."""
    RUNNING = ("●", "success")
    STOPPED = ("○", "muted")
    PROGRESS = ("◐", "warning")
    ERROR = ("✗", "error")
    WARNING = ("⚠", "warning")
    SUCCESS = ("✓", "success")


LOGO_MINIMAL = "▣ Memex"


def _get_instance_info() -> tuple[str, str, str, str]:
    """Get hosting mode, AI provider, instance name, and capture count.

    Returns defaults on any error so the banner always renders.
    """
    hosting = "Local"
    provider = ""
    instance = ""
    captures = ""

    try:
        from cli.services.instance import InstanceService
        config = InstanceService().load()
        hosting = config.hosting_mode.capitalize()
        instance = config.instance_name
    except Exception:
        pass

    try:
        from cli.config.credentials import get_configured_providers
        providers = get_configured_providers()
        if providers:
            provider = providers[0].capitalize()
    except Exception:
        pass

    try:
        from cli.services.health import HealthService
        count = HealthService().get_ocr_file_count()
        if count > 0:
            captures = f"{count:,} captures"
    except Exception:
        pass

    return hosting, provider, instance, captures


def print_logo():
    """Print the Memex elephant creature with version and instance info."""
    hosting, provider, instance, captures = _get_instance_info()

    # Build the info string: "Local · Anthropic · joe"
    info_parts = [hosting]
    if provider:
        info_parts.append(provider)
    if instance:
        info_parts.append(instance)
    info_line = " · ".join(info_parts)

    C = COLORS["creature_body"]
    E = COLORS["creature_eye"]
    M = COLORS["muted"]

    # Elephant creature lines paired with info lines
    creature_info = [
        (f"[{C}]       ▄▄[/]",          ""),
        (f"[{C}]    ▄▄████[/]",         f"[bold]Memex[/bold] [dim]v{__version__}[/dim]"),
        (f"[{C}]   ▐[/][{E}]◉[/][{C}]▌████▌[/]",  f"[dim]{info_line}[/dim]"),
        (f"[{C}]    ▀▌[/][{M}]▐▀▀▀[/]",  f"[dim]{captures}[/dim]" if captures else ""),
        (f"[{M}]     ▐▌[/]",            ""),
    ]

    console.print()
    for creature, info in creature_info:
        if info:
            console.print(f"  {creature}   {info}")
        else:
            console.print(f"  {creature}")
    console.print()


def print_header(title: str):
    """Print a styled header."""
    console.print()
    console.print(f"  [{COLORS['primary']}]{LOGO_MINIMAL}[/] {title}")
    console.print(f"  [dim]{'─' * 45}[/dim]")
    console.print()


def print_section(title: str, char: str = "─"):
    """Print a section divider."""
    console.print()
    console.print(f"  [bold]{title}[/bold]")
    console.print(f"  [dim]{char * 50}[/dim]")


def print_status_line(label: str, status: StatusIndicator, value: str, extra: str = ""):
    """Print a status line with indicator."""
    indicator, color = status.value
    extra_text = f"  [dim]{extra}[/dim]" if extra else ""
    console.print(f"  [{color}]{indicator}[/] {label:<12} {value}{extra_text}")


def print_key_value(key: str, value: str, indent: int = 2):
    """Print a key-value pair."""
    spaces = " " * indent
    console.print(f"{spaces}[dim]{key}[/dim]  {value}")


def print_success(message: str):
    """Print a success message."""
    console.print(f"  [{COLORS['success']}]✓[/] {message}")


def print_error(message: str):
    """Print an error message."""
    console.print(f"  [{COLORS['error']}]✗[/] {message}")


def print_warning(message: str):
    """Print a warning message."""
    console.print(f"  [{COLORS['warning']}]⚠[/] {message}")


def print_tip(message: str):
    """Print a contextual tip, styled dim so it doesn't compete with AI output."""
    console.print(f"  [dim]Tip: {message}[/dim]")


def print_check(label: str, passed: bool, value: str = "", suggestion: str = ""):
    """Print a check result (for doctor command)."""
    if passed:
        console.print(f"  [{COLORS['success']}]✓[/] {label:<22} [dim]{value}[/dim]")
    else:
        console.print(f"  [{COLORS['error']}]✗[/] {label:<22} [dim]{value}[/dim]")
        if suggestion:
            console.print(f"    [dim]→ {suggestion}[/dim]")


def print_check_warning(label: str, value: str = "", suggestion: str = ""):
    """Print a warning check result."""
    console.print(f"  [{COLORS['warning']}]⚠[/] {label:<22} [dim]{value}[/dim]")
    if suggestion:
        console.print(f"    [dim]→ {suggestion}[/dim]")


def create_bar(value: float, max_value: float, width: int = 40) -> str:
    """Create an ASCII progress bar."""
    if max_value == 0:
        return "░" * width
    filled = int((value / max_value) * width)
    return "█" * filled + "░" * (width - filled)


def format_number(n: int) -> str:
    """Format a number with commas."""
    return f"{n:,}"


def format_bytes(b: int) -> str:
    """Format bytes to human readable."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"
