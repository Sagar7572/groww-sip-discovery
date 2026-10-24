"""Groww reviews from Google Play (no API key needed)."""
from __future__ import annotations

import time

from google_play_scraper import Sort, reviews

from collect.common import build_keyword_matcher, load_config, make_record, save_records


def collect() -> dict:
    cfg = load_config()
    package = cfg["app"]["play_store_package"]
    country = cfg["app"]["country"]
    max_reviews = cfg["play_store"]["max_reviews"]
    matches = build_keyword_matcher(cfg["keywords"])

    pulled, kept, seen = 0, [], set()    # same review can appear in several language pulls
    for lang in cfg["play_store"]["languages"]:
        token, fetched = None, 0
        print(f"  Play Store [{lang}] ...")
        while fetched < max_reviews:
            batch, token = reviews(package, lang=lang, country=country,
                                   sort=Sort.NEWEST, count=200,
                                   continuation_token=token)
            if not batch:
                break
            fetched += len(batch)
            for r in batch:
                if r["reviewId"] in seen:
                    continue
                seen.add(r["reviewId"])
                text = r.get("content") or ""
                if matches(text):
                    kept.append(make_record(
                        "play_store", r["reviewId"], text,
                        source_detail=f"lang={lang}",
                        created_at=r.get("at"),
                        rating=r.get("score"),
                    ))
            if token is None or token.token is None:
                break
            time.sleep(0.5)          # be polite to the server
        pulled += fetched
        print(f"    pulled {fetched}, kept so far {len(kept)}")

    save_records(kept, "play_store.jsonl")
    return {"source": "play_store", "pulled": len(seen), "kept": len(kept)}


if __name__ == "__main__":
    print(collect())
