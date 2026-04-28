"""Intelligent input interpretation.

Runs before every LLM call to classify the user's intent, extract key
entities, and scan the active document for the sections most relevant to
what the user actually wants. The result is injected into the prompt as
a "Task framing" block so the LLM receives a focused brief instead of a
raw question + the whole document.

Pure local logic — no extra LLM round-trip.
"""

import re
from dataclasses import dataclass, field


# Intent patterns ordered by priority. First match wins, so put the
# narrow / unambiguous intents (edit, calculate) before broader ones.
_INTENT_PATTERNS = [
    ("edit", [
        r"\bedit\b", r"\brewrite\b", r"\breplace\b", r"\bchange\b.*\bto\b",
        r"\bfix (the )?typo\b", r"\bupdate\b.*\bto\b", r"\bdelete\b",
        r"\binsert\b", r"\brename\b",
    ]),
    ("filter_rank", [
        r"\btop\s+\d+\b", r"\bbottom\s+\d+\b", r"\bhighest\b", r"\blowest\b",
        r"\bbiggest\b", r"\bsmallest\b", r"\brank(ed)?\b", r"\bsort(ed)?\b",
        r"\babove\s+\$?\d", r"\bbelow\s+\$?\d", r"\bgreater than\b",
        r"\bless than\b", r"\bmore than\b", r"\bat least\b", r"\bat most\b",
        r"\bover\s+\$?\d", r"\bunder\s+\$?\d",
    ]),
    ("calculate", [
        r"\bcalculat(e|ion)\b", r"\bcompute\b", r"\btotal\b", r"\bsum\b",
        r"\baverage\b", r"\bmean\b", r"\bpercent(age)?\b", r"\bratio\b",
        r"\bmargin\b", r"\broi\b", r"\bnpv\b", r"\birr\b", r"\bcagr\b",
        r"\bhow much\b", r"\bhow many\b",
    ]),
    ("summarize", [
        r"\bsummariz?e\b", r"\bsummary\b", r"\btl;?dr\b", r"\bkey points?\b",
        r"\bkey takeaways?\b", r"\bmain points?\b", r"\boverview\b",
        r"\bgist\b", r"\bin short\b", r"\bin brief\b",
    ]),
    ("extract", [
        r"\blist (all|every|the)\b", r"\bfind (all|every)\b", r"\bextract\b",
        r"\bshow me (all|every|the)\b", r"\bpull out\b", r"\bget me\b",
        r"\bevery\b.*\b(row|entry|item|record|line)\b",
    ]),
    ("compare", [
        r"\bcompare\b", r"\bdifference between\b", r"\bvs\.?\b", r"\bversus\b",
        r"\bwhich is (better|higher|lower|bigger)\b",
    ]),
]

# Words to strip when building keyword queries for document scanning.
# Keep it small — aggressive stopword removal can drop meaningful terms
# like "income" or "north" that happen to be short.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "for", "with", "by", "from", "as",
    "and", "or", "but", "if", "then", "so", "not", "no",
    "i", "me", "my", "we", "us", "our", "you", "your", "it", "its",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    "how", "when", "where", "why", "do", "does", "did", "can", "could",
    "would", "should", "will", "shall", "may", "might", "must",
    "please", "tell", "show", "give", "list", "find", "get", "all",
    "every", "any", "some", "each", "than", "into", "about", "over",
    "under", "above", "below",
}


@dataclass
class Interpretation:
    """Structured result of interpreting a user message."""

    intent: str                    # e.g. "calculate", "summarize"
    keywords: list = field(default_factory=list)   # list[str] — strongest terms
    numbers: list = field(default_factory=list)    # list[str] — thresholds, quantities
    relevant_excerpts: list = field(default_factory=list)  # list[str] — top doc sections
    raw_input: str = ""

    def to_task_framing(self) -> str:
        """Render the interpretation as a prompt prefix for the LLM."""
        lines = [f"[Detected intent: {self.intent}]"]
        if self.keywords:
            lines.append(f"[Key terms: {', '.join(self.keywords[:8])}]")
        if self.numbers:
            lines.append(f"[Numbers in question: {', '.join(self.numbers)}]")
        guidance = _INTENT_GUIDANCE.get(self.intent)
        if guidance:
            lines.append(f"[Guidance: {guidance}]")
        return "\n".join(lines)

    def ui_summary(self) -> str:
        """Short human-readable summary for the chat UI."""
        label = _INTENT_LABELS.get(self.intent, self.intent)
        if self.keywords:
            return f"Understood: {label} — focus on {', '.join(self.keywords[:4])}"
        return f"Understood: {label}"


