"""Clean step: merge every file in data/raw/, drop duplicates and tiny items,
add year / language / context fields. Plain code only, no AI.

Usage (from the project folder):
    python -m pipeline.clean
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict

import numpy as np
from rapidfuzz import fuzz, process

from collect.common import RAW_DIR, ROOT, build_keyword_matcher, load_config

PROCESSED_DIR = ROOT / "data" / "processed"
MIN_WORDS = 6               # shorter items are dropped unless they mention a SIP keyword
NEAR_DUP_SCORE = 90         # rapidfuzz ratio (0-100) at or above this = near-duplicate
NEAR_DUP_MIN_CHARS = 20     # shorter texts are only compared for exact matches
MAIN_WINDOW_FROM = 2021
CONTEXT_CHARS = 300

# Romanised Hindi words that are not normal English words (used to spot Hinglish)
HINGLISH_WORDS = {
    "hai", "hain", "nahi", "nahin", "nhi", "kya", "kyu", "kyun", "kyon", "kaise", "kese", "kaisa",
    "ka", "ke", "ki", "ko", "mein", "mai", "hum", "aap", "apna", "apne", "bhi", "aur", "lekin",
    "magar", "koi", "kuch", "sab", "bahut", "bohot", "accha", "acha", "achha", "bekar", "paisa",
    "paise", "wala", "wali", "liye", "karo", "karna", "kar", "kare", "karein", "raha", "rahi",
    "rahe", "tha", "thi", "hota", "hoga", "sahi", "mat", "bhai", "nikal", "abhi", "toh", "ye", "yeh",
    "mera", "meri", "mujhe", "aapka", "isme", "usme", "jab", "tab", "wo", "woh",
}


# ---------- loading ----------
def load_raw() -> list[dict]:
    rows = []
    for path in sorted(RAW_DIR.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            rows += [json.loads(line) for line in f if line.strip()]
    return rows


# ---------- duplicates ----------
def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def find_duplicates(rows: list[dict]) -> set[int]:
    """Indexes of rows to drop. The first copy (file order) is kept."""
    drop, seen = set(), {}
    for i, r in enumerate(rows):                       # exact (ignoring case and punctuation)
        key = normalise(r["text"])
        if key in seen:
            drop.add(i)
        else:
            seen[key] = i

    keep = [i for i in range(len(rows)) if i not in drop
            and len(normalise(rows[i]["text"])) >= NEAR_DUP_MIN_CHARS]
    texts = [normalise(rows[i]["text"]) for i in keep]
    chunk = 500                                        # keeps memory small
    for start in range(0, len(keep), chunk):
        scores = process.cdist(texts[start:start + chunk], texts, scorer=fuzz.ratio,
                               score_cutoff=NEAR_DUP_SCORE, dtype=np.uint8, workers=-1)
        for a, row in enumerate(scores):
            i = start + a
            for j in np.nonzero(row)[0]:
                if j > i:                              # later copy goes, earlier one stays
                    drop.add(keep[j])
    return drop


# ---------- new fields ----------
def year_of(created_at: str | None) -> int | None:
    m = re.match(r"(\d{4})-", created_at or "")
    return int(m.group(1)) if m else None


def guess_language(text: str) -> str:
    """Simple rules: script of the letters, then romanised-Hindi words."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3:
        return "other"
    devanagari = sum("ऀ" <= c <= "ॿ" for c in letters) / len(letters)
    latin = sum(c.isascii() for c in letters) / len(letters)
    if devanagari > 0.5:
        return "hi"
    if devanagari > 0.1:
        return "hinglish"                              # Hindi and English letters mixed
    if latin < 0.5:
        return "other"                                 # Tamil, Malayalam, Bengali, ...
    words = re.findall(r"[a-z]+", text.lower())
    hits = sum(w in HINGLISH_WORDS for w in words)
    if hits >= 3 or (hits >= 1 and len(words) < 8):
        return "hinglish"
    return "en"


