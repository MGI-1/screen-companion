"""Windows document detection via pywin32 and Win32 API."""

import os
from pathlib import Path
from typing import Optional

from screencompanion.config import WIN_COM_MAP, SUPPORTED_READ_FORMATS
from screencompanion.detector.base import BaseDetector


class WindowsDetector(BaseDetector):
    """Detect the focused document on Windows using Win32 APIs."""

    def get_frontmost_app(self) -> Optional[tuple[str, str]]:
        """Return (window_title, process_name) of the foreground window."""
        try:
            import win32gui
            import win32process
            import psutil

            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None

            title = win32gui.GetWindowText(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            try:
                proc = psutil.Process(pid)
                proc_name = proc.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                proc_name = "unknown"

            return title, proc_name
        except ImportError:
            return None
        except Exception:
            return None

    def get_document_path(self) -> Optional[str]:
        """Get the file path of the document in the foreground window."""
        app_info = self.get_frontmost_app()
        if not app_info:
            return None

        title, proc_name = app_info

        # Skip our own app
        if "docwizard" in title.lower() or proc_name.lower() == "python.exe":
            return None

        # Strategy 1: COM automation for Office apps
        path = self._try_com_automation(proc_name)
        if path:
            return path

        # Strategy 2: Parse window title
        path = self._try_window_title(title)
        if path:
            return path

        return None

    def _try_com_automation(self, proc_name: str) -> Optional[str]:
        """Try getting document path via COM automation for Office apps."""
        proc_upper = proc_name.upper()
        com_info = WIN_COM_MAP.get(proc_upper)
        if not com_info:
            return None

        com_class, path_attr = com_info

        try:
            import win32com.client

            app = win32com.client.GetObject(Class=com_class)
            # Navigate the attribute chain (e.g., "ActiveDocument.FullName")
            obj = app
            for attr in path_attr.split("."):
                obj = getattr(obj, attr)
            path = str(obj)

            if os.path.isfile(path):
                return path
        except Exception:
            pass

        return None

    def _try_window_title(self, title: str) -> Optional[str]:
        """Try extracting a file path from the window title."""
        if not title:
            return None

        # If title contains a full path
        for part in title.split():
            if (":\\" in part or part.startswith("\\\\")) and os.path.isfile(part):
                return part

        # Try common separators — apps often show "filename - AppName"
        for sep in [" - ", " — ", " – ", " | "]:
            if sep in title:
                candidate = title.split(sep)[0].strip()
                path = self._search_for_file(candidate)
                if path:
                    return path

        # Try the whole title
        path = self._search_for_file(title)
        if path:
            return path

        return None

    def _search_for_file(self, filename: str) -> Optional[str]:
        """Search common directories for a matching filename."""
        if not filename:
            return None

        ext = Path(filename).suffix.lower()
        if ext and ext not in SUPPORTED_READ_FORMATS:
            return None

        home = Path.home()
        search_dirs = [
            home / "Documents",
            home / "Desktop",
            home / "Downloads",
            home,
        ]

        for d in search_dirs:
            candidate = d / filename
            if candidate.is_file():
                return str(candidate)

        return None
