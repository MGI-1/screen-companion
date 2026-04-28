"""Abstract base detector and cross-platform FocusWatcher."""

import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Optional

from screencompanion.config import POLL_INTERVAL_SECONDS


class BaseDetector(ABC):
    """Abstract base for platform-specific document detectors."""

    @abstractmethod
    def get_document_path(self) -> Optional[str]:
        """Return the POSIX/absolute path of the focused document, or None."""
        ...

    @abstractmethod
    def get_frontmost_app(self) -> Optional[tuple[str, str]]:
        """Return (app_name, bundle_id/process_name) of frontmost app, or None."""
        ...


class FocusWatcher:
    """Polls for document focus changes in a background thread."""

    def __init__(
        self,
        detector: BaseDetector,
        on_change: Callable[[str], None],
        on_clear: Optional[Callable[[], None]] = None,
        interval: float = POLL_INTERVAL_SECONDS,
    ):
        self._detector = detector
        self._on_change = on_change
        self._on_clear = on_clear          # called when app changes but has no document
        self._interval = interval
        self._current_path: Optional[str] = None
        self._current_proc: Optional[str] = None   # tracks foreground process name
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def current_path(self) -> Optional[str]:
        return self._current_path

    def start(self):
        """Start the polling thread."""
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the polling thread."""
        self._running = False

    def check_now(self) -> Optional[str]:
        """Immediately check for the current document (blocking).

        Unlike the poll loop, always fires on_change when a path is found,
        even if it matches the last seen path — the user clicked detect
        because they want to confirm/refresh what's loaded.
        """
        path = self._detector.get_document_path()
        if path:
            self._current_path = path
            self._on_change(path)
        return self._current_path

    def _poll_loop(self):
        while self._running:
            try:
                # Track which process is in the foreground so we know when
                # the user switches apps.
                app_info = self._detector.get_frontmost_app()
                new_proc = app_info[1] if app_info else None
                proc_changed = new_proc != self._current_proc

                path = self._detector.get_document_path()

                if path and path != self._current_path:
                    # New document detected — load it.
                    self._current_path = path
                    self._current_proc = new_proc
                    self._on_change(path)
                elif proc_changed and not path:
                    # User switched to an app that has no detectable document
                    # (e.g. VS Code with no file open, desktop, taskbar).
                    # Clear so Screen Companion reflects the current screen.
                    self._current_path = None
                    self._current_proc = new_proc
                    if self._on_clear:
                        self._on_clear()
                elif proc_changed:
                    # Process changed but path will be handled above next tick.
                    self._current_proc = new_proc

            except Exception:
                pass  # Silently continue polling
            time.sleep(self._interval)
