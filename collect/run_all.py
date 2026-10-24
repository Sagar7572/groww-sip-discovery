"""Run every collector and write a summary for the Evidence Log.

Usage (from the project folder):
    python -m collect.run_all                 # all sources
    python -m collect.run_all play_store      # just one or a few sources
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone

from collect import app_store, play_store, reddit, tradingqna, youtube
from collect.common import RAW_DIR

COLLECTORS = {
    "play_store": play_store.collect,
    "app_store": app_store.collect,
    "tradingqna": tradingqna.collect,
    "youtube": youtube.collect,
    "reddit": reddit.collect,
}


def main(names: list[str]) -> None:
    names = names or list(COLLECTORS)
    summary = []
    for name in names:
        print(f"\n== {name} ==")
        try:
            summary.append(COLLECTORS[name]())
        except Exception as exc:        # one source failing should not stop the rest
            traceback.print_exc()
            summary.append({"source": name, "error": str(exc)})

    stats_path = RAW_DIR / "collection_summary.json"
    old = json.loads(stats_path.read_text()) if stats_path.exists() else {}
    for s in summary:
        s["run_at"] = datetime.now(timezone.utc).isoformat()
        old[s["source"]] = s
    stats_path.write_text(json.dumps(old, indent=2))

    print("\n== Summary ==")
    for s in summary:
        status = s.get("error") or f"pulled {s.get('pulled', 0)}, kept {s.get('kept', 0)}"
        print(f"  {s['source']:<12} {status}")
    print(f"\nUpload everything in the data/raw folder to the chat.")


if __name__ == "__main__":
    main(sys.argv[1:])
