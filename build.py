"""Build Document Wizard as a standalone desktop application.

Usage:
    python3 build.py

Output:
    macOS:   dist/Document Wizard.app
    Windows: dist/DocumentWizard.exe
"""

import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.abspath(__file__))


def ensure_pyinstaller():
    """Install PyInstaller if not available."""
    try:
        import PyInstaller
        print(f"PyInstaller {PyInstaller.__version__} found.")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
        )
        print("PyInstaller installed.")


def ensure_icon():
    """Generate the app icon if it doesn't exist."""
    icon_png = os.path.join(ROOT, "assets", "icon.png")
    if not os.path.exists(icon_png):
        print("Generating app icon...")
        subprocess.check_call([sys.executable, os.path.join(ROOT, "generate_icon.py")])
    else:
        print(f"Icon exists: {icon_png}")
    return icon_png


def get_customtkinter_path():
    """Find the customtkinter package path for data inclusion."""
    import customtkinter
    return os.path.dirname(customtkinter.__file__)


def build():
    ensure_pyinstaller()
    icon_png = ensure_icon()

    ctk_path = get_customtkinter_path()
    icon_dir = os.path.join(ROOT, "assets")

    # Base PyInstaller args
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", "Document Wizard" if sys.platform == "darwin" else "DocumentWizard",
        # Include customtkinter theme data
        "--add-data", f"{ctk_path}{os.pathsep}customtkinter",
        # Hidden imports that PyInstaller misses
        "--hidden-import", "customtkinter",
        "--hidden-import", "pystray",
        "--hidden-import", "PIL",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "pdfplumber",
        "--hidden-import", "pdfminer",
        "--hidden-import", "pdfminer.high_level",
        "--hidden-import", "docx",
        "--hidden-import", "openpyxl",
        "--hidden-import", "pptx",
        "--hidden-import", "anthropic",
        "--hidden-import", "openai",
        "--hidden-import", "google.generativeai",
        "--hidden-import", "google.ai.generativelanguage",
        "--hidden-import", "tkinter",
        "--hidden-import", "tkinter.filedialog",
        # Collect all submodules for packages that need it
        "--collect-all", "customtkinter",
        "--collect-all", "pystray",
        # Don't show console window
        "--windowed",
    ]

    # Platform-specific options
    if sys.platform == "darwin":
        icns_path = os.path.join(icon_dir, "icon.icns")
        if os.path.exists(icns_path):
            args.extend(["--icon", icns_path])

        # macOS: create .app bundle
        args.extend([
            "--osx-bundle-identifier", "com.documentwizard.app",
        ])
    elif sys.platform == "win32":
        ico_path = os.path.join(icon_dir, "icon.ico")
        if os.path.exists(ico_path):
            args.extend(["--icon", ico_path])
        args.extend([
            "--hidden-import", "win32gui",
            "--hidden-import", "win32process",
            "--hidden-import", "win32com",
            "--hidden-import", "win32com.client",
            "--hidden-import", "psutil",
        ])

    # Entry point
    args.append(os.path.join(ROOT, "docwizard", "__main__.py"))

    print("\nBuilding Document Wizard...")
    print(f"Command: {' '.join(args)}\n")
    subprocess.check_call(args, cwd=ROOT)

    # Post-build: patch Info.plist on macOS
    if sys.platform == "darwin":
        _patch_info_plist()

    print("\n" + "=" * 50)
    if sys.platform == "darwin":
        app_path = os.path.join(ROOT, "dist", "Document Wizard.app")
        print(f"BUILD COMPLETE!")
        print(f"App: {app_path}")
        print(f"\nTo run: open \"{app_path}\"")
        print(f"To install: drag to /Applications")
    else:
        exe_path = os.path.join(ROOT, "dist", "DocumentWizard.exe")
        print(f"BUILD COMPLETE!")
        print(f"Executable: {exe_path}")
        print(f"\nDouble-click to run.")
    print("=" * 50)


def _patch_info_plist():
    """Add LSUIElement and accessibility description to Info.plist."""
    import plistlib

    plist_path = os.path.join(
        ROOT, "dist", "Document Wizard.app", "Contents", "Info.plist"
    )

    if not os.path.exists(plist_path):
        print(f"Warning: Info.plist not found at {plist_path}")
        return

    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    # No dock icon — it's a floating widget
    plist["LSUIElement"] = True

    # Accessibility description (for AppleScript document detection)
    plist["NSAppleEventsUsageDescription"] = (
        "Document Wizard needs accessibility access to detect "
        "which document you have open."
    )

    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)

    print("Patched Info.plist (LSUIElement + accessibility)")


if __name__ == "__main__":
    build()
