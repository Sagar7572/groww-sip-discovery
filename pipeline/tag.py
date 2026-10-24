"""AI tagging: fill in the codebook (codebook.yaml) for every item the relevance filter kept.

Model: openai/gpt-oss-120b on Groq's free tier (its own daily allowance, separate from the filter's).
Input: items marked yes / unsure in data/processed/relevance.jsonl, with their context, 20 per request.
Output: data/processed/tags.jsonl, one line per item, saved after every request (resumable).

The whole codebook goes into one fixed system prompt that is identical in every request and placed
first, so Groq's prompt caching can apply. The model answers in compact JSON with short keys and
numbered answer codes; this file maps them back to the full codebook names before saving.

Usage (from the project folder):
    python -m pipeline.tag --pilot 50      # 50 items spread across sources, then a report
    python -m pipeline.tag --report        # print the pilot report again
    python -m pipeline.tag --all           # full run (not used yet; resumable)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import requests
import yaml
from rapidfuzz.fuzz import partial_ratio_alignment
from dotenv import load_dotenv

from collect.common import ROOT, build_keyword_matcher
from pipeline.clean import PROCESSED_DIR, staff_ids
from pipeline.filter import API_URL, LONG_WAIT_SECONDS, DailyLimit, RESULT_FILE, parse_duration

# Two taggers, each with its own Groq allowance and its own output file (so two processes never write
# the same file). The tagger is chosen on the command line with --tagger; the globals below are set once.
TAGGERS = {
    "gpt-oss-120b": {"model": "openai/gpt-oss-120b", "effort": "low", "file": "tags.jsonl"},
    "qwen": {"model": "qwen/qwen3.8-27b", "effort": "none", "file": "tags_qwen.jsonl"},
}
TAGGER = "gpt-oss-120b"
MODEL = TAGGERS[TAGGER]["model"]
REASONING_EFFORT = TAGGERS[TAGGER]["effort"]


def use_tagger(name: str) -> None:
    global TAGGER, MODEL, REASONING_EFFORT, TAGS_FILE
    TAGGER, MODEL = name, TAGGERS[name]["model"]
    REASONING_EFFORT = TAGGERS[name]["effort"]
    TAGS_FILE = PROCESSED_DIR / TAGGERS[name]["file"]


def tagger_of(item_id: str) -> str:
    """Fixed random split of items between the two taggers, so neither model gets a special kind of item."""
    return "gpt-oss-120b" if int(hashlib.sha1(("tagger-split-v1" + item_id).encode()).hexdigest(), 16) % 2 == 0 else "qwen"


QUOTE_MIN_SCORE = 80           # a repaired quote scoring below this is flagged and never shown to users
TAG_PROMPT_VERSION = "t3"      # t1: early "rel 0" exit (bad); t2: no exit but too many "unclear"; see Entry 6
BATCH_SIZE = 20
MAX_TEXT_WORDS = 250        # tagging needs more of the text than the relevance check did
MAX_CONTEXT_WORDS = 40
PILOT_QUOTAS = {"play_store": 18, "tradingqna": 14, "youtube": 10, "app_store": 8}
PILOT_SEED = 11
YOUTUBE_SAMPLE = 800           # random 2021+ YouTube items to tag (the sample scope)
YOUTUBE_COHORT = 1100          # random cohort drawn first, since the filter drops about a quarter
MAIN_WINDOW_FROM = 2021
RUNS_FILE = PROCESSED_DIR / "tag_runs.jsonl"
# Tagged first: items that talk about stopping, pausing, failing, losing (inflections added).
PRIORITY_WORDS = ["stop", "stopped", "stopping", "pause", "paused", "pausing", "cancel", "cancelled",
                  "canceled", "cancelling", "band", "skip", "skipped", "skipping", "fail", "failed",
                  "failure", "bounce", "bounced", "mandate", "autopay", "auto pay", "loss", "negative",
                  "red", "redeem", "redeemed", "redeeming", "redemption"]

CLEAN_FILE = PROCESSED_DIR / "clean.jsonl"
TAGS_FILE = PROCESSED_DIR / TAGGERS[TAGGER]["file"]
PILOT_FILE = PROCESSED_DIR / "tag_pilot_ids.json"
CODEBOOK_FILE = ROOT / "codebook.yaml"

# Short output keys for each codebook field (segment_signals is a group of four).
SHORT = {"is_relevant": "rel", "investor_type": "it", "journey_stage": "js", "sip_action": "sa",
         "lapse_type": "lt", "stated_triggers": "tr", "underlying_reason": "ur",
         "checking_behaviour": "cb", "what_they_check": "wc", "emotion": "em",
         "outside_app_actions": "oa", "unmet_need": "un", "severity": "sv",
         "evidence_quote": "q", "confidence": "cf"}
SEGMENT_SHORT = {"income_stability": "inc", "age_band": "age", "money_source": "src",
                 "influenced_by": "inf"}
TEXT_FIELDS = ("underlying_reason", "unmet_need", "evidence_quote")


# ---------- codebook -> prompt, code maps ----------
def load_codebook() -> dict:
    with open(CODEBOOK_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def option_names(spec) -> list[str]:
    """Option names for a codebook field (options are written as a dict or a list)."""
    opts = spec["options"] if isinstance(spec, dict) else spec
    return [str(o) for o in (opts.keys() if isinstance(opts, dict) else opts)]


def build_maps(cb: dict) -> dict:
    """For each short key: field name, kind (one / many / text / number) and numbered options."""
    maps = {}
    for field, spec in cb["fields"].items():
        if field == "is_relevant":
            maps["rel"] = {"field": field, "kind": "bool"}
        elif spec["type"] == "group":
            for sub, short in SEGMENT_SHORT.items():
                names = option_names(spec[sub])
                numbered = {n: o for n, o in enumerate([o for o in names if o != "unclear"], 1)}
                maps[short] = {"field": sub, "kind": "one", "group": field,
                               "options": {0: "unclear", **numbered}}   # unclear is 0 in every segment field
        elif spec["type"] in ("one", "many"):
            maps[SHORT[field]] = {"field": field, "kind": spec["type"],
                                  "options": dict(enumerate(option_names(spec), 1))}
        elif spec["type"] == "text":
            maps[SHORT[field]] = {"field": field, "kind": "text"}
        else:
            maps[SHORT[field]] = {"field": field, "kind": "number"}
    return maps


def describe(spec, name: str) -> str:
    opts = spec["options"] if isinstance(spec, dict) else spec
    return str(opts[name]) if isinstance(opts, dict) and name in opts else ""


def build_system_prompt(cb: dict, maps: dict) -> str:
    """The fixed prompt: the whole codebook with numbered answer codes, then worked examples."""
    lines = [
        "You tag public posts about SIPs and mutual fund investing in India for a research project on",
        "why first-time investors stop their SIP. Fill in the codebook below for every numbered item.",
        "",
        "RULES",
        "- Tag what the text states OR plainly implies (a loss reported after 23 months implies",
        "  underwhelming_returns and disappointment; a question about where to find an investment implies",
        "  confusion). Use unclear / none / not_mentioned only when the text gives nothing to go on. Do not",
        "  invent details that neither appear in the text nor follow plainly from it.",
        "- Some items have a context line (the forum question or video title). It only helps you read a",
        "  short reply; tag what the item itself says.",
        "- Text may be English, Hindi or Hinglish. Write your text answers in English.",
        "- ALWAYS fill every field for every item, in the same compact format. The relevance filter has",
        "  already kept these items, so tag them all; rel is only a flag (see its wording below).",
        "- evidence_quote (q) must be ONE continuous span copied EXACTLY, character for character, from the",
        "  item text (not from the context line), with no '...' joining pieces, at most 25 words.",
        "- underlying_reason (ur) must be based only on what the text says; write \"unclear\" if unsupported.",
        "  Do not mention SIP, mandate or returns in ur unless the text does.",
        "",
        f"CODEBOOK (version {cb.get('version')}). Answer each field with its short key and the NUMBER",
        "of the option. Fields marked MANY take a list of numbers.",
    ]
    for field, spec in cb["fields"].items():
        if spec["type"] == "group":
            lines.append(f"\n{field} (note: {spec.get('note', '')})")
            for sub, short in SEGMENT_SHORT.items():
                opts = maps[short]["options"]
                lines.append(f"  {short} = {sub}: " + ", ".join(f"{n}={o}" for n, o in opts.items()))
            lines.append("  (in these four, 0 always means unclear)")
            continue
        short = SHORT[field]
        q = " ".join(str(spec.get("question", "")).split())
        if spec["type"] in ("one", "many"):
            tag = "MANY" if spec["type"] == "many" else "ONE"
            lines.append(f"\n{short} = {field} [{tag}] {q}")
            for n, o in maps[short]["options"].items():
                d = " ".join(describe(spec, o).split())
                lines.append(f"  {n}={o}" + (f": {d}" if d else ""))
        elif spec["type"] == "boolean":
            lines.append(f"\n{short} = {field} [1 or 0] {q}")
        else:
            lines.append(f"\n{short} = {field} [{spec['type']}] {q}")
    lines += ["", "WORKED EXAMPLES (input text -> answer):"]
    lines.append("(In real answers, i is the item's own number from the list. The examples are single items, shown as i = 1.)")
    for ex in cb["examples"]:
        lines.append(f"- {ex['text']!r}\n  -> {json.dumps(example_answer(ex, maps), ensure_ascii=False)}")
    lines += ["", "Answer with JSON only: {\"results\": [{\"i\": 1, \"rel\": 1, ...}, {\"i\": 2, ...}, ...]}, exactly one entry per item, in order, numbered i = 1, 2, 3 ... up to the last item."]
    return "\n".join(lines)


def example_answer(ex: dict, maps: dict) -> dict:
    """Turn a codebook example into the compact answer format, filling gaps with 'not stated' codes."""
    tags = ex["tags"]
    out = {"i": 1, "rel": 1 if tags.get("is_relevant", True) else 0}
    flat = {**{k: v for k, v in tags.items() if k != "segment_signals"}, **tags.get("segment_signals", {})}
    for short, m in maps.items():
        if short == "rel":
            continue
        field, value = m["field"], flat.get(m["field"])
        if m["kind"] in ("one", "many"):
            names = {name: n for n, name in m["options"].items()}
            if value is None:
                value = [default_option(names)] if m["kind"] == "many" else default_option(names)
            if m["kind"] == "many":
                out[short] = [names[v] for v in (value if isinstance(value, list) else [value])]
            else:
                out[short] = names[str(value)]
        elif m["kind"] == "text":
            out[short] = value or ("unclear" if field == "underlying_reason" else
                                   "none stated" if field == "unmet_need" else
                                   " ".join(ex["text"].split()[:25]))
        else:
            out[short] = value if value is not None else (1 if field == "severity" else 0.8)
    if out["rel"] == 0:
        out["ur"], out["un"], out["cf"] = "unclear", "none stated", 0.9
    return out


def default_option(names: dict) -> str:
    for candidate in ("unclear", "none", "not_mentioned", "not_applicable", "none_mentioned"):
        if candidate in names:
            return candidate
    return next(iter(names))


# ---------- calling Groq ----------
def clip_words(text: str, limit: int) -> str:
    words = text.split()
    return " ".join(words[:limit]) + (" ..." if len(words) > limit else "")


def build_user_prompt(batch: list[dict]) -> str:
    lines = []
    for n, r in enumerate(batch, 1):
        ctx = clip_words((r.get("context") or "").replace("\n", " "), MAX_CONTEXT_WORDS)
        line = f"[{n}] ({r['source']}"
        if r["source"] == "play_store" or r["source"] == "app_store":
            line += f", rating {r.get('rating')}"
        line += ")"
        if ctx:
            line += f" context: {ctx}\n    "
        line += " text: " + clip_words(r["text"], MAX_TEXT_WORDS)
        lines.append(line)
    return "Items:\n" + "\n".join(lines)


class RequestTooLarge(Exception):
    """Groq rejected the request as larger than the tokens-per-minute limit (HTTP 413)."""


class TagClient:
    def __init__(self, system_prompt: str) -> None:
        load_dotenv(ROOT / ".env")
        self.key = os.getenv("GROQ_API_KEY")
        if not self.key:
            sys.exit("No GROQ_API_KEY in .env")
        self.system_prompt = system_prompt
        self.tokens_used = self.prompt_tokens = self.cached_tokens = self.completion_tokens = 0
        self.requests_made = 0
        self.usage_example: dict = {}
        self.limits: dict[str, str] = {}

    def chat(self, user_prompt: str) -> str:
        body = {"model": MODEL, "temperature": 0, "reasoning_effort": REASONING_EFFORT,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": self.system_prompt},
                             {"role": "user", "content": user_prompt}]}
        for attempt in range(8):
            try:
                resp = requests.post(API_URL, json=body, timeout=180,
                                     headers={"Authorization": f"Bearer {self.key}"})
            except requests.RequestException as exc:
                print(f"    network problem ({type(exc).__name__}); retrying in 10s")
                time.sleep(10)
                continue
            self.requests_made += 1
            h = resp.headers
            for name in ("limit-requests", "limit-tokens"):
                if h.get("x-ratelimit-" + name):
                    self.limits[name] = h["x-ratelimit-" + name]
            if resp.status_code == 429:
                wait = float(h.get("retry-after") or 0) or parse_duration(h.get("x-ratelimit-reset-requests"))
                wait = max(wait, 5) + 1
                if wait > LONG_WAIT_SECONDS or "per day" in resp.text.lower():
                    when = f"about {wait / 3600:.1f} hours" if wait > 3600 else f"about {wait / 60:.0f} minutes"
                    raise DailyLimit(f"Groq's daily allowance for {MODEL} is used up (it resets in {when}).", wait=wait)
                print(f"    rate limited; waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code == 413:
                raise RequestTooLarge(resp.text[:200])
            if resp.status_code != 200:
                sys.exit(f"Groq error {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            usage = data.get("usage", {})
            self.usage_example = usage
            self.tokens_used += usage.get("total_tokens", 0)
            self.prompt_tokens += usage.get("prompt_tokens", 0)
            self.completion_tokens += usage.get("completion_tokens", 0)
            self.cached_tokens += (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
            self._pace(h)
            return data["choices"][0]["message"]["content"]
        raise DailyLimit("Groq kept refusing or failing after 8 tries; try again later.")

    def _pace(self, h) -> None:
        """If the headers say we are nearly out of requests or tokens, wait for the reset."""
        wait = 0.0
        if int(h.get("x-ratelimit-remaining-requests") or 99) <= 1:
            wait = max(wait, parse_duration(h.get("x-ratelimit-reset-requests")))
        if int(h.get("x-ratelimit-remaining-tokens") or 99999) < 7000:    # one request needs about 6-7K
            wait = max(wait, parse_duration(h.get("x-ratelimit-reset-tokens")))
        if 0 < wait <= LONG_WAIT_SECONDS:
            print(f"    near the limit; pausing {wait + 1:.0f}s")
            time.sleep(wait + 1)


# ---------- validating answers ----------
def decode_item(raw: dict, maps: dict) -> tuple[dict | None, str]:
    """Turn one compact answer into full codebook names. Returns (tags, "") or (None, problem)."""
    if raw.get("rel") not in (0, "0", False, 1, "1", True):
        return None, "rel missing or not 0/1"
    tags: dict = {"is_relevant": raw["rel"] in (1, "1", True)}
    for short, m in maps.items():
        if short == "rel":
            continue
        if short not in raw:
            return None, f"missing field {m['field']}"
        v = raw[short]
        if m["kind"] == "one":
            try:
                value = m["options"][int(v)]
            except (KeyError, TypeError, ValueError):
                return None, f"bad code {v!r} for {m['field']}"
            if m["field"] == "severity":
                value = int(value)
        elif m["kind"] == "many":
            if not isinstance(v, list) or not v:
                return None, f"{m['field']} must be a non-empty list"
            try:
                value = [m["options"][int(x)] for x in v]
            except (KeyError, TypeError, ValueError):
                return None, f"bad code in {m['field']}: {v!r}"
        elif m["kind"] == "text":
            if not isinstance(v, str) or not v.strip():
                return None, f"{m['field']} is empty"
            value = " ".join(v.split())
        else:
            try:
                value = float(v)
            except (TypeError, ValueError):
                return None, f"{m['field']} is not a number"
            if m["field"] == "confidence" and not 0 <= value <= 1:
                return None, "confidence outside 0-1"
            if m["field"] == "severity":
                if value not in (1, 2, 3):
                    return None, "severity not 1, 2 or 3"
                value = int(value)
        if m.get("group"):
            tags.setdefault(m["group"], {})[m["field"]] = value
        else:
            tags[m["field"]] = value
    return tags, ""


def tag_batch(client: TagClient, batch: list[dict], maps: dict) -> dict[int, tuple[dict | None, str]]:
    """{item number: (tags, problem)} for every item in the batch."""
    try:
        reply = client.chat(build_user_prompt(batch))
    except RequestTooLarge:                       # long texts: split the batch in half and try again
        if len(batch) == 1:
            return {1: (None, "single item too large for the request limit")}
        half = len(batch) // 2
        first, second = tag_batch(client, batch[:half], maps), tag_batch(client, batch[half:], maps)
        return {**first, **{n + half: v for n, v in second.items()}}
    try:
        entries = json.loads(reply)["results"]
    except (json.JSONDecodeError, KeyError, TypeError):
        entries = []
    out = {}
    entries = entries if isinstance(entries, list) else []
    numbers = []
    for e in entries:
        try:
            numbers.append(int(e["i"]))
        except (KeyError, TypeError, ValueError):
            numbers.append(None)
    # Use the model's item numbers when they are distinct and inside 1..N (an answer for only some items
    # is fine: the missing ones are retried). If they are not usable (for example every entry says
    # "i": 1), fall back to the order of the answers, which is only safe with exactly one per item.
    usable = None not in numbers and len(set(numbers)) == len(numbers) and all(1 <= n <= len(batch) for n in numbers)
    if usable:
        positions = dict(zip(numbers, entries))
    elif len(entries) == len(batch):
        positions = dict(enumerate(entries, 1))
    else:
        positions = {}
    for n, e in positions.items():
        out[n] = decode_item(e, maps)
    for n in range(1, len(batch) + 1):
        out.setdefault(n, (None, "no answer for this item"))
    return out


# ---------- free quality checks (plain code) ----------
def norm(text: str) -> str:
    return " ".join(text.split())


def quote_is_exact(quote: str, text: str) -> bool:
    return norm(quote).strip(" .…") in norm(text)


def repair_quote(quote: str, text: str) -> tuple[str, float, str]:
    """Fix a quote that is not an exact substring. Returns (span, score 0-100, method).
    1. If the quote joins pieces with '...', keep the longest piece that IS in the text (score 100).
    2. Otherwise take the closest matching span of the text (rapidfuzz), cut to whole words, 25 words max."""
    t = norm(text)
    if not t or not norm(quote):
        return "", 0.0, "none"
    pieces = [norm(x).strip(" .") for x in re.split(r"\.\.\.|…", quote)]
    exact = [x for x in pieces if x and x in t]
    if exact:
        return " ".join(max(exact, key=len).split()[:25]), 100.0, "longest_exact_piece"
    q = norm(quote).replace("...", " ").replace("…", " ")
    m = partial_ratio_alignment(q, t)
    start, end = m.dest_start, m.dest_end
    while start > 0 and not t[start - 1].isspace():
        start -= 1
    while end < len(t) and not t[end].isspace():
        end += 1
    return " ".join(t[start:end].split()[:25]), round(m.score, 1), "closest_span"


def quote_fields(tags: dict, text: str, context: str) -> dict:
    """Quote check and repair for one tagged item. quote_display is None when the quote is unreliable;
    anything user-facing must show quote_display, never tags['evidence_quote'] or quote_original."""
    q = tags.get("evidence_quote")
    if q is None:
        return {}
    out = {"quote_exact": quote_is_exact(q, text), "quote_repaired": False}
    if out["quote_exact"]:
        out.update(quote_display=q, quote_unreliable=False, needs_review=False)
        return out
    span, score, method = repair_quote(q, text)
    unreliable = score < QUOTE_MIN_SCORE
    tags["evidence_quote"] = span
    out.update(quote_repaired=True, quote_original=q, quote_from_context=quote_is_exact(q, context),
               quote_repair_score=score, quote_repair_method=method, quote_unreliable=unreliable,
               quote_display=None if unreliable else span, needs_review=unreliable)
    return out


UNSUPPORTED_RE = re.compile(r"\b(sips?|mandates?|auto-?pay|returns?)\b", re.I)


def reason_unsupported(reason: str, text: str) -> bool:
    """True if underlying_reason mentions SIP / mandate / returns but the item text does not."""
    return bool(UNSUPPORTED_RE.search(reason)) and not UNSUPPORTED_RE.search(text)


# ---------- files and run ----------
def load_jsonl(path) -> list[dict]:
    rows = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass                  # a line still being written by another running job
    return rows


def results_for(version: str) -> dict[str, dict]:
    """Relevance results of one prompt version (safe to read while the filter is still writing)."""
    return {r["id"]: r for r in load_jsonl(RESULT_FILE) if r.get("prompt_version") == version}


def tagged_ids() -> set[str]:
    return {r["id"] for r in load_jsonl(TAGS_FILE)
            if r.get("tag_prompt_version") == TAG_PROMPT_VERSION and r.get("model") == MODEL}


def relevant_items() -> list[dict]:
    """Clean items the filter marked yes / unsure (latest prompt version only), with the label."""
    clean = {r["id"]: r for r in load_jsonl(CLEAN_FILE)}
    items = []
    for i, rel in results_for("v3").items():
        if rel["relevant"] in ("yes", "unsure") and i in clean:
            items.append({**clean[i], "relevance": rel["relevant"]})
    return items


def has_priority_word(text: str) -> bool:
    return bool(_priority_match(text))


_priority_match = build_keyword_matcher(PRIORITY_WORDS)


def sample_items(tagger: str | None = None) -> list[dict]:
    """The agreed sample, in tagging order.
    Scope: every TradingQ&A, App Store and Play Store item, plus 800 random 2021+ YouTube items (a fixed
    random cohort is drawn first from all 2021+ YouTube items).
    Order: 1) priority items (stop / pause / cancel / ... words) taken straight from the clean data, without
    waiting for the filter, because the tag prompt flags relevance itself; 2) then every other item the
    filter has kept (yes / unsure) so far. If a tagger name is given, only that tagger's half of the items
    (fixed random split) is returned."""
    clean = load_jsonl(CLEAN_FILE)
    labels = results_for("v3")
    clean_yt = sorted((r for r in clean if r["source"] == "youtube" and (r.get("year") or 0) >= MAIN_WINDOW_FROM),
                      key=lambda r: hashlib.sha1(("yt-sample-v1" + r["id"]).encode()).hexdigest())
    cohort_ids = {r["id"] for r in clean_yt[:YOUTUBE_COHORT]}
    staff = staff_ids()      # the platform's own replies are not investors: never tagged, never counted
    in_scope = [r for r in clean if (r["source"] != "youtube" or r["id"] in cohort_ids) and r["id"] not in staff]
    for r in in_scope:
        r["relevance"] = labels[r["id"]]["relevant"] if r["id"] in labels else "pending"

    # Reddit items come first of all (the tag prompt flags relevance itself, so they do not wait for the quick filter)
    priority = [r for r in in_scope if r["source"] == "reddit" or has_priority_word(r["text"])]
    taken = {r["id"] for r in priority}
    rest = [r for r in in_scope if r["id"] not in taken and r["relevance"] in ("yes", "unsure")]
    youtube_room = YOUTUBE_SAMPLE - sum(r["source"] == "youtube" for r in priority)
    rest_yt = [r for r in rest if r["source"] == "youtube"][:max(youtube_room, 0)]
    items = priority + [r for r in rest if r["source"] != "youtube"] + rest_yt

    def order(r):
        return (r["source"] != "reddit", r["id"] not in taken, (r.get("year") or 0) < MAIN_WINDOW_FROM, -(r.get("year") or 0))
    items.sort(key=order)
    return [r for r in items if tagger is None or tagger_of(r["id"]) == tagger]


def run(items: list[dict], cb: dict, maps: dict) -> TagClient:
    client = TagClient(build_system_prompt(cb, maps))
    done = tagged_ids()
    todo = [r for r in items if r["id"] not in done]
    print(f"{len(items)} items selected, {len(items) - len(todo)} already tagged, {len(todo)} to do")
    started, saved = time.time(), 0
    client.failed = 0
    client.stopped, client.stop_wait, client.interrupted = False, None, False
    try:
        for start in range(0, len(todo), BATCH_SIZE):
            batch = todo[start:start + BATCH_SIZE]
            answers = tag_batch(client, batch, maps)
            bad = [n for n, (t, _) in answers.items() if t is None]
            if bad:                                           # retry the malformed items once
                retry_batch = [batch[n - 1] for n in bad]
                retry = tag_batch(client, retry_batch, maps)
                for k, n in enumerate(bad, 1):
                    answers[n] = retry[k]
            with open(TAGS_FILE, "a", encoding="utf-8") as f:
                for n, r in enumerate(batch, 1):
                    tags, problem = answers[n]
                    rec = {"id": r["id"], "source": r["source"], "relevance": r["relevance"],
                           "model": MODEL, "tagged_by": TAGGER, "tag_prompt_version": TAG_PROMPT_VERSION,
                           "codebook_version": cb.get("version"),
                           "status": "ok" if tags else "failed",
                           "tagged_at": datetime.now(timezone.utc).isoformat()}
                    if tags:
                        rec["tags"] = tags
                        rec.update(quote_fields(tags, r["text"], r.get("context") or ""))
                        ur = tags.get("underlying_reason")
                        rec["reason_unsupported"] = None if ur is None else reason_unsupported(ur, r["text"])
                    else:
                        rec["failed_reason"] = problem
                        client.failed += 1
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    saved += 1
            if (start // BATCH_SIZE) % 10 == 9:
                print(f"  {saved}/{len(todo)} tagged, {client.tokens_used:,} tokens so far")
    except DailyLimit as exc:
        client.stopped, client.stop_wait = True, exc.wait
        print(f"\nSTOPPED ({TAGGER}): {exc}")
    except KeyboardInterrupt:
        client.stopped, client.interrupted = True, True
        print("\nSTOPPED by you (Ctrl+C).")
    else:
        print("\nFinished.")
    client.elapsed = time.time() - started
    client.saved = saved
    with open(RUNS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"tag_prompt_version": TAG_PROMPT_VERSION, "model": MODEL, "items": saved,
                            "tokens": client.tokens_used, "prompt_tokens": client.prompt_tokens,
                            "cached_tokens": client.cached_tokens, "requests": client.requests_made,
                            "at": datetime.now(timezone.utc).isoformat()}) + "\n")
    left = [r for r in items if r["id"] not in tagged_ids()]
    print(f"This run: {saved} items saved ({client.failed} failed), {client.tokens_used:,} tokens, "
          f"{client.requests_made} requests.")
    print(f"Overall: {len(items) - len(left)} of {len(items)} selected items tagged, {len(left)} left."
          + (" Run the same command again to continue." if left else ""))
    return client


def pick_pilot(items: list[dict], total: int) -> list[dict]:
    rng = random.Random(PILOT_SEED)
    by_source = defaultdict(list)
    for r in items:
        by_source[r["source"]].append(r)
    scale = total / sum(PILOT_QUOTAS.values())
    picked = []
    for source, quota in PILOT_QUOTAS.items():
        pool = by_source.get(source, [])
        picked += rng.sample(pool, min(len(pool), round(quota * scale)))
    rng.shuffle(picked)
    return picked


# ---------- pilot report ----------
def short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def report(ids: list[str], client: TagClient | None, cb: dict) -> None:
    clean = {r["id"]: r for r in load_jsonl(CLEAN_FILE)}
    recs = {r["id"]: r for r in load_jsonl(TAGS_FILE)
            if r["id"] in set(ids) and r.get("model") == MODEL and r.get("tag_prompt_version") == TAG_PROMPT_VERSION}
    ok = [r for r in recs.values() if r["status"] == "ok"]
    rel = [r for r in ok if r["tags"]["is_relevant"]]
    failed = [r for r in recs.values() if r["status"] == "failed"]
    print(f"\n{len(recs)} items tagged: {len(rel)} relevant, {len(ok) - len(rel)} judged not relevant "
          f"(second look), {len(failed)} failed.")
    for r in failed:
        print(f"  failed: {r['id']}: {r['failed_reason']}")

    rng = random.Random(3)
    print("\n8 tagged items:\n")
    for r in rng.sample(rel, min(8, len(rel))):
        t, seg = r["tags"], r["tags"]["segment_signals"]
        print(f"[{r['source']}] {short(clean[r['id']]['text'], 110)!r}")
        print(f"   stage={t['journey_stage']} | sip_action={t['sip_action']} | lapse={t['lapse_type']} | "
              f"conf={t['confidence']} | severity={t['severity']}")
        print(f"   triggers={', '.join(t['stated_triggers'])} | emotion={t['emotion']}")
        print(f"   reason: {short(t['underlying_reason'], 110)}")
        print(f"   segment: income={seg['income_stability']}, age={seg['age_band']}, "
              f"money={seg['money_source']}, influenced_by={seg['influenced_by']}\n")

    lapse = Counter(r["tags"]["lapse_type"] for r in rel)
    trig = Counter(x for r in rel for x in r["tags"]["stated_triggers"])
    print("lapse_type counts:", dict(lapse.most_common()))
    print("top triggers:", ", ".join(f"{k} ({v})" for k, v in trig.most_common(8)))

    quotes = [r for r in rel if r["quote_exact"] is not None]
    bad_q = [r for r in quotes if not r["quote_exact"]]
    print(f"\nQuote check: {len(bad_q)} of {len(quotes)} evidence quotes are not an exact substring "
          f"of the text ({100 * len(bad_q) / max(len(quotes), 1):.0f}%).")
    for r in bad_q[:4]:
        print(f"   quote {short(r['tags']['evidence_quote'], 80)!r}  | text {short(clean[r['id']]['text'], 80)!r}")
    bad_r = [r for r in rel if r["reason_unsupported"]]
    print(f"Reason check: {len(bad_r)} of {len(rel)} underlying_reasons mention SIP / mandate / returns "
          f"but the text does not.")
    for r in bad_r[:4]:
        print(f"   reason {short(r['tags']['underlying_reason'], 90)!r}  | text {short(clean[r['id']]['text'], 80)!r}")

    if client and client.saved:
        n = client.saved
        print(f"\nTokens: {client.tokens_used:,} total for {n} items = {client.tokens_used / n:.0f} per item "
              f"({client.prompt_tokens / n:.0f} prompt, {client.completion_tokens / n:.0f} output), "
              f"{client.requests_made} requests, {client.elapsed:.0f}s.")
        print(f"Cached tokens reported by Groq: {client.cached_tokens:,} of {client.prompt_tokens:,} prompt tokens."
              f" Usage block of the last request: {json.dumps(client.usage_example)}")
        print(f"System prompt length: {len(client.system_prompt):,} characters.")
        estimate(client.tokens_used / n)


def estimate(tokens_per_item: float) -> None:
    """Days to tag everything relevant vs a sample, from the filter's results so far."""
    clean = load_jsonl(CLEAN_FILE)
    total = Counter(r["source"] for r in clean)
    seen, kept = Counter(), Counter()
    for r in results_for("v3").values():
        seen[r["source"]] += 1
        kept[r["source"]] += r["relevant"] in ("yes", "unsure")
    est, note = {}, []
    for s in total:
        rate = kept[s] / seen[s] if seen[s] else 0.6
        est[s] = round(total[s] * rate)
        note.append(f"{s}: {kept[s]}/{seen[s]} kept so far ({rate:.0%}) -> about {est[s]} of {total[s]}")
    day_tokens = 200_000
    per_day = day_tokens / tokens_per_item
    all_items = sum(est.values())
    sample = est.get("tradingqna", 0) + est.get("app_store", 0) + est.get("play_store", 0) + min(800, est.get("youtube", 0))
    print("\nEstimated relevant items (filter results so far, rates may still shift):")
    for line in note:
        print("  " + line)
    print(f"At {tokens_per_item:.0f} tokens per item and 200K tokens per day: about {per_day:,.0f} items a day.")
    print(f"  All relevant items (~{all_items:,}): about {all_items / per_day:.1f} days.")
    print(f"  Sample (all TradingQ&A + app stores + ~800 YouTube = ~{sample:,}): about {sample / per_day:.1f} days.")


