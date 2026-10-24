"""Shared helpers for all collectors.

Every collector produces records in the same shape, so the later pipeline
does not care where an item came from:

    id, source, source_detail, url, created_at, rating, title, text, collected_at

Usernames and author handles are never stored.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

FIELDS = ["id", "source", "source_detail", "url", "created_at", "rating",
          "title", "text", "collected_at"]


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------- privacy scrubbing ----------
_PATTERNS = [
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[PAN]"),                 # PAN number
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),                # email
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[PHONE]"),  # Indian mobile
    (re.compile(r"(?<!\d)\d{9,18}(?!\d)"), "[NUMBER]"),                 # account-like numbers
    (re.compile(r"(?<![\w/])u/[A-Za-z0-9_-]{3,}"), "[USER]"),            # reddit username mentions
    (re.compile(r"(?<!\w)@[A-Za-z0-9_.]{3,}"), "[USER]"),                # @handles
]


def scrub(text: str) -> str:
    if not text:
        return ""
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return re.sub(r"\s+", " ", text).strip()


# ---------- keyword filter ----------
def build_keyword_matcher(keywords: list[str]):
    """Short ASCII keywords ('sip', 'mf', 'nav') match whole words only,
    so 'navigate' or 'gossip' do not count. Non-ASCII keywords match anywhere."""
    parts = []
    for kw in keywords:
        kw = kw.strip().lower()
        if not kw:
            continue
        if kw.isascii():
            parts.append(r"\b" + re.escape(kw) + r"s?\b")
        else:
            parts.append(re.escape(kw))
    regex = re.compile("|".join(parts), re.IGNORECASE)
    return lambda text: bool(text) and bool(regex.search(text))


# ---------- record helpers ----------
def make_id(source: str, native_id: str) -> str:
    return source + "_" + hashlib.sha1(str(native_id).encode()).hexdigest()[:12]


def to_iso(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def make_record(source, native_id, text, *, source_detail=None, url=None,
                created_at=None, rating=None, title=None) -> dict:
    return {
        "id": make_id(source, native_id),
        "source": source,
        "source_detail": source_detail,
        "url": url,
        "created_at": to_iso(created_at),
        "rating": rating,
        "title": scrub(title) if title else None,
        "text": scrub(text),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def save_records(records: list[dict], filename: str) -> Path:
    """Write records as JSON lines, dropping duplicates and empty texts."""
    seen, out = set(), []
    for r in records:
        if not r["text"] or r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append({k: r.get(k) for k in FIELDS})
    path = RAW_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  saved {len(out)} items -> {path.relative_to(ROOT)}")
    return path
