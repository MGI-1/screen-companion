"""Windows document detection via pywin32 and Win32 API."""

import os
import re
from pathlib import Path
from typing import Optional

from screencompanion.config import WIN_COM_MAP, WIN_TITLE_APPS, WIN_BROWSER_PROCS, SUPPORTED_READ_FORMATS
from screencompanion.detector.base import BaseDetector
from screencompanion.logging_setup import get_logger

_log = get_logger("detector")

# Office apps expose an instance-global "active" document (ActiveWorkbook /
# ActiveDocument / ActivePresentation) that does NOT reliably follow the
# window the user is actually looking at when several files are open. For
# these we instead scan every open document and pick the one whose file name
# matches the foreground window caption. Maps the COM class to:
#   (collection attr, per-item name attr, per-item full-path attr)
_OFFICE_COLLECTION_MAP = {
    "Excel.Application": ("Workbooks", "Name", "FullName"),
    "Word.Application": ("Documents", "Name", "FullName"),
    "PowerPoint.Application": ("Presentations", "Name", "FullName"),
}

# Text editors / IDEs keep many internal files open (logs, caches, configs,
# the git index, extension state) whose extensions fall inside
# SUPPORTED_READ_FORMATS. Open-file-handle scanning cannot tell which handle
# belongs to the focused tab, so for these it surfaces IDE internals — e.g.
# VS Code's network-shared.log — and clobbers the real document. For editors
# the window title is authoritative, so we rely on title parsing ONLY and
# never scan their open handles.
_EDITORS_NO_OPEN_FILE_SCAN = {
    "CODE.EXE", "CODE - INSIDERS.EXE",          # VS Code
    "NOTEPAD.EXE", "NOTEPAD++.EXE", "WORDPAD.EXE",
    "SUBLIME_TEXT.EXE", "ATOM.EXE",
    "PYCHARM64.EXE", "IDEA64.EXE", "WEBSTORM64.EXE",  # JetBrains
    "GOLAND64.EXE", "CLION64.EXE", "RIDER64.EXE",
}

# Extensions that are almost never "the document the user is viewing" when
# found via open-file-handle scanning — every app keeps logs open. Excluded
# from the generic (no per-app allowlist) scan branch below.
_LOG_LIKE_EXTENSIONS = {".log", ".out", ".err", ".trace"}

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
    # Microsoft Office — used only as a fallback when COM detection fails.
    "EXCEL.EXE": {".xlsx", ".xls", ".csv", ".ods"},
    "WINWORD.EXE": {".docx", ".doc", ".rtf", ".odt"},
    "POWERPNT.EXE": {".pptx", ".ppt", ".odp"},
}

# Path fragments that indicate an internal/system file rather than a user
# document. Matched case-insensitively against the full path.
_OPEN_FILE_PATH_BLOCKLIST = (
    "\\appdata\\local\\adobe",
    "\\appdata\\roaming\\adobe",
    "\\appdata\\local\\packages",
    "\\appdata\\local\\temp",
    "\\appdata\\local\\microsoft",
    # AppData\Roaming is application state, never user documents. This blocks
    # IDE/tool internals such as VS Code logs (…\Roaming\Code\logs\…) and
    # JetBrains caches that would otherwise shadow the real document.
    "\\appdata\\roaming\\",
    "\\program files\\",
    "\\program files (x86)\\",
    "\\windows\\",
)

