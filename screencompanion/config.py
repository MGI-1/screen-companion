"""Constants, supported formats, and settings."""

import json
import os
import sys
from pathlib import Path

# ── Supported formats ──────────────────────────────────────────────
# Document formats
_DOC_FORMATS = {".pdf", ".docx", ".doc", ".txt", ".csv", ".xlsx", ".xls",
                ".pptx", ".ppt", ".rtf", ".odt", ".ods", ".odp"}
# Web / markup
_WEB_FORMATS = {".html", ".htm", ".xml", ".xhtml", ".svg"}
# Structured data
_DATA_FORMATS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
                 ".properties", ".env"}
# Markdown / docs
_MARKUP_FORMATS = {".md", ".markdown", ".rst", ".tex", ".latex", ".adoc",
                   ".org", ".wiki", ".textile"}
# Code / scripts (readable as plain text)
_CODE_FORMATS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp",
                 ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
                 ".kt", ".kts", ".scala", ".pl", ".pm", ".lua", ".r", ".R",
                 ".sh", ".bash", ".zsh", ".bat", ".ps1", ".sql", ".m",
                 ".mm", ".dart", ".vue", ".svelte", ".elm"}
# Styles / config
_STYLE_FORMATS = {".css", ".scss", ".sass", ".less", ".styl"}
# Logs and plain text variants
_LOG_FORMATS = {".log", ".out", ".err", ".trace", ".diff", ".patch"}

SUPPORTED_READ_FORMATS = (
    _DOC_FORMATS | _WEB_FORMATS | _DATA_FORMATS | _MARKUP_FORMATS |
    _CODE_FORMATS | _STYLE_FORMATS | _LOG_FORMATS
)
SUPPORTED_EDIT_FORMATS = {".txt", ".docx", ".csv", ".xlsx", ".md", ".html",
                          ".json", ".xml", ".yaml", ".yml"}

# ── Timing ─────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 2

# ── Content limits ─────────────────────────────────────────────────
MAX_CONTENT_CHARS = 200_000
MAX_FILE_SIZE_MB = 1024

# ── Window dimensions ─────────────────────────────────────────────
WINDOW_WIDTH = 370
WINDOW_HEIGHT = 520
TOGGLE_SIZE = 50

# ── Validator prompts ──────────────────────────────────────────────
CODE_GEN_SYSTEM_PROMPT = (
    "You are a Python/pandas data analyst. "
    "Given a pandas DataFrame `df` and a user question, write Python code to answer it precisely. "
    "Rules:\n"
    "- `df` and `pd` (pandas) are pre-loaded — do not import anything\n"
    "- Store the final human-readable answer as a string in a variable called `result`\n"
    "- Filter and look up data exactly as asked — never guess or infer category/field values\n"
    "- If the result is a list or table, format it as a readable string\n"
    "- Return ONLY the Python code, no explanation or markdown"
)

CODE_GEN_USER_TEMPLATE = (
    "DataFrame columns and types:\n{schema}\n\n"
    "Sample rows (first 3):\n{sample}\n\n"
    "Question: {question}\n\n"
    "Write Python code to answer this. Store the answer as a string in `result`."
)

RECONCILE_SYSTEM_PROMPT = (
    "You are reviewing your own answer alongside independent answers from other models. "
    "Check every item in every answer strictly against the source document. "
    "Correct any factual errors and return only the final accurate answer — no explanation."
)

RECONCILE_USER_TEMPLATE = (
    "Source document:\n<document>\n{document}\n</document>\n\n"
    "Question: {question}\n\n"
    "Your initial answer:\n{primary}\n\n"
    "Independent answers from other models:\n{answers}\n\n"
    "Cross-check all answers against the document. Fix any errors and return the final accurate answer only."
)

# ── LLM system prompt ─────────────────────────────────────────────
SYSTEM_PROMPT = """You are Screen Companion, an intelligent document assistant. \
You help users understand, analyze, and edit their documents.

When the user asks you to edit the document, respond with your explanation \
AND include a JSON code block with the edits. Supported edit types:

- replace: {"type": "replace", "search": "old text", "replace": "new text"}
- delete:  {"type": "delete", "search": "text to remove"}
- insert_after: {"type": "insert_after", "search": "text to find", "replace": "content to insert after it"}

```json
{"action": "edit", "edits": [{"type": "replace", "search": "old text", "replace": "new text"}]}
```

Be concise, helpful, and precise. Reference specific parts of the document \
when answering questions."""

