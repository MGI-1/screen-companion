"""Chat panel UI — message bubbles, input box, header with status."""

import os
import customtkinter as ctk
from datetime import datetime
from typing import Callable, Optional

from screencompanion.ui.theme import (
    get_colors,
    get_font,
    CORNER_RADIUS,
    CORNER_RADIUS_SM,
    PANEL_PADDING,
    FONT_SIZE,
    FONT_SIZE_SM,
    FONT_SIZE_LG,
    FONT_SIZE_TITLE,
)
from screencompanion.config import WINDOW_WIDTH, WINDOW_HEIGHT


class ChatWidget(ctk.CTkToplevel):
    """Main chat panel that appears above the toggle button."""

    def __init__(
        self,
        on_send: Callable[[str], None],
        on_theme_toggle: Callable[[], None],
        on_settings: Callable[[], None],
        on_detect: Optional[Callable[[], None]] = None,
        on_edit: Optional[Callable[[], None]] = None,
        mode: str = "dark",
    ):
        super().__init__()
        self._on_send = on_send
        self._on_theme_toggle = on_theme_toggle
        self._on_settings = on_settings
        self._on_detect = on_detect
        self._on_edit = on_edit
        self._mode = mode

        # Window config — use a normal window so keyboard input works on macOS
        self.title("Screen Companion")
        self.attributes("-topmost", True)
        self.resizable(False, False)

        # Hide from dock/taskbar on macOS
        import sys
        if sys.platform == "darwin":
            self.attributes("-alpha", 0.97)

        self._build_ui()
        self.withdraw()  # Hidden by default
        self._shown_once = False

        # Handle window close (X button) — quit the entire app
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """Quit the entire application when the chat window is closed."""
        if self._shown_once:
            import sys
            sys.exit(0)

    def show(self, x: int, y: int):
        """Show the panel positioned above the toggle button."""
        self._shown_once = True
        panel_x = x + 52 - WINDOW_WIDTH  # align right edge with button
        panel_y = y - WINDOW_HEIGHT - 10  # above the button
        # Ensure panel stays on screen
        if panel_x < 10:
            panel_x = 10
        if panel_y < 10:
            panel_y = 10
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{panel_x}+{panel_y}")
        self.deiconify()
        self.lift()

        # macOS: the process must become the active (frontmost) app to
        # receive keyboard events.  The root Tk window is withdrawn so
        # macOS will not activate the process on its own.
        self._activate_app()

        self.focus_force()
        self._input_field.focus_set()
        # Belt-and-suspenders: retry after the event loop settles
        self.after(150, lambda: (self.focus_force(), self._input_field.focus_set()))

    @staticmethod
    def _activate_app():
        """Tell macOS to make this process the key application."""
        import sys
        if sys.platform != "darwin":
            return
        try:
            from AppKit import NSApplication, NSApplicationActivateIgnoringOtherApps
            app = NSApplication.sharedApplication()
            app.activateIgnoringOtherApps_(True)
        except ImportError:
            # PyObjC not available — fall back to osascript
            import subprocess
            try:
                pid = str(os.getpid())
                subprocess.Popen(
                    ["osascript", "-e",
                     f'tell application "System Events" to set frontmost '
                     f'of (first process whose unix id is {pid}) to true'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                pass

    def hide(self):
        """Hide the chat panel."""
        self.withdraw()

    def is_visible(self) -> bool:
        return self.winfo_viewable()

    def _build_ui(self):
        colors = get_colors(self._mode)

        # Main container with glass border effect
        self._container = ctk.CTkFrame(
            self,
            fg_color=colors["bg"],
            corner_radius=CORNER_RADIUS,
            border_width=1,
            border_color=colors["bg_glass_border"],
        )
        self._container.pack(fill="both", expand=True, padx=1, pady=1)

        # ── Header ─────────────────────────────────────────────
        self._header = ctk.CTkFrame(
            self._container,
            fg_color=colors["header_bg"],
            corner_radius=0,
            height=48,
        )
        self._header.pack(fill="x", padx=0, pady=0)
        self._header.pack_propagate(False)

        # Title
        self._title_label = ctk.CTkLabel(
            self._header,
            text="Screen Companion",
            font=get_font(FONT_SIZE_TITLE, "bold"),
            text_color=colors["accent"],
            anchor="w",
        )
        self._title_label.pack(side="left", padx=PANEL_PADDING)

        # Settings gear button
        self._settings_btn = ctk.CTkButton(
            self._header,
            text="\u2699",
            width=30,
            height=30,
            corner_radius=15,
            fg_color="transparent",
            hover_color=colors["bg_glass"],
            text_color=colors["text_muted"],
            font=get_font(16),
            command=self._on_settings,
        )
        self._settings_btn.pack(side="right", padx=4)

        # Detect document button
        self._detect_btn = ctk.CTkButton(
            self._header,
            text="\U0001f50d",
            width=30,
            height=30,
            corner_radius=15,
            fg_color="transparent",
            hover_color=colors["bg_glass"],
            text_color=colors["text_muted"],
            font=get_font(14),
            command=self._handle_detect,
        )
        self._detect_btn.pack(side="right", padx=0)

        # Theme toggle (sun/moon)
        self._theme_btn = ctk.CTkButton(
            self._header,
            text="\u263e" if self._mode == "dark" else "\u2600",
            width=30,
            height=30,
            corner_radius=15,
            fg_color="transparent",
            hover_color=colors["bg_glass"],
            text_color=colors["text_muted"],
            font=get_font(16),
            command=self._on_theme_toggle,
        )
        self._theme_btn.pack(side="right", padx=0)

        # ── Document status bar ────────────────────────────────
        self._status_bar = ctk.CTkFrame(
            self._container,
            fg_color=colors["status_bg"],
            corner_radius=0,
            height=32,
        )
        self._status_bar.pack(fill="x", padx=0, pady=0)
        self._status_bar.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            self._status_bar,
            text="No document detected",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
            anchor="w",
        )
        self._status_label.pack(side="left", padx=PANEL_PADDING, pady=4)

        # Edit button (pencil) — shown only for editable documents
        self._edit_btn = ctk.CTkButton(
            self._status_bar,
            text="\u270E",
            width=26,
            height=26,
            corner_radius=13,
            fg_color="transparent",
            hover_color=colors["bg_glass"],
            text_color=colors["accent"],
            font=get_font(13),
            command=self._handle_edit_click,
        )
        # Hidden by default — shown when an editable doc is detected

        # ── Chat area (scrollable) ─────────────────────────────
        self._chat_frame = ctk.CTkScrollableFrame(
            self._container,
            fg_color=colors["bg"],
            corner_radius=0,
            scrollbar_button_color=colors["scrollbar"],
            scrollbar_button_hover_color=colors["accent"],
        )
        self._chat_frame.pack(fill="both", expand=True, padx=0, pady=0)
        # Fix internal canvas background to match theme (prevents green flash)
        try:
            self._chat_frame._parent_canvas.configure(bg=colors["bg"])
        except Exception:
            pass

        # ── Input area ─────────────────────────────────────────
        self._input_frame = ctk.CTkFrame(
            self._container,
            fg_color=colors["bg_glass"],
            corner_radius=0,
            height=56,
        )
        self._input_frame.pack(fill="x", padx=0, pady=0, side="bottom")
        self._input_frame.pack_propagate(False)

        self._input_field = ctk.CTkEntry(
            self._input_frame,
            placeholder_text="Ask about your document...",
            font=get_font(FONT_SIZE),
            fg_color=colors["input_bg"],
            border_color=colors["input_border"],
            text_color=colors["text"],
            placeholder_text_color=colors["text_muted"],
            corner_radius=CORNER_RADIUS_SM,
            height=36,
            border_width=1,
        )
        self._input_field.pack(
            side="left", fill="x", expand=True, padx=(PANEL_PADDING, 6), pady=10
        )
        self._input_field.bind("<Return>", self._handle_send)
        self._input_field.bind("<FocusIn>", self._on_input_focus)
        self._input_field.bind("<FocusOut>", self._on_input_blur)

        self._send_btn = ctk.CTkButton(
            self._input_frame,
            text="\u27a4",
            width=36,
            height=36,
            corner_radius=CORNER_RADIUS_SM,
            fg_color=colors["accent"],
            hover_color=colors["accent_hover"],
            text_color=colors["text_on_accent"],
            font=get_font(16),
            command=lambda: self._handle_send(None),
        )
        self._send_btn.pack(side="right", padx=(0, PANEL_PADDING), pady=10)

        # Bind Escape to hide
        self.bind("<Escape>", lambda e: self.hide())


    def _on_input_focus(self, event):
        colors = get_colors(self._mode)
        self._input_field.configure(border_color=colors["input_border_focus"])

    def _on_input_blur(self, event):
        colors = get_colors(self._mode)
        self._input_field.configure(border_color=colors["input_border"])

    def _handle_detect(self):
        if self._on_detect:
            self._on_detect()

    def _handle_edit_click(self):
        if self._on_edit:
            self._on_edit()

    def _handle_send(self, event):
        text = self._input_field.get().strip()
        if text:
            self._input_field.delete(0, "end")
            self._on_send(text)

    # ── Public methods ─────────────────────────────────────────

    def set_document_status(self, filename: str, editable: bool = False):
        """Update the document status bar."""
        colors = get_colors(self._mode)
        if filename:
            suffix = " (editable)" if editable else ""
            self._status_label.configure(
                text=f"\U0001f4c4 {filename}{suffix}",
                text_color=colors["text"],
            )
            if editable:
                self._edit_btn.pack(side="right", padx=4, pady=2)
            else:
                self._edit_btn.pack_forget()
        else:
            self._status_label.configure(
                text="No document detected",
                text_color=colors["text_muted"],
            )
            self._edit_btn.pack_forget()

    def add_user_message(self, text: str):
        """Add a user message bubble (right-aligned, orange)."""
        colors = get_colors(self._mode)

        wrapper = ctk.CTkFrame(self._chat_frame, fg_color="transparent")
        wrapper.pack(fill="x", padx=PANEL_PADDING, pady=(4, 2))

        bubble = ctk.CTkFrame(
            wrapper,
            fg_color=colors["user_bubble"],
            corner_radius=CORNER_RADIUS_SM,
        )
        bubble.pack(side="right", anchor="e")

        label = ctk.CTkLabel(
            bubble,
            text=text,
            font=get_font(FONT_SIZE),
            text_color=colors["user_bubble_text"],
            wraplength=WINDOW_WIDTH - 100,
            justify="left",
            anchor="w",
        )
        label.pack(padx=10, pady=6)

        self._scroll_to_bottom()

    def add_bot_message(self, text: str):
        """Add a bot message bubble (left-aligned, glass)."""
        colors = get_colors(self._mode)
        max_bubble_width = WINDOW_WIDTH - 2 * PANEL_PADDING - 20

        wrapper = ctk.CTkFrame(self._chat_frame, fg_color="transparent")
        wrapper.pack(fill="x", padx=PANEL_PADDING, pady=(2, 4))

        bubble = ctk.CTkFrame(
            wrapper,
            fg_color=colors["bot_bubble"],
            corner_radius=CORNER_RADIUS_SM,
            border_width=1,
            border_color=colors["border_subtle"],
        )
        bubble.pack(side="left", anchor="w")

        label = ctk.CTkLabel(
            bubble,
            text=text,
            font=get_font(FONT_SIZE),
            text_color=colors["bot_bubble_text"],
            wraplength=max_bubble_width - 20,
            justify="left",
            anchor="w",
        )
        label.pack(padx=10, pady=6)

        self._scroll_to_bottom()

    def add_system_message(self, text: str):
        """Add a system notification (centered, muted)."""
        colors = get_colors(self._mode)
        max_wrap = WINDOW_WIDTH - 2 * PANEL_PADDING - 10

        wrapper = ctk.CTkFrame(self._chat_frame, fg_color="transparent")
        wrapper.pack(fill="x", padx=PANEL_PADDING, pady=(6, 6))

        label = ctk.CTkLabel(
            wrapper,
            text=text,
            font=get_font(FONT_SIZE_SM),
            text_color=colors["system_msg"],
            wraplength=max_wrap,
            justify="center",
            anchor="center",
        )
        label.pack()

        self._scroll_to_bottom()

    def add_edit_proposal(
        self,
        description: str,
        on_apply: Callable,
        on_cancel: Callable,
    ):
        """Add an edit proposal with Apply/Cancel buttons."""
        colors = get_colors(self._mode)

        wrapper = ctk.CTkFrame(self._chat_frame, fg_color="transparent")
        wrapper.pack(fill="x", padx=PANEL_PADDING, pady=(2, 4))

        card = ctk.CTkFrame(
            wrapper,
            fg_color=colors["bot_bubble"],
            corner_radius=CORNER_RADIUS_SM,
            border_width=1,
            border_color=colors["accent"],
        )
        card.pack(side="left", anchor="w", fill="x", expand=True)

        label = ctk.CTkLabel(
            card,
            text=description,
            font=get_font(FONT_SIZE_SM),
            text_color=colors["bot_bubble_text"],
            wraplength=WINDOW_WIDTH - 120,
            justify="left",
            anchor="w",
        )
        label.pack(padx=10, pady=(8, 4))

        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(padx=10, pady=(0, 8))

        def _apply():
            on_apply()
            apply_btn.configure(state="disabled", text="Applied")
            cancel_btn.pack_forget()

        def _cancel():
            on_cancel()
            card.destroy()

        apply_btn = ctk.CTkButton(
            btn_frame,
            text="Apply",
            width=70,
            height=28,
            corner_radius=CORNER_RADIUS_SM,
            fg_color=colors["accent"],
            hover_color=colors["accent_hover"],
            text_color=colors["text_on_accent"],
            font=get_font(FONT_SIZE_SM, "bold"),
            command=_apply,
        )
        apply_btn.pack(side="left", padx=(0, 6))

        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=70,
            height=28,
            corner_radius=CORNER_RADIUS_SM,
            fg_color="transparent",
            hover_color=colors["bg_glass"],
            text_color=colors["text_muted"],
            font=get_font(FONT_SIZE_SM),
            border_width=1,
            border_color=colors["border_subtle"],
            command=_cancel,
        )
        cancel_btn.pack(side="left")

        self._scroll_to_bottom()

    def show_typing_indicator(self):
        """Show a typing indicator."""
        colors = get_colors(self._mode)
        self._typing_frame = ctk.CTkFrame(
            self._chat_frame, fg_color="transparent"
        )
        self._typing_frame.pack(fill="x", padx=PANEL_PADDING, pady=(2, 4))

        bubble = ctk.CTkFrame(
            self._typing_frame,
            fg_color=colors["bot_bubble"],
            corner_radius=CORNER_RADIUS_SM,
        )
        bubble.pack(side="left", anchor="w")

        self._typing_label = ctk.CTkLabel(
            bubble,
            text="Thinking...",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
        )
        self._typing_label.pack(padx=10, pady=6)
        self._scroll_to_bottom()

    def hide_typing_indicator(self):
        """Remove the typing indicator."""
        if hasattr(self, "_typing_frame") and self._typing_frame.winfo_exists():
            self._typing_frame.destroy()

    def clear_messages(self):
        """Remove all messages from the chat area."""
        for widget in self._chat_frame.winfo_children():
            widget.destroy()

    def set_input_enabled(self, enabled: bool):
        """Enable or disable the input field and send button."""
        state = "normal" if enabled else "disabled"
        self._input_field.configure(state=state)
        self._send_btn.configure(state=state)

    def _scroll_to_bottom(self):
        """Scroll chat area to the bottom."""
        self._chat_frame.update_idletasks()
        self._chat_frame._parent_canvas.yview_moveto(1.0)

    def update_theme(self, mode: str):
        """Rebuild UI with new theme colors."""
        self._mode = mode
        colors = get_colors(mode)

        # Update theme toggle icon
        self._theme_btn.configure(
            text="\u263e" if mode == "dark" else "\u2600"
        )

        # Update container
        self._container.configure(
            fg_color=colors["bg"],
            border_color=colors["bg_glass_border"],
        )

        # Update header
        self._header.configure(fg_color=colors["header_bg"])
        self._title_label.configure(text_color=colors["accent"])
        self._theme_btn.configure(
            text_color=colors["text_muted"],
            hover_color=colors["bg_glass"],
        )
        self._settings_btn.configure(
            text_color=colors["text_muted"],
            hover_color=colors["bg_glass"],
        )
        self._detect_btn.configure(
            text_color=colors["text_muted"],
            hover_color=colors["bg_glass"],
        )

        # Update status bar
        self._status_bar.configure(fg_color=colors["status_bg"])
        self._status_label.configure(text_color=colors["text_muted"])
        self._edit_btn.configure(
            text_color=colors["accent"],
            hover_color=colors["bg_glass"],
        )

        # Update chat frame
        self._chat_frame.configure(fg_color=colors["bg"])
        try:
            self._chat_frame._parent_canvas.configure(bg=colors["bg"])
        except Exception:
            pass

        # Update input area
        self._input_frame.configure(fg_color=colors["bg_glass"])
        self._input_field.configure(
            fg_color=colors["input_bg"],
            border_color=colors["input_border"],
            text_color=colors["text"],
            placeholder_text_color=colors["text_muted"],
        )
        self._send_btn.configure(
            fg_color=colors["accent"],
            hover_color=colors["accent_hover"],
        )
