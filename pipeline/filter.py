"""AI relevance filter: is each cleaned item about SIP / mutual-fund investing?

Uses Groq's free tier (small model set by MODEL below), 15 items per request, JSON output.
Results are appended to data/processed/relevance.jsonl after every request, so a run
can be stopped and resumed (finished ids are skipped). Rate limits are read from
Groq's response headers.

Usage (from the project folder):
    python -m pipeline.filter --pilot 100     # random mixed-source pilot, then a report
    python -m pipeline.filter --rerun-pilot   # same pilot items again (use with --prompt v1/v2)
    python -m pipeline.filter --compare       # v1 vs v2 on the pilot items
    python -m pipeline.filter --report        # re-print the pilot report
    python -m pipeline.filter --all           # full run (resumable; 2021+ items first)
Add  --prompt v1  to use the old prompt (default is the newest, v2).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from collect.common import ROOT, build_keyword_matcher
from pipeline.clean import PROCESSED_DIR

# llama-3.1-8b-instant was no longer offered on this Groq account (Oct 2026); gpt-oss-20b is the
# smallest chat model that was listed. Check https://console.groq.com/docs/models for changes.
MODEL = "openai/gpt-oss-20b"
API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_PROMPT = "v3"
REASONING_EFFORT = "low"     # gpt-oss models think before answering; keep it short to save tokens
LONG_WAIT_SECONDS = 600     # a wait longer than this means the daily limit is used up
PILOT_QUOTAS = {"app_store": 5, "play_store": 25, "tradingqna": 35, "youtube": 35}
MAIN_WINDOW_FROM = 2021

# How much of each item is sent. v1 cut by characters; v2 cuts by words to save tokens.
CLIP = {"v1": {"unit": "chars", "text": 700, "context": 200, "batch": 15},
        "v2": {"unit": "words", "text": 150, "context": 25, "batch": 15},
        "v3": {"unit": "words", "text": 150, "context": 25, "batch": 25}}

CLEAN_FILE = PROCESSED_DIR / "clean.jsonl"
RESULT_FILE = PROCESSED_DIR / "relevance.jsonl"
PILOT_FILE = PROCESSED_DIR / "pilot_ids.json"

PROMPTS = {}

# v1: first version, used for the first 100-item pilot. Kept unchanged for comparison.
PROMPTS["v1"] = """You label public posts about investing in India for a research project on why
people stop their SIP (systematic investment plan in mutual funds).

For each numbered item decide if it is RELEVANT:
- "yes": the person shares an experience, reason, question, problem, expectation or feeling about
  starting, continuing, pausing, reducing or stopping a SIP or mutual fund investing; being a new
  or first-time investor; SIP mandates / autopay / failed or skipped instalments; NAV or returns
  confusion; or redeeming / withdrawing mutual funds.
- "no": only stocks, F&O, trading, IPOs or demat; generic praise or abuse with no information
  (for example "good app for SIP", "mind blowing sir"); spam, links, greetings; or unrelated.
- "unsure": borderline. Use it when you cannot tell. Do not guess "no" on a borderline item.

Some items include a "context" line (the forum question or the video title the item replies to).
Use it only to understand a short reply; judge whether the item itself adds something relevant.
Text may be English, Hindi, or Hinglish (Hindi in English letters).

Answer with JSON only, in this exact shape, one entry per item, in order:
{"results": [{"i": 1, "relevant": "yes", "reason": "up to 10 words"}, ...]}"""

# v2: adds worked examples for yes / no / unsure, explicit "no" cases, a "never no" rule for
# confused investors, and a rule that the reason may only describe what the text says.
PROMPTS["v2"] = """You label public posts about investing in India for a research project on why
people stop their SIP (systematic investment plan in mutual funds).

For each numbered item decide if it is RELEVANT.

"yes": the person shares an experience, reason, question, problem, expectation or feeling about
starting, continuing, pausing, reducing or stopping a SIP or mutual fund investing; being a new or
first-time investor; SIP mandates / autopay / failed or skipped instalments; NAV or returns
confusion; or redeeming / withdrawing mutual funds.

"no": the item has NO mutual fund or SIP angle. This includes: stocks, F&O, trading, IPOs; demat
account, brokerage or account-opening charges; bank-account, KYC or login problems that do not
mention a mutual fund or SIP; generic praise or abuse with no information ("good app for SIP",
"mind blowing sir"); spam, links, greetings; anything unrelated.