UNCLEAR = {"unclear", "none", "not_mentioned", "not_applicable", "none_mentioned"}


def unclear_share(recs: list[dict]) -> dict[str, float]:
    """Share of relevant items per field whose answer is an 'unclear / none' option."""
    counts, total = Counter(), 0
    for r in recs:
        t = r["tags"]
        total += 1
        flat = {**{k: v for k, v in t.items() if k != "segment_signals"}, **t.get("segment_signals", {})}
        for k, v in flat.items():
            if k in ("is_relevant", "severity", "confidence", "underlying_reason", "unmet_need", "evidence_quote"):
                counts[k] += 0 if k not in ("underlying_reason", "unmet_need") else v in ("unclear", "none stated", "none")
                continue
            vals = v if isinstance(v, list) else [v]
            counts[k] += all(x in UNCLEAR for x in vals)
    return {k: 100 * c / total for k, c in counts.items()}


def compare(ids: list[str]) -> None:
    clean = {r["id"]: r for r in load_jsonl(CLEAN_FILE)}
    allrecs = load_jsonl(TAGS_FILE)
    by_v = {v: {r["id"]: r for r in allrecs if r["id"] in set(ids) and r.get("tag_prompt_version") == v
                and r["status"] == "ok"} for v in ("t2", "t3")}
    rel = {v: [r for r in d.values() if r["tags"]["is_relevant"]] for v, d in by_v.items()}
    sh = {v: unclear_share(rel[v]) for v in rel}
    print(f"\nRelevant items: t2 {len(rel['t2'])}, t3 {len(rel['t3'])}.  % answered unclear / none, per field:")
    print(f"{'field':<22}{'t2':>7}{'t3':>7}")
    for k in sh["t3"]:
        print(f"{k:<22}{sh['t2'].get(k, 0):>6.0f}%{sh['t3'][k]:>6.0f}%")
    for v in ("t2", "t3"):
        qs = [r for r in rel[v] if r.get("quote_exact") is not None]
        bad = sum(1 for r in qs if not r["quote_exact"])
        print(f"{v}: {bad} of {len(qs)} model quotes were not exact substrings ({100 * bad / max(len(qs), 1):.0f}%)"
              + (f"; {sum(bool(r.get('quote_repaired')) for r in qs)} repaired in code" if v == "t3" else ""))
    runs = {}
    for r in load_jsonl(RUNS_FILE):
        runs[r["tag_prompt_version"]] = r
    runs.setdefault("t2", {"items": 50, "tokens": 26798})       # t2 ran before run logging existed
    for v in ("t2", "t3"):
        if v in runs:
            print(f"{v}: {runs[v]['tokens'] / runs[v]['items']:.0f} tokens per item "
                  f"({runs[v]['tokens']:,} tokens for {runs[v]['items']} items)")
    print("\nThe two items that were under-tagged in t2:")
    for needle in ("मैने निप्पोन लार्जर कैप", "Mana investment to Kar diya"):
        for i, c in clean.items():
            if c["text"].startswith(needle) and i in by_v["t3"]:
                for v in ("t2", "t3"):
                    t = by_v[v][i]["tags"]
                    print(f"  [{v}] {needle[:28]!r}: stage={t['journey_stage']}, sip_action={t['sip_action']}, "
                          f"triggers={t['stated_triggers']}, emotion={t['emotion']}, severity={t['severity']}")
                    print(f"        reason: {t['underlying_reason']}")


