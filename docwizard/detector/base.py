"""Abstract base detector and cross-platform FocusWatcher."""

import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Optional

from docwizard.config import POLL_INTERVAL_SECONDS


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
        interval: float = POLL_INTERVAL_SECONDS,
    ):
        self._detector = detector
        self._on_change = on_change
        self._interval = interval
        self._current_path: Optional[str] = None
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
        """Immediately check for the current document (blocking)."""
        path = self._detector.get_document_path()
        if path and path != self._current_path:
            self._current_path = path
            self._on_change(path)
        return self._current_path

    def _poll_loop(self):
        while self._running:
            try:
                path = self._detector.get_document_path()
                if path and path != self._current_path:
                    self._current_path = path
                    self._on_change(path)
            except Exception:
                pass  # Silently continue polling
            time.sleep(self._interval)