"unsure": borderline, or you cannot tell. Always use unsure instead of guessing.

Rules:
- A confused or first-time investor asking about mutual funds, lumpsum versus SIP, timing, or where
  to see their investment must be "yes" or "unsure", never "no".
- A question that is only about which fund to pick is "unsure", not "no".
- The reason (up to 10 words) must describe only what the text actually says. Do not add details
  that are not in the text. If you answer unsure, start the reason with "unsure:" and say what is unclear.
- Some items have a "context" line (the forum question or video title the item replies to). Use it
  only to understand a short reply. Judge whether the item itself adds something relevant.
- Text may be English, Hindi, or Hinglish (Hindi in English letters).

Examples:
- "My SIP got skipped twice, autopay said insufficient balance" -> yes, "SIP skipped, autopay failed"
- "Started SIP last month, now it shows red. Should I worry?" -> yes, "new SIP investor worried about loss"
- "Is it a good time to invest lumpsum?" -> unsure, "unsure: lumpsum timing question, no SIP detail"
- "Nippon me invest karna best rahega ki nahi" -> unsure, "unsure: asks about one fund choice"
- "Demat AMC is Rs 300 a year, charged on 31 March" -> no, "demat account charge, no mutual fund"
- "Best app for stocks and F&O trading, very fast" -> no, "praises stock trading"
- "Good app for SIP" -> no, "generic praise, no information"
- "First call option expired worthless, lost 5000" -> no, "options trading loss"

Answer with JSON only, in this exact shape, one entry per item, in order:
{"results": [{"i": 1, "relevant": "yes", "reason": "up to 10 words"}, ...]}"""

# v3: the last tuning round. Shorter (4 examples + one "where do I see my investment" example),
# recall-first ("when in doubt between no and unsure, choose unsure"), reasons may not mention
# SIP unless the text does. Used with 25 items per request and the safety net below.
PROMPTS["v3"] = """You label public posts about investing in India for a research project on why
people stop their SIP (systematic investment plan in mutual funds). Your job is RECALL: it is
much worse to throw away a post that matters than to keep one that does not.

For each numbered item decide if it is RELEVANT.

"yes": the person shares an experience, reason, question, problem, expectation or feeling about
starting, continuing, pausing, reducing or stopping a SIP or mutual fund investing; being a new or
first-time investor; SIP mandates / autopay / failed or skipped instalments; NAV or returns
confusion; or redeeming / withdrawing mutual funds.

"no": no mutual fund or SIP angle at all: only stocks, F&O, trading, IPOs; demat, brokerage,
bank-account, KYC or login problems; generic praise or abuse with no information; spam, links,
greetings; anything unrelated.

"unsure": borderline, or you cannot tell.

Rules:
- When in doubt between "no" and "unsure", choose "unsure".
- A confused or first-time investor asking about mutual funds, lumpsum vs SIP, timing, which fund,
  or where to see their investment is "yes" or "unsure", never "no".
- The reason (up to 10 words) must describe only what the text says. It must not mention SIP unless
  the text does. For "unsure", start the reason with "unsure:".
- A "context" line (forum question or video title) is only there to help you understand a short reply.
- Text may be English, Hindi, or Hinglish (Hindi in English letters).

Examples:
- "My SIP got skipped twice, autopay said insufficient balance" -> yes, "SIP skipped, autopay failed"
- "I invested through my bank last year, how do I see it in this app?" -> yes, "asks where to see investment"
- "Is it a good time to invest lumpsum?" -> unsure, "unsure: lumpsum timing question"
- "Demat AMC is Rs 300 a year, charged on 31 March" -> no, "demat charge, no mutual fund"
- "Good app for SIP" -> no, "generic praise, no information"