def build_context(rows: list[dict]) -> None:
    question = {}                                      # thread -> first post text
    for r in rows:
        if r["source"] == "tradingqna" and r["source_detail"] == "question":
            question[thread_key(r)] = r["text"]
    reddit_post = {}                                   # Reddit thread -> the original post (title + text)
    for r in rows:
        if r["source"] == "reddit" and (r["source_detail"] or "").endswith("post"):
            reddit_post[reddit_thread(r)] = ((r.get("title") or "") + ". " + r["text"]).strip(". ")
    for r in rows:
        r["context"] = ""
        if r["source"] == "reddit" and (r["source_detail"] or "").endswith("comment"):
            q = reddit_post.get(reddit_thread(r), "") or (r.get("title") or "")
            r["context"] = q[:CONTEXT_CHARS] + ("..." if len(q) > CONTEXT_CHARS else "")
        elif r["source"] == "tradingqna" and r["source_detail"] == "reply":
            q = question.get(thread_key(r), "")
            r["context"] = q[:CONTEXT_CHARS] + ("..." if len(q) > CONTEXT_CHARS else "")
        elif r["source"] == "youtube":
            r["context"] = r.get("title") or ""


def reddit_thread(r: dict) -> str:
    m = re.search(r"/comments/([a-z0-9]+)", r.get("url") or "")
    return m.group(1) if m else (r.get("url") or "")


def thread_key(r: dict) -> str:
    return (r["url"] or "").rsplit("/", 1)[0]           # .../t/<slug>/<topic id>


# ---------- main ----------
def main() -> None:
    cfg = load_config()
    matches = build_keyword_matcher(cfg["keywords"])
    rows = load_raw()
    raw_counts = Counter(r["source"] for r in rows)

    drop_dup = find_duplicates(rows)
    survivors = [r for i, r in enumerate(rows) if i not in drop_dup]
    dropped = [{**r, "drop_reason": "duplicate"} for i, r in enumerate(rows) if i in drop_dup]
    after_dedupe = Counter(r["source"] for r in survivors)

    clean = []
    short_dropped = []
    for r in survivors:
        if len(r["text"].split()) < MIN_WORDS and not matches(r["text"]):
            short_dropped.append({**r, "drop_reason": "short"})
        else:
            clean.append(r)
    dropped += short_dropped

    build_context(clean)
    for r in clean:
        r["year"] = year_of(r["created_at"])
        r["language"] = guess_language(r["text"])

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in (("clean.jsonl", clean), ("dropped.jsonl", dropped)):
        with open(PROCESSED_DIR / name, "w", encoding="utf-8") as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    report(raw_counts, after_dedupe, clean, short_dropped)


def report(raw_counts, after_dedupe, clean, short_dropped) -> None:
    after_len = Counter(r["source"] for r in clean)
    by_year, by_lang = defaultdict(Counter), defaultdict(Counter)
    for r in clean:
        y = r["year"]
        by_year[r["source"]]["unknown" if y is None else ("2021+" if y >= MAIN_WINDOW_FROM else "older")] += 1
        by_lang[r["source"]][r["language"]] += 1

    print(f"\n{'source':<12}{'raw':>8}{'deduped':>9}{'final':>8}{'2021+':>8}{'older':>7}"
          f"{'en':>7}{'hi':>6}{'hingl':>7}{'other':>7}")
    totals = Counter()
    for s in sorted(raw_counts):
        row = [raw_counts[s], after_dedupe[s], after_len[s], by_year[s]["2021+"], by_year[s]["older"],
               by_lang[s]["en"], by_lang[s]["hi"], by_lang[s]["hinglish"], by_lang[s]["other"]]
        totals.update(dict(enumerate(row)))
        print(f"{s:<12}{row[0]:>8}{row[1]:>9}{row[2]:>8}{row[3]:>8}{row[4]:>7}"
              f"{row[5]:>7}{row[6]:>6}{row[7]:>7}{row[8]:>7}")
    t = [totals[i] for i in range(9)]
    print(f"{'TOTAL':<12}{t[0]:>8}{t[1]:>9}{t[2]:>8}{t[3]:>8}{t[4]:>7}{t[5]:>7}{t[6]:>6}{t[7]:>7}{t[8]:>7}")
    unknown = sum(c["unknown"] for c in by_year.values())
    if unknown:
        print(f"({unknown} items have no date)")
    print(f"\nSaved {len(clean)} items -> data/processed/clean.jsonl "
          f"(dropped items, with reasons -> data/processed/dropped.jsonl)")

    print("\n5 random dropped short items:")
    for r in random.sample(short_dropped, min(5, len(short_dropped))):
        print(f"  [{r['source']}] {r['text']!r}")


if __name__ == "__main__":
    main()


def staff_ids() -> set[str]:
    """TradingQ&A posts written by the platform's own staff / moderators / admins (flag fetched by
    `python -m collect.tradingqna_flags`). They are left out of every count and kept only as thread context."""
    f = RAW_DIR / "tradingqna_staff.json"
    if not f.exists():
        return set()
    return {i for i, v in json.loads(f.read_text()).items() if v}
