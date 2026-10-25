"""Read your corrections from the review workbook into data/manual/corrections.csv.

    python -m pipeline.import_review                 # reads data/review/review_workbook.xlsx
    python -m pipeline.import_review path/to/other.xlsx

Only rows of the tab 'All tagged posts' whose 'REVIEW: correct? (Y/N)' is N are used. Rows marked Y or left empty are skipped.
For each N row it needs a field and a correct value (picked from the dropdown or typed); your note becomes the reason.
Labels are turned back into the stored codes. A correction that already exists for the same post and field is updated, not repeated.
The next `python -m pipeline.export` applies the corrections and lists them on the Validation page as human corrections.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import load_workbook

from collect.common import ROOT
from pipeline.review_export import BY_KEY, BY_LABEL, CORRECTIONS_FILE, WORKBOOK, code_of, label_of

SHEET = "All tagged posts"
DEFAULT_REASON = "Human review in the spreadsheet (no note written)"


def parse_value(key: str, kind: str, text: str):
    """Stored value for what was typed: a code, a list of codes joined by '|', an int, or free text. Returns (value, problem)."""
    text = str(text).strip()
    if kind == "text":
        return text, None
    if kind == "many":
        codes, bad = [], []
        for part in [p for p in text.replace("|", ";").split(";") if p.strip()]:
            c = code_of(key, part)
            (codes if c else bad).append(c or part.strip())
        return ("|".join(codes), None) if codes and not bad else (None, f"unknown value(s) {bad or ['(empty)']}")
    c = code_of(key, text)
    return (str(c), None) if c is not None else (None, f"'{text}' is not an allowed value for this field")


def read_rows(path: Path) -> list[dict]:
    wb = load_workbook(path, data_only=True)
    if SHEET not in wb.sheetnames:
        sys.exit(f"The tab '{SHEET}' is missing from {path.name}.")
    ws = wb[SHEET]
    heads = [str(c.value or "").strip() for c in ws[1]]
    col = {h: i for i, h in enumerate(heads)}
    need = ["id", "REVIEW: correct? (Y/N)", "REVIEW: field to fix", "REVIEW: correct value", "REVIEW: note"]
    if any(n not in col for n in need):
        sys.exit("A REVIEW column header was renamed or removed; do not edit the header row.")
    out = []
    for n, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        g = lambda h: (row[col[h]] if col[h] < len(row) and row[col[h]] is not None else "")
        out.append({"line": n, "id": str(g("id")).strip(), "ok": str(g("REVIEW: correct? (Y/N)")).strip().upper(),
                    "field": str(g("REVIEW: field to fix")).strip(), "value": str(g("REVIEW: correct value")).strip(),
                    "note": " ".join(str(g("REVIEW: note")).split())})
    return out


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else WORKBOOK
    if not path.exists():
        sys.exit(f"{path} not found. Build it first with: python -m pipeline.review_export")
    existing: list[dict] = []
    if CORRECTIONS_FILE.exists():
        with open(CORRECTIONS_FILE, newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    index = {(r["id"], r["field"]): r for r in existing}
    added = updated = unchanged = 0
    skipped: list[str] = []
    seen_rows = 0
    for r in read_rows(path):
        if r["ok"] != "N":
            continue
        seen_rows += 1
        where = f"row {r['line']}"
        spec = BY_LABEL.get(r["field"])
        if not r["id"] or spec is None:
            skipped.append(f"{where}: field to fix '{r['field']}' is empty or not one of the field names")
            continue
        label, key, _, kind = spec
        if not r["value"]:
            skipped.append(f"{where}: no correct value written for '{label}'")
            continue
        value, problem = parse_value(key, kind, r["value"])
        if problem:
            skipped.append(f"{where} ({label}): {problem}")
            continue
        if key == "is_relevant" and value == "yes":
            skipped.append(f"{where}: marking a not-relevant post as relevant cannot be applied (it has no tags); ask Claude to re-tag it")
            continue
        reason = r["note"].removeprefix("Already corrected: ") or DEFAULT_REASON
        old = index.get((r["id"], key))
        if old is None:
            row = {"id": r["id"], "field": key, "corrected_value": value, "reason": reason}
            existing.append(row)
            index[(r["id"], key)] = row
            added += 1
        elif old["corrected_value"] == value and old["reason"] == reason:
            unchanged += 1
        else:
            old["corrected_value"], old["reason"] = value, reason
            updated += 1
    if added or updated:
        with open(CORRECTIONS_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["id", "field", "corrected_value", "reason"])
            w.writeheader()
            w.writerows(existing)
    print(f"{seen_rows} rows marked N: {added} added, {updated} updated, {unchanged} already in corrections.csv, {len(skipped)} skipped.")
    for s in skipped:
        print("  skipped:", s)
    if added or updated:
        print(f"Saved {CORRECTIONS_FILE.relative_to(ROOT)}. Now run: python -m pipeline.export")


if __name__ == "__main__":
    main()