_INTENT_LABELS = {
    "calculate":   "calculation",
    "filter_rank": "filter / rank",
    "edit":        "document edit",
    "summarize":   "summary",
    "extract":     "extract / list",
    "compare":     "comparison",
    "question":    "question answering",
}

_INTENT_GUIDANCE = {
    "calculate": (
        "Use the calculate JSON block with the appropriate math function. "
        "Pull exact numbers from the document — do not estimate."
    ),
    "filter_rank": (
        "MUST use a calculate JSON block with rank / filter_by_threshold / "
        "top_n. Trust the tool's filtered_items / ranked_items / top_items "
        "array — never hand-curate the list yourself."
    ),
    "edit": (
        "Respond with an edit JSON block. Preserve surrounding context when "
        "choosing the search string so it matches exactly once."
    ),
    "summarize": (
        "Produce a concise summary. Cover only what is present in the "
        "document; do not add outside information."
    ),
    "extract": (
        "Return a clean enumerated or bulleted list pulled verbatim from "
        "the document. Preserve original wording of each item."
    ),
    "compare": (
        "Put the comparison in a small table or side-by-side format. "
        "Cite the values from the document for each side."
    ),
    "question": (
        "Answer directly from the document and cite the specific section "
        "that supports your answer."
    ),
}


def classify_intent(user_input: str) -> str:
    """Return the best-matching intent label for the user's message."""
    lowered = user_input.lower()
    for intent, patterns in _INTENT_PATTERNS:
        for pat in patterns:
            if re.search(pat, lowered):
                return intent
    return "question"


def extract_keywords(user_input: str, limit: int = 8) -> list:
    """Pull content words from the user's message, preserving order."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", user_input)
    seen = set()
    keywords = []
    for tok in tokens:
        low = tok.lower()
        if low in _STOPWORDS or low in seen:
            continue
        seen.add(low)
        keywords.append(tok)
        if len(keywords) >= limit:
            break
    return keywords


def extract_numbers(user_input: str) -> list:
    """Pull numeric tokens (incl. currency / percentages) from the message."""
    return re.findall(r"\$?\d[\d,]*(?:\.\d+)?%?", user_input)


def scan_document(
    document_content: str, keywords: list, max_excerpts: int = 3,
    window_chars: int = 600,
) -> list:
    """Find sections of the document most relevant to the keywords.

    Scores each line by how many unique keywords it contains, then returns
    a surrounding window around the top lines. Used to give the LLM a
    focused "these sections likely hold the answer" hint even when the
    full document is also present in the prompt.
    """
    if not document_content or not keywords:
        return []

    lines = document_content.splitlines()
    if not lines:
        return []

    lowered_keywords = [k.lower() for k in keywords]
    line_scores = []  # list[(score, line_idx)]
    for idx, line in enumerate(lines):
        lower_line = line.lower()
        score = sum(1 for k in lowered_keywords if k in lower_line)
        if score > 0:
            line_scores.append((score, idx))

    line_scores.sort(key=lambda x: (-x[0], x[1]))

    # Build excerpts around the top-scoring lines, merging overlaps.
    selected_ranges = []  # list[(start, end)] over line indices
    for _, idx in line_scores:
        # Grow window ~window_chars worth of lines around idx
        start = idx
        end = idx
        size = len(lines[idx])
        while start > 0 and size < window_chars:
            start -= 1
            size += len(lines[start])
        while end < len(lines) - 1 and size < window_chars:
            end += 1
            size += len(lines[end])

        merged = False
        for i, (s, e) in enumerate(selected_ranges):
            if not (end < s or start > e):
                selected_ranges[i] = (min(s, start), max(e, end))
                merged = True
                break
        if not merged:
            selected_ranges.append((start, end))
        if len(selected_ranges) >= max_excerpts:
            break

    excerpts = []
    for s, e in selected_ranges[:max_excerpts]:
        excerpts.append("\n".join(lines[s:e + 1]).strip())
    return excerpts


def interpret(user_input: str, document_content: str = "") -> Interpretation:
    """Full pipeline: classify intent, extract entities, scan document."""
    intent = classify_intent(user_input)
    keywords = extract_keywords(user_input)
    numbers = extract_numbers(user_input)
    excerpts = scan_document(document_content, keywords) if document_content else []
    return Interpretation(
        intent=intent,
        keywords=keywords,
        numbers=numbers,
        relevant_excerpts=excerpts,
        raw_input=user_input,
    )
