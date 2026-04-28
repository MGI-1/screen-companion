"""Windows document detection via pywin32 and Win32 API."""

import os
import re
from pathlib import Path
from typing import Optional

from screencompanion.config import WIN_COM_MAP, WIN_TITLE_APPS, SUPPORTED_READ_FORMATS
from screencompanion.detector.base import BaseDetector

# Apps that are code/text editors — when one of these is the foreground
# window we skip detection entirely. They open too many internal files
# (logs, configs, caches) that are never the user's intended document.
# The user should switch to the document app (Word, Excel, browser, etc.)
# for Screen Companion to pick it up.
_SKIP_WHEN_FOCUSED = {
    "CODE.EXE",           # VS Code
    "CODE - INSIDERS.EXE",
    "CURSOR.EXE",         # Cursor AI editor
    "WINDSURF.EXE",
    "SUBLIME_TEXT.EXE",   # Sublime Text
    "ATOM.EXE",
    "NOTEPAD++.EXE",
    "NOTEPAD.EXE",
    "WORDPAD.EXE",
    "FLEET.EXE",          # JetBrains Fleet
}

# Process names for apps where we should always try open-file-handle detection
_ALWAYS_TRY_OPEN_FILES = {
    # Adobe Acrobat / Reader
    "ACROBAT.EXE", "ACRORD32.EXE", "ACRORD64.EXE",
    # WPS Office
    "WPS.EXE", "WPSOFFICE.EXE", "ET.EXE", "WPP.EXE",
    # Foxit
    "FOXITREADER.EXE", "FOXITPDFREADER.EXE", "FOXITPDFEDITOR.EXE",
    # SumatraPDF
    "SUMATRAPDF.EXE",
}

# Per-app allowlist of extensions considered "real documents" when scanning
# open file handles. Apps like Acrobat keep many supplementary files open
# (licensing logs, caches, config) whose extensions are technically in
# SUPPORTED_READ_FORMATS — without this filter they shadow the actual PDF.
_APP_DOC_EXTENSIONS = {
    "ACROBAT.EXE": {".pdf"},
    "ACRORD32.EXE": {".pdf"},
    "ACRORD64.EXE": {".pdf"},
    "FOXITREADER.EXE": {".pdf"},
    "FOXITPDFREADER.EXE": {".pdf"},
    "FOXITPDFEDITOR.EXE": {".pdf"},
    "SUMATRAPDF.EXE": {".pdf"},
    "WPS.EXE": {".pdf", ".doc", ".docx", ".rtf", ".odt"},
    "WPSOFFICE.EXE": {".pdf", ".doc", ".docx", ".rtf", ".odt"},
    "ET.EXE": {".xls", ".xlsx", ".csv", ".ods"},
    "WPP.EXE": {".ppt", ".pptx", ".odp"},
}

# Path fragments that indicate an internal/system file rather than a user
# document. Matched case-insensitively against the full path.
_OPEN_FILE_PATH_BLOCKLIST = (
    "\\appdata\\local\\adobe",
    "\\appdata\\roaming\\adobe",
    "\\appdata\\local\\packages",
    "\\appdata\\local\\temp",
    "\\appdata\\local\\microsoft",
    "\\program files\\",
    "\\program files (x86)\\",
    "\\windows\\",
)

# Exact filenames (case-insensitive) that are tool/IDE internals and should
# never be treated as user documents regardless of where they live on disk.
_BLOCKED_FILENAMES = {
    "typescript.log",       # VS Code TypeScript language server log
    "tsserver.log",         # VS Code TS server alternate log
    "eslint.log",
    "pylsp.log",
    "pyright.log",
    "lsp.log",
    "extension-host.log",
    "exthost.log",
    "renderer.log",
    "main.log",
    "sharedprocess.log",
    "watcherService.log",
    "npm-debug.log",
    "yarn-error.log",
    "yarn-debug.log",
    "pnpm-debug.log",
}

