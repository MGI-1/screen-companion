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
# MAX_CONTENT_CHARS is the fallback cap when no provider/model context is
# available. The active model's true input window is consulted at read-time
# via get_max_input_chars(). See model_specs in LLM_PROVIDERS below.
MAX_CONTENT_CHARS = 200_000
MAX_FILE_SIZE_MB = 1024

# Rough char-to-token conversion. Real tokenization varies (English ~3.5–4
# chars/token across Claude/GPT/Gemini); the reserve_tokens slack absorbs
# the error.
CHARS_PER_TOKEN = 4

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
    "- For datetime values: if the time part is midnight (00:00:00), show only the date (str(val.date())). If the date part is 1900-01-01 or today, show only the time (str(val.time())). Otherwise show both date and time (str(val)). Never show '00:00:00' when the original data only has a date.\n"
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

When the user asks you to calculate or compute something, respond with your explanation \
AND include a JSON code block with the calculation. Use the exact function names below:

```json
{"action": "calculate", "function": "<function_name>", "args": {"param": "value"}}
```

CRITICAL RULE for list questions: Whenever the user asks you to filter, select, rank, \
or pick the top items from a list (e.g. "items above $X", "top 5 by revenue", "every \
row where amount < 100"), you MUST emit a JSON calculation block using one of the \
Comparison & Selection functions and trust the returned `filtered_items` / `top_items` \
/ `ranked_items` array. Never produce the filtered list yourself from the document — \
the deterministic tool result will be fed back to you in a follow-up turn so you can \
write the final answer.

Available math functions (all numeric args are strings, e.g. "500000"):

Arithmetic: add(a, b), subtract(a, b), multiply(a, b), divide(a, b, precision=10), \
sum_values(values), average(values), weighted_average(values, weights), round(value, places=2)

Percentages: percentage(part, whole), percentage_change(old_value, new_value)

Financial: variance(actual, budget), compound_growth(principal, rate, periods), \
margin(revenue, cost), roi(gain, cost), npv(rate, cashflows), irr(cashflows), \
payback_period(initial_investment, annual_cashflow), cagr(begin_value, end_value, periods)

Ratios: current_ratio(current_assets, current_liabilities), \
quick_ratio(current_assets, inventory, current_liabilities), \
debt_to_equity(total_debt, total_equity), working_capital(current_assets, current_liabilities), \
dso(receivables, revenue, days=365)

Profitability: ebitda(revenue, cogs, opex, depreciation="0"), gross_margin(revenue, cogs), \
operating_margin(operating_income, revenue), roe(net_income, equity), roa(net_income, total_assets)

FX: fx_convert(amount, rate)

Comparison & Selection: rank(items, key, order="desc"), \
threshold_check(value, threshold, operator="gt"), \
filter_by_threshold(items, key, threshold, operator="gt"), \
top_n(items, key, n, order="desc")

Working Capital Cycle: dpo(payables, cogs, days=365), dio(inventory, cogs, days=365), \
cash_conversion_cycle(dso, dio, dpo), inventory_turnover(cogs, average_inventory)

Solvency & Coverage: interest_coverage(ebitda, interest_expense), \
debt_service_coverage(operating_income, debt_service)

Cost Analysis: contribution_margin(revenue, variable_costs), \
break_even(fixed_costs, price_per_unit, variable_cost_per_unit)

Advanced Valuation: wacc(equity, debt, cost_of_equity, cost_of_debt, tax_rate), \
xnpv(rate, cashflows, dates), xirr(cashflows, dates)

Time Series & Forecasting: moving_average(values, window=3), \
exponential_smoothing(values, alpha="0.3"), z_score(value, mean, std_dev), \
percentile(values, percentile), correlation(series_a, series_b)

Variance Decomposition: volume_price_mix(actual_volume, actual_price, budget_volume, budget_price)

Risk: value_at_risk(portfolio_value, volatility, confidence="0.95", days=1)

Loans: loan_payment(principal, annual_rate, periods)

