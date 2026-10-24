"""Page 2: opportunity areas ranked in two tables (why people stop; problems after stopping), with the numbers
and example quotes behind them, and the themes found without the form."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import common as C

FIX = {"yes": "something the product can fix within our rules", "partly": "something the product can only partly fix within our rules",
       "no": "not something the product can fix within our rules"}


def name_of(a: dict) -> str:
    return a["label"] or C.nice(a["key"])


def table_and_chart(areas: list[dict], what: str) -> None:
    df = pd.DataFrame([{
        "Rank": a["rank"], "Opportunity": name_of(a), "Posts": a["n"], "% of relevant tagged posts": round(100 * a["share_of_tagged"], 1),
        "Avg severity (1-3)": a["avg_severity"], "Metric-tree branch": a["branch_name"],
        "Fixable within our rules": a["solvable"], "Score (top = 100)": a["score_index"],
        "Rank if weights ignored": a["rank_equal_weights"], "Confidence": "low (under 15 posts)" if a["low_confidence"] else "ok",
    } for a in areas])
    st.dataframe(df, hide_index=True, width="stretch", height=35 * (len(df) + 1) + 3, column_config={
        "% of relevant tagged posts": st.column_config.NumberColumn(format="%.1f%%"),
        "Score (top = 100)": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d")})

    chart_df = pd.DataFrame([{"label": name_of(a), "score": a["score_index"], "branch": a["branch_name"],
                              "text": f"{a['score_index']}  (n={a['n']})"} for a in areas if a["score_index"] > 0])
    if chart_df.empty:
        return
    branch_names = {a["branch"]: a["branch_name"] for a in areas}
    domain = [branch_names[b] for b in "ABCDE" if b in branch_names]
    rng = [C.BRANCH_COLORS[b] for b in "ABCDE" if b in branch_names]
    order = list(chart_df.sort_values("score", ascending=False).label)
    base = alt.Chart(chart_df).encode(y=alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelLimit=330, ticks=False, domain=False)))
    bars = base.mark_bar(cornerRadiusEnd=4, size=16).encode(
        x=alt.X("score:Q", title=f"Opportunity score ({what}; top = 100)", axis=alt.Axis(grid=False)),
        color=alt.Color("branch:N", scale=alt.Scale(domain=domain, range=rng), legend=alt.Legend(title="Metric-tree branch", orient="bottom")),
        tooltip=["label", "score", "branch"])
    text = base.mark_text(align="left", dx=5, fontSize=12).encode(x="score:Q", text="text:N")
    st.altair_chart((bars + text).properties(height=30 * len(chart_df) + 150), width="stretch")


def quote_expanders(areas: list[dict]) -> None:
    for a in areas:
        flag = " (low confidence)" if a["low_confidence"] else ""
        with st.expander(f"#{a['rank']} {name_of(a)}: {a['n']} posts, severity {a['avg_severity']}{flag}"):
            st.markdown(f"**Branch:** {a['branch_name']} &nbsp;·&nbsp; **Fixable within our rules:** {a['solvable']}. {a['solvable_why']}")
            if not a["quotes"]:
                st.caption("No verified quotes yet.")
            for q in a["quotes"]:
                link = f" [open post]({q['url']})" if q.get("url") else ""
                st.markdown(f"> “{q['quote']}”  \n> <small>{C.SOURCE_NAMES.get(q['source'], q['source'])}{link}</small>", unsafe_allow_html=True)


def render(over: dict, posts: pd.DataFrame) -> None:
    opp, themes = C.load_json("opportunities"), C.load_json("themes")
    causes, after = opp.get("causes", []), opp.get("after_stop", [])
    if not causes:
        st.info("Not enough relevant tagged posts yet to rank opportunities.")
        return
    top = causes[0]
    st.title(f"Among causes, “{name_of(top)}” ranks first: {top['n']:,} posts ({100 * top['share_of_tagged']:.0f}% of {opp['n_tagged']:,} relevant tagged posts), "
             f"and it is {FIX[top['solvable']]}")
    st.write("Each problem area is scored as **number of posts × average severity × how directly it moves the 12-month metric × "
             "whether the product can fix it without giving fund advice or using fear, FOMO or urgency**. "
             "The weights are written-down judgements, listed below, and you can see how the ranking changes without them. "
             "Two tables keep two different questions apart: *why people stop or never get going*, and *what goes wrong after they have stopped*.")

    st.subheader("Table 1. Why people stop or never get going (causes)")
    st.caption("“Hard to use the app” is split into sub-themes (labelled “App: …”) by an AI pass that reads each post; the other rows are the reasons the posts state.")
    table_and_chart(causes, "causes")
    li = opp.get("label_info", {})
    st.caption(f"The AI read {li.get('labelled', 0):,} of {li.get('candidates', 0):,} candidate posts to place them in sub-themes. "
               f"{opp.get('app_posts_total', 0)} posts carry the reason “hard to use the app”; {opp.get('app_posts_not_ranked', 0)} of them were praise, plain questions or replies "
               "from a platform's staff and are not ranked. Autopay posts can appear in two rows (the stated reason “Autopay / payment problem” and the app sub-theme), so rows overlap.")

    st.subheader("Table 2. Problems after stopping: getting money out (redemption, withdrawal, refund)")
    if after:
        st.caption(f"{opp.get('exit_posts', 0)} posts are about money coming out. They are ranked here only and are not counted in Table 1. "
                   "These problems do not make people stop, but they damage trust and make it less likely that someone who stopped will come back, so they are placed on the Recovery branch (E).")
        table_and_chart(after, "after stopping")
    else:
        st.caption("No posts about getting money out have been labelled yet.")

    st.subheader("Example quotes behind each area")
    st.markdown("**Causes**")
    quote_expanders(causes)
    if after:
        st.markdown("**After stopping**")
        quote_expanders(after)

    with st.expander("How the score is built, and how much the ranking depends on my judgement"):
        w = opp["assumptions"]
        st.markdown(f"{w['formula'].capitalize()}.")
        st.markdown("**Metric-tree branch weights** (how directly the branch decides whether a SIP is still active after 12 months): "
                    + ", ".join(f"{k} = {v}" for k, v in w["branch_weight"].items())
                    + ".  **Fixable weights:** " + ", ".join(f"{k} = {v}" for k, v in w["solvable_weight"].items()) + ".")
        for title, areas in (("causes", causes), ("after stopping", after)):
            moved = [(name_of(a), a["rank"], a["rank_equal_weights"]) for a in areas if abs(a["rank"] - a["rank_equal_weights"]) >= 3]
            if moved:
                st.write(f"Areas in the {title} table whose rank changes by 3 or more when the weights are ignored: "
                         + "; ".join(f"{n} (#{r} with weights, #{e} without)" for n, r, e in moved) + ".")
            elif areas:
                st.write(f"No area in the {title} table moves by 3 or more places when the weights are ignored.")
        st.caption("A post can carry several reasons, so the counts overlap and do not add up to the number of posts. "
                   "The sub-theme labels are written by AI and were checked by hand on a sample (see the evidence log on page 8).")

    st.subheader("Themes the form did not name")
    st.write("Posts were also grouped by meaning, without using the form's categories, to catch problems nobody planned for. "
             "Hindi, Hinglish and Malayalam filler words were removed first so that posts group by topic and not by language. "
             "A theme where few posts carry a named reason is a candidate for something new.")
    clusters = themes.get("clusters", [])
    if not clusters:
        st.info(themes.get("note", "Themes appear once enough posts are tagged."))
        return
    byid = posts.set_index("id")
    ordered = sorted(clusters, key=lambda c: c["with_named_trigger"])

    def theme_name(c: dict) -> str:
        return c.get("name") or c["label"]

    tdf = pd.DataFrame([{"Theme (named by AI)": theme_name(c), "Distinctive words": c["label"], "Posts": c["size"],
                         "% of relevant tagged posts": round(100 * c["share"], 1),
                         "Posts with a named reason": f"{100 * c['with_named_trigger']:.0f}%", "Avg severity": c["avg_severity"]}
                        for c in ordered])
    st.dataframe(tdf, hide_index=True, width="stretch")
    st.caption("Sorted with the least-named themes first. " + (
        "Names are short descriptions written by an AI model from each group's words and example posts." if themes.get("named_by_ai")
        else "AI names are not available in this export, so the most distinctive words are shown instead."))
    for c in ordered[:3]:
        ex = [byid.loc[i] for i in c["example_ids"] if i in byid.index and byid.loc[i].quote_display]
        if ex:
            with st.expander(f"Theme: {theme_name(c)}"):
                for r in ex:
                    st.markdown(f"> “{r.quote_display}”  \n> <small>{C.SOURCE_NAMES.get(r.source, r.source)}</small>", unsafe_allow_html=True)
