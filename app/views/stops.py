"""Page 2, What stops SIPs: the top reasons in one chart, failure vs choice by source, and trouble after stopping."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import common as C
import ui

TOP = 8


def one_row(posts: pd.DataFrame, a: dict, biggest: int, total: int, label: str, indent: bool = False) -> None:
    col = ui.COLOUR[ui.area_kind(posts, a)]
    pad, c1, c2, c3 = st.columns([0.45 if indent else 0.001, 3.6, 5.6, 1.6], vertical_alignment="center")
    if c1.button(label, key=f"pick_{ui.area_id(a)}", type="tertiary"):
        st.session_state["open_reason"] = ui.area_id(a)
    c2.markdown(f'<div class="bar-track"><div class="bar-fill" style="width:{100 * a["n"] / biggest:.1f}%;background:{col}"></div></div>',
                unsafe_allow_html=True)
    c3.markdown(f'<div class="num">{a["n"]:,} <span>· {100 * a["n"] / total:.1f}%</span></div>', unsafe_allow_html=True)


def reason_rows(posts: pd.DataFrame, areas: list[dict], total: int) -> None:
    """One row per reason: a button with its name, a bar coloured by failure/choice, and 'count · share'.
    A combined group is one row (each post counted once) with its reasons indented beneath it."""
    biggest = max(a["n"] for a in areas)
    with st.container(key="reasons"):
        for a in areas:
            if a["kind"] != "group":
                one_row(posts, a, biggest, total, ui.area_label(a))
                continue
            one_row(posts, a, biggest, total, f"{a['label']} (combined, each post counted once)")
            for ch in sorted(a["children"], key=lambda c: -c["n"]):
                one_row(posts, ch, biggest, total, ui.area_label(ch), indent=True)


SHORT_NAME = {"mandate_payment_issue": "payment problems", "making_sense_of_returns": "confusion about returns"}


def title_for(units: list[dict]) -> str:
    """Page title from the data: two near-tied reasons are named together, otherwise the top one alone."""
    top = units[0]
    if ui.near_tie(units):
        a, b = (SHORT_NAME.get(u["key"]) or ui.soft_lower(ui.area_label(u)) for u in units[:2])
        return f"{a[0].upper() + a[1:]} and {b} are the two biggest reasons SIPs stop"
    return (f"“{ui.area_label(top)}” is the top reason SIPs stop" if top["key"] not in SHORT_NAME else f"{SHORT_NAME[top['key']].capitalize()} are the top reason SIPs stop")


def group_note(opp: dict, top: dict) -> str:
    """One computed sentence comparing the combined 'making sense of returns' group with autopay, overall and for first-time investors."""
    c, g = opp.get("group_compare"), (opp.get("groups") or [None])[0]
    if not c or not g:
        return ""
    lead = ("Overall, autopay is named in more posts" if c["autopay"] > c["group_unique"] else
            "Overall, returns is named in more posts" if c["autopay"] < c["group_unique"] else "Overall, the two are named in the same number of posts")
    return (f"<b>{ui.esc(g['label'])}</b> combines three reasons: confusing numbers, returns feel too small and expected faster growth. "
            f"Each post is counted once, so it is {c['group_unique']:,} posts, not {c['group_sum_of_parts']:,}. Autopay: {c['autopay']:,}. "
            f"{lead}, but among {c['first_time_posts']:,} first-time investors it is <b>{c['first_time_group']:,}</b> posts for returns vs "
            f"<b>{c['first_time_autopay']:,}</b> for autopay.")


def render() -> None:
    posts, opp = C.load_posts(), C.load_json("opportunities")
    title_slot = st.container()
    head = st.columns([3, 1.2], vertical_alignment="bottom")
    with head[1]:
        excl = st.toggle("Leave out Reddit (hand-picked threads)", value=False, key="excl_reddit")
    if excl:
        opp = opp.get("without_reddit", opp)
        posts = posts[posts.source != "reddit"]
    causes, unsplit = ui.units_of(opp), ui.unsplit_of(opp)
    after = sorted(opp.get("after_stop", []), key=lambda a: -a["n"])
    if not causes:
        st.info("Not enough labelled posts yet to rank reasons.")
        return
    total = opp["n_tagged"]
    top = causes[0]
    name = ui.area_label(top)
    with title_slot:
        st.title(title_for(causes))
    head[0].markdown(f'<p class="sub" style="margin:0">The reasons people give, counted across {total:,} posts. Click a reason to read what people said.</p>',
                     unsafe_allow_html=True)
    note = group_note(opp, top)
    if note:
        st.markdown(f'<div class="qbox" style="margin:.8rem 0 0;background:#f4f6fa">{note}</div>', unsafe_allow_html=True)
    st.write("")

    # ---- the chart ---------------------------------------------------------------
    show_all = st.session_state.get("show_all_reasons", False)
    shown = causes if show_all else causes[:TOP]
    kinds = {ui.area_kind(posts, a) for a in shown}
    with st.container(key="card_reasons"):
        st.markdown(f'<div style="display:flex;justify-content:space-between;flex-wrap:wrap;align-items:baseline"><h3 style="margin:0">'
                    f'{"All" if show_all else f"Top {min(TOP, len(causes))}"} reasons SIPs stop</h3><div class="legend" style="font-size:.85rem;color:#3a4352">'
                    f'<span class="sw" style="background:{ui.FAIL}"></span>Payment or app failure'
                    f'<span class="sw" style="background:{ui.CHOICE}"></span>Person’s own choice'
                    + (f'<span class="sw" style="background:{ui.UNCLEAR}"></span>Other or too few stories' if "unclear" in kinds else "") + "</div></div>",
                    unsafe_allow_html=True)
        reason_rows(posts, shown, total)

        by_id = {ui.area_id(a): a for a in causes + [c for g in causes for c in g.get("children", [])]}
        opened = by_id.get(st.session_state.get("open_reason")) or top
        op = ui.area_posts(posts, opened)
        qs = ui.pick_quotes(op, 2, 160, hints=ui.HINTS.get(opened['key']))
        panel = f'<div class="qbox" style="margin-top:1rem;background:#f4f6fa"><b style="font-size:.85rem;color:#3a4352">Opened: {ui.esc(ui.area_label(opened))} · {opened["n"]:,} posts</b>'
        for q in qs:
            panel += (f'<div style="margin:.45rem 0 0">“{ui.esc(q["text"])}” <span style="color:#5b6574;font-size:.8rem">· {ui.SHORT.get(q["source"], q["source"])}'
                      f'{ui.year_of(q["year"])}</span></div>')
        if not qs:
            panel += '<div style="margin:.45rem 0 0;color:#5b6574">No verified English or Hinglish quote for this reason yet; the posts are in Ask &amp; browse.</div>'
        st.markdown(panel + "</div>", unsafe_allow_html=True)
        ui.go(f"Read all {opened['n']:,} posts", "browse", "read_all", browse_reason=ui.area_id(opened), f_year="All years")
        if len(causes) > TOP and st.button(f"Show all {len(causes)} reasons" if not show_all else f"Show only the top {TOP}", key="toggle_all"):
            st.session_state["show_all_reasons"] = not show_all
            st.rerun()
        st.caption("A post can give more than one reason, so the counts overlap."
                   + (f" {unsplit:,} posts about “hard to use the app” are still waiting for the AI to sort them into specific problems, so they are not shown as a reason here." if unsplit else ""))

    # ---- failure vs choice by source / after stopping ----------------------------
    left, right = st.columns(2, gap="medium")
    by_src = {s: ui.lapse_split(g) for s, g in posts.groupby("source")}
    rows = sorted(by_src.items(), key=lambda kv: -ui.pct(kv[1]["fail"], kv[1]["n"]) if kv[1]["n"] else 0)
    with left, st.container(key="card_bysource"):
        st.markdown("### Failure or choice? It depends on the source")
        body = ""
        for s, v in rows:
            if v["n"] < 5:          # too few stopped-SIP stories to draw a bar
                continue
            body += (f'<div style="display:flex;justify-content:space-between;margin:.55rem 0 .15rem;color:#3a4352;font-size:.88rem"><span>{ui.LONG[s]}</span>'
                     f'<span>n = {v["n"]} stories{" (few)" if v["n"] < 15 else ""}</span></div>{ui.split_bar(v, 18)}')
        st.markdown(body, unsafe_allow_html=True)
        big = [(s, v) for s, v in rows if v["n"] >= 15]
        if len(big) >= 2:
            most_fail, most_choice = big[0][0], max(big, key=lambda kv: kv[1]["choice"] / kv[1]["n"])[0]
            st.markdown(f'<div style="margin-top:.8rem;color:#3a4352;font-size:.92rem">{ui.KIND_OF[most_fail]} collect complaints about failed payments; '
                        f'{ui.KIND_OF[most_choice].lower()} collect decisions to stop. Both matter.</div>', unsafe_allow_html=True)
        st.caption("Orange = payment or app failure, blue = the person’s own choice, grey = unclear.")
    with right, st.container(key="card_after"):
        st.markdown("### After stopping: trouble getting money out")
        st.markdown('<p style="color:#5b6574;font-size:.92rem;margin-top:-.3rem">These don’t cause stopping, but they damage trust and make a return less likely.</p>',
                    unsafe_allow_html=True)
        if after:
            for a in after[:3]:
                st.markdown(f'<div style="display:flex;justify-content:space-between;background:#f4f6fa;border-radius:8px;padding:9px 12px;margin:6px 0">'
                            f'<span>{ui.esc(ui.area_label(a))}</span><b>{a["n"]}</b></div>', unsafe_allow_html=True)
        else:
            st.caption("No posts about getting money out have been labelled yet.")