Answer with JSON only, in this exact shape, one entry per item, in order:
{"results": [{"i": 1, "relevant": "yes", "reason": "up to 10 words"}, ...]}"""

# Safety net (plain code, no AI). A model "no" is upgraded to "unsure" when the text mentions one of
# these words AND is a question or a first-person experience. Wrong "no" loses data for good;
# a wrong "unsure" is caught later by the tagging step.
SAFETY_KEYWORDS = ["sip", "mutual fund", "mf", "lumpsum", "lumpsome", "lump sum", "mandate", "autopay",
                   "auto pay", "nav", "redeem", "redemption", "first investment", "beginner"]
_safety_match = build_keyword_matcher(SAFETY_KEYWORDS)
_QUESTION = re.compile(
    r"\?|^\s*(how|what|why|when|where|which|who|can|could|should|is|are|do|does|will|would|kya|kaise|"
    r"kese|kab|kitna|kaun|kyu|kyun|kahan|konsa)\b", re.I)
_FIRST_PERSON = re.compile(
    r"\b(i|i'm|i've|i'd|i'll|my|me|mine|myself|we|our|maine|mujhe|mera|meri|mere|humne|hamara|hum)\b", re.I)


def safety_net(text: str, label: str) -> bool:
    """True if a model 'no' should be upgraded to 'unsure'."""
    return (label == "no" and _safety_match(text)
            and bool(_QUESTION.search(text) or _FIRST_PERSON.search(text)))



# Safety net 2 (plain code, no AI), added after the pilot showed wrong "no" labels on fund-choice
# questions, vague "where is my investment" questions and mutual fund complaints. A model "no" becomes
# "unsure" if the text has ANY of:
#   a. a fund-house name (names that are also banks or companies, like HDFC, SBI, ICICI, Axis, Kotak,
#      Tata, HSBC, IDFC, need a fund word nearby such as fund / invest / amc / scheme / nfo / elss / etf)
#   b. "invest..." in a question (English or Hinglish)
#   c. "MF" or "mutual fund" together with a complaint word (problem, not updated, incorrect, ...)
_FUND_HOUSES = ["nippon", "mirae", "parag parikh", "ppfas", "quant", "motilal", "dsp", "uti", "franklin",
                "invesco", "edelweiss", "bandhan", "canara robeco", "navi", "aditya birla", "sundaram",
                "whiteoak", "mahindra manulife", "pgim", "lic mf", "baroda bnp", "jm financial"]
_AMBIGUOUS_HOUSES = ["hdfc", "sbi", "icici", "axis", "kotak", "tata", "hsbc", "idfc", "bajaj"]
_FUND_WORDS = ["fund", "funds", "mf", "amc", "scheme", "nfo", "elss", "etf", "invest", "investing", "investment"]
_house_match = build_keyword_matcher(_FUND_HOUSES)
_ambiguous_match = build_keyword_matcher(_AMBIGUOUS_HOUSES)
_fund_word_match = build_keyword_matcher(_FUND_WORDS)
_invest_match = build_keyword_matcher(["invest", "investing", "investment", "invested"])
_mf_match = build_keyword_matcher(["mf", "mutual fund"])
_HINGLISH_QUESTION = re.compile(r"\b(kya|kaise|kese|kahan|kaha|kab|kitna|kitne|kaun|kyu|kyun|konsa|ki nahi|ya nahi)\b", re.I)
_complaint_match = build_keyword_matcher([
    "problem", "issue", "error", "not working", "doesnt work", "failed", "failure", "crash", "hang", "bug",
    "stuck", "delay", "delayed", "pending", "unable", "cannot", "can't", "not able", "not showing",
    "not updated", "incorrect", "wrong", "mismatch", "missing", "glitch", "complaint", "refund",
    "deducted", "not resolved", "not received"])


def fund_rule(text: str, label: str) -> bool:
    """Safety net 2: True if a model 'no' should be upgraded to 'unsure'."""
    if label != "no":
        return False
    if _house_match(text) or (_ambiguous_match(text) and _fund_word_match(text)):
        return True
    if _invest_match(text) and (_QUESTION.search(text) or _HINGLISH_QUESTION.search(text)):
        return True
    return _mf_match(text) and _complaint_match(text)


def rescue_rule(text: str, label: str) -> str | None:
    """Which safety net (if any) turns a model 'no' into 'unsure'."""
    if safety_net(text, label):
        return "keyword_question"
    if fund_rule(text, label):
        return "fund_or_complaint"
    return None

VALID = {"yes", "no", "unsure"}


# ---------- Groq calls ----------
def parse_duration(value: str | None) -> float:
    """Groq reset headers look like '7.66s', '2m59.56s' or '1h2m3s'."""
    if not value:
        return 0.0
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", value):
        total += float(num) * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[unit]
    return total


class Groq:
    def __init__(self, version: str) -> None:
        self.version = version
        load_dotenv(ROOT / ".env")
        self.key = os.getenv("GROQ_API_KEY")
        if not self.key:
            sys.exit("No GROQ_API_KEY in .env")
        self.tokens_used = 0
        self.requests_made = 0
        self.limits: dict[str, str] = {}

    def chat(self, user_prompt: str) -> str:
        body = {"model": MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": PROMPTS[self.version]},
                             {"role": "user", "content": user_prompt}]}
        if MODEL.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = REASONING_EFFORT
        for attempt in range(8):
            try:
                resp = requests.post(API_URL, json=body, timeout=90,
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
                per_day = "per day" in resp.text.lower()      # Groq names the limit it hit (RPD / TPD)
                if wait > LONG_WAIT_SECONDS or per_day:
                    when = f"about {wait / 3600:.1f} hours" if wait > 3600 else f"about {wait / 60:.0f} minutes"
                    raise DailyLimit(f"Groq's daily allowance for {MODEL} is used up "
                                     f"(it resets in {when}).", wait=wait)
                print(f"    rate limited; waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            if resp.status_code != 200:
                sys.exit(f"Groq error {resp.status_code}: {resp.text[:300]}")
            self.tokens_used += resp.json().get("usage", {}).get("total_tokens", 0)
            self._pace(h)
            return resp.json()["choices"][0]["message"]["content"]
        raise DailyLimit("Groq kept refusing or failing after 8 tries; try again later.")

    def _pace(self, h) -> None:
        """If the headers say we are nearly out of requests or tokens, wait for the reset."""
        wait = 0.0
        if int(h.get("x-ratelimit-remaining-requests") or 99) <= 1:
            wait = max(wait, parse_duration(h.get("x-ratelimit-reset-requests")))
        if int(h.get("x-ratelimit-remaining-tokens") or 99999) < 4000:
            wait = max(wait, parse_duration(h.get("x-ratelimit-reset-tokens")))
        if 0 < wait <= LONG_WAIT_SECONDS:
            print(f"    near the limit; pausing {wait + 1:.0f}s")
            time.sleep(wait + 1)


class DailyLimit(Exception):
    """Groq's daily allowance is used up. `wait` is the number of seconds Groq says until it resets."""

    def __init__(self, message: str, wait: float | None = None) -> None:
        super().__init__(message)
        self.wait = wait


