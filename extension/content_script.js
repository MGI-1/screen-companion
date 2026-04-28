/**
 * content_script.js — injected into every webpage.
 *
 * Responds to GET_CONTENT messages from background.js by returning:
 *   { url, title, text }
 *
 * This script runs inside the page so it has direct access to the DOM.
 * It cannot open WebSockets — that's background.js's job.
 */

const MAX_CHARS = 400_000; // ~100K tokens — enough for any model

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "GET_CONTENT") return false;

  try {
    let text = "";

    // Prefer <article> or <main> when available — gives cleaner text
    // for news articles, blog posts, and documentation pages.
    const focus =
      document.querySelector("article") ||
      document.querySelector("main") ||
      document.body;

    text = focus ? focus.innerText || "" : "";

    // Fall back to full body if the focused region is nearly empty
    if (text.length < 200 && document.body) {
      text = document.body.innerText || "";
    }

    // Collapse excessive blank lines produced by hidden elements
    text = text.replace(/\n{4,}/g, "\n\n\n").trim();

    if (text.length > MAX_CHARS) {
      text = text.slice(0, MAX_CHARS) + "\n\n[Content truncated — page too long]";
    }

    sendResponse({
      url: window.location.href,
      title: document.title || window.location.href,
      text: text,
    });
  } catch (err) {
    sendResponse({ url: window.location.href, title: document.title, text: "" });
  }

  return true; // Keep message channel open for async sendResponse
});
