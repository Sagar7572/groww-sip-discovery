"""Reddit posts and comments.

Two routes, used automatically:
1. Reddit API (PRAW) - only if REDDIT_CLIENT_ID / SECRET are in .env (needs Reddit's approval).
2. Manual file - data/manual/reddit_manual.csv, filled by hand (see README).
Both routes can be used together; results are merged.
"""
from __future__ import annotations

import csv
import os

from dotenv import load_dotenv

from collect.common import ROOT, build_keyword_matcher, load_config, make_record, save_records

MANUAL_FILE = ROOT / "data" / "manual" / "reddit_manual.csv"


def from_api(cfg: dict, matches) -> list[dict]:
    import praw

    reddit = praw.Reddit(client_id=os.getenv("REDDIT_CLIENT_ID"),
                         client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
                         user_agent=os.getenv("REDDIT_USER_AGENT", "groww-sip-research/0.1"))
    reddit.read_only = True

    out, seen_posts = [], set()
    for sub in cfg["subreddits"]:
        for q in cfg["queries"]:
            for post in reddit.subreddit(sub).search(q, sort="relevance", time_filter="all",
                                                     limit=cfg["posts_per_query"]):
                if post.id in seen_posts:
                    continue
                seen_posts.add(post.id)
                body = f"{post.title}\n{post.selftext or ''}"
                if not matches(body):
                    continue
                url = f"https://www.reddit.com{post.permalink}"
                out.append(make_record("reddit", post.id, post.selftext or post.title,
                                       title=post.title, source_detail=f"r/{sub} post",
                                       url=url, created_at=post.created_utc,
                                       rating=post.score))
                post.comments.replace_more(limit=0)
                for c in post.comments.list()[: cfg["max_comments_per_post"]]:
                    out.append(make_record("reddit", c.id, c.body, title=post.title,
                                           source_detail=f"r/{sub} comment", url=url,
                                           created_at=c.created_utc, rating=c.score))
            print(f"  Reddit r/{sub} '{q}': total items {len(out)}")
    return out


def from_manual() -> list[dict]:
    if not MANUAL_FILE.exists():
        return []
    out = []
    with open(MANUAL_FILE, encoding="utf-8-sig", newline="") as f:
        for i, row in enumerate(csv.DictReader(f), 1):
            text = (row.get("text") or "").strip()
            if not text:
                continue
            out.append(make_record("reddit", f"manual-{row.get('url', '')}-{i}", text,
                                   title=row.get("thread_title"),
                                   source_detail=f"{row.get('subreddit', '')} {row.get('kind', '')} (manual)".strip(),
                                   url=row.get("url"), created_at=row.get("date") or None))
    print(f"  Reddit manual file: {len(out)} items")
    return out


def collect() -> dict:
    load_dotenv(ROOT / ".env")
    cfg = load_config()["reddit"]
    matches = build_keyword_matcher(load_config()["keywords"])

    items, route = [], []
    if os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"):
        try:
            items += from_api(cfg, matches)
            route.append("api")
        except Exception as exc:
            print(f"  Reddit API failed ({exc}); continuing with the manual file only")
    manual = from_manual()
    if manual:
        items += manual
        route.append("manual")
    if not items:
        print("  Reddit: no API keys and no manual file yet, skipping")

    save_records(items, "reddit.jsonl")
    return {"source": "reddit", "pulled": len(items), "kept": len(items), "route": route}


if __name__ == "__main__":
    print(collect())
