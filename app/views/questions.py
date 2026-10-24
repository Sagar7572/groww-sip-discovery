"""Page 3: the nine questions from the brief, each answered with a chart, key numbers and real quotes."""
from __future__ import annotations

import re
from collections import Counter

import altair as alt
import pandas as pd
import streamlit as st

import common as C

ACTIVE_STOP = ["considering_stop", "paused", "reduced", "stopped", "instalment_failed"]
CONTINUING = ["continuing", "increased", "started"]
STOP_WORDS = set("""a an the and or but if of to in on for with at by from is are was were be been it its this that these those i me my we our you your
they them he she his her as so not no do does did have has had can could will would should just very too also than then there here what when where which who how why
sip sips mutual fund funds groww app invest investing investment money pay paid get got want need needed""".split())


def metric_row(items: list[tuple[str, str, str | None]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value, help_) in zip(cols, items):
        col.metric(label, value, help=help_)


def trigger_bar(df: pd.DataFrame, total: int, top: int = 8, color: str = C.BLUE) -> None:
    counts = C.explode_counts(df, "triggers", drop=("none", "other")).head(top)
    if counts.empty:
        st.caption("No stated reasons in this group yet.")
        return
    st.altair_chart(C.hbar(counts[["label", "n"]], total=total, color=color, title="Posts mentioning this reason"), width="stretch")


def render(over: dict, posts: pd.DataFrame) -> None:
    n = len(posts)
    lapse = posts[posts.lapse_story]
    top = C.explode_counts(posts, "triggers", drop=("none", "other")).head(2)
    top_txt = " and ".join(f"“{r.label}” ({100 * r.n / n:.0f}%)" for r in top.itertuples()) if len(top) else "no clear reason yet"
    st.title(f"What {n:,} relevant tagged posts say about the nine questions: the most common stated reasons are {top_txt}")
    st.write("Each section answers one question from the brief with what the posts actually say. Where public posts say little "
             "(for example how often people check their investments), the section says so plainly.")
    if n < 50:
        st.warning("Fewer than 50 relevant posts are tagged, so treat every number here as a first look.")

    # Q1 ------------------------------------------------------------------
    with st.expander("1. Why do people start a SIP, and what do they expect?", expanded=True):
        start = posts[posts.stage.isin(["before_start", "month_0_1"]) | posts.action.eq("started")]
        exp = posts[posts.triggers.apply(lambda t: "expectation_mismatch" in t)]
        metric_row([("Posts from people starting out", f"{len(start):,}", "Posts at the stage before starting or in the first month, or about starting a SIP."),
                    ("Posts about expecting faster growth", f"{len(exp):,}", "Posts tagged with the reason 'expected faster growth'."),
                    ("First-time investors", C.pct(posts.first_time.sum(), n), "Share of relevant tagged posts where the person is clearly a first-time investor.")])
        if len(start) >= 5:
            st.altair_chart(C.hbar(C.counts_frame(start.emotion, top=7)[["label", "n"]], total=len(start), title="How people starting out feel"), width="stretch")
        C.show_quotes(start, 2)
        st.caption("Public posts rarely say why someone started. What they do show is what people expect (steady, visible growth) and what they struggle with at the start.")

    # Q2 ------------------------------------------------------------------
    with st.expander("2. What changes in behaviour in the months after starting?"):
        known = posts[posts.stage != "unclear"]
        if len(known) >= 5:
            d = known.groupby(["stage", known.lapse_type.map(lambda x: x if x in ("voluntary", "involuntary", "both") else "no lapse or unclear")]).size().reset_index(name="posts")
            d["stage_label"] = d.stage.map(C.nice)
            d["kind"] = d.lapse_type.map(lambda x: {"voluntary": "Person chose to stop", "involuntary": "Stopped without choosing", "both": "Both"}.get(x, "No lapse or unclear"))
            st.altair_chart(C.stacked_bar(d, "posts", "stage_label", "kind",
                                          ["Stopped without choosing", "Person chose to stop", "Both", "No lapse or unclear"],
                                          [C.ORANGE, C.BLUE, C.AQUA, "#cfcfca"], order=[C.nice(s) for s in C.STAGE_ORDER if s != "unclear"],
                                          x_title="Posts"), width="stretch")
            early = known[known.stage.isin(["month_0_1", "month_1_3"])]
            metric_row([("Posts that state a stage", f"{len(known):,}", f"{100 * len(known) / n:.0f}% of relevant tagged posts; the rest do not say when."),
                        ("Early months (first 3)", f"{len(early):,}", None),
                        ("Early posts that are lapse stories", C.pct(early.lapse_story.sum(), len(early)), None)])
        C.show_quotes(lapse[lapse.stage.isin(["month_1_3", "month_4_12"])], 2)
        st.caption("Most posts do not say how long the person has been investing, so this view rests on the minority that do.")

    # Q3 ------------------------------------------------------------------
    with st.expander("3. What leads investors to pause, reduce or stop?"):
        stop = posts[posts.action.isin(ACTIVE_STOP)]
        metric_row([("Posts about pausing, reducing or stopping", f"{len(stop):,}", None),
                    ("Lapse stories (stop, pause or failure)", f"{len(lapse):,}", "Posts where a SIP stopped, is at risk, or a payment failed."),
                    ("...where the person did not choose it", C.pct(lapse.involuntary.sum(), len(lapse)), "Autopay or payment failures and similar.")])
        trigger_bar(lapse, len(lapse))
        C.show_quotes(lapse, 3)

    # Q4 ------------------------------------------------------------------
    with st.expander("4. What do investors check, and how often, once they have started?"):
        how_often = posts[posts.checking_stated]
        what = posts[posts.checks_stated]
        mention = posts[posts.checking_stated | posts.checks_stated]
        metric_row([("Posts that say how often they check or what they look at", f"{len(mention):,}", "Either field filled in by the tagger."),
                    ("...say how often", f"{len(how_often):,}", None), ("...say what they look at", f"{len(what):,}", None),
                    ("Share of relevant tagged posts", C.pct(len(mention), n), None)])
        if len(how_often):
            st.altair_chart(C.hbar(C.counts_frame(how_often.checking)[["label", "n"]], total=len(how_often), title="How often they check"), width="stretch")
        chk = C.explode_counts(posts, "checks", drop=("not_mentioned",))
        if len(chk):
            st.altair_chart(C.hbar(chk[["label", "n"]].head(6), total=len(what), color=C.AQUA, title="What they look at"), width="stretch")
        C.show_quotes(mention, 2)
        st.caption("Almost no public post says how often the person checks. This question needs interviews; the engine cannot answer it from posts alone.")

    # Q5 ------------------------------------------------------------------
    with st.expander("5. What confuses or worries them inside the app?"):
        app_t = ["app_experience", "confusing_numbers", "mandate_payment_issue", "trust_concern"]
        inapp = posts[posts.triggers.apply(lambda t: any(x in t for x in app_t))]
        metric_row([("Posts about app confusion or worry", f"{len(inapp):,}", None), ("Share of relevant tagged posts", C.pct(len(inapp), n), None),
                    ("Most common feeling", C.nice(inapp.emotion.mode().iloc[0]) if len(inapp) else "n/a", None)])
        d = C.explode_counts(inapp, "triggers", drop=("none", "other"))
        d = d[d.key.isin(app_t)]
        if len(d):
            st.altair_chart(C.hbar(d[["label", "n"]], total=len(inapp), title="Posts mentioning this"), width="stretch")
        C.show_quotes(inapp, 3)

    # Q6 ------------------------------------------------------------------
    with st.expander("6. What do they do outside the app when they feel unsure?"):
        out = C.explode_counts(posts, "outside", drop=("none_mentioned",))
        out_posts = posts[posts.outside_stated]
        metric_row([("Posts that mention an outside action", f"{len(out_posts):,}", None), ("Share of relevant tagged posts", C.pct(len(out_posts), n), None)])
        if len(out):
            st.altair_chart(C.hbar(out[["label", "n"]], total=n, color=C.ORANGE, title="Posts mentioning this (% of all relevant tagged posts)"), width="stretch")
        src = posts.source.value_counts()
        st.write("The sources themselves are outside-the-app behaviour: " + ", ".join(f"{C.SOURCE_NAMES.get(s, s)} ({k:,} posts)" for s, k in src.items())
                 + ". People who go to a forum or a video comment box are often looking for reassurance or an answer the app did not give.")
        C.show_quotes(out_posts, 2)

    # Q7 ------------------------------------------------------------------
    with st.expander("7. What separates investors who continue from those who quietly drop off?"):
        cont = posts[posts.action.isin(CONTINUING)]
        drop = posts[posts.action.isin(ACTIVE_STOP)]
        metric_row([("Posts from people continuing", f"{len(cont):,}", None), ("Posts about stopping or failing", f"{len(drop):,}", None),
                    ("First-time share: continuing vs stopping", f"{C.pct(cont.first_time.sum(), len(cont))} vs {C.pct(drop.first_time.sum(), len(drop))}", None)])
        if len(cont) >= 5 and len(drop) >= 5:
            rows = []
            for label, grp in (("Continuing", cont), ("Stopping or failing", drop)):
                cnt = C.explode_counts(grp, "triggers", drop=("none", "other"))
                for _, r in cnt.iterrows():
                    rows.append({"group": label, "reason": r.label, "share": 100 * r.n / len(grp)})
            d = pd.DataFrame(rows)
            keep = d.groupby("reason").share.max().nlargest(7).index
            d = d[d.reason.isin(keep)]
            ch = alt.Chart(d).mark_bar(cornerRadiusEnd=3, size=12).encode(
                y=alt.Y("reason:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240, ticks=False, domain=False)),
                yOffset="group:N", x=alt.X("share:Q", title="% of posts in the group", axis=alt.Axis(grid=False)),
                color=alt.Color("group:N", scale=alt.Scale(domain=["Continuing", "Stopping or failing"], range=[C.BLUE, C.ORANGE]), legend=alt.Legend(title=None, orient="bottom")),
                tooltip=["group", "reason", alt.Tooltip("share:Q", format=".0f")]).properties(height=36 * len(keep) + 150)
            st.altair_chart(ch, width="stretch")
        st.caption("Bias to keep in mind: people who are happy and still investing write far fewer posts, so this comparison is lopsided. "
                   "What it can show is which reasons appear in the stopping posts and rarely in the continuing ones.")
        C.show_quotes(cont, 2)

    # Q8 ------------------------------------------------------------------
    with st.expander("8. How do these patterns differ across user segments?"):
        unclear_share = {f: 100 * posts[f].eq("unclear").mean() for f in ("income", "age", "money", "influenced_by")}
        metric_row([("Posts that state income stability", f"{100 - unclear_share['income']:.0f}%", None), ("...age", f"{100 - unclear_share['age']:.0f}%", None),
                    ("...source of money", f"{100 - unclear_share['money']:.0f}%", None), ("...who influenced them", f"{100 - unclear_share['influenced_by']:.0f}%", None)])
        irr = posts[posts.irregular_income]
        st.write(f"Public posts almost never reveal age, income or where the money comes from, so those segments **cannot be measured here and are validated through interviews**. "
                 f"The engine uses proxies instead: the irregular-income reason ({len(irr)} posts), the first-time flag ({int(posts.first_time.sum())} posts), the source and the journey stage. "
                 "See page 5 for the comparison.")

    # Q9 ------------------------------------------------------------------
    with st.expander("9. What unmet needs appear consistently?"):
        needs = posts[~posts.unmet_need.str.lower().str.contains(r"^(?:none|unclear|not stated|no need)", regex=True, na=True)]
        metric_row([("Posts that state an unmet need", f"{len(needs):,}", None), ("Share of relevant tagged posts", C.pct(len(needs), n), None)])
        words = Counter(w for t in needs.unmet_need for w in re.findall(r"[a-z]{4,}", t.lower()) if w not in STOP_WORDS)
        if words:
            wdf = pd.DataFrame(words.most_common(10), columns=["label", "n"])
            st.altair_chart(C.hbar(wdf, title="Words most used when describing what was missing"), width="stretch")
        st.markdown("**Examples of what people needed (written by the AI from the post):**")
        for t in needs.unmet_need.value_counts().head(5).index:
            st.markdown(f"- {t}")
        C.show_quotes(needs, 2)
