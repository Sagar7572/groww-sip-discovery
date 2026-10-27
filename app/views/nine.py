"""Page 3, the nine questions from the brief: one card each, with a chip saying whether public posts answer it well."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import common as C
import ui

ACTIVE_STOP = ["considering_stop", "paused", "reduced", "stopped", "instalment_failed"]
CONTINUING = ["continuing", "increased", "started"]
CLEAR_AT = 10          # a question counts as "clear in posts" when at least this % of relevant posts speak to it
APP_REASONS = ["app_experience", "confusing_numbers", "mandate_payment_issue", "trust_concern"]


def names(df: pd.DataFrame, col: str, k: int, drop=("none", "other", "not_mentioned", "none_mentioned")) -> list[str]:
    return [ui.soft_lower(ui.plain(x)) for x in C.explode_counts(df, col, drop=drop).key.head(k)]


def join(xs: list[str]) -> str:
    return " and ".join(xs) if len(xs) < 3 else ", ".join(xs[:-1]) + " and " + xs[-1]


def bar(df: pd.DataFrame, total: int, title: str, colour: str = ui.CHOICE) -> None:
    if df.empty:
        st.caption("Nothing to chart yet.")
        return
    st.altair_chart(C.hbar(df[["label", "n"]], total=total, color=colour, title=title), width="stretch")


def build(posts: pd.DataFrame, un: dict) -> list[dict]:
    n = len(posts)
    out = []

    exp = posts[posts.triggers.apply(lambda t: "expectation_mismatch" in t)]
    by_key = {a["key"]: a["n"] for a in C.load_json("opportunities").get("causes", []) if a["kind"] == "reason"}   # same counts as the What stops SIPs page
    n_exp = by_key.get("expectation_mismatch", len(exp))
    small = by_key.get("underwhelming_returns", int(posts.triggers.apply(lambda t: "underwhelming_returns" in t).sum()))
    out.append(dict(i=1, q="Why do people start, and what do they expect?", num=f"{n_exp} posts", cov=n_exp,
                    text=f"say they expected faster growth, and {small} say returns feel too small.", df=exp))

    known = posts[posts.stage != "unclear"]
    early = known[known.stage.isin(["month_0_1", "month_1_3"])]
    out.append(dict(i=2, q="What changes in the months after starting?", num=f"{ui.pct(early.lapse_story.sum(), len(early))}%", cov=len(known),
                    text="of posts from the first few months are about stopping or a failed payment." if len(early) else "of early posts: too few to say.",
                    df=known[known.lapse_story]))

    lapse = posts[posts.lapse_story]
    causes = ui.causes_of(C.load_json("opportunities"))
    top3 = [ui.soft_lower(ui.area_label(a)) for a in causes[:3]]
    out.append(dict(i=3, q="What leads people to pause, reduce or stop?", num=f"{100 * causes[0]['share_of_tagged']:.0f}%" if causes else "n/a", cov=len(lapse),
                    text=(f"cite {top3[0]}, the top reason. " + (f"{ui.sentence_case(join(top3[1:]))} follow." if len(top3) > 1 else "")) if causes else "", df=lapse))

    how = posts[posts.checking_stated]
    what = posts[posts.checks_stated]
    mention = posts[posts.checking_stated | posts.checks_stated]
    chk = names(posts, "checks", 2)
    out.append(dict(i=4, q="What do they check, and how often?", num=f"{ui.pct(len(mention), n)}%", cov=len(mention),
                    text=f"of posts say what they check{', mostly ' + join(chk) if chk else ''}. How often is stated in {ui.pct_text(len(how), n)} of posts.", df=mention))

    inapp = posts[posts.triggers.apply(lambda t: any(x in t for x in APP_REASONS))]
    feel = C.nice(inapp.emotion.mode().iloc[0]).lower() if len(inapp) else "n/a"
    out.append(dict(i=5, q="What confuses or worries them in the app?", num=f"{ui.pct(len(inapp), n)}%", cov=len(inapp),
                    text=f"of posts describe app, payment or number confusion. The most common feeling is {feel}.", df=inapp))

    outside = posts[posts.outside_stated]
    top_out = names(posts, "outside", 1)
    out.append(dict(i=6, q="What do they do outside the app when unsure?", num=f"{ui.pct(len(outside), n)}%", cov=len(outside),
                    text=f"mention it{', mostly ' + top_out[0] if top_out else ''}. Posting on a forum is itself an outside step.", df=outside))

    cont, drop = posts[posts.action.isin(CONTINUING)], posts[posts.action.isin(ACTIVE_STOP)]
    sc, ss = names(cont, "triggers", 1), names(drop, "triggers", 2)
    out.append(dict(i=7, q="What separates people who continue from those who stop?", num=f"{len(cont)} vs {len(drop)}", cov=len(cont) + len(drop),
                    text=("posts. " + (f"Stoppers cite {join(ss)}" if ss else "Stoppers give no clear reason")
                          + ("; " + f"continuers mostly talk about {sc[0]}." if sc else ".")), df=drop, df2=cont))

    stated = max(100 * (posts[f] != "unclear").mean() for f in ("income", "age", "money"))
    ft = ui.lapse_split(posts[posts.first_time])
    out.append(dict(i=8, q="How do patterns differ across segments?", num=f"{stated:.0f}%", cov=round(stated * n / 100),
                    text="of posts state age, income or source of money." + (f" First-timers mostly stop by {'choice' if ft['choice'] >= ft['fail'] else 'payment failure'} "
                                                                           f"({ui.pct(max(ft['choice'], ft['fail']), ft['n'])}%)." if ft["n"] else ""),
                    df=posts[posts.first_time & posts.lapse_story]))

    themes, k = un.get("themes", []), un.get("posts_with_need", 0)
    out.append(dict(i=9, q="What unmet needs come up again and again?", num=f"{k} posts", cov=k,
                    text="state a need." + (f" Of the {un.get('grouped', k):,} grouped into themes so far, the top are " + ", ".join(f"{ui.soft_lower(t['theme'])} ({t['n']})" for t in themes[:3]) + "." if themes else ""), df=posts))
    for c in out:
        c["clear"] = 100 * c["cov"] / n >= CLEAR_AT if n else False
    return out


def detail(c: dict, posts: pd.DataFrame, un: dict) -> None:
    n, i, df = len(posts), c["i"], c["df"]
    st.markdown(f"#### Q{i}. {c['q']}")
    if i == 1:
        start = posts[posts.stage.isin(["before_start", "month_0_1"]) | posts.action.eq("started")]
        if len(start) >= 5:
            bar(C.counts_frame(start.emotion, top=7), len(start), "How people starting out feel (posts)")
        st.caption("Public posts rarely say why someone started. They show what people expect, and where it stops matching.")
    elif i == 2:
        k = posts[posts.stage != "unclear"]
        if len(k) >= 5:
            d = k.groupby(["stage", k.lapse_type.map(lambda x: x if x in ("voluntary", "involuntary", "both") else "none")]).size().reset_index(name="posts")
            d["stage_label"] = d.stage.map(C.nice)
            d["kind"] = d.lapse_type.map({"voluntary": "Person's own choice", "involuntary": "Payment or app failure", "both": "Both"}).fillna("No stop or unclear")
            st.altair_chart(C.stacked_bar(d, "posts", "stage_label", "kind", ["Payment or app failure", "Person's own choice", "Both", "No stop or unclear"],
                                          [ui.FAIL, ui.CHOICE, C.AQUA, ui.UNCLEAR], order=[C.nice(s) for s in C.STAGE_ORDER if s != "unclear"], x_title="Posts"),
                            width="stretch")
        st.caption(f"Only {ui.pct(len(k), n)}% of posts say how long the person has been investing.")
    elif i == 3:
        bar(C.explode_counts(df, "triggers", drop=("none", "other")).head(8).assign(label=lambda d: d.key.map(ui.plain)), len(df), "Stopped-SIP stories giving this reason", ui.FAIL)
    elif i == 4:
        bar(C.explode_counts(posts, "checks", drop=("not_mentioned",)).head(6), len(posts[posts.checks_stated]) or 1, "What they look at (posts)", ui.CHOICE)
        if posts.checking_stated.any():
            bar(C.counts_frame(posts[posts.checking_stated].checking), int(posts.checking_stated.sum()), "How often they check (posts)")
        st.caption("Almost no post says how often someone checks. Interviews will have to answer this.")
    elif i == 5:
        d = C.explode_counts(df, "triggers", drop=("none", "other"))
        d = d[d.key.isin(APP_REASONS)].assign(label=lambda x: x.key.map(ui.plain))
        bar(d, len(df), "Posts mentioning this")
    elif i == 6:
        bar(C.explode_counts(posts, "outside", drop=("none_mentioned",)), n, "Posts mentioning this (% of all posts)", ui.CHOICE)
    elif i == 7:
        cont, drop = c["df2"], df
        if len(cont) >= 5 and len(drop) >= 5:
            rows = []
            for lab, g in (("Continuing", cont), ("Stopping or failing", drop)):
                for _, r in C.explode_counts(g, "triggers", drop=("none", "other")).iterrows():
                    rows.append({"group": lab, "reason": ui.plain(r.key), "share": 100 * r.n / len(g)})
            d = pd.DataFrame(rows)
            keep = d.groupby("reason").share.max().nlargest(7).index
            d = d[d.reason.isin(keep)]
            st.altair_chart(alt.Chart(d).mark_bar(cornerRadiusEnd=3, size=12).encode(
                y=alt.Y("reason:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240, ticks=False, domain=False)), yOffset="group:N",
                x=alt.X("share:Q", title="% of posts in the group", axis=alt.Axis(grid=False)),
                color=alt.Color("group:N", scale=alt.Scale(domain=["Continuing", "Stopping or failing"], range=[ui.CHOICE, ui.FAIL]), legend=alt.Legend(title=None, orient="bottom")),
                tooltip=["group", "reason", alt.Tooltip("share:Q", format=".0f")]).properties(height=36 * len(keep) + 120), width="stretch")
        st.caption("People who are happy and still investing write far fewer posts, so this comparison is lopsided.")
    elif i == 8:
        s = pd.DataFrame({"label": ["Income stability", "Age", "Source of money", "Who influenced them"],
                          "n": [int((posts[f] != "unclear").sum()) for f in ("income", "age", "money", "influenced_by")]})
        bar(s, n, "Posts that state this", ui.CHOICE)
        ft, rest = ui.lapse_split(posts[posts.first_time]), ui.lapse_split(posts[~posts.first_time])
        if ft["n"]:
            st.markdown(f"**First-time investors** ({ft['n']} stopped-SIP stories, to be tested in interviews)" + ui.split_bar(ft, 22), unsafe_allow_html=True)
            st.markdown(f"**Everyone else** ({rest['n']} stories)" + ui.split_bar(rest, 22), unsafe_allow_html=True)
        st.caption("Posts almost never say age or income, so segments are tested in interviews. First-time status is only known when people say so.")
    elif i == 9:
        themes = un.get("themes", [])
        if themes:
            bar(pd.DataFrame({"label": [t["theme"] for t in themes], "n": [t["n"] for t in themes]}), un.get("grouped") or un.get("posts_with_need", 1),
                "Posts in this theme (% of posts that state a need)", ui.CHOICE)
            years = posts.set_index("id").year
            shown = 0
            for t in themes:
                for q in t["quotes"]:
                    if shown < 2 and ui.latin_share(q["quote"]) >= 0.85:
                        shown += 1
                        st.markdown(ui.quote_html({"text": ui.cut(q["quote"]), "source": q["source"], "year": years.get(q["id"]), "url": q.get("url")},
                                                  f" · {t['theme']}"), unsafe_allow_html=True)
                        break
        return
    ui.show_quotes(df if len(df) else posts, 2)


def render() -> None:
    posts, un = C.load_posts(), C.load_json("unmet_needs")
    cards = build(posts, un)
    clear = sum(c["clear"] for c in cards)
    st.title(f"Public posts answer {clear} of the 9 questions well; {9 - clear} need interviews")
    st.markdown('<p class="sub">One answer per research question. Open a card for the chart and the posts behind it.</p>', unsafe_allow_html=True)
    st.markdown(f'{ui.chip("Clear in posts", "green")} enough posts to rely on (at least {CLEAR_AT}% of posts speak to it) &nbsp;&nbsp; '
                f'{ui.chip("Needs interviews", "orange")} posts rarely say this', unsafe_allow_html=True)
    st.write("")
    for row in range(3):
        cols = st.columns(3, gap="medium")
        for col, c in zip(cols, cards[row * 3: row * 3 + 3]):
            with col, st.container(key=f"card_q{c['i']}"):
                st.markdown(f'<div style="display:flex;justify-content:space-between;align-items:center"><span class="lab" style="margin:0">Q{c["i"]}</span>'
                            f'{ui.chip("Clear in posts", "green") if c["clear"] else ui.chip("Needs interviews", "orange")}</div>'
                            f'<div class="lead" style="font-size:1.05rem;margin:.5rem 0 .3rem">{ui.esc(c["q"])}</div>'
                            f'<div style="font-size:2.2rem;font-weight:800;color:{ui.CHOICE};line-height:1.1">{ui.esc(c["num"])}</div>'
                            f'<div style="color:#3a4352;font-size:.92rem;line-height:1.45;margin-top:.3rem">{ui.esc(c["text"])}</div>', unsafe_allow_html=True)
                if st.button("Open chart and quotes" if st.session_state.get("open_q") != c["i"] else "Close", key=f"openq{c['i']}", type="tertiary"):
                    st.session_state["open_q"] = None if st.session_state.get("open_q") == c["i"] else c["i"]
                    st.rerun()
    sel = st.session_state.get("open_q")
    if sel:
        st.write("")
        with st.container(key="card_detail"):
            detail(next(c for c in cards if c["i"] == sel), posts, un)
