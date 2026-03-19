"""Dark/Light glassmorphism theme — Outfit font, orange accent."""

import sys

THEMES = {
    "dark": {
        # Backgrounds (deep navy, layered glass)
        "bg_deep": "#0c1526",
        "bg": "#142039",
        "bg_glass": "#162240",
        "bg_glass_border": "#1e2d4d",
        # Accents
        "accent": "#ff7e00",
        "accent_hover": "#ff9933",
        "accent_secondary": "#e11d48",
        # Text
        "text": "#e2e8f0",
        "text_muted": "#94a3b8",
        "text_on_accent": "#ffffff",
        # Chat bubbles
        "user_bubble": "#ff7e00",
        "user_bubble_text": "#ffffff",
        "bot_bubble": "#1a2744",
        "bot_bubble_text": "#e2e8f0",
        # Input
        "input_bg": "#0f1a2e",
        "input_border": "#2a3a5c",
        "input_border_focus": "#ff7e00",
        # Misc
        "success": "#22c55e",
        "border_subtle": "#1e2d4d",
        "shadow": "#00000066",
        "toggle_icon_bg": "#ff7e00",
        "header_bg": "#0c1526",
        "status_bg": "#0f1a2e",
        "scrollbar": "#2a3a5c",
        "system_msg": "#94a3b8",
    },
    "light": {
        # Backgrounds (soft white/gray, frosted glass)
        "bg_deep": "#f0f2f5",
        "bg": "#f8f9fb",
        "bg_glass": "#ffffff",
        "bg_glass_border": "#e2e5ea",
        # Accents
        "accent": "#ff7e00",
        "accent_hover": "#e06e00",
        "accent_secondary": "#e11d48",
        # Text
        "text": "#1e293b",
        "text_muted": "#64748b",
        "text_on_accent": "#ffffff",
        # Chat bubbles
        "user_bubble": "#ff7e00",
        "user_bubble_text": "#ffffff",
        "bot_bubble": "#f1f3f6",
        "bot_bubble_text": "#1e293b",
        # Input
        "input_bg": "#ffffff",
        "input_border": "#d1d5db",
        "input_border_focus": "#ff7e00",
        # Misc
        "success": "#16a34a",
        "border_subtle": "#e5e7eb",
        "shadow": "#0000001a",
        "toggle_icon_bg": "#ff7e00",
        "header_bg": "#f0f2f5",
        "status_bg": "#e8eaed",
        "scrollbar": "#c4c8cf",
        "system_msg": "#64748b",
    },
}

# Font setup — Outfit with platform fallbacks
FONT_FAMILY = "Outfit"
if sys.platform == "win32":
    FONT_FALLBACK = "Segoe UI"
elif sys.platform == "darwin":
    FONT_FALLBACK = "SF Pro Display"
else:
    FONT_FALLBACK = "Helvetica Neue"

FONT_SIZE_SM = 11
FONT_SIZE = 13
FONT_SIZE_LG = 15
FONT_SIZE_TITLE = 17
FONT_WEIGHT_NORMAL = "normal"
FONT_WEIGHT_BOLD = "bold"

CORNER_RADIUS = 14
CORNER_RADIUS_SM = 8
PANEL_PADDING = 12


def get_font(size: int = FONT_SIZE, weight: str = FONT_WEIGHT_NORMAL) -> tuple:
    """Return a font tuple, preferring Outfit with fallback."""
    return (FONT_FAMILY, size, weight)


def get_colors(mode: str = "dark") -> dict:
    """Return color dict for the given mode."""
    return THEMES.get(mode, THEMES["dark"])
