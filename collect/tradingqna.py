"""Threads from TradingQ&A (Zerodha's public Discourse forum, no API key needed).

The forum is searched with the queries in config.yaml; every post in each
matching thread is kept, with the thread title stored as context.
"""
from __future__ import annotations

import html
import re
import time

import requests

from collect.common import load_config, make_record, save_records

HEADERS = {"User-Agent": "groww-sip-research/0.1", "Accept": "application/json"}
TAG_RE = re.compile(r"<[^>]+>")
QUOTE_RE = re.compile(r"<aside class=\"quote.*?</aside>", re.S)   # drop quoted replies


def clean_html(raw: str) -> str:
    raw = QUOTE_RE.sub(" ", raw or "")
    return html.unescape(TAG_RE.sub(" ", raw))


def get_json(url: str, params=None, tries: int = 3):
    for attempt in range(tries):
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        if resp.status_code == 429:                  # rate limited: wait and retry
            time.sleep(10 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Rate limited too many times: {url}")


def collect() -> dict:
    cfg = load_config()["tradingqna"]
    base = cfg["base_url"].rstrip("/")

    topic_ids = {}
    for q in cfg["queries"]:
        data = get_json(f"{base}/search.json", params={"q": q})
        for t in data.get("topics", [])[: cfg["max_topics_per_query"]]:
            topic_ids[t["id"]] = t.get("title", "")
        print(f"  TradingQ&A '{q}': {len(data.get('topics', []))} threads")
        time.sleep(1.5)

    kept = []
    for i, (tid, title) in enumerate(topic_ids.items(), 1):
        try:
            topic = get_json(f"{base}/t/{tid}.json")
        except Exception as exc:                     # skip a broken thread, keep going
            print(f"    skipped thread {tid}: {exc}")
            continue
        slug = topic.get("slug", "")
        for p in topic.get("post_stream", {}).get("posts", []):
            text = clean_html(p.get("cooked", ""))
            kept.append(make_record(
                "tradingqna", p["id"], text,
                title=title,
                source_detail="question" if p.get("post_number") == 1 else "reply",
                url=f"{base}/t/{slug}/{tid}/{p.get('post_number', 1)}",
                created_at=p.get("created_at"),
            ))
        if i % 10 == 0:
            print(f"    fetched {i}/{len(topic_ids)} threads")
        time.sleep(1.5)

    save_records(kept, "tradingqna.jsonl")
    return {"source": "tradingqna", "pulled": len(kept), "kept": len(kept),
            "threads": len(topic_ids)}


if __name__ == "__main__":
    print(collect())
