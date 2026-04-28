/**
 * background.js — service worker for the Screen Companion Bridge extension.
 *
 * Responsibilities:
 *   1. Maintain a persistent WebSocket connection to Screen Companion (localhost:9147).
 *   2. Listen for tab-switch and page-load events.
 *   3. Ask the active tab's content_script for page text.
 *   4. Forward { url, title, text } to Screen Companion over the socket.
 *   5. Auto-reconnect if Screen Companion is restarted.
 *   6. Retry after a short delay for SPAs that render content after page-ready.
 *   7. Notify popup.js of connection state changes.
 */

const SC_WS_URL = "ws://localhost:9147";
const RECONNECT_DELAY_MS = 3000;
const SPA_RETRY_DELAY_MS = 1500;   // wait for SPA frameworks to render
const MIN_CONTENT_CHARS   = 100;   // below this → treat as not-yet-rendered

let ws = null;
let reconnectTimer = null;
let retryTimer = null;
let connectionState = "disconnected";
let lastSentUrl = null;

// ── WebSocket lifecycle ──────────────────────────────────────────────────────

function connect() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  if (ws && ws.readyState === WebSocket.OPEN) return;

  setConnectionState("connecting");
  ws = new WebSocket(SC_WS_URL);

  ws.onopen = () => {
    setConnectionState("connected");
    console.log("[SC Bridge] Connected to Screen Companion on", SC_WS_URL);
    lastSentUrl = null;
    sendActiveTabContent();
  };

  ws.onclose = () => {
    setConnectionState("disconnected");
    console.log("[SC Bridge] Disconnected. Retrying in", RECONNECT_DELAY_MS, "ms...");
    reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
  };

  ws.onerror = () => {};
}

function setConnectionState(state) {
  connectionState = state;
  chrome.runtime.sendMessage({ type: "CONNECTION_STATE", state }).catch(() => {});
}

// ── Content retrieval ────────────────────────────────────────────────────────

function sendActiveTabContent(retryCount = 0) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs[0]) return;
    const tab = tabs[0];

    // Skip browser-internal pages (chrome://, about:, etc.)
    if (!tab.url || !/^https?:\/\//.test(tab.url)) return;

    // Skip if already sent this URL and we have enough content
    if (tab.url === lastSentUrl) return;

    chrome.tabs.sendMessage(tab.id, { type: "GET_CONTENT" }, (response) => {
      if (chrome.runtime.lastError) {
        // Content script not injected yet — retry once after a short delay
        if (retryCount < 3) {
          scheduleRetry(retryCount);
        }
        return;
      }

      if (!response) return;

      const text = response.text || "";

      // SPA pages (React, Vue, Angular) often have an empty or near-empty DOM
      // right after load. If content is too short, retry after SPA_RETRY_DELAY_MS
      // to give the framework time to render. Cap at 3 retries.
      if (text.length < MIN_CONTENT_CHARS && retryCount < 3) {
        console.log(
          "[SC Bridge] Content too short (" + text.length + " chars) on",
          response.title, "— retrying in", SPA_RETRY_DELAY_MS, "ms (attempt", retryCount + 1, ")"
        );
        scheduleRetry(retryCount);
        return;
      }

      if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

      lastSentUrl = response.url;
      ws.send(JSON.stringify({ url: response.url, title: response.title, text }));
      console.log("[SC Bridge] Sent", text.length.toLocaleString(), "chars from", response.title);
    });
  });
}

function scheduleRetry(currentCount) {
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    sendActiveTabContent(currentCount + 1);
  }, SPA_RETRY_DELAY_MS);
}

// ── Tab event listeners ──────────────────────────────────────────────────────

chrome.tabs.onActivated.addListener(() => {
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
  lastSentUrl = null;
  sendActiveTabContent();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.active) {
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
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
