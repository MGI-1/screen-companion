"""Main application — coordinates UI, detector, reader, chat, and editor."""

import os
import sys
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from screencompanion.config import (
    LLM_PROVIDERS,
    SUPPORTED_EDIT_FORMATS,
    WINDOW_WIDTH,
    WINDOW_HEIGHT,
    load_user_config,
    save_user_config,
    get_max_input_chars,
)
from screencompanion.ui.theme import get_colors, get_font, CORNER_RADIUS, CORNER_RADIUS_SM, FONT_SIZE, FONT_SIZE_SM, FONT_SIZE_LG, PANEL_PADDING
from screencompanion.ui.toggle_button import ToggleButton
from screencompanion.ui.chat_widget import ChatWidget
from screencompanion.chat import DocumentChat
from screencompanion.reader import read_document, read_dataframe, UnsupportedFormatError, FileTooLargeError
from screencompanion.editor import apply_edits, UnsupportedEditError
from screencompanion.browser_server import BrowserServer


class ScreenCompanionApp:
    """Main application class."""

    def __init__(self):
        self._config = load_user_config()
        self._mode = self._config.get("theme", "dark")
        self._current_doc_path: Optional[str] = None

        # Init customtkinter
        ctk.set_appearance_mode("dark" if self._mode == "dark" else "light")
        self._root = ctk.CTk()
        self._root.geometry("1x1+-10000+-10000")  # Off-screen, not withdrawn
        self._root.overrideredirect(True)          # No title bar

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
            on_edit=self._on_edit_document,
            mode=self._mode,
        )

        # Detector + focus watcher
        self._detector = None
        self._watcher = None
        self._init_detector()

        # Browser extension WebSocket server
        self._browser_server = BrowserServer(on_content=self._on_browser_content)
        self._browser_server.start()
        if not self._browser_server.available:
            # Surface the pip install hint once at startup
            self._root.after(
                1000,
                lambda: self._chat_widget.add_system_message(
                    self._browser_server.missing_msg
                ),
            )

        # Show settings on first launch if not configured
        if not self._chat.is_configured():
            self._root.after(500, self._show_first_launch)

    def _load_llm_config(self):
        """Load LLM provider config from saved settings, falling back to env vars."""
        import os
        provider = self._config.get("provider")
        api_key = self._config.get("api_key")
        model = self._config.get("model", "")

        if provider and api_key:
            self._chat.configure(provider, api_key, model)
        else:
            # Fall back to environment variables for any provider
            for provider_key, info in LLM_PROVIDERS.items():
                env_key = info.get("env_key", "")
                env_val = os.environ.get(env_key, "")
                if env_val:
                    self._chat.configure(provider_key, env_val, model)
                    self._config["provider"] = provider_key
                    self._config["model"] = model or info["default_model"]
                    break

        # Load optional validator config
        v_provider = self._config.get("validator_provider", "")
        v_key = self._config.get("validator_api_key", "")
        if v_provider and v_key:
            self._chat.configure_validator(v_provider, v_key)

    def _init_detector(self):
        """Initialize the platform-specific detector."""
        try:
            from screencompanion.detector import Detector
            from screencompanion.detector.base import FocusWatcher

            self._detector = Detector()
            self._watcher = FocusWatcher(
                detector=self._detector,
                on_change=self._on_document_change,
                on_clear=self._on_document_cleared,
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

    def _on_edit_document(self):
        """Open the Find & Replace dialog for the current document."""
        if not self._current_doc_path:
            self._chat_widget.add_system_message("No document to edit.")
            return

        ext = Path(self._current_doc_path).suffix.lower()
        if ext not in SUPPORTED_EDIT_FORMATS:
            self._chat_widget.add_system_message(
                f"'{ext}' files cannot be edited. "
                f"Editable: {', '.join(sorted(SUPPORTED_EDIT_FORMATS))}"
            )
            return

        self._show_find_replace_dialog()

    def _show_find_replace_dialog(self):
        """Show Find & Replace dialog for the current document."""
        colors = get_colors(self._mode)
        filename = Path(self._current_doc_path).name

        dialog = ctk.CTkToplevel(self._root)
        dialog.title("Find & Replace")
        dialog.geometry("340x310")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)

        # Center on screen
        dialog.update_idletasks()
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        x = (sw - 340) // 2
        y = (sh - 310) // 2
        dialog.geometry(f"340x310+{x}+{y}")

        frame = ctk.CTkFrame(dialog, fg_color=colors["bg"], corner_radius=0)
        frame.pack(fill="both", expand=True)

        # Title with filename
        ctk.CTkLabel(
            frame,
            text="Find & Replace",
            font=get_font(FONT_SIZE_LG, "bold"),
            text_color=colors["accent"],
        ).pack(pady=(20, 4))

        ctk.CTkLabel(
            frame,
            text=filename,
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
        ).pack(pady=(0, 12))

        # Find field
        ctk.CTkLabel(
            frame,
            text="Find",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
            anchor="w",
        ).pack(padx=24, anchor="w")

        find_entry = ctk.CTkEntry(
            frame,
            placeholder_text="Text to find...",
            font=get_font(FONT_SIZE),
            fg_color=colors["input_bg"],
            border_color=colors["input_border"],
            text_color=colors["text"],
            placeholder_text_color=colors["text_muted"],
            width=292,
            height=36,
            corner_radius=CORNER_RADIUS_SM,
        )
        find_entry.pack(padx=24, pady=(4, 12))

        # Replace field
        ctk.CTkLabel(
            frame,
            text="Replace with",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
            anchor="w",
        ).pack(padx=24, anchor="w")

        replace_entry = ctk.CTkEntry(
            frame,
            placeholder_text="Replacement text...",
            font=get_font(FONT_SIZE),
            fg_color=colors["input_bg"],
            border_color=colors["input_border"],
            text_color=colors["text"],
            placeholder_text_color=colors["text_muted"],
            width=292,
            height=36,
            corner_radius=CORNER_RADIUS_SM,
        )
        replace_entry.pack(padx=24, pady=(4, 16))

        # Result label
        result_var = ctk.StringVar(value="")
        result_label = ctk.CTkLabel(
            frame,
            textvariable=result_var,
            font=get_font(FONT_SIZE_SM),
            text_color=colors["system_msg"],
        )
        result_label.pack(pady=(0, 8))

        # Buttons
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(padx=24)

        def _replace_all():
            search = find_entry.get()
            replace = replace_entry.get()
            if not search:
                result_var.set("Enter text to find.")
                return
            edits = [{"type": "replace", "search": search, "replace": replace}]
            try:
                result = apply_edits(self._current_doc_path, edits)
                # Re-read document to update chat context
                doc = read_document(self._current_doc_path)
                df = read_dataframe(self._current_doc_path)
                self._chat.set_document(self._current_doc_path, doc.text, doc.images, dataframe=df)
                # Show result in dialog and chat
                lines = result.split("\n")
                summary = lines[-1] if lines else result
                result_var.set(summary)
                self._chat_widget.add_system_message(f"Edit: {summary}")
            except (UnsupportedEditError, PermissionError) as e:
                result_var.set(f"Failed: {e}")
            except Exception as e:
                result_var.set(f"Error: {e}")

        ctk.CTkButton(
            btn_frame,
            text="Replace All",
            font=get_font(FONT_SIZE, "bold"),
            fg_color=colors["accent"],
            hover_color=colors["accent_hover"],
            text_color=colors["text_on_accent"],
            width=140,
            height=38,
            corner_radius=CORNER_RADIUS_SM,
            command=_replace_all,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            font=get_font(FONT_SIZE),
            fg_color="transparent",
            hover_color=colors["bg_glass"],
            text_color=colors["text_muted"],
            border_width=1,
            border_color=colors["border_subtle"],
            width=140,
            height=38,
            corner_radius=CORNER_RADIUS_SM,
            command=dialog.destroy,
        ).pack(side="left")

        # Focus the find field
        dialog.after(100, find_entry.focus_set)

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

    def _on_document_cleared(self):
        """Called when the user switches to an app with no detectable document."""
        self._current_doc_path = None
        self._root.after(0, self._clear_document_status)

    def _clear_document_status(self):
        """Reset the UI to show no document is loaded (called on main thread)."""
        self._chat.set_document("", "")
        self._chat_widget.set_document_status("No document detected", editable=False)
        self._toggle.set_doc_detected(False)

    def _on_browser_content(self, url: str, title: str, text: str):
        """Called from the BrowserServer asyncio thread when the extension sends a page."""
        # Cap text to the active model's char budget (same logic as local files)
        max_chars = self._max_chars_for_active_model()
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + "\n\n[Content truncated to fit model context window]"

        self._current_doc_path = url  # Use URL as the "path" for browser pages
        # Marshal to the Tk main thread before touching UI or chat state
        self._root.after(0, lambda: self._process_browser_page(url, title, text))

    def _process_browser_page(self, url: str, title: str, text: str):
        """Load browser page content into the chat (called on main thread)."""
        # Use a short display label: just the page title (truncated if needed)
        display = title[:60] + "…" if len(title) > 60 else title

        self._chat.set_document(url, text)
        self._chat_widget.set_document_status(display, editable=False)
        self._toggle.set_doc_detected(True)
        self._chat_widget.add_system_message(
            f"Browser page loaded: {display} ({len(text):,} chars)"
        )

    def _max_chars_for_active_model(self) -> int | None:
        """Char cap derived from the active model's input window, or None."""
        if not self._chat.is_configured():
            return None
        return get_max_input_chars(self._chat._provider, self._chat._model)

    def _process_document(self, path: str, filename: str):
        """Read and load document content (called on main thread)."""
        ext = Path(path).suffix.lower()
        editable = ext in SUPPORTED_EDIT_FORMATS
        self._chat_widget.set_document_status(filename, editable=editable)
        self._toggle.set_doc_detected(True)

        try:
            result = read_document(path, max_chars=self._max_chars_for_active_model())
            df = read_dataframe(path)
            self._chat.set_document(path, result.text, result.images, dataframe=df)
            img_note = f", {len(result.images)} image(s)" if result.images else ""
            df_note = f", {len(df):,} rows (code mode)" if df is not None else ""
            self._chat_widget.add_system_message(
                f"Loaded: {filename} ({len(result.text):,} chars{img_note}{df_note})"
            )
        except (UnsupportedFormatError, FileTooLargeError, FileNotFoundError) as e:
            self._chat_widget.add_system_message(str(e))
        except Exception as e:
            self._chat_widget.add_system_message(f"Error reading file: {e}")

    def _reload_active_document(self):
        """Re-read the currently loaded document with the active model's char cap.

        Called after the user switches model in settings so a switch from a
        small-window model (Claude 200K) to a large-window one (Gemini 1.5 Pro
        2M) actually grants the larger document context.
        """
        if not self._current_doc_path:
            return
        try:
            result = read_document(
                self._current_doc_path,
                max_chars=self._max_chars_for_active_model(),
            )
            df = read_dataframe(self._current_doc_path)
            self._chat.set_document(
                self._current_doc_path, result.text, result.images, dataframe=df
            )
        except Exception:
            pass  # Best-effort — model switch shouldn't fail because of a re-read

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

        # Show what the interpreter understood so the user can catch
        # misreads early. Consumed (one-shot) so it never re-renders.
        interp = self._chat.consume_last_interpretation()
        if interp is not None:
            self._chat_widget.add_system_message(interp.ui_summary())

        # Check for edit instructions (still parsed here — edits are user-confirmed)
        edits = DocumentChat.parse_edit_instructions(response)

        # Show the text response (strip any leftover JSON block for cleaner display)
        import re
        display_text = re.sub(
            r"```json\s*\n?\{.*?\}\s*\n?```", "", response, flags=re.DOTALL
        ).strip()
        if display_text:
            self._chat_widget.add_bot_message(display_text)

        # Render math sidebar from the envelope produced inside chat.ask().
        # The math has already been executed and fed back to the LLM, so the
        # bot prose above already reflects this exact result.
        math_envelope = self._chat.consume_last_math_result()
        if math_envelope is not None:
            if "error" in math_envelope:
                self._chat_widget.add_system_message(
                    f"Calculation error: {math_envelope['error']}"
                )
            else:
                unit = math_envelope.get("unit", "")
                result_val = math_envelope.get("result", "")
                formula = math_envelope.get("formula", "")
                display = f"Result: {result_val}{unit}\nFormula: {formula}"
                self._chat_widget.add_system_message(display)

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
            doc = read_document(self._current_doc_path)
            df = read_dataframe(self._current_doc_path)
            self._chat.set_document(self._current_doc_path, doc.text, doc.images, dataframe=df)
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
        dialog.geometry("340x580")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)

        # Center on screen
        dialog.update_idletasks()
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        x = (sw - 340) // 2
        y = (sh - 580) // 2
        dialog.geometry(f"340x580+{x}+{y}")

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

        # ── Validator section ──────────────────────────────────────
        ctk.CTkLabel(
            frame,
            text="Output Validator (optional)",
            font=get_font(FONT_SIZE_SM, "bold"),
            text_color=colors["accent"],
            anchor="w",
        ).pack(padx=24, pady=(12, 2), anchor="w")

        ctk.CTkLabel(
            frame,
            text="Validator Provider",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
            anchor="w",
        ).pack(padx=24, anchor="w")

        v_provider_names = {"(disabled)": ""} | {v["name"]: k for k, v in LLM_PROVIDERS.items()}
        current_v_provider = self._config.get("validator_provider", "")
        current_v_name = "(disabled)"
        if current_v_provider:
            current_v_name = LLM_PROVIDERS.get(current_v_provider, {}).get("name", "(disabled)")

        v_provider_var = ctk.StringVar(value=current_v_name)

        v_provider_menu = ctk.CTkOptionMenu(
            frame,
            values=list(v_provider_names.keys()),
            variable=v_provider_var,
            fg_color=colors["input_bg"],
            button_color=colors["accent"],
            button_hover_color=colors["accent_hover"],
            text_color=colors["text"],
            font=get_font(FONT_SIZE),
            width=292,
            height=36,
            corner_radius=CORNER_RADIUS_SM,
        )
        v_provider_menu.pack(padx=24, pady=(4, 8))

        ctk.CTkLabel(
            frame,
            text="Validator API Key",
            font=get_font(FONT_SIZE_SM),
            text_color=colors["text_muted"],
            anchor="w",
        ).pack(padx=24, anchor="w")

        v_api_key_entry = ctk.CTkEntry(
            frame,
            placeholder_text="Leave blank to use primary key",
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
        v_api_key_entry.pack(padx=24, pady=(4, 16))
        existing_v_key = self._config.get("validator_api_key", "")
        if existing_v_key:
            v_api_key_entry.insert(0, existing_v_key)

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

            # Save validator config
            v_name = v_provider_var.get()
            v_key = v_provider_names.get(v_name, "")
            v_api_key = v_api_key_entry.get().strip() or api_key  # fallback to primary key
            if v_key:
                self._config["validator_provider"] = v_key
                self._config["validator_api_key"] = v_api_key
                self._chat.configure_validator(v_key, v_api_key)
            else:
                self._config.pop("validator_provider", None)
                self._config.pop("validator_model", None)  # clean up legacy key
                self._config.pop("validator_api_key", None)
                self._chat.clear_validator()

            save_user_config(self._config)

            validator_info = f" + {LLM_PROVIDERS[v_key]['name']} validator" if v_key else ""
            self._chat.configure(provider_key, api_key, model)
            # Re-read the active document with the new model's char cap so a
            # switch to a larger-window model actually expands available context.
            self._reload_active_document()
            self._chat_widget.add_system_message(
                f"Configured: {name} / {model}{validator_info}"
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