# ── LLM provider configs ──────────────────────────────────────────
LLM_PROVIDERS = {
    "anthropic": {
        "name": "Anthropic (Claude)",
        "models": [
            "claude-sonnet-4-20250514",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-20250514",
        ],
        "default_model": "claude-sonnet-4-20250514",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "name": "OpenAI (GPT)",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "o3-mini",
        ],
        "default_model": "gpt-4o",
        "env_key": "OPENAI_API_KEY",
    },
    "google": {
        "name": "Google (Gemini)",
        "models": [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-pro",
        ],
        "default_model": "gemini-2.0-flash",
        "env_key": "GOOGLE_API_KEY",
    },
}

# ── macOS AppleScript map ──────────────────────────────────────────
APP_SCRIPT_MAP = {
    # Apple apps
    "com.apple.Preview": (
        'tell application "Preview" to return POSIX path of '
        "(file of front document as alias)"
    ),
    "com.apple.TextEdit": (
        'tell application "TextEdit" to return POSIX path of '
        "(file of front document as alias)"
    ),
    "com.apple.iWork.Pages": (
        'tell application "Pages" to return POSIX path of '
        "(file of front document as alias)"
    ),
    "com.apple.iWork.Numbers": (
        'tell application "Numbers" to return POSIX path of '
        "(file of front document as alias)"
    ),
    "com.apple.iWork.Keynote": (
        'tell application "Keynote" to return POSIX path of '
        "(file of front document as alias)"
    ),
    # Microsoft Office
    "com.microsoft.Word": (
        'tell application "Microsoft Word" to return POSIX path of '
        "(full name of active document as alias)"
    ),
    "com.microsoft.Excel": (
        'tell application "Microsoft Excel" to return POSIX path of '
        "(full name of active workbook as alias)"
    ),
    "com.microsoft.Powerpoint": (
        'tell application "Microsoft PowerPoint" to return POSIX path of '
        "(full name of active presentation as alias)"
    ),
    # Text editors with AppleScript support
    "com.barebones.bbedit": (
        'tell application "BBEdit" to return POSIX path of '
        "(file of front document)"
    ),
    "com.macromates.TextMate": (
        'tell application "TextMate" to return POSIX path of '
        "(file of front document)"
    ),
    "com.macromates.TextMate.preview": (
        'tell application "TextMate" to return POSIX path of '
        "(file of front document)"
    ),
    # LibreOffice
    "org.libreoffice.script": (
        'tell application "LibreOffice" to return POSIX path of '
        "(file of front document)"
    ),
}

# Apps where we rely on window-title parsing (no reliable AppleScript).
# Maps bundle_id to the app name for window-title extraction.
WINDOW_TITLE_APPS = {
    "com.microsoft.VSCode",
    "com.sublimetext.4",
    "com.sublimetext.3",
    "com.googlecode.iterm2",
    "com.apple.Terminal",
    "com.jetbrains.intellij",
    "com.jetbrains.pycharm",
    "com.jetbrains.webstorm",
    "com.jetbrains.goland",
    "com.jetbrains.CLion",
    "com.jetbrains.rider",
    "com.github.atom",
    "com.panic.Nova",
    "com.coteditor.CotEditor",
    "abnerworks.Typora",
    "com.apple.Safari",
    "com.google.Chrome",
    "org.mozilla.firefox",
    "com.brave.Browser",
    "com.operasoftware.Opera",
    "com.microsoft.edgemac",
}

# ── Windows COM map ────────────────────────────────────────────────
WIN_COM_MAP = {
    "WINWORD.EXE": ("Word.Application", "ActiveDocument.FullName"),
    "EXCEL.EXE": ("Excel.Application", "ActiveWorkbook.FullName"),
    "POWERPNT.EXE": ("PowerPoint.Application", "ActivePresentation.FullName"),
}

# ── User config persistence ───────────────────────────────────────
CONFIG_DIR = Path.home() / ".screencompanion"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_user_config() -> dict:
    """Load user config from ~/.screencompanion/config.json."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_user_config(config: dict) -> None:
    """Save user config to ~/.screencompanion/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
