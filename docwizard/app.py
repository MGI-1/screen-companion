"""Main application — coordinates UI, detector, reader, chat, and editor."""

import os
import sys
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from docwizard.config import (
    LLM_PROVIDERS,
    WINDOW_WIDTH,
    WINDOW_HEIGHT,
    load_user_config,
    save_user_config,
)
from docwizard.ui.theme import get_colors, get_font, CORNER_RADIUS, CORNER_RADIUS_SM, FONT_SIZE, FONT_SIZE_SM, FONT_SIZE_LG, PANEL_PADDING
from docwizard.ui.toggle_button import ToggleButton
from docwizard.ui.chat_widget import ChatWidget
from docwizard.chat import DocumentChat
from docwizard.reader import read_document, UnsupportedFormatError, FileTooLargeError
from docwizard.editor import apply_edits, UnsupportedEditError


class ScreenCompanionApp:
    """Main application class."""

    def __init__(self):
        self._config = load_user_config()
        self._mode = self._config.get("theme", "dark")
        self._current_doc_path: Optional[str] = None

        # Init customtkinter
        ctk.set_appearance_mode("dark" if self._mode == "dark" else "light")
        self._root = ctk.CTk()
        self._root.withdraw()  # Hide the root window

        # Chat engine
        self._chat = DocumentChat()
        self._load_llm_config()

        # UI components
        self._toggle = ToggleButton(
            on_toggle=self._on_toggle,
            mode=self._mode,
        )
        self._chat_widget = ChatWidget(
            on_send=self._on_send_message,
            on_theme_toggle=self._on_theme_toggle,
            on_settings=self._on_settings,
            on_detect=self._on_detect_document,
            mode=self._mode,
        )

        # Detector + focus watcher
        self._detector = None
        self._watcher = None
        self._init_detector()

        # Show settings on first launch if not configured
        if not self._chat.is_configured():
            self._root.after(500, self._show_first_launch)

    def _load_llm_config(self):
        """Load LLM provider config from saved settings."""
        provider = self._config.get("provider")
        api_key = self._config.get("api_key")
        model = self._config.get("model", "")

        if provider and api_key:
            self._chat.configure(provider, api_key, model)

    def _init_detector(self):
        """Initialize the platform-specific detector."""
        try:
            from docwizard.detector import Detector
            from docwizard.detector.base import FocusWatcher

            self._detector = Detector()
            self._watcher = FocusWatcher(
                detector=self._detector,
                on_change=self._on_document_change,
            )
            self._watcher.start()
        except (RuntimeError, ImportError) as e:
            # Platform not supported or missing dependencies
            self._chat_widget.add_system_message(
                f"Document detection unavailable: {e}"
            )

    def _on_detect_document(self):
        """Manually trigger document detection."""
        if self._watcher:
            self._watcher.check_now()
            if not self._current_doc_path:
                self._chat_widget.add_system_message("No document detected.")
        else:
            self._chat_widget.add_system_message(
                "Document detection is not available."
            )

    def _on_toggle(self):
        """Toggle the chat panel open/closed."""
        if self._chat_widget.is_visible():
            self._chat_widget.hide()
        else:
            # Check for document before showing
            if self._watcher:
                self._watcher.check_now()
            x, y = self._toggle.get_position()
            self._chat_widget.show(x, y)

    def _on_document_change(self, path: str):
        """Called when the focused document changes (from background thread)."""
        self._current_doc_path = path
        filename = Path(path).name

        # Schedule UI updates on main thread
        self._root.after(0, lambda: self._process_document(path, filename))

    def _process_document(self, path: str, filename: str):
        """Read and load document content (called on main thread)."""
        self._chat_widget.set_document_status(filename)
        self._toggle.set_doc_detected(True)

        try:
            content = read_document(path)
            self._chat.set_document(path, content)
            self._chat_widget.add_system_message(
                f"Loaded: {filename} ({len(content):,} chars)"
            )
        except (UnsupportedFormatError, FileTooLargeError, FileNotFoundError) as e:
            self._chat_widget.add_system_message(str(e))
        except Exception as e:
            self._chat_widget.add_system_message(f"Error reading file: {e}")

    def _on_send_message(self, text: str):
        """Handle user message from chat input."""
        # Handle special commands
        if text.startswith("/"):
            self._handle_command(text)
            return

        self._chat_widget.add_user_message(text)

        if not self._chat.is_configured():
            self._chat_widget.add_bot_message(
                "Please configure your LLM provider first. "
                "Click the gear icon (\u2699) in the header."
            )
            return

        # Show typing indicator and disable input
        self._chat_widget.show_typing_indicator()
        self._chat_widget.set_input_enabled(False)

        # Run LLM call in background thread
        def _ask():
            response = self._chat.ask(text)
            self._root.after(0, lambda: self._handle_response(response))

        threading.Thread(target=_ask, daemon=True).start()

    def _handle_response(self, response: str):
        """Process LLM response (called on main thread)."""
        self._chat_widget.hide_typing_indicator()
        self._chat_widget.set_input_enabled(True)

        # Check for edit instructions
        edits = DocumentChat.parse_edit_instructions(response)

        # Show the text response (strip the JSON block for cleaner display)
        import re
        display_text = re.sub(
            r"```json\s*\n?\{.*?\}\s*\n?```", "", response, flags=re.DOTALL
        ).strip()
        if display_text:
            self._chat_widget.add_bot_message(display_text)

        # Show edit proposal if detected
        if edits and self._current_doc_path:
            desc_parts = []
            for edit in edits:
                s = edit.get("search", "")[:40]
                r = edit.get("replace", "")[:40]
                desc_parts.append(f"'{s}' → '{r}'")
            description = "Proposed edits:\n" + "\n".join(desc_parts)

            self._chat_widget.add_edit_proposal(
                description=description,
                on_apply=lambda: self._apply_edits(edits),
                on_cancel=lambda: None,
            )

    def _apply_edits(self, edits: list[dict]):
        """Apply edits to the current document."""
        if not self._current_doc_path:
            self._chat_widget.add_system_message("No document to edit.")
            return

        try:
            result = apply_edits(self._current_doc_path, edits)
            self._chat_widget.add_system_message(f"Edits applied:\n{result}")

            # Re-read the document
            content = read_document(self._current_doc_path)
            self._chat.set_document(self._current_doc_path, content)
        except (UnsupportedEditError, PermissionError) as e:
            self._chat_widget.add_system_message(f"Edit failed: {e}")
        except Exception as e:
            self._chat_widget.add_system_message(f"Error applying edits: {e}")

    def _handle_command(self, text: str):
        """Handle slash commands."""
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd in ("/quit", "/exit"):
            self._root.quit()

        elif cmd == "/clear":
            self._chat_widget.clear_messages()
            self._chat.messages = []
            self._chat_widget.add_system_message("Conversation cleared.")

        elif cmd == "/reload":
            if self._current_doc_path:
                filename = Path(self._current_doc_path).name
                self._process_document(self._current_doc_path, filename)
            else:
                self._chat_widget.add_system_message("No document to reload.")

        elif cmd == "/switch":
            if len(parts) > 1:
                path = parts[1].strip().strip('"').strip("'")
                path = os.path.expanduser(path)
                if os.path.isfile(path):
                    filename = Path(path).name
                    self._current_doc_path = path
                    self._process_document(path, filename)
                else:
                    self._chat_widget.add_system_message(f"File not found: {path}")
            else:
                self._chat_widget.add_system_message("Usage: /switch <file_path>")

        elif cmd == "/status":
            provider = self._config.get("provider", "not set")
            model = self._config.get("model", "not set")
            doc = self._current_doc_path or "none"
            platform = sys.platform
            self._chat_widget.add_system_message(
                f"Platform: {platform}\n"
                f"Provider: {provider}\n"
                f"Model: {model}\n"
                f"Document: {doc}"
            )

        else:
            self._chat_widget.add_system_message(
                "Commands: /clear, /reload, /switch <path>, /status, /quit"
            )

    def _on_theme_toggle(self):
        """Toggle between dark and light mode."""
        self._mode = "light" if self._mode == "dark" else "dark"
        ctk.set_appearance_mode(self._mode)

        self._toggle.update_theme(self._mode)
        self._chat_widget.update_theme(self._mode)

        self._config["theme"] = self._mode
        save_user_config(self._config)

    def _on_settings(self):
        """Show the settings dialog."""
        self._show_settings_dialog()

    def _show_first_launch(self):
        """Show welcome + settings on first launch."""
        x, y = self._toggle.get_position()
        self._chat_widget.show(x, y)
        self._chat_widget.add_system_message(
            "Welcome to Screen Companion! Configure your LLM provider to get started."
        )
        self._show_settings_dialog()

    def _show_settings_dialog(self):
        """Show settings dialog for LLM provider configuration."""
        colors = get_colors(self._mode)

        dialog = ctk.CTkToplevel(self._root)
        dialog.title("Screen Companion Settings")
        dialog.geometry("340x380")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)

        # Center on screen
        dialog.update_idletasks()
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        x = (sw - 340) // 2
        y = (sh - 380) // 2
        dialog.geometry(f"340x380+{x}+{y}")

        frame = ctk.CTkFrame(
            dialog,
            fg_color=colors["bg"],
            corner_radius=0,
        )
        frame.pack(fill="both", expand=True)

        # Title
        ctk.CTkLabel(
            frame,
            text="LLM Settings",
            font=get_font(FONT_SIZE_LG, "bold"),
            text_color=colors["accent"],
        ).pack(pady=(20, 16))

        # Provider dropdown
        ctk.CTkLabel(
            frame,
            text="Provider",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
            anchor="w",
        ).pack(padx=24, anchor="w")

        provider_names = {v["name"]: k for k, v in LLM_PROVIDERS.items()}
        current_provider = self._config.get("provider", "")
        current_name = ""
        if current_provider:
            current_name = LLM_PROVIDERS.get(current_provider, {}).get("name", "")

        provider_var = ctk.StringVar(value=current_name)
        provider_menu = ctk.CTkOptionMenu(
            frame,
            values=list(provider_names.keys()),
            variable=provider_var,
            fg_color=colors["input_bg"],
            button_color=colors["accent"],
            button_hover_color=colors["accent_hover"],
            text_color=colors["text"],
            font=get_font(FONT_SIZE),
            width=292,
            height=36,
            corner_radius=CORNER_RADIUS_SM,
            command=lambda v: _on_provider_change(v),
        )
        provider_menu.pack(padx=24, pady=(4, 12))

        # Model dropdown
        ctk.CTkLabel(
            frame,
            text="Model",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
            anchor="w",
        ).pack(padx=24, anchor="w")

        current_model = self._config.get("model", "")
        model_var = ctk.StringVar(value=current_model)
        model_menu = ctk.CTkOptionMenu(
            frame,
            values=self._get_models_for_provider(current_provider),
            variable=model_var,
            fg_color=colors["input_bg"],
            button_color=colors["accent"],
            button_hover_color=colors["accent_hover"],
            text_color=colors["text"],
            font=get_font(FONT_SIZE),
            width=292,
            height=36,
            corner_radius=CORNER_RADIUS_SM,
        )
        model_menu.pack(padx=24, pady=(4, 12))

        def _on_provider_change(name):
            key = provider_names.get(name, "")
            models = self._get_models_for_provider(key)
            model_menu.configure(values=models)
            if models:
                model_var.set(models[0])

        # API Key
        ctk.CTkLabel(
            frame,
            text="API Key",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
            anchor="w",
        ).pack(padx=24, anchor="w")

        api_key_entry = ctk.CTkEntry(
            frame,
            placeholder_text="sk-... or AIza...",
            font=get_font(FONT_SIZE),
            fg_color=colors["input_bg"],
            border_color=colors["input_border"],
            text_color=colors["text"],
            placeholder_text_color=colors["text_muted"],
            width=292,
            height=36,
            corner_radius=CORNER_RADIUS_SM,
            show="*",
        )
        api_key_entry.pack(padx=24, pady=(4, 20))

        # Pre-fill existing key (masked)
        existing_key = self._config.get("api_key", "")
        if existing_key:
            api_key_entry.insert(0, existing_key)

        # Save button
        def _save():
            name = provider_var.get()
            provider_key = provider_names.get(name)
            model = model_var.get()
            api_key = api_key_entry.get().strip()

            if not provider_key:
                return
            if not api_key:
                return

            self._config["provider"] = provider_key
            self._config["model"] = model
            self._config["api_key"] = api_key
            save_user_config(self._config)

            self._chat.configure(provider_key, api_key, model)
            self._chat_widget.add_system_message(
                f"Configured: {name} / {model}"
            )
            dialog.destroy()

        ctk.CTkButton(
            frame,
            text="Save",
            font=get_font(FONT_SIZE, "bold"),
            fg_color=colors["accent"],
            hover_color=colors["accent_hover"],
            text_color=colors["text_on_accent"],
            width=292,
            height=40,
            corner_radius=CORNER_RADIUS_SM,
            command=_save,
        ).pack(padx=24)

    def _get_models_for_provider(self, provider_key: str) -> list[str]:
        """Get available models for a provider."""
        info = LLM_PROVIDERS.get(provider_key, {})
        return info.get("models", [])

    def run(self):
        """Start the application main loop."""
        self._root.mainloop()


def main():
    """Entry point."""
    app = ScreenCompanionApp()
    app.run()


if __name__ == "__main__":
    main()
