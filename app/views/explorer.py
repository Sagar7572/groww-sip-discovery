"""Page 6: filter the relevant tagged posts and read them. Shows quote_display only."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import common as C


def render(over: dict, posts: pd.DataFrame) -> None:
    st.title(f"Read the evidence yourself: {len(posts):,} relevant tagged posts, filterable by source, stage, action, reason and more")
    tagged = over["funnel"]["tagged_ok"]
    st.caption(f"This list shows the {len(posts):,} relevant tagged posts only (of {tagged:,} tagged; the other {tagged - len(posts):,} were judged not to be about SIPs). "
               "Every number in this tool can be traced back to posts here. Quotes that could not be verified are hidden.")

    def opts(col, mapper=None):
        vals = sorted(posts[col].dropna().unique(), key=str)
        return vals

    c1, c2, c3, c4 = st.columns(4)
    source = c1.multiselect("Source", opts("source"), format_func=lambda x: C.SOURCE_NAMES.get(x, x))
    years = sorted(posts.year.dropna().astype(int).unique(), reverse=True)
    year = c2.multiselect("Year (default: 2021 onward; clear it to see older posts)", years, default=[y for y in years if y >= 2021])
    stage = c3.multiselect("Journey stage", [s for s in C.STAGE_ORDER if s in set(posts.stage)], format_func=C.nice)
    action = c4.multiselect("What happened to the SIP", opts("action"), format_func=C.nice_action)
    c5, c6, c7, c8 = st.columns(4)
    lapse = c5.multiselect("Lapse type", opts("lapse_type"), format_func=C.nice)
    all_triggers = sorted({t for ts in posts.triggers for t in ts})
    trigger = c6.multiselect("Stated reason", all_triggers, format_func=C.nice)
    lang = c7.multiselect("Language", opts("language"))
    tagger = c8.multiselect("Tagger", opts("tagged_by"))
    search = st.text_input("Search the text (optional)")

    df = posts
    for col, vals in (("source", source), ("year", year), ("stage", stage), ("action", action), ("lapse_type", lapse), ("language", lang), ("tagged_by", tagger)):
        if vals:
            df = df[df[col].isin(vals)]
    if trigger:
        df = df[df.triggers.apply(lambda t: any(x in t for x in trigger))]
    if search:
        df = df[df.text.str.contains(search, case=False, regex=False)]

    df = df.sort_values(["severity", "year"], ascending=[False, False], kind="stable")        # most severe first, then newest
    st.write(f"**{len(df):,} posts match**, most severe first, then newest." + (" Showing the first 500." if len(df) > 500 else ""))
    show = df.head(500)
    table = pd.DataFrame({
        "Source": show.source.map(lambda s: C.SOURCE_NAMES.get(s, s)), "Year": show.year, "Post": show.text.str.slice(0, 280),
        "Verified quote": show.quote_display.fillna("(not shown: could not be verified)" ),
        "Stage": show.stage.map(C.nice), "SIP action": show.action.map(C.nice_action), "Lapse": show.lapse_type.map(C.nice),
        "Problem area (AI)": show.problem_area.map(lambda x: C.nice(x) if isinstance(x, str) else ""),
        "Reasons": show.triggers.map(lambda t: ", ".join(C.nice(x) for x in t if x != "none") or "none given"),
        "Emotion": show.emotion.map(C.nice), "Severity": show.severity, "Language": show.language, "Tagger": show.tagged_by,
        "Needs review": show.needs_review.map({True: "yes", False: ""}), "Link": show.url,
    })
    st.dataframe(table, hide_index=True, width="stretch", height=560,
                 column_config={"Link": st.column_config.LinkColumn("Link", display_text="open"), "Post": st.column_config.TextColumn(width="large"),
                                "Verified quote": st.column_config.TextColumn(width="medium")})
    st.caption("Tags are written by AI and can be wrong; \"Needs review\" marks posts whose quote could not be verified. The AI also writes the deeper reason and the unmet need, shown in the full record when you pick a post below.")
    if len(df):
        pick = st.selectbox("Open one post's full tags", range(min(len(df), 500)), format_func=lambda i: f"{C.SOURCE_NAMES.get(df.iloc[i].source, df.iloc[i].source)}: {df.iloc[i].text[:90]}")
        r = df.iloc[pick]
        st.markdown(f"**Post:** {r.text}")
        if r.context:
            st.caption(f"Context it replies to: {r.context}")
        st.markdown(f"- **Deeper reason (AI):** {r.reason}\n- **Unmet need (AI):** {r.unmet_need}\n- **Emotion:** {C.nice(r.emotion)}  ·  **Severity:** {r.severity}\n"
                    f"- **Tagged by:** {r.tagged_by}  ·  **Quick filter said:** {r.filter_label}")