# Known app name suffixes to strip from window titles
_APP_SUFFIXES = [
    "- Adobe Acrobat Reader", "- Adobe Acrobat Pro", "- Adobe Acrobat",
    "- Acrobat Reader", "- Acrobat Pro", "- Acrobat",
    "- WPS Office", "- WPS Writer", "- WPS Spreadsheets", "- WPS Presentation",
    "- WPS PDF", "- Kingsoft Writer", "- Kingsoft Spreadsheets",
    "- Foxit Reader", "- Foxit PDF Reader", "- Foxit PDF Editor",
    "- SumatraPDF",
    "- Microsoft Word", "- Microsoft Excel", "- Microsoft PowerPoint",
    "- Notepad", "- Notepad++", "- WordPad",
]


class WindowsDetector(BaseDetector):
    """Detect the focused document on Windows using Win32 APIs."""

    def __init__(self):
        self._own_pid: int = os.getpid()

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
        """Get the file path of a document.

        Order of preference:
          1. The foreground window — strongest signal of user intent.
          2. Any other visible document window.
        """
        fg = self.get_frontmost_app()
        if fg:
            title, proc_name = fg
            path = self._extract_path_for(title, proc_name)
            if path:
                return path

        # Fallback: scan all visible windows (e.g. document is in a partially
        # obscured window, or the frontmost is a utility without a document)
        candidates = self._get_all_document_windows()
        fg_proc = fg[1].upper() if fg else None

        for title, proc_name in candidates:
            if proc_name.upper() == fg_proc:
                continue  # already tried
            path = self._extract_path_for(title, proc_name)
            if path:
                return path

        return None

    def _extract_path_for(self, title: str, proc_name: str) -> Optional[str]:
        """Try every detection strategy for a single window/process."""
        proc_upper = proc_name.upper()

        # Skip code editors when they are the focused window — they keep
        # too many internal files open that are not user documents.
        if proc_upper in _SKIP_WHEN_FOCUSED:
            return None

        path = self._try_com_automation(proc_name)
        if path:
            return path

        path = self._try_window_title(title, proc_upper)
        if path:
            return path

        if proc_upper in _ALWAYS_TRY_OPEN_FILES or proc_upper in WIN_TITLE_APPS:
            path = self._try_open_files(proc_name)
            if path:
                return path

        return None

    def _get_all_document_windows(self) -> list[tuple[str, str]]:
        """Return (title, proc_name) for all visible windows that might have documents."""
        results = []
        try:
            import win32gui
            import win32process
            import psutil

            def callback(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if not title or len(title) < 3:
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                # Skip our own process
                if pid == self._own_pid:
                    return
                try:
                    proc = psutil.Process(pid)
                    proc_name = proc.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return
                results.append((title, proc_name))

            win32gui.EnumWindows(callback, None)
        except Exception:
            pass

        # Sort: prioritize known document apps over others
        def sort_key(item):
            _, pname = item
            pu = pname.upper()
            if pu in WIN_COM_MAP or pu in _ALWAYS_TRY_OPEN_FILES:
                return 0  # Document apps first
            if pu in WIN_TITLE_APPS:
                return 1
            return 2

        results.sort(key=sort_key)
        return results

    def _try_com_automation(self, proc_name: str) -> Optional[str]:
        """Try getting document path via COM automation for Office apps."""
        proc_upper = proc_name.upper()
        com_info = WIN_COM_MAP.get(proc_upper)
        if not com_info:
            return None

        com_class, path_attr = com_info

        # Skip Acrobat COM — it's unreliable; we use open-file-handles instead
        if com_class == "AcroExch.App":
            return None

        try:
            import win32com.client

            app = win32com.client.GetObject(Class=com_class)
            obj = app
            for attr in path_attr.split("."):
                obj = getattr(obj, attr)
            path = str(obj)

            if os.path.isfile(path):
                return path
        except Exception:
            pass

        return None

    @staticmethod
    def _is_blocked_filename(path: str) -> bool:
        """Return True if the filename is a known IDE/tool internal log."""
        from pathlib import Path as _Path
        return _Path(path).name.lower() in _BLOCKED_FILENAMES

    def _try_window_title(self, title: str, proc_upper: str = "") -> Optional[str]:
        """Try extracting a file path from the window title."""
        if not title:
            return None

        # Check if the title contains a full file path
        path_match = re.search(r'([A-Za-z]:\\[^<>"|?*\n]+\.\w{2,5})', title)
        if path_match:
            candidate = path_match.group(1).strip()
            if os.path.isfile(candidate):
                return candidate

        # Strip known app name suffixes first for cleaner filename extraction
        cleaned_title = title
        for suffix in _APP_SUFFIXES:
            if cleaned_title.lower().endswith(suffix.lower()):
                cleaned_title = cleaned_title[: -len(suffix)].strip()
                break

        # Try common separators — apps often show "filename - AppName"
        for sep in [" - ", " — ", " – ", " | "]:
            if sep in cleaned_title:
                candidate = cleaned_title.split(sep)[0].strip().lstrip("* ")
                path = self._search_for_file(candidate)
                if path:
                    return path
                candidate = cleaned_title.rsplit(sep, 1)[-1].strip().lstrip("* ")
                path = self._search_for_file(candidate)
                if path:
                    return path

        # Try the cleaned title as a whole filename
        path = self._search_for_file(cleaned_title.strip().lstrip("* "))
        if path:
            return path

        return None

    def _search_for_file(self, filename: str) -> Optional[str]:
        """Search common directories for a matching filename."""
        if not filename or len(filename) < 2:
            return None

        if filename.lower() in _BLOCKED_FILENAMES:
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

        # Try exact name first
        for d in search_dirs:
            candidate = d / filename
            if candidate.is_file():
                return str(candidate)

        # If no extension, try appending common document extensions
        if not ext:
            common_exts = [".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv",
                           ".doc", ".xls", ".ppt"]
            for d in search_dirs:
                for try_ext in common_exts:
                    candidate = d / (filename + try_ext)
                    if candidate.is_file():
                        return str(candidate)

        # Try recursive search in common dirs (one level deep)
        for d in search_dirs:
            if not d.is_dir():
                continue
            try:
                for sub in d.iterdir():
                    if sub.is_dir():
                        if ext:
                            candidate = sub / filename
                            if candidate.is_file():
                                return str(candidate)
                        else:
                            for try_ext in [".pdf", ".docx", ".xlsx", ".pptx",
                                            ".txt", ".csv"]:
                                candidate = sub / (filename + try_ext)
                                if candidate.is_file():
                                    return str(candidate)
            except PermissionError:
                continue

        return None

    def _try_open_files(self, proc_name: str) -> Optional[str]:
        """Try finding a document by checking the process's open file handles."""
        proc_upper = proc_name.upper()
        allowed_exts = _APP_DOC_EXTENSIONS.get(proc_upper)

        try:
            import psutil
        except ImportError:
            return None

        candidates: list[str] = []
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                if not proc.info["name"] or proc.info["name"].upper() != proc_upper:
                    continue
                try:
                    for f in proc.open_files():
                        path = f.path
                        ext = Path(path).suffix.lower()
                        if allowed_exts is not None:
                            if ext not in allowed_exts:
                                continue
                        elif ext not in SUPPORTED_READ_FORMATS:
                            continue
                        lowered = path.lower()
                        if any(frag in lowered for frag in _OPEN_FILE_PATH_BLOCKLIST):
                            continue
                        if self._is_blocked_filename(path):
                            continue
                        candidates.append(path)
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
        except Exception:
            return None

        if not candidates:
            return None

        # Prefer files under typical user document locations
        home = str(Path.home()).lower()
        preferred_roots = [
            os.path.join(home, "documents").lower(),
            os.path.join(home, "desktop").lower(),
            os.path.join(home, "downloads").lower(),
        ]

        def rank(path: str) -> int:
            p = path.lower()
            for i, root in enumerate(preferred_roots):
                if p.startswith(root):
                    return i
            if p.startswith(home):
                return len(preferred_roots)
            return len(preferred_roots) + 1

        candidates.sort(key=rank)
        return candidates[0]
