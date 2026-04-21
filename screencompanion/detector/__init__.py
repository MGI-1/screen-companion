"""Platform-specific document detector dispatcher."""

import sys

if sys.platform == "darwin":
    from screencompanion.detector.macos import MacOSDetector as Detector
elif sys.platform == "win32":
    from screencompanion.detector.windows import WindowsDetector as Detector
else:
    raise RuntimeError(
        f"Screen Companion currently supports macOS and Windows, not {sys.platform}"
    )

__all__ = ["Detector"]
