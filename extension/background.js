/**
 * background.js — service worker for the Screen Companion Bridge extension.
 *
 * Responsibilities:
 *   1. Maintain a persistent WebSocket connection to Screen Companion (localhost:9147).
 *   2. Listen for tab-switch and page-load events.
 *   3. Ask the active tab's content_script for page text.
 *   4. Forward { url, title, text } to Screen Companion over the socket.
 *   5. Auto-reconnect if Screen Companion is restarted.
 *   6. Notify popup.js of connection state changes.
 */

const SC_WS_URL = "ws://localhost:9147";
const RECONNECT_DELAY_MS = 3000;

let ws = null;
let reconnectTimer = null;
let connectionState = "disconnected"; // "connected" | "disconnected" | "connecting"
let lastSentUrl = null;

// ── WebSocket lifecycle ──────────────────────────────────────────────────────

function connect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  if (ws && ws.readyState === WebSocket.OPEN) return; // Already connected

  setConnectionState("connecting");

  ws = new WebSocket(SC_WS_URL);

  ws.onopen = () => {
    setConnectionState("connected");
    console.log("[SC Bridge] Connected to Screen Companion on", SC_WS_URL);
    // Send current tab content immediately so Screen Companion has something
    // loaded as soon as the extension connects.
    lastSentUrl = null;
    sendActiveTabContent();
  };

  ws.onclose = () => {
    setConnectionState("disconnected");
    console.log("[SC Bridge] Disconnected. Retrying in", RECONNECT_DELAY_MS, "ms...");
    reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
  };

  ws.onerror = () => {
    // onclose fires right after onerror — reconnect logic lives there.
  };
}

function setConnectionState(state) {
  connectionState = state;
  // Notify any open popup
  chrome.runtime.sendMessage({ type: "CONNECTION_STATE", state }).catch(() => {});
}

// ── Content retrieval ────────────────────────────────────────────────────────

function sendActiveTabContent() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs[0]) return;
    const tab = tabs[0];

    // Skip browser-internal pages (chrome://, about:, etc.)
    if (!tab.url || !/^https?:\/\//.test(tab.url)) return;

    // Skip if this is the same URL we already sent (avoids duplicate loads
    // on minor events like Chrome re-firing onUpdated for the same page).
    if (tab.url === lastSentUrl) return;

    chrome.tabs.sendMessage(tab.id, { type: "GET_CONTENT" }, (response) => {
      if (chrome.runtime.lastError) {
        // Content script not yet injected (e.g. brand-new tab still loading).
        // The onUpdated listener will retry when the page finishes.
        return;
      }
      if (!response || !response.text) return;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;

      lastSentUrl = response.url;
      const payload = JSON.stringify({
        url: response.url,
        title: response.title,
        text: response.text,
      });
      ws.send(payload);
      console.log(
        "[SC Bridge] Sent",
        response.text.length.toLocaleString(),
        "chars from",
        response.title
      );
    });
  });
}

// ── Tab event listeners ──────────────────────────────────────────────────────

// User switched to a different tab
chrome.tabs.onActivated.addListener(() => {
  lastSentUrl = null; // Force a fresh send for the newly active tab
  sendActiveTabContent();
});

// A tab finished loading (navigation, refresh, SPA route change)
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.active) {
    lastSentUrl = null;
    sendActiveTabContent();
  }
});

// ── Popup message handler ────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "GET_STATE") {
    sendResponse({ state: connectionState });
  }
  return true;
});

// ── Boot ─────────────────────────────────────────────────────────────────────

connect();
