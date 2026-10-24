"""Page 5: proxy-based segments and source-by-source comparisons. Small groups are flagged."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import common as C

MIN_GROUP = 15


def group_table(df: pd.DataFrame, by: str, labels: dict | None = None) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(by):
        lapse = g[g.lapse_story]
        top = C.explode_counts(g, "triggers", drop=("none", "other"))
        rows.append({"group": (labels or {}).get(key, C.nice(key)), "posts": len(g), "lapse_stories": len(lapse),
                     "pct_failure": 100 * lapse.involuntary.sum() / len(lapse) if len(lapse) else None,
                     "pct_choice": 100 * lapse.voluntary.sum() / len(lapse) if len(lapse) else None,
                     "avg_severity": round(g.severity.mean(), 2),
                     "top_reason": top.label.iloc[0] if len(top) else "n/a",
                     "confidence": f"low (under {MIN_GROUP} lapse stories)" if len(lapse) < MIN_GROUP else "ok"})
    return pd.DataFrame(rows)


def show_group(df: pd.DataFrame, title: str, by: str, labels: dict | None = None, order: list | None = None) -> None:
    st.subheader(title)
    t = group_table(df, by, labels)
    if order:
        t["_o"] = t.group.map({o: i for i, o in enumerate(order)})
        t = t.sort_values("_o").drop(columns="_o")
    st.dataframe(t.rename(columns={"group": "Group", "posts": "Posts", "lapse_stories": "Lapse stories", "pct_failure": "% failures",
                                   "pct_choice": "% own choice", "avg_severity": "Avg severity", "top_reason": "Most common reason",
                                   "confidence": "Confidence"}), hide_index=True, width="stretch",
                 column_config={"% failures": st.column_config.NumberColumn(format="%.0f%%"),
                                "% own choice": st.column_config.NumberColumn(format="%.0f%%")})
    ok = t[t.lapse_stories > 0]
    if len(ok) >= 2:
        long = ok.melt(id_vars=["group", "posts"], value_vars=["pct_failure", "pct_choice"], var_name="kind", value_name="share")
        long["kind"] = long.kind.map({"pct_failure": "Failure, not chosen", "pct_choice": "Person's choice"})
        long = long.merge(ok[["group", "lapse_stories"]], on="group")
        long["low"] = long.lapse_stories < MIN_GROUP
        ch = alt.Chart(long).mark_bar(cornerRadiusEnd=3, size=11).encode(
            y=alt.Y("group:N", sort=list(ok.group), title=None, axis=alt.Axis(labelLimit=240, ticks=False, domain=False)), yOffset="kind:N",
            x=alt.X("share:Q", title="% of the group's lapse stories", axis=alt.Axis(grid=False)),
            opacity=alt.condition("datum.low", alt.value(0.35), alt.value(1.0)),
            color=alt.Color("kind:N", scale=alt.Scale(domain=["Failure, not chosen", "Person's choice"], range=[C.ORANGE, C.BLUE]), legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["group", "kind", alt.Tooltip("share:Q", format=".0f"), "posts", "lapse_stories"]).properties(height=34 * len(ok) + 150)
        st.altair_chart(ch, width="stretch")
        if (ok.lapse_stories < MIN_GROUP).any():
            st.caption("Faded bars are groups with fewer than 15 lapse stories: low confidence, do not read much into them. "
                       "Groups with no lapse story are not shown.")


def render(over: dict, posts: pd.DataFrame) -> None:
    n = len(posts)
    irr = posts[posts.irregular_income]
    ft = posts[posts.first_time]
    stated = {f: 100 * (posts[f] != "unclear").mean() for f in ("income", "age", "money")}
    st.title(f"Only {max(stated.values()):.0f}% of posts state income, age or source of money, so segments are compared through proxies")
    cols = st.columns(4)
    for col, (label, field) in zip(cols, (("Income stability", "income"), ("Age band", "age"), ("Source of money", "money"), ("Who influenced them", "influenced_by"))):
        col.metric(f"{label}: stated", C.pct((posts[field] != "unclear").sum(), n), help="Share of relevant tagged posts where the person states or makes this very obvious.")
    st.info("The brief asks how patterns differ by income stability, age, source of money and who influenced the investor. Posts almost never say these things, "
            "so **those segments cannot be measured from public posts and will be validated through interviews**. "
            "The comparisons below use proxies that posts do reveal: the first-time flag, the source and the journey stage. "
            f"Of {n:,} relevant tagged posts, {len(ft)} are clearly from first-time investors.")
    st.markdown(f"**Irregular income:** {len(irr)} of {n:,} posts gave it as a reason, " + ("so it cannot be compared here; interviews will have to test it." if len(irr) < MIN_GROUP
                else "enough to look at on the Evidence explorer (page 6)."))
    st.caption("A group needs at least 15 lapse stories (posts where a SIP stopped, is at risk, or a payment failed) to be read with confidence; smaller groups are marked low confidence.")

    show_group(posts, "First-time investors against others", "investor_type", order=["First-time investor", "Experienced investor", "Not stated"])
    show_group(posts, "Source by source", "source", labels=C.SOURCE_NAMES)
    show_group(posts, "Journey stage", "stage", order=[C.nice(s) for s in C.STAGE_ORDER])

    st.subheader("Which reasons dominate in each source?")
    trig = posts.explode("triggers")
    trig = trig[~trig.triggers.isin(["none", "other"])]
    tot = posts.groupby("source").size()
    m = trig.groupby(["source", "triggers"]).size().reset_index(name="n")
    m["share"] = 100 * m.n / m.source.map(tot)
    m["source_name"] = m.source.map(C.SOURCE_NAMES)
    m["reason"] = m.triggers.map(C.nice)
    m["posts_in_source"] = m.source.map(tot)
    keep = trig.triggers.value_counts().head(8).index
    m = m[m.triggers.isin(keep)]
    heat = alt.Chart(m).mark_rect(stroke="white", strokeWidth=2).encode(
        x=alt.X("source_name:N", title=None, axis=alt.Axis(labelAngle=0)), y=alt.Y("reason:N", title=None, sort=[C.nice(k) for k in keep], axis=alt.Axis(labelLimit=240)),
        color=alt.Color("share:Q", scale=alt.Scale(range=["#cde2fb", "#0d366b"]), legend=alt.Legend(title="% of the source's posts")),
        tooltip=["source_name", "reason", alt.Tooltip("share:Q", format=".0f"), "n", "posts_in_source"])
    txt = alt.Chart(m).mark_text(fontSize=12).encode(x="source_name:N", y=alt.Y("reason:N", sort=[C.nice(k) for k in keep]),
                                                     text=alt.Text("share:Q", format=".0f"),
                                                     color=alt.condition("datum.share > 14", alt.value("white"), alt.value("black")))
    st.altair_chart((heat + txt).properties(height=36 * len(keep) + 90), width="stretch")
    small = [C.SOURCE_NAMES.get(s, s) for s, k in tot.items() if k < MIN_GROUP]
    st.caption("Cells show the percentage of that source's relevant tagged posts that give the reason. "
               + (f"Low confidence (fewer than 15 posts): {', '.join(small)}. " if small else "")
               + "Sources differ in who writes: app reviews skew negative, TradingQ&A is a Zerodha community of more experienced investors, YouTube comments are short and noisy.")
