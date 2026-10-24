"""Reddit through Apify (pay-per-result scraper), with cost guards.

Actor: trudax/reddit-scraper-lite (set in config.yaml, section reddit_apify). Pricing is read from the Apify API
every time; nothing runs without a hard spending cap, and the full run is refused unless a test run was done first
and you pass --approved.

    python -m collect.reddit_apify --pricing            # cost per 1,000 results, your credit, the plan. Runs nothing.
    python -m collect.reddit_apify --test               # one small run (max 30 items), report + 5 sample items (done)
    python -m collect.reddit_apify --stage posts        # step 1: searches, POSTS ONLY (no comments), about 150 posts
    python -m collect.reddit_apify --stage shortlist    # step 2: free, plain code: keep posts about stopping / failing / etc.
    python -m collect.reddit_apify --stage comments --approved   # step 3: comments (15 per post) for the shortlist only

A spending ledger (data/raw/apify_reddit_ledger.json) adds up every run; no run starts if it could take the total over
budget_total_usd in config.yaml.

Inputs: thread URLs in data/manual/reddit_threads.txt (one per line, optional) and searches limited to three subreddits.
Posts from 2021 onward only, up to 30 comments per post.

Privacy: every author / username field is dropped BEFORE anything is written to disk, usernames inside text or links
are masked, and the text goes through scrub(). The post's own text is kept as the context of its comments (in
pipeline/clean.py). The token is read from .env (APIFY_TOKEN) and never printed.
Output: data/raw/reddit_apify.jsonl (standard records, git-ignored) and the sanitised raw run in data/raw/apify_reddit_*.json.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from collect.common import RAW_DIR, ROOT, load_config, make_record, save_records, scrub

API = "https://api.apify.com/v2"
THREAD_FILE = ROOT / "data" / "manual" / "reddit_threads.txt"
TEST_REPORT = RAW_DIR / "apify_reddit_test_report.json"
AUTHOR_KEY = re.compile(r"user|author|flair|avatar|creator|^html$", re.I)     # html repeats the body and may carry user links
COMMENT_TITLE = re.compile(r"^\s*/?u/\S+ on ", re.I)       # the actor titles a comment "/u/<name> on <post title>"
USER_IN_TEXT = re.compile(r"(?i)(?:https?://)?(?:\w+\.)?reddit\.com/(?:user|u)/[A-Za-z0-9_-]+/?|(?<![\w/])/?u/[A-Za-z0-9_-]{3,}")


# ---------------------------------------------------------------------------
# Apify API helpers
# ---------------------------------------------------------------------------
def headers() -> dict:
    load_dotenv(ROOT / ".env")
    token = os.getenv("APIFY_TOKEN")
    if not token:
        sys.exit("No APIFY_TOKEN in .env")
    return {"Authorization": f"Bearer {token}"}


def get(path: str, **params) -> dict:
    for attempt in range(6):                            # a slow answer from Apify must not crash a run that is already being billed
        try:
            r = requests.get(f"{API}{path}", headers=headers(), params=params, timeout=90)
            break
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
    else:
        sys.exit(f"Apify did not answer on {path}; the run (if any) keeps going on Apify and can be recovered with --recover <run id>.")
    if r.status_code >= 400:
        sys.exit(f"Apify error {r.status_code} on {path}: {r.text[:200]}")
    return r.json()["data"] if "data" in r.json() else r.json()


def actor_id(cfg: dict) -> str:
    return cfg["actor"].replace("/", "~")


def pricing(cfg: dict) -> dict:
    """Per-result price and start fee, read live from the actor's current pricing."""
    a = get(f"/acts/{actor_id(cfg)}")
    info = (a.get("pricingInfos") or [{}])[-1]
    events = (info.get("pricingPerEvent") or {}).get("actorChargeEvents", {})
    result = events.get("result", {})
    tiers = result.get("eventTieredPricingUsd") or {}
    per_result = (tiers.get("FREE") or {}).get("tieredEventPriceUsd", result.get("eventPriceUsd"))
    start = events.get("actor-start-gb", {}).get("eventPriceUsd", 0.0)
    if per_result is None:
        sys.exit("Could not read a per-result price from the actor; not running anything.")
    memory = (a.get("defaultRunOptions") or {}).get("memoryMbytes") or 1024
    return {"model": info.get("pricingModel"), "per_result": float(per_result), "start_per_gb": float(start),
            "memory_mb": int(cfg.get("memory_mb") or memory), "title": a.get("title")}


def account() -> dict:
    lim = get("/users/me/limits")
    return {"cap": float(lim["limits"]["maxMonthlyUsageUsd"]), "used": float(lim["current"]["monthlyUsageUsd"]),
            "cycle_end": lim["monthlyUsageCycle"]["endAt"][:10]}


