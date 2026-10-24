"""Groww SIP Discovery Engine: the hosted front-end.

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
from views import ask, explorer, metric_tree, opportunity, overview, questions, segments, validation  # noqa: E402

st.set_page_config(page_title="SIP Discovery Engine", page_icon=":mag:", layout="wide")

PAGES = {
    "1. Overview and how it works": overview,
    "2. Opportunity ranking": opportunity,
    "3. The nine questions": questions,
    "4. Metric tree": metric_tree,
    "5. Segments and sources": segments,
    "6. Evidence explorer": explorer,
    "7. Ask the data": ask,
    "8. Validation and limitations": validation,
}


def banner(over: dict) -> None:
    f = over.get("funnel", {})
    if not f:
        st.warning("No exported data found. Run `python -m pipeline.export` first.")
        return
    st.markdown(
        f"<div style='padding:8px 14px;border-left:5px solid {common.BLUE};background:rgba(42,120,214,0.08);"
        f"border-radius:4px;margin-bottom:10px;font-size:0.95rem'>"
        f"<b>Data as of {over['as_of']}</b> &nbsp;·&nbsp; {f['tagged_ok']:,} of {f['in_tagging_queue']:,} sampled posts tagged "
        f"&nbsp;·&nbsp; <b>{f['relevant_tagged']:,} relevant tagged posts</b> are used on every page &nbsp;·&nbsp; "
        f"<b>partial results</b> (collection and tagging are still running)</div>",
        unsafe_allow_html=True)


def main() -> None:
    over = common.load_json("overview")
    posts = common.load_posts()
    st.sidebar.title("SIP Discovery Engine")
    st.sidebar.caption("What public conversations say about starting, continuing and stopping a SIP in India.")
    choice = st.sidebar.radio("Pages", list(PAGES), label_visibility="collapsed")
    st.sidebar.markdown("---")
    st.sidebar.caption(common.STATUS_NOTE)
    st.sidebar.caption("All data comes from public posts, with usernames removed and personal numbers masked.")
    banner(over)
    if posts.empty:
        st.stop()
    common.QUOTES_SEEN.clear()
    PAGES[choice].render(over, posts)


main()
