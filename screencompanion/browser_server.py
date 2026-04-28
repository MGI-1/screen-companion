"""WebSocket server that receives webpage content from the browser extension.

The extension (extension/background.js) connects to ws://localhost:9147 and
sends JSON payloads whenever the active tab changes:

    { "url": "https://...", "title": "Page title", "text": "page text..." }

This module starts the server in a background thread so it doesn't block
the Tkinter main loop. The caller supplies an on_content callback that is
invoked (from the asyncio thread) when a new payload arrives — the caller
must marshal UI updates to the main thread itself (e.g. via root.after()).
"""

import asyncio
import json
import threading
from typing import Callable, Optional

PORT = 9147
_WEBSOCKETS_MISSING_MSG = (
    "Browser detection unavailable: 'websockets' package not installed. "
    "Run:  pip install websockets"
)


def _import_websockets():
    try:
        import websockets  # noqa: F401
        return True
    except ImportError:
        return False


class BrowserServer:
    """Runs a WebSocket server on localhost:{PORT} for the browser extension."""

    def __init__(self, on_content: Callable[[str, str, str], None]):
        """
        Parameters
        ----------
        on_content : callable(url, title, text)
            Called every time the extension sends a new page.
            Runs on the asyncio event-loop thread — marshal to the
            Tk main thread with root.after(0, ...) before touching UI.
        """
        self._on_content = on_content
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._running = False
        self._available = _import_websockets()

    @property
    def available(self) -> bool:
        """True if the websockets package is installed."""
        return self._available

    @property
    def port(self) -> int:
        return PORT

    @property
    def missing_msg(self) -> str:
        return _WEBSOCKETS_MISSING_MSG

    def start(self):
        """Start the WebSocket server in a daemon thread."""
        if not self._available or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="BrowserServer")
        self._thread.start()

    def stop(self):
        """Gracefully stop the server."""
        self._running = False
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ── Internal ────────────────────────────────────────────────────────────

    def _run(self):
        """Entry point for the background thread — owns its own event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            pass
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    async def _serve(self):
        import websockets

        self._server = await websockets.serve(
            self._handler,
            "localhost",
            PORT,
            ping_interval=20,
            ping_timeout=20,
        )
        # Keep running until stop() is called
        while self._running:
            await asyncio.sleep(0.5)

        self._server.close()
        await self._server.wait_closed()

    async def _handler(self, websocket):
        """Handle one browser extension connection."""
        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                url   = data.get("url",   "").strip()
                title = data.get("title", "").strip()
                text  = data.get("text",  "").strip()

                if url and text:
                    try:
                        self._on_content(url, title, text)
                    except Exception:
                        pass  # Never let a callback crash the server
        except Exception:
            pass  # Connection closed or protocol error — harmless
