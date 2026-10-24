"""Comments on personal-finance YouTube videos (free YouTube Data API key).

Quota use: each search costs 100 units, each page of 100 comments costs 1.
With the default config this is roughly 600 + 300 = ~900 of the free 10,000 daily units.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from collect.common import ROOT, load_config, make_record, save_records


def collect() -> dict:
    load_dotenv(ROOT / ".env")
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        print("  YouTube: no YOUTUBE_API_KEY in .env, skipping")
        return {"source": "youtube", "pulled": 0, "kept": 0, "skipped": True}

    cfg = load_config()["youtube"]
    yt = build("youtube", "v3", developerKey=key, cache_discovery=False)

    videos = {vid: None for vid in cfg.get("extra_video_ids") or []}
    for q in cfg["search_queries"]:
        res = yt.search().list(q=q, part="snippet", type="video", maxResults=cfg["videos_per_query"],
                               regionCode="IN", relevanceLanguage="en").execute()
        for item in res.get("items", []):
            videos[item["id"]["videoId"]] = item["snippet"]["title"]
        print(f"  YouTube search '{q}': {len(res.get('items', []))} videos")

    kept = []
    for vid, title in videos.items():
        token, pages = None, 0
        while pages < cfg["max_comment_pages_per_video"]:
            try:
                res = yt.commentThreads().list(videoId=vid, part="snippet,replies", maxResults=100,
                                               pageToken=token, textFormat="plainText").execute()
            except HttpError as exc:                 # comments disabled etc.
                print(f"    skipped video {vid}: {exc.status_code if hasattr(exc, 'status_code') else exc}")
                break
            for thread in res.get("items", []):
                top = thread["snippet"]["topLevelComment"]
                comments = [top] + thread.get("replies", {}).get("comments", [])
                for c in comments:
                    s = c["snippet"]
                    kept.append(make_record(
                        "youtube", c["id"], s.get("textDisplay", ""),
                        title=title,
                        source_detail="comment" if c is top else "reply",
                        url=f"https://www.youtube.com/watch?v={vid}",
                        created_at=s.get("publishedAt"),
                    ))
            pages += 1
            token = res.get("nextPageToken")
            if not token:
                break

    print(f"  YouTube: {len(videos)} videos, {len(kept)} comments")
    save_records(kept, "youtube.jsonl")
    return {"source": "youtube", "pulled": len(kept), "kept": len(kept), "videos": len(videos)}


if __name__ == "__main__":
    print(collect())