# Exact filenames (case-insensitive) that are tool/IDE internals and should
# never be treated as user documents regardless of where they live on disk.
_BLOCKED_FILENAMES = {
    # VS Code internal logs
    "typescript.log",
    "tsserver.log",
    "exthosttelemetry.log",
    "exthost.log",
    "extension-host.log",
    "renderer.log",
    "main.log",
    "sharedprocess.log",
    "watcherservice.log",
    "network.log",
    "window1.log",
    "window2.log",
    "window3.log",
    "notebook.rendering.log",
    "ptyhost.log",
    "remoteagent.log",
    "filewatcher.log",
    # Language server logs
    "eslint.log",
    "pylsp.log",
    "pyright.log",
    "lsp.log",
    "pylance.log",
    # Package manager logs
    "npm-debug.log",
    "yarn-error.log",
    "yarn-debug.log",
    "pnpm-debug.log",
    # Generic tool logs
    "error.log",
    "debug.log",
    "output.log",
    "install.log",
    # Microsoft / Windows logs
    "microsoft authentication.log",
    "aadplugin.log",
    "msal.log",
    "wam.log",
    "container tools.log",
    "windowspackagemanager.log",
    "windowsterminal.log",
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

    def is_self_foreground(self) -> bool:
        """True when the foreground window belongs to our own process."""
        try:
            import win32gui
            import win32process

            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return False
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid == self._own_pid
        except Exception:
            return False

    def get_document_path(self) -> Optional[str]:
        """Get the file path of the document in the foreground window.

        Only the foreground window is checked — background windows are
        intentionally ignored. This ensures Screen Companion always shows
        what the user is currently looking at, not a document sitting
        behind another app.
        """
        fg = self.get_frontmost_app()
        if not fg:
            return None
        title, proc_name = fg
        return self._extract_path_for(title, proc_name)

    def get_any_document_path(self) -> Optional[str]:
        """Find a document in any open window, preferring the foreground one.

        Used by the manual detect button and panel-open, where our own window
        holds focus. Tries the foreground first (correct when a document app is
        actually focused), then falls back to scanning every visible window so
        the file behind the panel is still detected.
        """
        fg = self.get_document_path()
        if fg:
            return fg

        for title, proc_name in self._get_all_document_windows():
            path = self._extract_path_for(title, proc_name)
            if path:
                _log.debug("  -> any-window matched: %s (%s)", path, proc_name)
                return path
        _log.debug("  -> any-window scan found no document")
        return None

    def _extract_path_for(self, title: str, proc_name: str) -> Optional[str]:
        """Try every detection strategy for a single window/process."""
        proc_upper = proc_name.upper()
        _log.debug("detect: proc=%s title=%r", proc_name, title)

        # Browsers are handled by the WebSocket extension — skip file detection
        # so the FocusWatcher doesn't clear the document while the extension
        # is about to send the page content.
        if proc_upper in WIN_BROWSER_PROCS:
            _log.debug("  -> browser process, deferring to extension")
            return None

        path = self._try_com_automation(proc_name, title)
        if path:
            _log.debug("  -> COM matched: %s", path)
            return path

        path = self._try_window_title(title, proc_upper)
        if path:
            _log.debug("  -> title search matched: %s", path)
            return path

        # Office apps also fall back to open-file-handle scanning: COM can be
        # unavailable (unlicensed Excel, cross-elevation) and the file may live
        # outside the searched folders (e.g. opened from another app). Editors
        # are excluded — their open handles are all IDE internals, so a match
        # there is noise that overwrites the real document (see the set above).
        if (proc_upper not in _EDITORS_NO_OPEN_FILE_SCAN
                and (proc_upper in _ALWAYS_TRY_OPEN_FILES
                     or proc_upper in WIN_TITLE_APPS
                     or proc_upper in WIN_COM_MAP)):
            path = self._try_open_files(proc_name, title)
            if path:
                _log.debug("  -> open-files matched: %s", path)
                return path

        _log.debug("  -> no document detected for %s", proc_name)
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

    def _try_com_automation(self, proc_name: str, title: str = "") -> Optional[str]:
        """Try getting document path via COM automation for Office apps."""
        proc_upper = proc_name.upper()
        com_info = WIN_COM_MAP.get(proc_upper)
        if not com_info:
            return None

        com_class, path_attr = com_info

        # Skip Acrobat COM — it's unreliable; we use open-file-handles instead
        if com_class == "AcroExch.App":
            return None

        # For Office apps, resolve the document that matches the foreground
        # window instead of trusting the instance-global ActiveWorkbook /
        # ActiveDocument, which lags behind when several files are open and
        # was causing the wrong workbook to be loaded.
        if com_class in _OFFICE_COLLECTION_MAP:
            path = self._office_path_for_foreground(com_class, title)
            if path:
                return path
            # Fall through to the active-object below as a last resort.
            _log.debug("  COM: no foreground match for %s, trying active object", com_class)

        try:
            import win32com.client

            app = win32com.client.GetObject(Class=com_class)
            obj = app
            for attr in path_attr.split("."):
                obj = getattr(obj, attr)
            path = str(obj)

            if os.path.isfile(path):
                # Only trust the instance-global active object if its file name
                # appears in the foreground title. Otherwise it may be a
                # workbook in a background window — not what the user is looking
                # at — so we decline rather than load the wrong document.
                if not title or Path(path).stem.lower() in title.lower():
                    return path
                _log.debug(
                    "  COM active object %r doesn't match foreground title %r",
                    path, title,
                )
            else:
                _log.debug("  COM active object path not a file: %r", path)
        except Exception as e:
            _log.debug("  COM GetObject(%s) failed: %s", com_class, e)

        return None

    def _office_path_for_foreground(self, com_class: str, title: str) -> Optional[str]:
        """Return the open Office document whose name matches the foreground title.

        Scans every open document across every running instance of the app and
        picks the one whose file name (without extension) appears in the
        foreground window caption. When several match — e.g. "plan" and
        "plan-15jul2026" are both open — the longest name wins, since the
        caption always contains the full name of the active file.
        """
        if not title:
            return None

        coll_attr, name_attr, fullname_attr = _OFFICE_COLLECTION_MAP[com_class]
        title_l = title.lower()

        def _best_match(app) -> Optional[str]:
            best_path, best_len = None, -1
            try:
                collection = getattr(app, coll_attr)
            except Exception:
                return None
            try:
                for item in collection:
                    try:
                        name = str(getattr(item, name_attr))
                        full = str(getattr(item, fullname_attr))
                    except Exception:
                        continue
                    stem = Path(name).stem.strip().lower()
                    if not stem or stem not in title_l:
                        continue
                    if len(stem) > best_len and os.path.isfile(full):
                        best_path, best_len = full, len(stem)
            except Exception:
                return best_path
            return best_path

        for app in self._iter_office_apps(com_class):
            hit = _best_match(app)
            if hit:
                return hit
        return None

    def _iter_office_apps(self, com_class: str):
        """Yield every running instance of the given Office application.

        The primary instance (via GetObject) is yielded first so the common
        case — all files open in one Office process — never touches the
        Running Object Table. Additional instances (files opened in separate
        processes) are found by enumerating the ROT, but only if the caller
        keeps iterating because the primary instance had no match.
        """
        try:
            import win32com.client
            import pythoncom
        except ImportError:
            return

        coll_attr = _OFFICE_COLLECTION_MAP[com_class][0]
        seen: set = set()

        def _key(app) -> int:
            try:
                return int(getattr(app, "Hwnd", 0))
            except Exception:
                return 0

        # Fast path: the primary registered instance.
        try:
            app = win32com.client.GetObject(Class=com_class)
            seen.add(_key(app))
            yield app
        except Exception:
            pass

        # Slow path: other instances registered in the ROT.
        try:
            rot = pythoncom.GetRunningObjectTable()
            for moniker in rot:
                try:
                    disp = win32com.client.Dispatch(rot.GetObject(moniker))
                    app = getattr(disp, "Application", None)
                    if app is None:
                        continue
                    key = _key(app)
                    if key in seen:
                        continue
                    getattr(app, coll_attr)  # verify it's the right app type
                    seen.add(key)
                    yield app
                except Exception:
                    continue
        except Exception:
            pass

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

    def _try_open_files(self, proc_name: str, title: str = "") -> Optional[str]:
        """Try finding a document by checking the process's open file handles."""
        proc_upper = proc_name.upper()
        allowed_exts = _APP_DOC_EXTENSIONS.get(proc_upper)

        # For Office apps, files shared via other apps (WhatsApp, Teams, Slack)
        # are opened straight from those apps' package folders, so don't block
        # AppData\Local\Packages here — but keep temp/cache paths blocked.
        blocklist = _OPEN_FILE_PATH_BLOCKLIST
        if proc_upper in WIN_COM_MAP:
            blocklist = tuple(
                f for f in _OPEN_FILE_PATH_BLOCKLIST
                if f != "\\appdata\\local\\packages"
            )

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
                        elif ext not in SUPPORTED_READ_FORMATS or ext in _LOG_LIKE_EXTENSIONS:
                            # No per-app allowlist: accept real document types
                            # but never log files — every app holds logs open,
                            # so a handle match on one is never the user's doc.
                            continue
                        lowered = path.lower()
                        if any(frag in lowered for frag in blocklist):
                            continue
                        if self._is_blocked_filename(path):
                            continue
                        # Skip Excel/Office lock files (~$name.xlsx).
                        if Path(path).name.startswith("~$"):
                            continue
                        candidates.append(path)
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
        except Exception:
            return None

        if not candidates:
            _log.debug("  open-files: no candidates for %s", proc_name)
            return None

        _log.debug("  open-files candidates: %s", candidates)

        # Detect ONLY the document in the focused window. A process may hold
        # many files open (background tabs, other windows of the same app,
        # internal files); the foreground window title is what the user is
        # actually looking at. Keep only candidates whose file name appears in
        # that title — if none do, we cannot confirm which file is on screen,
        # so we detect nothing rather than guess a background/unrelated file.
        title_l = title.lower()
        if not title_l:
            _log.debug("  open-files: no foreground title to match against")
            return None
        titled = [c for c in candidates if Path(c).stem.lower() in title_l]
        if not titled:
            _log.debug("  open-files: no open file matches foreground title %r", title)
            return None

        # Among files that match the title, prefer typical user document
        # locations (handles the rare case of two same-named open files).
        home = str(Path.home()).lower()
        preferred_roots = [
            os.path.join(home, "documents").lower(),
            os.path.join(home, "desktop").lower(),
            os.path.join(home, "downloads").lower(),
        ]

        def rank(path: str) -> tuple:
            p = path.lower()
            for i, root in enumerate(preferred_roots):
                if p.startswith(root):
                    return (i,)
            if p.startswith(home):
                return (len(preferred_roots),)
            return (len(preferred_roots) + 1,)

        titled.sort(key=rank)
        return titled[0]
