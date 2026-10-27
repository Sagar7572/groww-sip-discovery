"""Page 1, Key findings: four cards, each one number, one sentence, one real quote."""
from __future__ import annotations

import streamlit as st

import common as C
import ui


def top_reason_everywhere(posts, key: str) -> tuple[int, int]:
    """In how many of the sources (with enough posts) is this stated reason the most common one?"""
    wins = total = 0
    for _, g in posts.groupby("source"):
        if len(g) < 15:
            continue
        counts = C.explode_counts(g, "triggers", drop=("none", "other"))
        if counts.empty:
            continue
        total += 1
        wins += int(counts.key.iloc[0] == key)
    return wins, total


def first_time_sentence(a: dict) -> str:
    fail, choice = ui.pct(a["fail"], a["n"]), ui.pct(a["choice"], a["n"])
    if choice >= 85:
        return "When first-timers stop, it is almost always their own decision, not a failed payment."
    if choice >= 60:
        return "When first-timers stop, it is mostly their own decision rather than a failed payment."
    if fail > choice:
        return "When first-timers stop, it is more often a failed payment than their own decision."
    return "When first-timers stop, it is about as often a failed payment as their own decision."


def render() -> None:
    over, posts = C.load_json("overview"), C.load_posts()
    opp, un = C.load_json("opportunities"), C.load_json("unmet_needs")
    f, n = over["funnel"], len(posts)

    st.title("Why do first-time investors stop their SIPs?")
    st.markdown(f'<p class="sub">We read {f["raw_pulled"]:,} public reviews, forum threads and comments about SIPs in India. Four things stand out.</p>',
                unsafe_allow_html=True)

    # ---- 1. top cause(s) ----------------------------------------------------
    units = ui.units_of(opp)
    c1, c2 = st.columns(2, gap="medium")
    with c1, st.container(key="card_cause"):
        if ui.near_tie(units):
            u1, u2 = units[:2]
            cmp = opp.get("group_compare") or {}
            body = "".join(
                f'<div style="flex:1;min-width:130px">{ui.big(f"{u['n']:,}", "posts")}<div style="font-weight:700;color:#161c28;margin-top:.15rem">{ui.esc(ui.area_label(u))}</div></div>'
                for u in (u1, u2))
            st.markdown(ui.label("Top causes", ui.FAIL) + f'<div class="lead" style="font-weight:800">Two problems, nearly tied</div>'
                        f'<div style="display:flex;gap:1rem;flex-wrap:wrap;margin:.4rem 0">{body}</div>', unsafe_allow_html=True)
            keys = {u1["key"], u2["key"]}
            if keys == {"mandate_payment_issue", "making_sense_of_returns"} and cmp.get("first_time_posts"):
                ft_g, ft_a = cmp["first_time_group"], cmp["first_time_autopay"]
                word = "returns confusion is" if ft_g > ft_a else "payment problems are"
                hi, lo = (ft_g, ft_a) if ft_g > ft_a else (ft_a, ft_g)
                st.markdown(f'<div class="lead">Among first-time investors, {word} named in {hi} posts vs {lo} for '
                            f'{"autopay" if ft_g > ft_a else "returns"}.</div>', unsafe_allow_html=True)
        else:
            top = units[0]
            st.markdown(ui.label("Top cause", ui.FAIL) + ui.big(f"{top['n']:,}", "posts")
                        + f'<div class="lead">{ui.esc(ui.area_label(top))} is the #1 reason SIPs stop.</div>', unsafe_allow_html=True)
            for q in ui.pick_quotes(ui.area_posts(posts, top), 1, hints=ui.HINTS.get(top["key"])):
                st.markdown(ui.quote_html(q), unsafe_allow_html=True)
        ui.go("See all reasons", "stops", "go_reasons")

    # ---- 2. first-time investors ------------------------------------------------
    ft = ui.lapse_split(posts[posts.first_time])
    with c2, st.container(key="card_first"):
        if ft["n"]:
            kind = "choice" if ft["choice"] >= ft["fail"] else "fail"
            big_n = ui.pct(ft[kind], ft["n"])
            st.markdown(ui.label("First-time investors", ui.CHOICE) + ui.big(f"{big_n}%", "chose to stop" if kind == "choice" else "had a failed payment")
                        + f'<div class="lead">{ui.esc(first_time_sentence(ft))}</div>', unsafe_allow_html=True)
            ftp = posts[posts.first_time & posts.lapse_story]
            ftp = ftp[(ftp.voluntary & ~ftp.involuntary) if kind == "choice" else (ftp.involuntary & ~ftp.voluntary)]
            for q in ui.pick_quotes(ftp, 1):
                st.markdown(ui.quote_html(q, f" · based on {ft['n']} stories, to be tested in interviews"), unsafe_allow_html=True)
        else:
            st.markdown(ui.label("First-time investors", ui.CHOICE) + '<div class="lead">Too few stopped-SIP stories from first-time investors yet.</div>',
                        unsafe_allow_html=True)
        ui.go("See the segment question", "nine", "go_segment", open_q=8)

    # ---- 3. depends where you listen --------------------------------------------
    c3, c4 = st.columns(2, gap="medium")
    by_src = {s: ui.lapse_split(g) for s, g in posts.groupby("source")}
    pair = [s for s in ("play_store", "youtube") if by_src.get(s, {}).get("n", 0) >= 15]
    if len(pair) < 2:
        pair = [s for s, v in sorted(by_src.items(), key=lambda kv: -kv[1]["n"]) if v["n"] >= 15][:2]
    with c3, st.container(key="card_source"):
        if len(pair) == 2:
            a, b = by_src[pair[0]], by_src[pair[1]]
            if a["fail"] > a["choice"] and b["choice"] > b["fail"]:
                lead = f"{ui.KIND_OF[pair[0]]} are mostly about failed payments; {ui.KIND_OF[pair[1]].lower()} are mostly about choosing to stop."
            else:
                lead = f"{ui.SHORT[pair[0]]}: {ui.pct(a['fail'], a['n'])}% failures. {ui.SHORT[pair[1]]}: {ui.pct(b['fail'], b['n'])}% failures."
            body = "".join(f'<div style="margin:.5rem 0 .15rem;color:#3a4352;font-size:.9rem">{ui.LONG[s]}</div>{ui.split_bar(by_src[s], 24)}' for s in pair)
            st.markdown(ui.label("It depends where you listen") + f'<div class="lead">{ui.esc(lead)}</div>{body}', unsafe_allow_html=True)
        else:
            st.markdown(ui.label("It depends where you listen") + '<div class="lead">Not enough stopped-SIP stories in two sources yet.</div>', unsafe_allow_html=True)
        ui.go("See every source", "stops", "go_sources")

    # ---- 4. biggest unmet need --------------------------------------------------
    themes = un.get("themes", [])
    with c4, st.container(key="card_need"):
        if themes:
            t = themes[0]
            st.markdown(ui.label("Biggest unmet need", ui.GREEN) + ui.big(f"{t['n']:,}", "posts")
                        + f'<div class="lead">The most common unmet need is “{ui.esc(t["theme"].lower())}”, '
                          f'named in {100 * t["share_of_needs"]:.0f}% of the posts that state a need.</div>', unsafe_allow_html=True)
            years = posts.set_index("id").year
            for q in t["quotes"]:
                if ui.latin_share(q["quote"]) >= 0.85 and q["quote"] not in C.QUOTES_SEEN:
                    C.QUOTES_SEEN.add(q["quote"])
                    st.markdown(ui.quote_html({"text": ui.cut(q["quote"]), "source": q["source"], "year": years.get(q["id"]), "url": q.get("url")}),
                                unsafe_allow_html=True)
                    break
        else:
            st.markdown(ui.label("Biggest unmet need", ui.GREEN) + '<div class="lead">Unmet needs are not grouped yet.</div>', unsafe_allow_html=True)
        ui.go("See all unmet needs", "nine", "go_needs", open_q=9)

    # ---- bottom strip -----------------------------------------------------------
    st.markdown("<hr style='border:none;border-top:1px solid #e3e7ee;margin:1.8rem 0 1rem'>", unsafe_allow_html=True)
    s1, s2 = st.columns([5, 1])
    s1.markdown(f'<div class="flow"><span style="color:#5b6574;font-weight:700;margin-right:14px">How we got here</span>'
                f'<b>{f["raw_pulled"]:,}</b> posts collected &nbsp;→&nbsp; <b>{f["clean"]:,}</b> after cleaning &nbsp;→&nbsp; '
                f'<b>{f["relevant_tagged"]:,}</b> read and labelled by AI</div>', unsafe_allow_html=True)
    with s2:
        ui.go("How it works", "how", "go_how")
