"""Re-fetch ONLY the staff flag of TradingQ&A posts already collected.

Discourse marks posts written by staff, moderators and admins (here: the platform's own people replying to users).
Those are the company's replies, not investors, so the engine leaves them out of every count and keeps them only as
thread context. Only three true/false fields are read; usernames and names are never read, kept or printed.

    python -m collect.tradingqna_flags

Writes data/raw/tradingqna_staff.json: {post id: true/false} for every collected TradingQ&A post.
"""
from __future__ import annotations

import json
import re
import time

from collect.common import RAW_DIR, load_config, make_id
from collect.tradingqna import get_json

OUT = RAW_DIR / "tradingqna_staff.json"


def collect_flags() -> dict:
    base = load_config()["tradingqna"]["base_url"].rstrip("/")
    records = [json.loads(l) for l in (RAW_DIR / "tradingqna.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    threads = sorted({re.search(r"/t/[^/]+/(\d+)/", r["url"]).group(1) for r in records})
    flags: dict[str, bool] = {}
    for i, tid in enumerate(threads, 1):
        try:
            topic = get_json(f"{base}/t/{tid}.json")
        except Exception as exc:
            print(f"    skipped thread {tid}: {exc}")
            continue
        for p in topic.get("post_stream", {}).get("posts", []):
            flags[make_id("tradingqna", p["id"])] = bool(p.get("staff") or p.get("moderator") or p.get("admin"))
        if i % 20 == 0:
            print(f"    {i}/{len(threads)} threads")
        time.sleep(1.5)
    mine = {r["id"]: flags.get(r["id"]) for r in records}
    OUT.write_text(json.dumps({k: v for k, v in mine.items() if v is not None}, indent=0))
    n_staff = sum(1 for v in mine.values() if v)
    missing = sum(1 for v in mine.values() if v is None)
    return {"posts": len(records), "staff_posts": n_staff, "no_flag_found": missing}


if __name__ == "__main__":
    print(collect_flags())
