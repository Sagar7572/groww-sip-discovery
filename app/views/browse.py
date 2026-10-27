"""Page 4, Ask & browse: ask a question (answers only from the posts, with numbered sources), then browse the posts as cards."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import common as C
import ui
from views import ask as A

PAGE = 20
EXAMPLES = ["Why do people pause their SIP?", "What do people say about returns?", "What confuses people about NAV?"]
STOPPED_BY = {"Payment or app failure": "fail", "Person's own choice": "choice"}


def set_question(q: str) -> None:
    st.session_state["q"] = q
    st.session_state["run_ask"] = True


def ask_panel(posts: pd.DataFrame) -> None:
    st.title("Ask a question about what investors say")
    st.markdown("<p class='sub'>Answers come only from the collected posts, with the posts shown as sources. It won’t give investment advice.</p>", unsafe_allow_html=True)
    mat, _ = C.load_embeddings()
    if mat is None:
        st.info("Search is not available in this build (no embeddings file).")
        return
    c1, c2 = st.columns([8, 1.1], vertical_alignment="bottom")
    question = c1.text_input("Your question", key="q", max_chars=300, placeholder="Why do autopay payments fail?", label_visibility="collapsed")
    go = c2.button("Ask", type="primary", width="stretch")
    chips = st.columns(len(EXAMPLES))
    for col, ex in zip(chips, EXAMPLES):
        col.button(ex, key=f"ex_{ex}", on_click=set_question, args=(ex,), width="stretch")
    run = (go or st.session_state.pop("run_ask", False)) and question.strip()
    status = st.empty()

    def show_status() -> None:
        left = A.PER_SESSION - st.session_state.get("asked", 0)
        status.caption(f"{left} of {A.PER_SESSION} questions left this visit · free AI models, so it can be busy at times")
    show_status()
    if not run:
        return
    if st.session_state.get("asked", 0) >= A.PER_SESSION:
        st.error(f"You have used the {A.PER_SESSION} questions available in this visit. Please come back later.")
        return
    if A.today_used() >= A.PER_DAY:
        st.error("The daily limit for this tool has been reached. Please try again tomorrow.")
        return

    with st.spinner("Searching the posts (the first search loads a small model and can take a minute)…"):
        hits = A.retrieve(question, posts)
    if not hits or hits[0][1] < A.MIN_SIMILARITY:
        A.count_question()
        show_status()
        st.markdown("**The data doesn’t cover this.** None of the posts are close enough to the question to answer it.")
        return
    with st.spinner("Writing an answer from the closest posts…"):
        answer, model = A.ask_groq(question, hits, posts)
    box = ""
    if answer is None:
        box = ("The answer service is not set up, so only the closest posts are listed." if model == "no_key"
               else "The free AI services are busy right now. Please try again in a minute. The closest posts are listed below.")
    else:
        A.count_question()
        show_status()
        raw = answer
        answer, ok, removed = A.check_citations(raw, len(hits))
        if ok:
            box = ui.esc(answer.replace("**", ""))
        else:
            box = "The data doesn’t cover this. The closest posts are listed below."
    with st.container(key="card_answer"):
        st.markdown(f'{ui.label("Answer")}<div style="font-size:1.1rem;line-height:1.55;color:#161c28">{box}</div>', unsafe_allow_html=True)
        lines = []
        for n, (i, sim) in enumerate(hits, 1):
            r = posts.iloc[i]
            link = f' · <a href="{ui.esc(r.url)}" target="_blank">open</a>' if isinstance(r.url, str) and r.url else ""
            lines.append(f'<li style="margin:.25rem 0">“{ui.esc(ui.cut(r.text, 170))}” <span style="color:#5b6574;font-size:.85rem">· {ui.SHORT.get(r.source, r.source)}{ui.year_of(r.year)}{link}</span></li>')
        st.markdown('<ol style="padding-left:1.2rem;color:#2a3342;font-size:.95rem;margin-top:.8rem">' + "".join(lines) + "</ol>", unsafe_allow_html=True)


def reason_options() -> dict[str, str]:
    opp = C.load_json("opportunities")
    areas = ui.with_groups(opp) + sorted(opp.get("after_stop", []), key=lambda a: -a["n"])
    return {ui.area_id(a): ui.area_label(a) for a in areas}


def post_card(r) -> str:
    chips = ""
    if r.action in ui.ACTION:
        chips += ui.chip(ui.ACTION[r.action])
    why = [t for t in r.triggers if t not in ("none", "other")]
    if why:
        chips += ui.chip(ui.plain(why[0]))
    elif isinstance(r.problem_area, str) and r.problem_area != "not_a_problem":
        chips += ui.chip(ui.plain(r.problem_area))
    return (f'<div class="post"><div class="txt">“{ui.esc(ui.cut(r.text, 170))}”</div>'
            f'<div class="meta">{ui.SHORT.get(r.source, r.source)}{ui.year_of(r.year)} &nbsp; {chips}</div></div>')


def browse_panel(posts: pd.DataFrame) -> None:
    st.markdown("<hr style='border:none;border-top:1px solid #e3e7ee;margin:2rem 0 1rem'>", unsafe_allow_html=True)
    opts = reason_options()
    opp_groups = C.load_json("opportunities").get("groups", [])
    h, f1, f2, f3 = st.columns([2.2, 1.3, 1.5, 1.2], vertical_alignment="bottom")
    h.markdown("## Browse the posts")
    source = f1.selectbox("Source", ["all"] + list(ui.SHORT), format_func=lambda s: "All sources" if s == "all" else ui.SHORT[s], key="f_source")
    reason = f2.selectbox("Reason", ["all"] + list(opts), format_func=lambda k: "All reasons" if k == "all" else opts[k], key="browse_reason")
    years = sorted(posts.year.dropna().astype(int).unique(), reverse=True)
    year = f3.selectbox("Year", ["2021 onward", "All years"] + years, key="f_year")
    with st.expander("More filters"):
        m1, m2, m3 = st.columns(3)
        happened = m1.multiselect("What happened to the SIP", list(ui.ACTION), format_func=lambda a: ui.ACTION[a], key="f_action")
        stopped = m2.selectbox("Why it stopped", ["Any"] + list(STOPPED_BY), key="f_by")
        stage = m3.multiselect("When in the journey", [s for s in C.STAGE_ORDER if s in set(posts.stage)], format_func=C.nice, key="f_stage")
        m4, m5 = st.columns(2)
        lang = m4.multiselect("Language", sorted(posts.language.dropna().unique()), key="f_lang")
        search = m5.text_input("Search the text", key="f_search")

    df = posts
    if source != "all":
        df = df[df.source == source]
    if reason != "all":
        kind, key = reason.split(":", 1)
        if kind == "group":
            members = next(g["members"] for g in opp_groups if g["key"] == key)
            df = df[df.triggers.apply(lambda t: any(k in t for k in members))]
        else:
            df = df[df.triggers.apply(lambda t: key in t)] if kind == "reason" else df[df.problem_area == key]
    if year == "2021 onward":
        df = df[df.year >= 2021]
    elif year != "All years":
        df = df[df.year == year]
    if happened:
        df = df[df.action.isin(happened)]
    if stopped != "Any":
        df = df[df.lapse_story & (df.involuntary & ~df.voluntary if STOPPED_BY[stopped] == "fail" else df.voluntary & ~df.involuntary)]
    if stage:
        df = df[df.stage.isin(stage)]
    if lang:
        df = df[df.language.isin(lang)]
    if search:
        df = df[df.text.str.contains(search, case=False, regex=False)]
    df = df.sort_values(["severity", "year"], ascending=[False, False], kind="stable")

    sig = (source, reason, str(year), tuple(happened), stopped, tuple(stage), tuple(lang), search)
    if st.session_state.get("browse_sig") != sig:
        st.session_state["browse_sig"], st.session_state["browse_n"] = sig, PAGE
    shown = min(st.session_state.get("browse_n", PAGE), len(df))
    st.markdown(f'<p class="sub" style="margin:0 0 1rem">{len(df):,} posts · most serious first</p>', unsafe_allow_html=True)
    if df.empty:
        st.info("No posts match these filters.")
        return
    rows = df.head(shown)
    for k in range(0, len(rows), 2):
        cols = st.columns(2, gap="medium")
        for col, r in zip(cols, rows.iloc[k:k + 2].itertuples()):
            col.markdown(post_card(r), unsafe_allow_html=True)
        st.write("")
    if shown < len(df):
        _, mid, _ = st.columns([2, 1, 2])
        if mid.button(f"Show more posts ({len(df) - shown:,} left)", width="stretch"):
            st.session_state["browse_n"] = shown + PAGE
            st.rerun()
    st.caption("Tags are written by AI and can be wrong. Posts are shown exactly as written, with usernames removed and personal numbers masked.")


def render() -> None:
    posts = C.load_posts()
    ask_panel(posts)
    browse_panel(posts)