Be concise, helpful, and precise. Reference specific parts of the document \
when answering questions."""

# ── LLM provider configs ──────────────────────────────────────────
# model_specs maps each model to:
#   input_tokens  — full context window
#   output_tokens — max generation per response
#   reasoning     — True for OpenAI reasoning models that require
#                   max_completion_tokens instead of max_tokens
# Verify these against provider docs whenever you add or change a model.
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
        "model_specs": {
            "claude-sonnet-4-20250514":  {"input_tokens": 200_000, "output_tokens": 64_000},
            "claude-haiku-4-5-20251001": {"input_tokens": 200_000, "output_tokens": 64_000},
            "claude-opus-4-20250514":    {"input_tokens": 200_000, "output_tokens": 32_000},
        },
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
        "model_specs": {
            "gpt-4o":      {"input_tokens": 128_000, "output_tokens": 16_384},
            "gpt-4o-mini": {"input_tokens": 128_000, "output_tokens": 16_384},
            "gpt-4-turbo": {"input_tokens": 128_000, "output_tokens": 4_096},
            "o3-mini":     {"input_tokens": 200_000, "output_tokens": 100_000, "reasoning": True},
        },
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
        "model_specs": {
            "gemini-2.0-flash":      {"input_tokens": 1_048_576, "output_tokens": 8_192},
            "gemini-2.0-flash-lite": {"input_tokens": 1_048_576, "output_tokens": 8_192},
            "gemini-1.5-pro":        {"input_tokens": 2_097_152, "output_tokens": 8_192},
        },
    },
}


_DEFAULT_MODEL_SPEC = {"input_tokens": 100_000, "output_tokens": 4_096}


def get_model_spec(provider: str, model: str) -> dict:
    """Return the input/output token spec for a provider+model, with a safe fallback."""
    return (
        LLM_PROVIDERS.get(provider, {})
        .get("model_specs", {})
        .get(model, _DEFAULT_MODEL_SPEC)
    )


def get_max_input_chars(provider: str, model: str, reserve_tokens: int = 8_000) -> int:
    """
    Convert a model's input window into a character cap for document truncation.

    Reserves room for the system prompt, conversation history, and the model's
    own response (output_tokens) so the document fits comfortably inside the
    real context window.
    """
    spec = get_model_spec(provider, model)
    usable_tokens = spec["input_tokens"] - reserve_tokens - spec["output_tokens"]
    if usable_tokens < 10_000:
        usable_tokens = 10_000
    return usable_tokens * CHARS_PER_TOKEN


def get_output_tokens(provider: str, model: str) -> int:
    """Return the max output tokens for a provider+model."""
    return get_model_spec(provider, model)["output_tokens"]


def is_reasoning_model(provider: str, model: str) -> bool:
    """True if the model uses max_completion_tokens instead of max_tokens (e.g. o3-mini)."""
    return bool(get_model_spec(provider, model).get("reasoning"))

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
    "ACROBAT.EXE": ("AcroExch.App", None),   # special handling
    "ACRORD32.EXE": ("AcroExch.App", None),  # Acrobat Reader 32-bit
    "ACRORD64.EXE": ("AcroExch.App", None),  # Acrobat Reader 64-bit
}

# WPS Office and other apps that embed the file path in the window title.
# Maps process name (upper) to the separator used in the title.
WIN_TITLE_APPS = {
    "WPS.EXE", "WPSOFFICE.EXE", "ET.EXE", "WPP.EXE",       # WPS Office
    "LIBREOFFICE.EXE", "SOFFICE.EXE",                        # LibreOffice
    "NOTEPAD.EXE", "NOTEPAD++.EXE", "WORDPAD.EXE",           # Text editors
    "CODE.EXE",                                               # VS Code
    "FOXITREADER.EXE", "FOXITPDFEDITOR.EXE",                  # Foxit PDF
    "SUMATRAPDF.EXE",                                         # SumatraPDF
}

# Browser processes — content comes via the browser extension (WebSocket),
# not from file detection. The detector returns None for these so the
# FocusWatcher doesn't clear the document while waiting for the extension.
WIN_BROWSER_PROCS = {
    "CHROME.EXE", "MSEDGE.EXE", "FIREFOX.EXE",
    "BRAVE.EXE", "OPERA.EXE", "VIVALDI.EXE",
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
