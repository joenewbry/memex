"""Color scheme and styles for Memex CLI."""

from rich.style import Style
from rich.theme import Theme

# Color palette
COLORS = {
    "primary": "#3B82F6",      # Blue (filing cabinet / professional)
    "secondary": "#6366F1",    # Indigo
    "success": "#10B981",      # Green
    "warning": "#F59E0B",      # Amber
    "error": "#EF4444",        # Red
    "muted": "#6B7280",        # Gray
    "text": "#F3F4F6",         # Light gray
    "dim": "#4B5563",          # Darker gray
    "creature_body": "#06B6D4", # Cyan-500 (legacy)
    "creature_eye": "#FACC15",  # Yellow-400 (legacy)
    "accent": "#A78BFA",        # Violet-400 (group headers)
    "stone": "#78716C",         # Stone-500 (gate pillars)
    "rune": "#60A5FA",          # Blue-400 (elven runes)
    "moon": "#FDE68A",          # Amber-200 (moonlight)
    "star": "#E2E8F0",          # Slate-200 (stars)
    "night": "#1E293B",         # Slate-800 (night sky)
}

# Rich styles
STYLES = {
    "header": Style(color=COLORS["primary"], bold=True),
    "success": Style(color=COLORS["success"]),
    "warning": Style(color=COLORS["warning"]),
    "error": Style(color=COLORS["error"]),
    "muted": Style(color=COLORS["muted"]),
    "dim": Style(color=COLORS["dim"]),
    "bold": Style(bold=True),
    "value": Style(color=COLORS["text"]),
}

# Rich theme for console
MEMEX_THEME = Theme({
    "info": COLORS["primary"],
    "success": COLORS["success"],
    "warning": COLORS["warning"],
    "error": COLORS["error"],
    "muted": COLORS["muted"],
})
