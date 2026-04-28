const dot        = document.getElementById("dot");
const statusText = document.getElementById("status-text");
const pageTitle  = document.getElementById("page-title");
const hint       = document.getElementById("hint");

const LABELS = {
  connected:    "Connected to Screen Companion",
  connecting:   "Connecting…",
  disconnected: "Screen Companion not running",
};

const HINTS = {
  connected:    "The active tab's content is being sent automatically.",
  connecting:   "Trying to reach Screen Companion on localhost:9147…",
  disconnected: "Start Screen Companion, then this will connect automatically.",
};

function applyState(state) {
  dot.className      = `dot ${state}`;
  statusText.textContent = LABELS[state] || state;
  hint.textContent       = HINTS[state]  || "";
}

// Ask background for current state
chrome.runtime.sendMessage({ type: "GET_STATE" }, (res) => {
  if (res) applyState(res.state);
});

// Listen for live state changes while popup is open
chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "CONNECTION_STATE") applyState(message.state);
});

// Show active tab title
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  if (tabs && tabs[0]) {
    pageTitle.textContent = tabs[0].title || tabs[0].url || "—";
  }
});
