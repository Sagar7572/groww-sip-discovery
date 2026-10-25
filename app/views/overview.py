"""Page 1: how the engine works, what it has read, where it stands."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import common as C


def render(over: dict, posts: pd.DataFrame) -> None:
    f, src = over["funnel"], over["sources"]
    active = [s for s, v in src.items() if v["clean"]]
    st.title(f"The engine has read {f['clean']:,} public posts from {len(active)} sources; {f['relevant_tagged']:,} relevant ones are tagged and analysed so far")
    st.write("Every number in this tool comes from public reviews, forum posts and video comments, read and tagged by AI, "
             "with simple code checking the AI's work. The steps below show how.")

    d = over.get("definitions", {})
    st.info(f"**Two words used the same way on every page.** **Tagged** = {d.get('tagged', '')}  \n"
            f"**Relevant** = {d.get('relevant', '')}  \n"
            f"**Staff replies** = {d.get('staff', '')} ({over.get('staff_excluded', 0):,} such posts are excluded.)  \n"
            f"Right now: **{f['tagged_ok']:,} tagged**, of which **{f['relevant_tagged']:,} relevant** and {f['tagged_not_relevant']:,} not.")

    dot = f'''digraph G {{
      rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", fillcolor="#e8f0fb", color="#2a78d6",
      fontname="Helvetica", fontsize=11, margin="0.15,0.08"]; edge [color="#6b6b66", arrowsize=0.7];
      c [label="1. Collect\\n{f['raw_pulled']:,} pulled\\n(app reviews, forum,\\nYouTube)"];
      cl [label="2. Clean\\n{f['clean']:,} kept\\n(duplicates and\\ntiny posts removed)"];
      r [label="3. Quick filter\\n{f['filter_kept']:,} kept so far\\nof {f['filter_labelled']:,} checked\\n(AI + 2 code rules)"];
      t [label="4. Tag\\n{f['tagged_ok']:,} tagged, {f['relevant_tagged']:,}\\nrelevant (AI fills\\na fixed form)"];
      a [label="5. Analyse\\ncount, compare,\\ngroup themes,\\nrank opportunities"];
      v [label="6. Validate\\nsecond AI tagger,\\ncode checks, hand-\\nlabelled set (to come)"];
      c -> cl -> r -> t -> a -> v; }}'''
    st.graphviz_chart(dot, width="stretch")

    with st.expander("What happens at each step, in plain words"):
        st.markdown(
            "1. **Collect**: public Play Store and App Store reviews of Groww, posts from the TradingQ&A forum and comments on "
            "YouTube videos about SIPs. Usernames are never stored; phone numbers, emails and account numbers are masked.\n"
            "2. **Clean**: exact and near-identical copies are removed (for example one comment posted 170 times) and posts under six words "
            "are dropped unless they mention a SIP word.\n"
            "3. **Quick filter**: an AI model says *yes / no / unsure* to \"is this about SIP or mutual fund investing?\". "
            "A wrong \"no\" loses data for good, so two plain-code rules turn risky \"no\" answers into \"unsure\".\n"
            "4. **Tag**: a stronger AI model fills one fixed form (the *codebook*) for each post: where the person is in their journey, what happened to the SIP, "
            "whether stopping was their choice, the reasons they give, the deeper reason, emotion, severity and an exact quote.\n"
            "5. **Analyse**: the tags are counted and compared, posts are grouped by meaning to find themes nobody planned for, and each problem area is scored.\n"
            "6. **Validate**: a second AI model tags the same posts as a check, code verifies every quote, and the engine's work is compared with a small set of "
            "posts labelled by hand (coming). Page 8 shows this.")

    left, right = st.columns([1, 1])
    with left:
        st.subheader(f"From {f['raw_pulled']:,} pulled posts to {f['relevant_tagged']:,} relevant tagged ones")
        funnel = pd.DataFrame([
            ("Pulled from the sources", f["raw_pulled"]), ("Kept after cleaning", f["clean"]),
            ("Chosen for tagging (the sample)", f["in_tagging_queue"]),
            ("Tagged so far", f["tagged_ok"]), ("Relevant tagged posts (used everywhere)", f["relevant_tagged"])], columns=["label", "n"])
        st.altair_chart(C.hbar(funnel), width="stretch")
        st.caption(f"The sample is every TradingQ&A and App Store post, the Play Store posts, and a random part of the YouTube comments; "
                   "posts with words like stop, pause, failed or autopay go first. "
                   f"The quick relevance filter has checked {f['filter_labelled']:,} of {f['clean']:,} cleaned posts and decides which of the other posts are tagged; "
                   f"the {f['tagged_not_relevant']:,} tagged posts that turned out not to be about SIPs are left out of every analysis.")
    with right:
        st.subheader("Where the posts come from and which years they cover")
        years = pd.DataFrame([(C.SOURCE_NAMES.get(s, s), str(y), n) for s, v in src.items() for y, n in v["by_year"].items()],
                             columns=["source", "year", "posts"])
        names = [C.SOURCE_NAMES[s] for s in C.SOURCE_COLORS if s in src and src[s]["clean"]]
        cols = [C.SOURCE_COLORS[s] for s in C.SOURCE_COLORS if s in src and src[s]["clean"]]
        st.altair_chart(C.stacked_bar(years, "posts", "year", "source", names, cols, order=sorted(years.year.unique()), horizontal=False,
                                      x_title="Cleaned posts"), width="stretch")
        st.caption("2021 onward is the main analysis window; older posts are kept and reported separately.")

    st.subheader("Volumes per source")
    rows = []
    for s, v in src.items():
        rows.append({"Source": C.SOURCE_NAMES.get(s, s), "Pulled": f"{v['raw_pulled']:,}" if v["raw_pulled"] else "not collected",
                     "Cleaned": f"{v['clean']:,}", "Passed quick filter (so far)": "skipped, tagged first" if s == "reddit" else f"{v['filter_kept']:,}", "Tagged": f"{v['tagged']:,}",
                     "Relevant (analysed)": f"{v['relevant']:,}",
                     "First post": v["first_date"] or "n/a", "Latest post": v["last_date"] or "n/a"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Reddit is a curated sample, not all of Reddit: 35 threads about stopping, pausing or failing SIPs, picked from search results in r/IndiaInvestments, r/mutualfunds and r/personalfinanceindia and collected through a third-party scraper (Apify). It is first in the tagging queue, but tagging runs under free daily limits, so it fills in over several days. "
               "Counts follow the definitions above: \"Relevant\" is what the rest of the dashboard uses.")

    st.subheader("The AI models and what each one does")
    st.table(pd.DataFrame(over["models"]).rename(columns={"stage": "Step", "model": "Model", "job": "What it does"}))
    st.caption("All models are free-tier. Tagging is limited by free daily allowances, so it runs over several days and the numbers here grow every refresh.")