LEDGER = RAW_DIR / "apify_reddit_ledger.json"


def ledger() -> list[dict]:
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else []


def spent(cfg: dict) -> float:
    return sum(e["usd"] for e in ledger())


def add_to_ledger(what: str, usd: float, items: int, run_id: str) -> None:
    LEDGER.write_text(json.dumps(ledger() + [{"what": what, "usd": round(usd, 4), "items": items, "run_id": run_id,
                                              "at": datetime.now(timezone.utc).isoformat()}], indent=1))


def estimate(price: dict, items: int, runs: int) -> float:
    return items * price["per_result"] + runs * price["start_per_gb"] * price["memory_mb"] / 1024


def read_threads() -> list[str]:
    if not THREAD_FILE.exists():
        return []
    return [l.strip() for l in THREAD_FILE.read_text(encoding="utf-8").splitlines() if l.strip().startswith("http")]


def dataset_items(dataset_id: str) -> list[dict]:
    for attempt in range(6):
        try:
            return requests.get(f"{API}/datasets/{dataset_id}/items", headers=headers(),
                                params={"format": "json", "clean": "true"}, timeout=120).json()
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
    sys.exit("Could not download the results.")


def run_actor(cfg: dict, price: dict, acct: dict, run_input: dict, max_items: int, what: str = "run") -> dict:
    """One run with a hard cap on what it can charge. Refuses if it could take the account over its credit."""
    cap_run = round(estimate(price, max_items, 1) * 1.15 + 0.01, 3)
    if acct["used"] + cap_run > acct["cap"] * 0.98:
        sys.exit(f"Stopping: this run could charge up to ${cap_run} and only ${acct['cap'] - acct['used']:.2f} of credit is left.")
    if spent(cfg) + cap_run > cfg["budget_total_usd"]:
        sys.exit(f"Stopping: spent so far ${spent(cfg):.3f} + this run's cap ${cap_run} would pass the ${cfg['budget_total_usd']:.2f} budget.")
    run_input = {**run_input, "maxItems": max_items}
    r = requests.post(f"{API}/acts/{actor_id(cfg)}/runs", headers=headers(), json=run_input, timeout=60,
                      params={"memory": price["memory_mb"], "maxTotalChargeUsd": cap_run})
    if r.status_code >= 400:
        sys.exit(f"Could not start the run: {r.status_code} {r.text[:200]}")
    run = r.json()["data"]
    print(f"  run {run['id']} started (hard cap ${cap_run})")
    while run["status"] in ("READY", "RUNNING", "ABORTING"):
        time.sleep(8)
        run = get(f"/actor-runs/{run['id']}")
    items = dataset_items(run["defaultDatasetId"])
    run = get(f"/actor-runs/{run['id']}")          # refreshed so usage is final
    print(f"  run finished: {run['status']}, {len(items)} items, charged ${run.get('usageTotalUsd') or 0:.4f}")
    add_to_ledger(what, float(run.get("usageTotalUsd") or 0), len(items), run["id"])
    return {"run_id": run["id"], "status": run["status"], "usd": float(run.get("usageTotalUsd") or 0),
            "charged_events": run.get("chargedEventCounts"), "items": items}


# ---------------------------------------------------------------------------
# privacy and mapping
# ---------------------------------------------------------------------------
def mask_users(t: str) -> str:
    return USER_IN_TEXT.sub("[USER]", COMMENT_TITLE.sub("", t))


def strip_authors(obj):
    """Remove every author / user key at any depth and mask usernames inside any text value, so no username is ever
    written to disk (done before anything is saved)."""
    if isinstance(obj, dict):
        return {k: strip_authors(v) for k, v in obj.items() if not AUTHOR_KEY.search(k)}
    if isinstance(obj, list):
        return [strip_authors(v) for v in obj]
    if isinstance(obj, str):
        return mask_users(obj)
    return obj


def clean_text(t: str) -> str:
    return scrub(mask_users(html.unescape(t or "")))


