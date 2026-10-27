"""Compare t4 re-tags with the corrected answers for the 100 hand-checked posts (50 most severe + 50 random).

Gold = the answers after the human corrections (data/processed/retag_gold.json). Baseline = the original t3 AI tags.
Two measures of a wrong post:
  headline: the set of headline reasons (autopay / payment, confusing numbers, returns too small, expected faster growth) differs;
  strict:   the full set of reasons differs ('none' and 'other' are ignored).
"""
from __future__ import annotations

import json

from pipeline.clean import PROCESSED_DIR
from pipeline.retag import GOLD_FILE, HEADLINE, TEST_IDS_FILE, t4_file
from pipeline.tag import TAGGERS, load_jsonl

IGNORE = {"none", "other"}


def load_t4() -> dict[str, dict]:
    out = {}
    for name in TAGGERS:
        for r in load_jsonl(t4_file(name)):
            if r.get("status") == "ok" and r.get("tag_prompt_version") == "t4":
                out[r["id"]] = r
    return out


def load_t3() -> dict[str, dict]:
    out = {}
    for name, cfg in TAGGERS.items():
        for r in load_jsonl(PROCESSED_DIR / cfg["file"]):
            if r.get("status") == "ok" and r.get("tag_prompt_version") == "t3" and r.get("model") == cfg["model"]:
                out.setdefault(r["id"], r)
    return out


def mismatch(a: list[str], b: list[str]) -> tuple[bool, bool]:
    a, b = set(a), set(b)
    return (a & HEADLINE) != (b & HEADLINE), (a - IGNORE) != (b - IGNORE)


def measure(ids: list[str], gold: dict, recs: dict) -> dict:
    rows, head, strict, n = [], 0, 0, 0
    for i in ids:
        if i not in recs or i not in gold:
            continue
        n += 1
        t = recs[i]["tags"]["stated_triggers"]
        h, s = mismatch(t, gold[i]["triggers"])
        head, strict = head + h, strict + s
        if h or s:
            rows.append((i, t, gold[i]["triggers"], recs[i]["tags"].get("is_own_experience")))
    return {"n": n, "headline": head, "strict": strict, "rows": rows}


def report() -> None:
    ids = json.loads(TEST_IDS_FILE.read_text())
    gold = json.loads(GOLD_FILE.read_text())
    t4, t3 = load_t4(), load_t3()
    texts = {r["id"]: r for r in load_jsonl(PROCESSED_DIR / "clean.jsonl")}
    for label in ("random", "severe"):
        print(f"\n=== {label} 50 ===")
        both = [i for i in ids[label] if i in t4]
        for name, recs in (("t3 (old)", t3), ("t4 (new)", t4)):
            m = measure(both, gold, recs)
            print(f"{name}: {m['n']} posts compared | headline reasons wrong: {m['headline']} ({100 * m['headline'] / max(m['n'], 1):.0f}%)"
                  f" | any reason differs from corrected: {m['strict']} ({100 * m['strict'] / max(m['n'], 1):.0f}%)")
        m4 = measure(both, gold, t4)
        for i, new, want, own in m4["rows"]:
            print(f"   t4 differs: {i} own={own} t4={new} corrected={want} | {texts[i]['text'][:110]!r}")
        own = {}
        for i in both:
            own[t4[i]['tags'].get('is_own_experience')] = own.get(t4[i]['tags'].get('is_own_experience'), 0) + 1
        print(f"   is_own_experience: {own}")
        print(f"   missing from t4 so far: {len(ids[label]) - len(both)}")


if __name__ == "__main__":
    report()