# ---------- batching ----------
def clip(text: str, limit: int, unit: str) -> str:
    if unit == "words":
        words = text.split()
        return " ".join(words[:limit]) + (" ..." if len(words) > limit else "")
    return text[:limit]


def build_prompt(batch: list[dict], version: str) -> str:
    c = CLIP[version]
    lines = []
    for n, r in enumerate(batch, 1):
        ctx = clip((r.get("context") or "").replace("\n", " "), c["context"], c["unit"])
        line = f"[{n}] ({r['source']})"
        if ctx:
            line += f" context: {ctx}\n    "
        line += " text: " + clip(r["text"], c["text"], c["unit"])
        lines.append(line)
    return "Items:\n" + "\n".join(lines)


def classify(client: Groq, batch: list[dict]) -> dict[int, tuple[str, str]]:
    """Returns {item number: (relevant, reason)} for the items the model answered properly."""
    try:
        data = json.loads(client.chat(build_prompt(batch, client.version)))
        entries = data["results"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}
    out = {}
    for e in entries:
        try:
            n, rel = int(e["i"]), str(e["relevant"]).strip().lower()
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= n <= len(batch) and rel in VALID:
            out[n] = (rel, " ".join(str(e.get("reason", "")).split()[:12]))
    return out


# ---------- files ----------
def load_jsonl(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def results_for(version: str) -> dict[str, dict]:
    return {r["id"]: r for r in load_jsonl(RESULT_FILE) if r.get("prompt_version") == version}


def print_progress(items: list[dict], version: str, client: Groq) -> None:
    """How far the run got, so it is clear whether to run the same command again."""
    finished = results_for(version)
    left = [r for r in items if r["id"] not in finished]
    left_main = sum(1 for r in left if (r.get("year") or 0) >= MAIN_WINDOW_FROM)
    print(f"This run: {client.saved} items labelled, {client.tokens_used:,} tokens, "
          f"{client.requests_made} requests.")
    print(f"Overall ({version}, {MODEL}): {len(items) - len(left)} of {len(items)} items labelled, "
          f"{len(left)} left ({left_main} of them from {MAIN_WINDOW_FROM} onward).")
    if left:
        print("To continue, run the same command again (finished items are skipped).")


def run(items: list[dict], version: str) -> Groq:
    client = Groq(version)
    finished = results_for(version)
    todo = [r for r in items if r["id"] not in finished]
    print(f"{len(items)} items selected, {len(items) - len(todo)} already done, {len(todo)} to do")
    started = time.time()
    saved = 0
    client.stopped, client.stop_wait, client.interrupted = False, None, False
    try:
        size = CLIP[version]["batch"]
        for start in range(0, len(todo), size):
            batch = todo[start:start + size]
            answers = classify(client, batch)
            if len(answers) < len(batch):                 # one retry for items the model skipped
                missing = [r for n, r in enumerate(batch, 1) if n not in answers]
                retry = classify(client, missing)
                answers = {n: answers[n] for n in answers}
                for k, r in enumerate(missing, 1):
                    if k in retry:
                        answers[batch.index(r) + 1] = retry[k]
            with open(RESULT_FILE, "a", encoding="utf-8") as f:
                for n, r in enumerate(batch, 1):
                    if n not in answers:
                        continue                          # stays undone, picked up on the next run
                    rel, reason = answers[n]
                    rule = rescue_rule(r["text"], rel) if version == "v3" else None
                    rescued = rule is not None
                    f.write(json.dumps({"id": r["id"], "source": r["source"],
                                        "relevant": "unsure" if rescued else rel,
                                        "model_relevant": rel, "rescued_by_rule": rescued,
                                        "rescue_rule": rule,
                                        "reason": reason, "model": MODEL,
                                        "prompt_version": version,
                                        "labelled_at": datetime.now(timezone.utc).isoformat()},
                                       ensure_ascii=False) + "\n")
                    saved += 1
            if (start // size) % 10 == 9:
                print(f"  {saved}/{len(todo)} labelled, {client.tokens_used:,} tokens so far")
    except DailyLimit as exc:
        client.stopped, client.stop_wait = True, exc.wait
        print(f"\nSTOPPED: {exc}")
    except KeyboardInterrupt:
        client.interrupted = True
        print("\nSTOPPED by you (Ctrl+C).")
    else:
        print("\nFinished.")
    client.elapsed = time.time() - started
    client.saved = saved
    print_progress(items, version, client)
    return client


# ---------- pilot ----------
def pick_pilot(clean: list[dict], total: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    by_source = defaultdict(list)
    for r in clean:
        by_source[r["source"]].append(r)
    scale = total / sum(PILOT_QUOTAS.values())
    picked = []
    for source, quota in PILOT_QUOTAS.items():
        pool = by_source.get(source, [])
        picked += rng.sample(pool, min(len(pool), round(quota * scale)))
    rng.shuffle(picked)
    return picked


def count_table(results_by_version: dict[str, dict[str, dict]], ids: list[str]) -> None:
    """Rows: source x label for each prompt version side by side."""
    labels = ("yes", "no", "unsure")
    counts = {v: defaultdict(Counter) for v in results_by_version}
    for v, res in results_by_version.items():
        for i in ids:
            if i in res:
                counts[v][res[i]["source"]][res[i]["relevant"]] += 1
    versions = list(results_by_version)
    head = f"{'source':<12}" + "".join(f"{v + ' ' + l:>10}" for v in versions for l in labels)
    print("\n" + head)
    sources = sorted({s for v in versions for s in counts[v]})
    for s in sources + ["TOTAL"]:
        cells = ""
        for v in versions:
            c = Counter()
            for src in (sources if s == "TOTAL" else [s]):
                c.update(counts[v][src])
            cells += "".join(f"{c[l]:>10}" for l in labels)
        print(f"{s:<12}{cells}")


def report(clean_by_id: dict[str, dict], ids: list[str], version: str,
           client: Groq | None = None, samples: bool = True) -> None:
    results = results_for(version)
    count_table({version: results}, ids)

    if samples:
        rng = random.Random(1)
        for label in ("yes", "no"):
            pool = [results[i] for i in ids if i in results and results[i]["relevant"] == label]
            print(f"\n10 random '{label}' items:")
            for r in rng.sample(pool, min(10, len(pool))):
                item = clean_by_id[r["id"]]
                print(f"  [{r['source']}] {item['text'][:160]!r}\n      -> {r['reason']}")

    if client and client.saved:
        per_item = client.tokens_used / client.saved
        full = len(clean_by_id)
        sec_per_item = client.elapsed / client.saved
        print(f"\nPilot ({version}): {client.tokens_used:,} tokens, {client.requests_made} requests, "
              f"{client.elapsed:.0f}s for {client.saved} items "
              f"({per_item:.0f} tokens and {sec_per_item:.1f}s per item).")
        print(f"Full run estimate: {full * per_item:,.0f} tokens, "
              f"about {full / CLIP[version]["batch"]:.0f} requests, about {full * sec_per_item / 60:.0f} minutes "
              f"(if the daily limit allows). Limits seen in headers: {client.limits}")


def compare(clean_by_id: dict[str, dict], ids: list[str]) -> None:
    v1, v2, v3 = results_for("v1"), results_for("v2"), results_for("v3")
    count_table({"v1": v1, "v2": v2, "v3": v3}, ids)
    changed = [i for i in ids if i in v2 and i in v3 and v2[i]["relevant"] != v3[i]["relevant"]]
    print(f"\n{len(changed)} of {len(ids)} items changed label from v2 to v3:")
    for i in changed:
        print(f"  [{v2[i]['source']}] {clean_by_id[i]['text'][:140]!r}\n"
              f"      v2: {v2[i]['relevant']} ({v2[i]['reason']})\n"
              f"      v3: {v3[i]['relevant']} ({v3[i]['reason']})")
    rescued = [i for i in ids if i in v3 and v3[i].get("rescued_by_rule")]
    print(f"\nSafety net rescued {len(rescued)} items (model said no, rule made it unsure):")
    for i in rescued:
        print(f"  [{v3[i]['source']}] {clean_by_id[i]['text'][:200]!r}  (model reason: {v3[i]['reason']})")
    remaining = [i for i in ids if i in v3 and v3[i]["relevant"] == "no"]
    print(f"\n{len(remaining)} items are still 'no' in v3:")
    for i in remaining:
        print(f"  {i[-6:]} [{v3[i]['source']}] {clean_by_id[i]['text'][:260]!r}\n      -> {v3[i]['reason']}")


def main_window_first(items: list[dict]) -> list[dict]:
    """2021+ items first, newest year first; within each group TradingQ&A and the app stores
    before YouTube (YouTube is the noisiest source). Older and undated items come last."""
    def key(r):
        y = r.get("year")
        in_window = bool(y and y >= MAIN_WINDOW_FROM)
        return (0 if in_window else 1, 1 if r["source"] == "youtube" else 0, -(y or 0))
    return sorted(items, key=key)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, metavar="N", help="pick N new mixed-source pilot items and label them")
    ap.add_argument("--rerun-pilot", action="store_true", help="label the same pilot items again")
    ap.add_argument("--compare", action="store_true", help="v1 vs v2 on the pilot items")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--auto-resume", action="store_true",
                    help="with --all: when the daily allowance runs out, wait until the reset time Groq states, then continue")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, choices=sorted(PROMPTS))
    args = ap.parse_args()

    clean = load_jsonl(CLEAN_FILE)
    by_id = {r["id"]: r for r in clean}
    if args.pilot or args.rerun_pilot:
        if args.pilot:
            pilot = pick_pilot(clean, args.pilot)
            PILOT_FILE.write_text(json.dumps([r["id"] for r in pilot]))
        else:
            pilot = [by_id[i] for i in json.loads(PILOT_FILE.read_text())]
        client = run(pilot, args.prompt)
        report(by_id, [r["id"] for r in pilot], args.prompt, client, samples=bool(args.pilot))
    elif args.compare:
        compare(by_id, json.loads(PILOT_FILE.read_text()))
    elif args.report:
        report(by_id, json.loads(PILOT_FILE.read_text()), args.prompt)
    elif args.all:
        while True:
            client = run(main_window_first(clean), args.prompt)
            if not (args.auto_resume and client.stopped) or client.interrupted:
                break
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