def pick(d: dict, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def thread_of(url: str) -> str:
    m = re.search(r"/comments/([a-z0-9]+)", url or "")
    return m.group(1) if m else ""


def to_record(item: dict) -> dict | None:
    """Standard record from one (author-free) Apify item; None for items that are not a post or comment."""
    kind = (pick(item, "dataType", "type") or "").lower()
    if kind not in ("post", "comment"):
        return None
    url = pick(item, "url", "link") or ""
    community = pick(item, "communityName", "parsedCommunityName", "subreddit") or ""
    community = str(community).replace("r/", "")
    title = pick(item, "title") if kind == "post" else pick(item, "postTitle", "title")
    body = pick(item, "body", "text", "selftext", "content") or ""
    text = body if (kind == "comment" or body) else (title or "")
    created = pick(item, "createdAt", "created_at", "createdUtc")
    native = pick(item, "parsedId", "id") or url
    rec = make_record("reddit", f"apify-{native}", clean_text(text), title=html.unescape(mask_users(title)) if title else None,
                      source_detail=f"r/{community} {kind}".strip(), url=url, created_at=created,
                      rating=pick(item, "upVotes", "score", "upvotes"))
    rec["text"] = rec["text"] or ""
    return rec


def map_items(items: list[dict], min_year: int) -> tuple[list[dict], dict]:
    out, skipped = [], {"not_post_or_comment": 0, "before_year": 0, "empty": 0}
    for it in items:
        rec = to_record(it)
        if rec is None:
            skipped["not_post_or_comment"] += 1
        elif not rec["text"]:
            skipped["empty"] += 1
        elif rec["created_at"] and int(rec["created_at"][:4]) < min_year:
            skipped["before_year"] += 1
        else:
            out.append(rec)
    return out, skipped


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------
def base_input(cfg: dict) -> dict:
    return {"skipComments": False, "maxComments": cfg["max_comments"], "postDateLimit": cfg["post_date_limit"],
            "commentDateLimit": cfg["post_date_limit"], "includeNSFW": False, "sort": "relevance", "time": "all",
            "searchPosts": True, "skipUserPosts": True, "skipCommunity": True,
            "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}}


def do_test(cfg: dict, price: dict, acct: dict) -> None:
    sub, q = cfg["subreddits"][0], cfg["queries"][0]
    inp = {**base_input(cfg), "searches": [q], "searchCommunityName": sub, "maxPostCount": 3, "maxComments": 10}
    print(f"TEST run: search '{q}' in r/{sub}, at most {cfg['test_max_items']} items")
    run = run_actor(cfg, price, acct, inp, cfg["test_max_items"], "test")
    items = strip_authors(run["items"])
    (RAW_DIR / "apify_reddit_test.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    recs, skipped = map_items(items, cfg["min_year"])
    after = account()
    report = {"at": datetime.now(timezone.utc).isoformat(), "items_received": len(items), "usable_records": len(recs), "skipped": skipped,
              "run_usd": run["usd"], "monthly_used_before": acct["used"], "monthly_used_after": after["used"],
              "charged_events": run["charged_events"], "status": run["status"]}
    TEST_REPORT.write_text(json.dumps(report, indent=1))
    print(f"\nItems received: {len(items)}   usable posts/comments: {len(recs)}   skipped: {skipped}")
    print(f"Credit used by this run: ${run['usd']:.4f}  (account usage ${acct['used']:.4f} -> ${after['used']:.4f} of ${after['cap']:.2f})")
    print(f"Keys the actor returns (author keys already removed): {sorted({k for it in items for k in it})}")
    print("\n5 sample items (usernames removed, text scrubbed):")
    for r in recs[:5]:
        print(f" - [{r['source_detail']}] {r['created_at'][:10] if r['created_at'] else '?'} | {(r['title'] or '')[:60]!r}\n     {r['text'][:220]!r}\n     {r['url']}")


POSTS_FILE = RAW_DIR / "apify_reddit_posts.json"
SHORTLIST_FILE = RAW_DIR / "apify_reddit_shortlist.json"
COMMENTS_FILE = RAW_DIR / "apify_reddit_comments.json"
# step 2: a post is kept when its title or text mentions one of these, AND it is about SIPs / mutual funds
TOPIC = re.compile(r"\b(stop(ped|ping)?|paus(e|ed|ing)|cancel(l?ed|l?ing)?|autopay|auto[- ]pay|mandate|fail(ed|ure|s)?|bounce[sd]?|"
                   r"skip(ped|ping)?|first sip|negative|loss(es)?|should i continue|irregular income|salary)\b", re.I)
CORE = re.compile(r"\b(stop(ped|ping)?|paus(e|ed|ing)|cancel(l?ed|l?ing)?|autopay|auto[- ]pay|mandate|nach|fail(ed|ure|s)?|bounce[sd]?|skip(ped|ping)?|"
                  r"first|negative|should i|irregular|scared|xirr|deduct(ed)?|continue)\b", re.I)          # words that signal a SIP-continuation story
SIP_CONTEXT = re.compile(r"\b(sips?|mutual funds?|mfs?|elss|nav|xirr|index funds?|autopay|mandate)\b", re.I)


PARTS_FILE = RAW_DIR / "apify_reddit_posts_parts.json"      # step-1 results kept per subreddit as each run finishes


def recover(run_id: str, label: str) -> None:
    """Take the results (and the charge) of a run that finished on Apify but was not saved here. Costs nothing."""
    run = get(f"/actor-runs/{run_id}")
    if run["status"] != "SUCCEEDED":
        sys.exit(f"Run is {run['status']}, not recovered.")
    parts = json.loads(PARTS_FILE.read_text()) if PARTS_FILE.exists() else {}
    parts[label] = strip_authors(dataset_items(run["defaultDatasetId"]))
    PARTS_FILE.write_text(json.dumps(parts, ensure_ascii=False, indent=1), encoding="utf-8")
    if run_id not in {e["run_id"] for e in ledger()}:
        add_to_ledger(f"posts {label}", float(run.get("usageTotalUsd") or 0), len(parts[label]), run_id)
    print(f"recovered {len(parts[label])} items for {label}, charge ${run.get('usageTotalUsd') or 0}")


def do_posts(cfg: dict, price: dict, acct: dict) -> None:
    """Step 1: posts only (no comments), searches across the three subreddits. Subreddits already done are skipped."""
    per = cfg["posts_stage_max_items"] // len(cfg["subreddits"])
    parts = json.loads(PARTS_FILE.read_text()) if PARTS_FILE.exists() else {}
    print(f"STEP 1: posts only, {len(cfg['subreddits'])} runs x at most {per} posts ({len(parts)} already done)")
    for sub in cfg["subreddits"]:
        if f"r/{sub}" in parts:
            continue
        print(f"\n== r/{sub} ==")
        inp = {**base_input(cfg), "skipComments": True, "maxComments": 0, "searches": cfg["queries"], "searchCommunityName": sub,
               "maxPostCount": per // len(cfg["queries"]) + 1}          # spread over all the queries, not just the first
        run = run_actor(cfg, price, account(), inp, per, f"posts r/{sub}")
        parts[f"r/{sub}"] = strip_authors(run["items"])
        PARTS_FILE.write_text(json.dumps(parts, ensure_ascii=False, indent=1), encoding="utf-8")
    all_items = [it for v in parts.values() for it in v]
    POSTS_FILE.write_text(json.dumps(all_items, ensure_ascii=False, indent=1), encoding="utf-8")
    recs, skipped = map_items(all_items, cfg["min_year"])
    posts = [r for r in recs if r["source_detail"].endswith("post")]
    print(f"\nPosts received: {len(all_items)}, usable 2021+ posts: {len(posts)} (unique: {len({r['url'] for r in posts})}), skipped {skipped}")
    step1 = sum(e["usd"] for e in ledger() if e["what"].startswith("posts"))
    print(f"Cost of step 1: ${step1:.4f}.  Total spent so far (test + step 1): ${spent(cfg):.4f} of ${cfg['budget_total_usd']:.2f}")


def do_shortlist(cfg: dict) -> None:
    """Step 2: free, plain code. Nothing is bought and no AI is used."""
    items = strip_authors(json.loads(POSTS_FILE.read_text(encoding="utf-8")))
    recs, _ = map_items(items, cfg["min_year"])
    seen, posts = set(), []
    for r in recs:
        if r["source_detail"].endswith("post") and r["url"] not in seen:
            seen.add(r["url"])
            posts.append(r)
    keyword = [r for r in posts if TOPIC.search(f"{r['title'] or ''} {r['text']}")]
    short = [r for r in keyword if SIP_CONTEXT.search(f"{r['title'] or ''} {r['text']}")]
    def score(r):      # the title says most: stop / failure words in the title count most, then in the text; SIP in the title helps
        title, text = r["title"] or "", r["text"]
        return 5 * len(CORE.findall(title)) + 3 * bool(re.search(r"\bsips?\b", title, re.I)) + 2 * len(TOPIC.findall(title)) + min(len(TOPIC.findall(text)), 3)
    short.sort(key=lambda r: (-score(r), r["created_at"] or ""))
    def title_signal(r):
        return 5 * len(CORE.findall(r["title"] or "")) + 3 * bool(re.search(r"\bsips?\b", r["title"] or "", re.I))
    SHORTLIST_FILE.write_text(json.dumps([{"url": r["url"], "title": r["title"], "created_at": r["created_at"], "sub": r["source_detail"],
                                           "title_signal": title_signal(r)} for r in short], indent=1))
    print(f"  of these, {sum(1 for r in short if title_signal(r) > 0)} have a stop / failure / SIP word in the TITLE (only those get comments in step 3)")
    print(f"STEP 2 (free): {len(posts)} unique posts, {len(keyword)} mention a stop / failure / loss / income word, "
          f"{len(short)} of those are also about SIPs or mutual funds -> shortlist")
    for r in short:
        print(f" - [{r['sub'] if 'sub' in r else r['source_detail'][:22]}] {r['created_at'][:10] if r['created_at'] else '?'} | {r['title']}")


def do_comments(cfg: dict, price: dict) -> None:
    """Step 3: comments only for shortlisted threads, your own URLs first, within what is left of the budget."""
    short = json.loads(SHORTLIST_FILE.read_text())
    urls = list(dict.fromkeys(read_threads() + [x["url"] for x in short if x.get("title_signal", 0) > 0]))
    per_thread = cfg["comments_stage_max_comments"] + 1                      # the post itself is returned again and charged
    left = cfg["budget_total_usd"] - spent(cfg) - price["start_per_gb"] * price["memory_mb"] / 1024
    afford = int(left * 0.85 / (per_thread * price["per_result"]))           # 15% safety margin
    chosen = urls[:afford]
    titles = {x["url"]: x["title"] for x in short}
    for i, u in enumerate(chosen, 1):
        print(f"   {i:2d}. {titles.get(u) or u}")
    print(f"STEP 3: {len(urls)} threads wanted ({len(read_threads())} of yours first), budget left ${cfg['budget_total_usd'] - spent(cfg):.3f}, "
          f"worst case {per_thread} items per thread -> {len(chosen)} threads will be fetched")
    if not chosen:
        sys.exit("Nothing affordable.")
    inp = {**base_input(cfg), "startUrls": [{"url": u} for u in chosen], "maxComments": cfg["comments_stage_max_comments"],
           "maxPostCount": len(chosen)}
    run = run_actor(cfg, price, account(), inp, len(chosen) * per_thread, "comments")
    items = strip_authors(run["items"])
    COMMENTS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    recs, skipped = map_items(strip_authors(json.loads(POSTS_FILE.read_text(encoding="utf-8"))) + items, cfg["min_year"])
    keep_threads = {thread_of(u) for u in chosen}
    recs = [r for r in recs if thread_of(r["url"]) in keep_threads]          # only the chosen threads: posts + their comments
    save_records(recs, "reddit_apify.jsonl")
    posts = sum(1 for r in recs if r["source_detail"].endswith("post"))
    after = account()
    summary = {"source": "reddit_apify", "actor": cfg["actor"], "threads": len(chosen), "items_received_step3": len(items), "saved": len(recs),
               "posts": posts, "comments": len(recs) - posts, "skipped": skipped, "ledger": ledger(), "credit_used_usd": round(spent(cfg), 4),
               "monthly_used_after": after["used"], "run_at": datetime.now(timezone.utc).isoformat()}
    (RAW_DIR / "apify_reddit_summary.json").write_text(json.dumps(summary, indent=1))
    print(f"\nDone: {len(chosen)} threads, {len(items)} items received, {len(recs)} saved ({posts} posts, {len(recs) - posts} comments). "
          f"Total credit used (all runs): ${spent(cfg):.4f} of the ${cfg['budget_total_usd']:.2f} budget.")


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pricing", action="store_true")
    g.add_argument("--test", action="store_true")
    g.add_argument("--recover", nargs=2, metavar=("RUN_ID", "LABEL"), help="take over a finished run that was not saved, e.g. NXb... r/mutualfunds")
    g.add_argument("--stage", choices=["posts", "shortlist", "comments"])
    ap.add_argument("--approved", action="store_true", help="required for the comments stage: you have seen the shortlist")
    a = ap.parse_args()
    cfg = load_config()["reddit_apify"]
    if a.stage == "shortlist":
        return do_shortlist(cfg)
    if a.recover:
        return recover(*a.recover)
    price, acct = pricing(cfg), account()
    print(f"Spent so far on Reddit via Apify: ${spent(cfg):.4f} of the ${cfg['budget_total_usd']:.2f} budget "
          f"(account credit left ${acct['cap'] - acct['used']:.2f}); per result ${price['per_result']:.4f} = ${1000 * price['per_result']:.2f} per 1,000")
    if a.pricing:
        return
    if a.test:
        do_test(cfg, price, acct)
    elif a.stage == "posts":
        do_posts(cfg, price, acct)
    else:
        if not SHORTLIST_FILE.exists():
            sys.exit("Do the shortlist step first and look at it.")
        if not a.approved:
            sys.exit("The comments stage needs --approved, after you have seen the shortlist.")
        do_comments(cfg, price)


if __name__ == "__main__":
    main()
