"""Groww reviews from Apple's public App Store reviews feed (no API key needed)."""
from __future__ import annotations

import time

import requests

from collect.common import build_keyword_matcher, load_config, make_record, save_records

HEADERS = {"User-Agent": "groww-sip-research/0.1"}


def find_app_id(term: str, country: str) -> int:
    resp = requests.get("https://itunes.apple.com/search",
                        params={"term": term, "country": country,
                                "entity": "software", "limit": 5},
                        headers=HEADERS, timeout=20)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    for app in results:
        if term.lower() in app.get("trackName", "").lower():
            print(f"  App Store app: {app['trackName']} (id {app['trackId']})")
            return app["trackId"]
    raise RuntimeError("Could not find the app on the App Store; set app_store_id in config.yaml")


def collect() -> dict:
    cfg = load_config()
    country = cfg["app"]["country"]
    app_id = cfg["app"].get("app_store_id") or find_app_id(cfg["app"]["app_store_search_term"], country)
    matches = build_keyword_matcher(cfg["keywords"])

    pulled, kept = 0, []
    for page in range(1, cfg["app_store"]["max_pages"] + 1):
        url = (f"https://itunes.apple.com/{country}/rss/customerreviews/"
               f"page={page}/id={app_id}/sortby=mostrecent/json")
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            break
        entries = resp.json().get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        entries = [e for e in entries if "im:rating" in e]   # first entry can be app info
        if not entries:
            break
        pulled += len(entries)
        for e in entries:
            title = e.get("title", {}).get("label", "")
            text = e.get("content", {}).get("label", "")
            if matches(f"{title} {text}"):
                kept.append(make_record(
                    "app_store", e.get("id", {}).get("label", title + text), text,
                    title=title,
                    created_at=e.get("updated", {}).get("label"),
                    rating=int(e.get("im:rating", {}).get("label", 0)) or None,
                ))
        time.sleep(0.5)

    print(f"  App Store: pulled {pulled}, kept {len(kept)}")
    save_records(kept, "app_store.jsonl")
    return {"source": "app_store", "pulled": pulled, "kept": len(kept)}


if __name__ == "__main__":
    print(collect())
