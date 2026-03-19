"""Floating circular toggle button — sits in the bottom-right corner of the screen."""

import os
import sys
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from docwizard.ui.theme import get_colors, get_font


def _get_icon_path() -> str:
    """Resolve the icon path for both dev and bundled (PyInstaller) environments."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent.parent
    return str(base / "assets" / "icon.png")


TOGGLE_SIZE = 52
SCREEN_PADDING = 20


class ToggleButton(ctk.CTkToplevel):
    """Small floating button that opens/closes the chat panel."""

    def __init__(self, on_toggle: callable, mode: str = "dark"):
        super().__init__()
        self._on_toggle = on_toggle
        self._mode = mode
        self._doc_detected = False

        # Window config — frameless, always on top
        self.overrideredirect(True)
        self.attributes("-topmost", True)

        # Set background to match the button color
        colors = get_colors(self._mode)
        self.configure(fg_color=colors["bg_deep"])

        # Position bottom-right
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = screen_w - TOGGLE_SIZE - SCREEN_PADDING
        y = screen_h - TOGGLE_SIZE - SCREEN_PADDING - 60  # above taskbar
        self.geometry(f"{TOGGLE_SIZE}x{TOGGLE_SIZE}+{x}+{y}")

        self._build_ui()

        # Dragging support
        self._drag_x = 0
        self._drag_y = 0

    def _build_ui(self):
        colors = get_colors(self._mode)

        # Load the app icon
        icon_path = _get_icon_path()
        icon_size = TOGGLE_SIZE - 2  # slight padding
        try:
            pil_image = Image.open(icon_path).resize(
                (icon_size * 2, icon_size * 2), Image.LANCZOS
            )
            self._icon_image = ctk.CTkImage(
                light_image=pil_image,
                dark_image=pil_image,
                size=(icon_size, icon_size),
            )
        except Exception:
            self._icon_image = None

        self._btn = ctk.CTkButton(
            self,
            width=TOGGLE_SIZE,
            height=TOGGLE_SIZE,
            corner_radius=TOGGLE_SIZE // 2,
            text="" if self._icon_image else "W",
            image=self._icon_image,
            font=get_font(20, "bold"),
            fg_color=colors["bg_deep"],
            hover_color=colors["bg_deep"],
            text_color=colors["text_on_accent"],
            command=self._on_toggle,
            border_width=0,
        )
        self._btn.pack(fill="both", expand=True)

        # Enable dragging
        self._btn.bind("<Button-1>", self._start_drag)
        self._btn.bind("<B1-Motion>", self._do_drag)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        x = self.winfo_x() + event.x - self._drag_x
        y = self.winfo_y() + event.y - self._drag_y
        self.geometry(f"+{x}+{y}")

    def set_doc_detected(self, detected: bool):
        """Visual feedback when a document is detected."""
        self._doc_detected = detected
        colors = get_colors(self._mode)
        if detected:
            self._btn.configure(
                border_width=2,
                border_color=colors["accent"],
            )
        else:
            self._btn.configure(
                border_width=0,
            )

    def update_theme(self, mode: str):
        """Switch between dark and light theme."""
        self._mode = mode
        colors = get_colors(mode)
        self._btn.configure(
            fg_color=colors["bg_deep"],
            hover_color=colors["bg_deep"],
        )
        self.configure(fg_color=colors["bg_deep"])
        if self._doc_detected:
            self.set_doc_detected(True)

    def get_position(self) -> tuple[int, int]:
        """Return current (x, y) position of the button."""
        return self.winfo_x(), self.winfo_y()