def field_values(tags: dict) -> dict:
    flat = {**{k: v for k, v in tags.items() if k != "segment_signals"}, **tags.get("segment_signals", {})}
    return {k: v for k, v in flat.items() if k not in TEXT_FIELDS and k != "confidence"}


def agreement(n: int, cb: dict, maps: dict) -> None:
    """Inter-model check: qwen tags the first n pilot items that gpt-oss-120b (t3) already tagged;
    then compare field by field."""
    ids = json.loads(PILOT_FILE.read_text())[:n]
    first = TAGS_FILE.parent / TAGGERS["gpt-oss-120b"]["file"]
    base = {r["id"]: r for r in load_jsonl(first) if r.get("tag_prompt_version") == TAG_PROMPT_VERSION
            and r.get("model") == TAGGERS["gpt-oss-120b"]["model"] and r["status"] == "ok"}
    by_id = {r["id"]: r for r in load_jsonl(CLEAN_FILE)}
    labels = results_for("v3")
    items = [{**by_id[i], "relevance": labels[i]["relevant"] if i in labels else "pending"} for i in ids if i in base]
    print(f"{len(items)} of the first {n} pilot items already have gpt-oss-120b tags; qwen tags them now.")
    use_tagger("qwen")
    run(items, cb, maps)
    other = {r["id"]: r for r in load_jsonl(TAGS_FILE) if r.get("tag_prompt_version") == TAG_PROMPT_VERSION
             and r["status"] == "ok"}
    both = [i for i in ids if i in base and i in other]
    print(f"\n{len(both)} items tagged by both models.")
    rel_agree = sum(base[i]["tags"]["is_relevant"] == other[i]["tags"]["is_relevant"] for i in both)
    print(f"is_relevant: {rel_agree}/{len(both)} agree ({100 * rel_agree / max(len(both), 1):.0f}%)")
    both_rel = [i for i in both if base[i]["tags"]["is_relevant"] and other[i]["tags"]["is_relevant"]]
    stats = defaultdict(lambda: [0, 0, 0.0])        # field -> [exact agree, total, jaccard sum]
    for i in both_rel:
        a, b = field_values(base[i]["tags"]), field_values(other[i]["tags"])
        for k in a:
            if k == "is_relevant":
                continue
            x, y = (set(a[k]), set(b[k])) if isinstance(a[k], list) else ({a[k]}, {b[k]})
            stats[k][0] += x == y
            stats[k][1] += 1
            stats[k][2] += len(x & y) / len(x | y)
    print(f"\nField by field, on the {len(both_rel)} items both models call relevant "
          f"(exact = identical answer; overlap = shared share for list fields):")
    print(f"{'field':<22}{'exact':>8}{'overlap':>9}")
    for k, (ok, tot, jac) in stats.items():
        print(f"{k:<22}{100 * ok / tot:>7.0f}%{100 * jac / tot:>8.0f}%")
    overall = sum(v[0] for v in stats.values()) / max(sum(v[1] for v in stats.values()), 1)
    core = [k for k in ("journey_stage", "sip_action", "lapse_type", "stated_triggers", "emotion", "severity")]
    core_ok = sum(stats[k][0] for k in core) / max(sum(stats[k][1] for k in core), 1)
    print(f"All fields: {100 * overall:.0f}% exact. Six core fields (stage, sip_action, lapse_type, triggers, "
          f"emotion, severity): {100 * core_ok:.0f}% exact.")
    print("\nDisagreements on core fields (up to 12):")
    shown = 0
    for i in both_rel:
        a, b = field_values(base[i]["tags"]), field_values(other[i]["tags"])
        diffs = [k for k in core if (set(a[k]) if isinstance(a[k], list) else {a[k]}) != (set(b[k]) if isinstance(b[k], list) else {b[k]})]
        if diffs and shown < 12:
            shown += 1
            print(f"  [{by_id[i]['source']}] {short(by_id[i]['text'], 90)!r}")
            for k in diffs:
                print(f"      {k}: 120b={a[k]}  qwen={b[k]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, metavar="N")
    ap.add_argument("--rerun-pilot", action="store_true", help="same pilot items again with the current prompt")
    ap.add_argument("--tagger", default="gpt-oss-120b", choices=sorted(TAGGERS))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--agreement", type=int, metavar="N", help="qwen tags the first N pilot items; compare with gpt-oss-120b")
    ap.add_argument("--compare", action="store_true", help="t2 vs t3 on the pilot items")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--auto-resume", action="store_true",
                    help="with --all: when the daily allowance runs out, wait until the reset time Groq states, then continue")
    args = ap.parse_args()

    use_tagger(args.tagger)
    cb = load_codebook()
    maps = build_maps(cb)
    if args.agreement:
        agreement(args.agreement, cb, maps)
    elif args.pilot:
        pilot = pick_pilot(relevant_items(), args.pilot)
        PILOT_FILE.write_text(json.dumps([r["id"] for r in pilot]))
        client = run(pilot, cb, maps)
        report([r["id"] for r in pilot], client, cb)
    elif args.rerun_pilot:
        by_id = {r["id"]: r for r in relevant_items()}
        ids = json.loads(PILOT_FILE.read_text())
        client = run([by_id[i] for i in ids], cb, maps)
        report(ids, client, cb)
    elif args.compare:
        compare(json.loads(PILOT_FILE.read_text()))
    elif args.report:
        report(json.loads(PILOT_FILE.read_text()), None, cb)
    elif args.all:
        while True:
            items = sample_items(TAGGER)
            todo = [r for r in items if r["id"] not in tagged_ids()]
            pending = sum(r["relevance"] == "pending" for r in items)
            print(f"[{TAGGER}] sample so far: {len(items)} items for this tagger "
                  f"({sum(has_priority_word(r['text']) for r in items)} with priority words), "
                  f"{len(todo)} still to tag, {pending} not yet seen by the relevance filter.")
            if not todo:
                if args.auto_resume and pending:
                    print("Waiting 30 minutes for the relevance filter to keep more items, then checking again.")
                    try:
                        time.sleep(1800)
                    except KeyboardInterrupt:
                        break
                    continue
                break
            client = run(items, cb, maps)
            if not client.stopped:
                continue                             # finished the list: look for newly kept items
            if not args.auto_resume or client.interrupted:
                break                                # daily allowance used up: stop and report
            wait = max((client.stop_wait or 900) + 90, 120)
            print(f"Auto-resume: waiting {wait / 60:.0f} minutes for Groq's stated reset, then continuing "
                  f"(resumes about {datetime.fromtimestamp(time.time() + wait):%H:%M}). Press Ctrl+C to stop.")
            try:
                time.sleep(wait)
            except KeyboardInterrupt:
                break
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
