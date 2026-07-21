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

    def is_self_foreground(self) -> bool:
        """Return True when Screen Companion's own window is in the foreground.

        Used so that clicking into the chat panel to type isn't mistaken for
        switching away from the document (which would clear it). Overridden
        per platform; defaults to False.
        """
        return False

    def get_any_document_path(self) -> Optional[str]:
        """Return a document path from ANY open window, not just the foreground.

        The foreground-only ``get_document_path`` is right for the passive poll
        loop (it tracks what the user is actively looking at). But the manual
        "detect" button and opening the panel run while the user is interacting
        with OUR window — so the foreground is Screen Companion itself and a
        foreground-only scan always finds nothing. This scans every visible
        window so the document sitting behind the panel is still found.

        Overridden per platform; defaults to the foreground-only result.
        """
        return self.get_document_path()


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

        Scans every window (not just the foreground) because this runs while
        the user is interacting with our own panel: the document they want is
        sitting behind it, so a foreground-only check would always miss it.
        """
        path = self._detector.get_any_document_path()
        if path:
            self._current_path = path
            self._on_change(path)
        return self._current_path

    def _poll_loop(self):
        # COM automation (Office document detection on Windows) requires COM to
        # be initialized on the calling thread. This poll loop runs on its own
        # background thread, so without this every Excel/Word COM call fails
        # with "CoInitialize has not been called" and detection silently falls
        # back to less reliable strategies. No-op on non-Windows platforms.
        _com_ready = False
        try:
            import pythoncom
            pythoncom.CoInitialize()
            _com_ready = True
        except Exception:
            pass

        try:
            self._run_poll_loop()
        finally:
            if _com_ready:
                try:
                    import pythoncom
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _run_poll_loop(self):
        while self._running:
            try:
                # Interacting with our own chat window must not be treated as
                # switching away from the document — otherwise clicking the
                # input box clears the loaded document before the user can ask.
                if self._detector.is_self_foreground():
                    time.sleep(self._interval)
                    continue

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
                elif proc_changed:
                    # App switched — always update the tracked process.
                    self._current_proc = new_proc
                    if not path and self._current_path is not None:
                        # Had a document before; now there's nothing — clear once.
                        self._current_path = None
                        if self._on_clear:
                            self._on_clear()

            except Exception:
                pass  # Silently continue polling
            time.sleep(self._interval)
