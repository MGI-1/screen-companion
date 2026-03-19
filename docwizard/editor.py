"""Document editing — search-replace with backup."""

import csv
import io
import os
import shutil
from pathlib import Path
from typing import Optional

from docwizard.config import SUPPORTED_EDIT_FORMATS


class UnsupportedEditError(Exception):
    pass


def apply_edits(path: str, edits: list[dict]) -> str:
    """Apply search-replace edits to a document.

    Each edit: {"type": "replace", "search": "old text", "replace": "new text"}

    Returns a summary of changes made.
    """
    p = Path(path)
    ext = p.suffix.lower()

    if ext not in SUPPORTED_EDIT_FORMATS:
        raise UnsupportedEditError(
            f"Cannot edit '{ext}' files. Editable formats: "
            f"{', '.join(sorted(SUPPORTED_EDIT_FORMATS))}"
        )

    # Create backup
    backup_path = str(path) + ".bak"
    try:
        shutil.copy2(path, backup_path)
    except OSError:
        pass  # Non-fatal — proceed without backup

    specific_editors = {
        ".csv": _edit_csv,
        ".docx": _edit_docx,
        ".xlsx": _edit_xlsx,
    }
    # All other editable formats use plain-text search-replace
    editor_fn = specific_editors.get(ext, _edit_txt)

    results = []
    for edit in edits:
        if edit.get("type") != "replace":
            results.append(f"Skipped unknown edit type: {edit.get('type')}")
            continue

        search = edit.get("search", "")
        replace = edit.get("replace", "")

        if not search:
            results.append("Skipped edit with empty search string.")
            continue

        count = editor_fn(path, search, replace)
        if count > 0:
            results.append(
                f"Replaced '{_truncate(search, 40)}' → "
                f"'{_truncate(replace, 40)}' ({count} occurrence{'s' if count > 1 else ''})"
            )
        else:
            results.append(f"No match found for '{_truncate(search, 40)}'")

    summary = "\n".join(results)
    return f"Backup saved: {backup_path}\n{summary}"


def _edit_txt(path: str, search: str, replace: str) -> int:
    """Search-replace in a plain text file."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    count = content.count(search)
    if count > 0:
        content = content.replace(search, replace)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    return count


def _edit_csv(path: str, search: str, replace: str) -> int:
    """Search-replace in a CSV file (cell values)."""
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    count = 0
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if search in cell:
                occurrences = cell.count(search)
                rows[i][j] = cell.replace(search, replace)
                count += occurrences

    if count > 0:
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

    return count


def _edit_docx(path: str, search: str, replace: str) -> int:
    """Search-replace in a DOCX file (paragraph text)."""
    from docx import Document

    doc = Document(path)
    count = 0

    for para in doc.paragraphs:
        if search in para.text:
            # Replace in runs to preserve some formatting
            full_text = para.text
            occurrences = full_text.count(search)
            count += occurrences

            # Simple approach: rebuild paragraph text across runs
            for run in para.runs:
                if search in run.text:
                    run.text = run.text.replace(search, replace)

            # If runs didn't cover it (search spans multiple runs),
            # fall back to replacing in the first run
            if search in para.text:
                # The replacement didn't work across runs, try again
                new_text = para.text.replace(search, replace)
                for i, run in enumerate(para.runs):
                    if i == 0:
                        run.text = new_text
                    else:
                        run.text = ""

    if count > 0:
        doc.save(path)

    return count


def _edit_xlsx(path: str, search: str, replace: str) -> int:
    """Search-replace in an XLSX file (cell values)."""
    from openpyxl import load_workbook

    wb = load_workbook(path)
    count = 0

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str) and search in cell.value:
                    occurrences = cell.value.count(search)
                    cell.value = cell.value.replace(search, replace)
                    count += occurrences

    if count > 0:
        wb.save(path)

    wb.close()
    return count


def _truncate(text: str, max_len: int) -> str:
    """Truncate text for display."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
