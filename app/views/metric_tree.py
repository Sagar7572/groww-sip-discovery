"""Page 4: the metric tree with counts per branch, and voluntary vs involuntary lapse side by side."""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

import common as C

MIN_LAPSE = 15      # a source with fewer lapse stories than this is marked low confidence

RECOVERY = re.compile(r"\b(resume|resumed|resuming|restart|restarted|restarting|start(ed)? again|reactivat\w*)\b", re.I)


def split_counts(df: pd.DataFrame) -> dict:
    ls = df.lapse_story
    inv, vol = df.involuntary, df.voluntary
    return {"posts": len(df), "lapse": int(ls.sum()), "involuntary": int((inv & ls).sum()), "voluntary": int((vol & ls).sum()),
            "inv_only": int((inv & ~vol & ls).sum()), "vol_only": int((vol & ~inv & ls).sum()), "both": int((inv & vol & ls).sum())}


def render(over: dict, posts: pd.DataFrame) -> None:
    n = len(posts)
    lapse = posts[posts.lapse_story]
    s = split_counts(posts)
    by_src = {src: split_counts(g) for src, g in posts.groupby("source")}
    ok_src = {k: v for k, v in by_src.items() if v["lapse"] >= MIN_LAPSE}
    fail_src = max(ok_src, key=lambda k: ok_src[k]["inv_only"] / ok_src[k]["lapse"], default=None)
    choice_src = max(ok_src, key=lambda k: ok_src[k]["vol_only"] / ok_src[k]["lapse"], default=None)
    if fail_src and choice_src and fail_src != choice_src:
        st.title(f"Whether a lapse is a failure or a choice depends on the source: {C.pct(ok_src[fail_src]['inv_only'], ok_src[fail_src]['lapse'])} of "
                 f"lapse stories in {C.SOURCE_NAMES[fail_src]} are failures, {C.pct(ok_src[choice_src]['vol_only'], ok_src[choice_src]['lapse'])} of "
                 f"those in {C.SOURCE_NAMES[choice_src]} are the person's own choice")
    else:
        st.title("Whether a lapse is a failure or a choice cannot be stated for all investors: it depends on the source of the post")
    st.write("The metric is: **of first-time mutual fund investors, the share who still have an active SIP 12 months after starting.** "
             "The tree below splits what goes wrong into branches. A *lapse story* is a post where a SIP stopped, is at risk, or a payment failed.")

    # --- branch counts -----------------------------------------------------
    start = posts[posts.stage.isin(["before_start", "month_0_1"]) | posts.action.eq("started")]
    a_problem = start[start.triggers.apply(lambda t: any(x in t for x in ("app_experience", "mandate_payment_issue", "confusing_numbers")))]
    d_posts = posts[posts.triggers.apply(lambda t: "disengaged_forgot" in t) | posts.checking.eq("rarely")]
    e_posts = posts[posts.text.str.contains(RECOVERY)]
    cols = st.columns(5)
    cards = [("A. Getting going", len(a_problem), f"of {len(start):,} posts from people starting out have a set-up or app problem", C.BRANCH_COLORS["A"]),
             ("B. Involuntary lapse", s["involuntary"], f"of {s['lapse']:,} lapse stories (includes {s['both']} that are also the person's choice); varies a lot by source", C.BRANCH_COLORS["B"]),
             ("C. Voluntary lapse", s["voluntary"], f"of {s['lapse']:,} lapse stories (includes {s['both']} that are also failures); varies a lot by source", C.BRANCH_COLORS["C"]),
             ("D. Disengagement", len(d_posts), "forgot, lost interest, or rarely checks", C.BRANCH_COLORS["D"]),
             ("E. Recovery", len(e_posts), "mention resuming or restarting (keyword count)", C.BRANCH_COLORS["E"])]
    for col, (title, val, sub, color) in zip(cols, cards):
        col.markdown(f"<div style='border-top:5px solid {color};padding:6px 0'><b>{title}</b></div>", unsafe_allow_html=True)
        col.metric("Posts", f"{val:,}", help=sub)
        col.caption(sub)
    st.caption("Branch D and E are rough: the form has no field for resuming, so E counts the words resume / restart in the text. "
               "A post can sit in several branches, so the cards do not add up to the number of posts.")

    # --- voluntary vs involuntary, by source -----------------------------------
    st.subheader("Who decided, source by source: the person, or a failure?")
    kinds = ["Failure, not the person's choice", "The person's own choice", "Both", "Unclear who decided"]
    rows = []
    for src in list(by_src) + ["all"]:
        c = s if src == "all" else by_src[src]
        if not c["lapse"]:
            continue
        name = "All sources combined" if src == "all" else C.SOURCE_NAMES.get(src, src)
        label = f"{name} (n={c['lapse']}{', low confidence' if c['lapse'] < MIN_LAPSE else ''})"
        for kind, n_ in zip(kinds, (c["inv_only"], c["vol_only"], c["both"], c["lapse"] - c["inv_only"] - c["vol_only"] - c["both"])):
            rows.append({"source": label, "kind": kind, "posts": n_, "share": 100 * n_ / c["lapse"],
                         "text": f"{100 * n_ / c['lapse']:.0f}%" if n_ and n_ / c["lapse"] >= 0.08 else ""})
    comp = pd.DataFrame(rows)
    comp["kind_order"] = comp.kind.map({k: i for i, k in enumerate(kinds)})
    comp = comp.sort_values(["source", "kind_order"])
    comp["end"] = comp.groupby("source").share.cumsum()
    comp["start"] = comp.end - comp.share
    comp["mid"] = (comp.start + comp.end) / 2
    order = list(dict.fromkeys(comp.source))
    import altair as alt
    base = alt.Chart(comp).encode(y=alt.Y("source:N", sort=order, title=None, axis=alt.Axis(labelLimit=330, ticks=False, domain=False)))
    bars = base.mark_bar(stroke="white", strokeWidth=2, size=26).encode(
        x=alt.X("start:Q", title="% of the source's lapse stories", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(grid=False)), x2="end:Q",
        color=alt.Color("kind:N", scale=alt.Scale(domain=kinds, range=[C.ORANGE, C.BLUE, C.AQUA, "#cfcfca"]),
                        legend=alt.Legend(title=None, orient="bottom", columns=2, labelLimit=420, symbolType="square")),
        tooltip=["source", "kind", "posts", alt.Tooltip("share:Q", format=".0f")])
    labels = base.mark_text(fontSize=12, color="white", fontWeight="bold").encode(x="mid:Q", text="text:N")
    st.altair_chart((bars + labels).properties(height=44 * len(order) + 130), width="stretch")
    st.warning(f"**Do not read the combined row as a general fact.** It is {C.pct(s['inv_only'], s['lapse'])} failures and {C.pct(s['vol_only'], s['lapse'])} own choice "
               "only because of how many lapse stories each source contributes. A likely reason for the gap (not tested here) is who writes where: people with a failed payment "
               "go to the app store to complain, while YouTube comments react to videos about whether to stop. The real split among all first-time investors is unknown. "
               "Sources with fewer than 15 lapse stories are marked low confidence.")

    # --- per tagger ---------------------------------------------------------
    st.subheader("The same split, tagger by tagger")
    rows = []
    for label, grp in (("Both taggers combined", posts), ("gpt-oss-120b only", posts[posts.tagged_by == "gpt-oss-120b"]), ("qwen only", posts[posts.tagged_by == "qwen"])):
        c = split_counts(grp)
        rows.append({"Tagger": label, "Tagged posts": c["posts"], "Lapse stories": c["lapse"],
                     "Failure, not chosen": f"{c['involuntary']} ({C.pct(c['involuntary'], c['lapse'])})",
                     "Person's choice": f"{c['voluntary']} ({C.pct(c['voluntary'], c['lapse'])})",
                     "Share of all tagged posts that are failures": C.pct(c["involuntary"], c["posts"])})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    ag = C.load_json("validation").get("agreement", {})
    inv = ag.get("involuntary_flagged", {})
    st.info(f"Why two taggers are shown: in a check where both models tagged the same {ag.get('n_items', 0)} posts, the second model (qwen) "
            f"found fewer payment failures ({inv.get('qwen', '?')}) than the first (gpt-oss-120b, {inv.get('gpt-oss-120b', '?')}). "
            "In the table above the two taggers saw different random halves of the posts, so differences between them mix model differences with chance. "
            "Treat the combined failure share as a lower bound.")

    # --- when ----------------------------------------------------------------
    st.subheader("When in the journey does each kind happen?")
    known = lapse[lapse.stage != "unclear"]
    if len(known) >= 5:
        d = pd.DataFrame({"stage": known.stage.map(C.nice),
                          "kind": known.apply(lambda r: "Failure, not chosen" if r.involuntary and not r.voluntary else
                                              "Person's choice" if r.voluntary and not r.involuntary else "Both or unclear", axis=1)})
        d = d.groupby(["stage", "kind"]).size().reset_index(name="posts")
        st.altair_chart(C.stacked_bar(d, "posts", "stage", "kind", ["Failure, not chosen", "Person's choice", "Both or unclear"],
                                      [C.ORANGE, C.BLUE, "#cfcfca"], order=[C.nice(x) for x in C.STAGE_ORDER if x != "unclear"],
                                      x_title="Lapse stories that state a stage"), width="stretch")
        st.caption(f"Only {len(known):,} of {len(lapse):,} lapse stories say when in the journey they happened.")
    else:
        st.caption("Too few lapse stories state a stage to show this yet.")

    # --- the 'market fell' question -----------------------------------------
    mf = posts[posts.triggers.apply(lambda t: "market_fall" in t)]
    st.subheader("When people say \"the market fell\", what is underneath?")
    removed = int(posts.triggers_removed.apply(lambda t: "market_fall" in t).sum())
    st.write(f"{len(mf)} posts give the market falling as a reason (after code removed {removed} tags that the posts' own words did not support; see the evidence log). "
             "The AI's reading of the deeper reason in those posts:")
    for t in mf.reason[~mf.reason.str.lower().str.startswith("unclear")].head(5):
        st.markdown(f"- {t}")
    if len(mf) == 0:
        st.caption("No posts with this reason yet.")
    C.show_quotes(mf, 2)
