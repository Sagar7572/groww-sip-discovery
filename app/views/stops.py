"""Page 2, What stops SIPs: the top reasons in one chart, failure vs choice by source, and trouble after stopping."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import common as C
import ui

TOP = 8


def reason_rows(posts: pd.DataFrame, areas: list[dict], total: int) -> None:
    """One row per reason: a button with its name, a bar coloured by failure/choice, and 'count · share'."""
    biggest = max(a["n"] for a in areas)
    with st.container(key="reasons"):
        for a in areas:
            label = ui.area_label(a) + (f" ({len(a['members'])} reasons combined)" if a["kind"] == "group" else "")
            col = ui.COLOUR[ui.kind_of_group(ui.area_posts(posts, a))]
            c1, c2, c3 = st.columns([3.2, 6, 1.5], vertical_alignment="center")
            if c1.button(label, key=f"pick_{ui.area_id(a)}", type="tertiary"):
                st.session_state["open_reason"] = ui.area_id(a)
            c2.markdown(f'<div class="bar-track"><div class="bar-fill" style="width:{100 * a["n"] / biggest:.1f}%;background:{col}"></div></div>',
                        unsafe_allow_html=True)
            c3.markdown(f'<div class="num">{a["n"]:,} <span>· {100 * a["n"] / total:.1f}%</span></div>', unsafe_allow_html=True)


def group_note(opp: dict, top: dict) -> str:
    """One computed sentence comparing the combined 'making sense of returns' group with autopay, overall and for first-time investors."""
    c, g = opp.get("group_compare"), (opp.get("groups") or [None])[0]
    if not c or not g or top["key"] != "mandate_payment_issue":
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
    causes, unsplit = ui.with_groups(opp), ui.unsplit_of(opp)
    after = sorted(opp.get("after_stop", []), key=lambda a: -a["n"])
    if not causes:
        st.info("Not enough labelled posts yet to rank reasons.")
        return
    total = opp["n_tagged"]
    top = ui.causes_of(opp)[0]
    name = ui.area_label(top)
    with title_slot:
        st.title(("Autopay and payment problems are" if top["key"] == "mandate_payment_issue" else f"“{name}” is") + " the top reason SIPs stop")
    head[0].markdown(f'<p class="sub" style="margin:0">The reasons people give, counted across {total:,} posts. Click a reason to read what people said.</p>',
                     unsafe_allow_html=True)
    note = group_note(opp, top)
    if note:
        st.markdown(f'<div class="qbox" style="margin:.8rem 0 0;background:#f4f6fa">{note}</div>', unsafe_allow_html=True)
    st.write("")

    # ---- the chart ---------------------------------------------------------------
    show_all = st.session_state.get("show_all_reasons", False)
    shown = causes if show_all else causes[:TOP]
    kinds = {ui.kind_of_group(ui.area_posts(posts, a)) for a in shown}
    with st.container(key="card_reasons"):
        st.markdown(f'<div style="display:flex;justify-content:space-between;flex-wrap:wrap;align-items:baseline"><h3 style="margin:0">'
                    f'{"All" if show_all else f"Top {min(TOP, len(causes))}"} reasons SIPs stop</h3><div class="legend" style="font-size:.85rem;color:#3a4352">'
                    f'<span class="sw" style="background:{ui.FAIL}"></span>Payment or app failure'
                    f'<span class="sw" style="background:{ui.CHOICE}"></span>Person’s own choice'
                    + (f'<span class="sw" style="background:{ui.UNCLEAR}"></span>Too few stories to say' if "unclear" in kinds else "") + "</div></div>",
                    unsafe_allow_html=True)
        reason_rows(posts, shown, total)

        by_id = {ui.area_id(a): a for a in causes}
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
