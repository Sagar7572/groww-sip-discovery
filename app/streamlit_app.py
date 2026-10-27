"""Groww SIP Discovery Engine: the hosted front-end (five pages, top navigation).

Run locally:   streamlit run app/streamlit_app.py
Refresh data:  python -m pipeline.export   (then commit data/export and push; the hosted app updates itself)

The app reads only the files in data/export/. It never scrapes anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import nav  # noqa: E402
import ui  # noqa: E402
from views import browse, findings, how, nine, stops  # noqa: E402

st.set_page_config(page_title="SIP Discovery Engine", page_icon=":mag:", layout="wide", initial_sidebar_state="collapsed")


def main() -> None:
    over, posts = common.load_json("overview"), common.load_posts()
    nav.PAGES.update({
        "findings": st.Page(findings.render, title="Key findings", url_path="findings", default=True),
        "stops": st.Page(stops.render, title="What stops SIPs", url_path="what-stops-sips"),
        "nine": st.Page(nine.render, title="9 questions", url_path="nine-questions"),
        "browse": st.Page(browse.render, title="Ask & browse", url_path="ask-and-browse"),
        "how": st.Page(how.render, title="How it works", url_path="how-it-works"),
    })
    page = st.navigation(list(nav.PAGES.values()), position="top")
    ui.inject_css()
    if posts.empty or not over.get("funnel"):
        st.warning("No exported data found. Run `python -m pipeline.export` first.")
        st.stop()
    ui.banner(over, posts)
    common.QUOTES_SEEN.clear()
    page.run()


main()
