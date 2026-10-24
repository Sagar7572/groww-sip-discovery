"""Small AI passes used by the export step, kept apart from tagging so they cost almost nothing:

1. `label_problem_areas`: splits "Hard to use the app" into sub-themes and finds posts about problems getting money
   OUT (redemption, withdrawal, refund). Only posts that carry the app_experience reason, or whose text mentions
   redemption / withdrawal / refund words, are sent (about 100 posts, 5 requests).
2. `name_themes`: gives each automatically found theme a short plain-English name.

Both use the free Groq models only (gpt-oss-120b first, then qwen, then gpt-oss-20b), cache their answers in
data/processed/ so a later export reuses them, and never stop the export: if no model is reachable the posts stay
unlabelled and the themes keep their keyword names, and the dashboard says so.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

import requests
from dotenv import load_dotenv

from collect.common import ROOT
from pipeline.clean import PROCESSED_DIR

API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
AREA_FILE = PROCESSED_DIR / "problem_area_labels.jsonl"
THEME_NAME_FILE = PROCESSED_DIR / "theme_names.json"
AREA_PROMPT_VERSION = "pa1"
WAIT_MINUTES = 0          # set by `python -m pipeline.export --wait-for-ai N`: keep retrying for up to N minutes

# key -> (side, plain label, one-line definition shown to the model)
AREAS = {
    "autopay_setup": ("cause", "Autopay / mandate set-up and changes",
                      "setting up, changing or deleting autopay or a mandate; bank limits; double debits; bounce charges; SIP activation not working"),
    "sip_controls": ("cause", "Cannot pause, skip, edit or cancel a SIP easily",
                     "the person wants to pause, skip, change the amount or cancel a SIP and the app does not let them, or makes it hard"),
    "returns_display": ("cause", "Portfolio and returns shown wrongly or slowly",
                        "portfolio value, returns, NAV, XIRR or gains shown wrongly, confusingly, slowly or missing"),
    "app_bugs": ("cause", "App updates, bugs and slowness",
                 "app crashes, hangs, lag, login trouble, a bad update, interface or font complaints"),
    "support": ("cause", "Support is unreachable or unhelpful",
                "customer support about a SIP or the app that does not answer, does not fix, or is slow"),
    "missing_feature": ("cause", "A feature the person wants is missing",
                        "a request for something that does not exist yet (alerts, categories, switching, tracking, etc.)"),
    "exit_delay": ("after_stop", "Redemption, withdrawal or refund is slow or stuck",
                   "money requested out (redemption, withdrawal, refund) is slow, blocked or not received"),
    "exit_amount": ("after_stop", "Amount received differs from what the app showed",
                    "the amount that arrived after redeeming is different from what the app showed, or looks wrongly deducted"),
    "exit_hard": ("after_stop", "Cannot find or complete a redemption",
                  "no redemption option, the app hangs or fails while redeeming, or the process is confusing"),
    "not_a_problem": ("none", "Not a problem post",
                      "praise, a plain question, a reply from the platform's staff, or not about any of the problems above"),
}
EXIT_WORDS = re.compile(r"redemption|redeem|withdraw|refund|not (been )?credited", re.I)

AREA_SYSTEM = (
    "You label public posts about SIP / mutual fund apps in India. For each numbered post pick exactly ONE problem area "
    "that best describes the main complaint, or not_a_problem. Areas:\n"
    + "\n".join(f"- {k}: {v[2]}" for k, v in AREAS.items())
    + "\nRules: judge the post itself; a reply written by a platform's staff member is not_a_problem; praise is not_a_problem; "
      "a question about how to redeem is not_a_problem unless it complains. Never guess beyond the text. "
      'Answer ONLY with JSON: {"labels":[{"n":1,"area":"<key>"}, ...]} with one entry per post, in order.')

THEME_SYSTEM = (
    "You name groups of public posts about SIPs and mutual funds in India. For each group you get its most distinctive words, "
    "the reasons already tagged on its posts, and a few short example posts. Give each group a SHORT plain-English name "
    "(2 to 6 words) saying what the posts are about, such as 'Redemption money not received' or 'Beginners asking how SIPs work'. "
    "Describe the topic only: no advice, no judgement about funds, no fear or urgency words, no Hindi. "
    'Answer ONLY with JSON: {"names":[{"group":0,"name":"..."}, ...]} with one entry per group.')


def clip(text: str, words: int = 80) -> str:
    w = " ".join((text or "").split()).split()
    return " ".join(w[:words]) + (" ..." if len(w) > words else "")


def _ask(system: str, user: str) -> str | None:
    """Try the free Groq models in turn; return the JSON text, or None if none is reachable right now.
    With WAIT_MINUTES set, a round where every model is at its daily limit is retried every minute until time is up."""
    deadline = time.time() + 60 * WAIT_MINUTES
    while True:
        out = _ask_once(system, user)
        if out is not None or time.time() + 60 > deadline:
            return out
        print("  every free model is at its limit right now; trying again in a minute")
        time.sleep(60)


def _ask_once(system: str, user: str) -> str | None:
    load_dotenv(ROOT / ".env")
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    for model in MODELS:
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        for attempt in range(3):
            try:
                r = requests.post(API_URL, json=body, timeout=120, headers={"Authorization": f"Bearer {key}"})
            except requests.RequestException:
                time.sleep(5)
                continue
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code == 429:
                wait = float(r.headers.get("retry-after") or 0)
                if wait == 0 or wait > 90 or "per day" in r.text.lower():
                    break                       # daily allowance used up: try the next model
                time.sleep(wait + 1)
                continue
            if r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            break
    return None


def _parse(text: str | None) -> dict | None:
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# 1. problem areas
# ---------------------------------------------------------------------------
def candidates(posts: list[dict]) -> list[dict]:
    return [p for p in posts if "app_experience" in p["triggers"] or EXIT_WORDS.search(p["text"])]


def load_area_cache() -> dict:
    cache = {}
    if AREA_FILE.exists():
        for line in AREA_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("version") == AREA_PROMPT_VERSION:
                    cache[r["id"]] = r
    return cache


def label_problem_areas(posts: list[dict], batch_size: int = 20) -> tuple[dict, dict]:
    """Returns ({post id: area key}, info). Posts that could not be labelled are simply missing from the dict."""
    cache = load_area_cache()
    todo = [p for p in candidates(posts) if p["id"] not in cache]
    done = fail = 0
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        user = "Posts:\n" + "\n".join(f"[{n}] ({p['source']}) {clip(p['text'])}" for n, p in enumerate(batch, 1))
        out = _parse(_ask(AREA_SYSTEM, user))
        labels = (out or {}).get("labels") or []
        # same lesson as in tag.py: trust the model's numbers only when they are valid and distinct, else use order
        numbers = [item.get("n") if isinstance(item, dict) else None for item in labels]
        use_order = len(labels) == len(batch) and sorted(map(str, numbers)) != sorted(str(n) for n in range(1, len(batch) + 1))
        got = {}
        for pos, item in enumerate(labels, 1):
            area = item.get("area") if isinstance(item, dict) else None
            try:
                n = pos if use_order else int(item["n"])
            except (KeyError, TypeError, ValueError):
                continue
            if 1 <= n <= len(batch) and area in AREAS:
                got[n] = area
        with open(AREA_FILE, "a", encoding="utf-8") as f:
            for n, p in enumerate(batch, 1):
                if n in got:
                    f.write(json.dumps({"id": p["id"], "area": got[n], "version": AREA_PROMPT_VERSION}) + "\n")
                    cache[p["id"]] = {"id": p["id"], "area": got[n]}
                    done += 1
                else:
                    fail += 1
    cand = candidates(posts)
    areas = {p["id"]: cache[p["id"]]["area"] for p in cand if p["id"] in cache}
    return areas, {"candidates": len(cand), "labelled": len(areas), "new_this_run": done, "failed_this_run": fail}


# ---------------------------------------------------------------------------
# 2. theme names
# ---------------------------------------------------------------------------
def name_themes(groups: list[dict]) -> dict[int, str]:
    """groups: [{group, keywords, triggers, examples}] -> {group: plain-English name}. Cached by group membership."""
    cache = json.loads(THEME_NAME_FILE.read_text()) if THEME_NAME_FILE.exists() else {}
    keys = {g["group"]: hashlib.md5("|".join(sorted(g["member_ids"])).encode()).hexdigest()[:12] for g in groups}
    names = {g: cache[k] for g, k in keys.items() if k in cache}
    missing = [g for g in groups if g["group"] not in names]
    if missing:
        user = "Groups:\n" + "\n".join(
            f"Group {g['group']}: words: {', '.join(g['keywords'])}; tagged reasons: {', '.join(g['triggers']) or 'none'}\n"
            + "\n".join(f"   - {clip(t, 35)}" for t in g["examples"]) for g in missing)
        out = _parse(_ask(THEME_SYSTEM, user))
        for item in (out or {}).get("names") or []:
            try:
                gid, name = int(item["group"]), str(item["name"]).strip().strip(".")
            except (KeyError, TypeError, ValueError):
                continue
            if gid in keys and 2 <= len(name.split()) <= 8 and gid not in names:
                names[gid] = name
                cache[keys[gid]] = name
        THEME_NAME_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return names
