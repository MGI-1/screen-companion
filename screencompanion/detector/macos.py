"""macOS document detection via AppleScript."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from screencompanion.config import APP_SCRIPT_MAP, WINDOW_TITLE_APPS, SUPPORTED_READ_FORMATS
from screencompanion.detector.base import BaseDetector


class MacOSDetector(BaseDetector):
    """Detect the focused document on macOS using AppleScript."""

    def get_frontmost_app(self) -> Optional[tuple[str, str]]:
        """Return (app_name, bundle_id) of the frontmost app."""
        script = (
            'tell application "System Events"\n'
            "  set frontApp to first process whose frontmost is true\n"
            "  return {name of frontApp, bundle identifier of frontApp}\n"
            "end tell"
        )
        result = self._run_osascript(script)
        if result:
            parts = result.split(", ", 1)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
        return None

    def get_document_path(self) -> Optional[str]:
        """Get the file path of the document in the frontmost app."""
        app_info = self.get_frontmost_app()
        if not app_info:
            return None

        app_name, bundle_id = app_info

        # Skip our own app
        if "docwizard" in app_name.lower() or "python" in app_name.lower():
            return None
        if "screen companion" in app_name.lower():
            return None

        # Strategy 1: App-specific AppleScript
        path = self._try_app_script(bundle_id)
        if path:
            return path

        # Strategy 2: Parse window title for filename
        path = self._try_window_title(app_name)
        if path:
            return path

        # Strategy 3: Use lsof to find open files for the app's process
        path = self._try_lsof(app_name)
        if path:
            return path

        return None

    def _try_app_script(self, bundle_id: str) -> Optional[str]:
        """Try getting document path via app-specific AppleScript."""
        script = APP_SCRIPT_MAP.get(bundle_id)
        if not script:
            return None

        result = self._run_osascript(script)
        if result:
            path = result.strip()
            # Convert HFS path if needed (contains ":")
            if ":" in path and not path.startswith("/"):
                path = self._hfs_to_posix(path)
            if os.path.isfile(path):
                return path
        return None

    def _try_window_title(self, app_name: str) -> Optional[str]:
        """Try extracting a file path from the window title."""
        script = (
            'tell application "System Events"\n'
            "  tell process \"" + app_name + "\"\n"
            "    return name of front window\n"
            "  end tell\n"
            "end tell"
        )
        title = self._run_osascript(script)
        if not title:
            return None

        title = title.strip()

        # If title looks like an absolute path
        if title.startswith("/") and os.path.isfile(title):
            return title

        # If title contains an absolute path somewhere (e.g. "main.py — /Users/x/project")
        for token in title.split():
            if token.startswith("/") and os.path.isfile(token):
                return token

        # Try common separators — apps often show "filename — AppName"
        # or "AppName — filename" or "filename - /path/to/dir"
        candidates = []
        for sep in [" — ", " - ", " – ", " | ", " : "]:
            if sep in title:
                parts = title.split(sep)
                for part in parts:
                    part = part.strip()
                    if part:
                        candidates.append(part)

        # If no separators found, try the whole title
        if not candidates:
            candidates.append(title)

        # VS Code pattern: "filename — folder — VS Code"
        # Sublime: "filename — folder"
        # Typora: "filename"
        for candidate in candidates:
            # Skip known app name suffixes
            lower = candidate.lower()
            if any(skip in lower for skip in [
                "visual studio code", "vs code", "sublime text",
                "safari", "chrome", "firefox", "brave", "edge", "opera",
                "untitled", "nova", "pycharm", "intellij", "webstorm",
            ]):
                continue

            # If it's an absolute path
            if candidate.startswith("/") and os.path.isfile(candidate):
                return candidate

            # Try as filename
            path = self._search_for_file(candidate)
            if path:
                return path

            # For "filename.ext" without path, also try adding extensions
            if "." not in candidate:
                for ext in [".txt", ".md", ".html", ".py", ".json", ".xml",
                            ".csv", ".pdf", ".docx", ".xlsx"]:
                    path = self._search_for_file(candidate + ext)
                    if path:
                        return path

        return None

    def _try_lsof(self, app_name: str) -> Optional[str]:
        """Use lsof to find open document files for a process."""
        try:
            # Get PID of the frontmost app
            pid_script = (
                'tell application "System Events"\n'
                f'  return unix id of (first process whose name is "{app_name}")\n'
                "end tell"
            )
            pid_result = self._run_osascript(pid_script)
            if not pid_result:
                return None

            pid = pid_result.strip()
            if not pid.isdigit():
                return None

            # Use lsof to list open files for this PID
            result = subprocess.run(
                ["lsof", "-p", pid, "-Fn"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None

            # Parse lsof output: lines starting with 'n' are file paths
            best_match = None
            for line in result.stdout.splitlines():
                if not line.startswith("n/"):
                    continue
                filepath = line[1:]  # strip 'n' prefix
                if not os.path.isfile(filepath):
                    continue
                ext = Path(filepath).suffix.lower()
                if ext in SUPPORTED_READ_FORMATS:
                    # Prefer files in user directories
                    home = str(Path.home())
                    if filepath.startswith(home):
                        return filepath
                    if best_match is None:
                        best_match = filepath

            return best_match

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
            return None

    def _search_for_file(self, filename: str) -> Optional[str]:
        """Search common directories for a matching filename."""
        if not filename:
            return None

        # Reject obviously non-file strings
        if len(filename) > 255 or "\n" in filename:
            return None

        # Check if extension is supported (if present)
        ext = Path(filename).suffix.lower()
        if ext and ext not in SUPPORTED_READ_FORMATS:
            return None

        # If no extension, still search — many titles drop the extension
        home = Path.home()
        search_dirs = [
            home / "Documents",
            home / "Desktop",
            home / "Downloads",
            home,
            home / "Projects",
            home / "Developer",
            home / "Code",
            home / "repos",
            home / "src",
            home / "work",
            Path("/tmp"),
        ]

        for d in search_dirs:
            candidate = d / filename
            if candidate.is_file():
                return str(candidate)

        # Try a shallow recursive search in Documents and Desktop
        for d in [home / "Documents", home / "Desktop", home / "Downloads"]:
            if not d.is_dir():
                continue
            try:
                for child in d.iterdir():
                    if child.is_dir():
                        candidate = child / filename
                        if candidate.is_file():
                            return str(candidate)
            except PermissionError:
                continue

        return None

    def _hfs_to_posix(self, hfs_path: str) -> str:
        """Convert HFS path (Macintosh HD:Users:...) to POSIX."""
        script = f'POSIX path of "{hfs_path}"'
        result = self._run_osascript(script)
        return result.strip() if result else hfs_path

    @staticmethod
    def _run_osascript(script: str) -> Optional[str]:
        """Run an AppleScript and return stdout, or None on error."""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        return None
