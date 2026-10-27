"""Page 5, How it works: six steps, where the posts come from, how the AI was checked, what to keep in mind."""
from __future__ import annotations

import re

import altair as alt
import pandas as pd
import streamlit as st

import common as C
import ui

EVIDENCE_LOG = "https://github.com/Sagar7572/groww-sip-discovery/blob/main/docs/evidence_log_notes.md"
CORE = ["journey_stage", "sip_action", "lapse_type", "stated_triggers", "emotion", "severity"]
STEPS = [("Collect", "Public reviews, forum threads, video comments and Reddit."),
         ("Clean", "Remove copies, spam, staff replies and very short posts."),
         ("Filter", "AI keeps posts about SIPs; when unsure, it keeps them."),
         ("Label", "AI fills the same short form for every post."),
         ("Count", "Compare reasons, sources and stages; rank problems."),
         ("Check", "Two AI models, code checks and a person’s review.")]


def log_entries(md: str) -> list[tuple[str, str]]:
    out = []
    for p in re.split(r"\n(?=#{2,3} Entry )", md):
        m = re.match(r"#{2,3} (Entry [^\n]+)", p)
        if m:
            out.append((m.group(1), p.split("\n", 1)[1].strip()))
    return out


def tile(big: str, text: str) -> str:
    return f'<div class="tile"><div class="t">{ui.esc(big)}</div><div class="d">{ui.esc(text)}</div></div>'


def full_details(posts: pd.DataFrame, val: dict, ag: dict) -> None:
    rel = pd.DataFrame(val.get("relevance_pilot", []))
    if len(rel):
        st.markdown("**Relevance filter: three prompts tried on the same 100 posts**")
        st.dataframe(rel.rename(columns={"prompt": "Prompt", "yes": "Yes", "no": "No", "unsure": "Unsure", "rescued_by_rules": "Turned from no to unsure by code rules"}),
                     hide_index=True, width="stretch")
        st.caption("The first prompt never said “unsure”, so borderline posts were forced into yes or no. The final prompt favours keeping a post. "
                   "The rules were tuned on the same 100 posts, so accuracy here is optimistic; the hand-labelled set will measure the real figure.")
    tag = pd.DataFrame(val.get("tagging_pilot", []))
    if len(tag):
        st.markdown("**Labelling: three prompts tried on the same 50 posts**")
        st.dataframe(tag.rename(columns={"prompt": "Prompt", "items": "Posts", "failed": "Failed", "judged_relevant": "Judged relevant",
                                         "judged_not_relevant": "Judged not relevant", "quote_mismatch_pct": "Quotes not an exact copy (%)",
                                         "tokens_per_item": "Tokens per post"}), hide_index=True, width="stretch")
    fields = ag.get("fields", {})
    if fields:
        st.markdown(f"**Two AI models labelled the same {ag.get('n_items', 0)} posts: agreement by field**")
        d = pd.DataFrame([{"field": C.nice(k), "agree": v, "kind": "Core field" if k in CORE else "Other field"} for k, v in fields.items()])
        d["text"] = d.agree.map(lambda v: f"{v}%")
        base = alt.Chart(d).encode(y=alt.Y("field:N", sort=list(d.sort_values("agree", ascending=False).field), title=None, axis=alt.Axis(ticks=False, domain=False, labelLimit=240)))
        bars = base.mark_bar(cornerRadiusEnd=4, size=14).encode(
            x=alt.X("agree:Q", title="% of posts where both models gave the identical answer", scale=alt.Scale(domain=[0, 105]), axis=alt.Axis(grid=False)),
            color=alt.Color("kind:N", scale=alt.Scale(domain=["Core field", "Other field"], range=[ui.CHOICE, "#9ab9e0"]), legend=alt.Legend(title=None, orient="bottom")))
        st.altair_chart((bars + base.mark_text(align="left", dx=5, fontSize=12).encode(x="agree:Q", text="text:N")).properties(height=24 * len(d) + 110), width="stretch")
        inv = ag.get("involuntary_flagged", {})
        st.caption(f"The second model found payment failures in {inv.get('qwen', '?')} of these posts, the first in {inv.get('gpt-oss-120b', '?')}. "
                   "Segment fields agree only because both say “not stated” almost every time. Agreement between two models is not accuracy: both can be wrong in the same way.")
    corr = val.get("corrections", [])
    if corr:
        st.markdown("**Where AI output was rejected or corrected**")
        st.table(pd.DataFrame(corr).rename(columns={"what_ai_did": "What the AI did", "correction": "What was changed", "why": "Why"}))
    hc = val.get("human_corrections", [])
    st.markdown("**Corrections made by a person**")
    if hc:
        st.table(pd.DataFrame([{"Post (start of text)": c["post"][:140] + ("..." if len(c["post"]) > 140 else ""), "Field": c["field"],
                                "AI said": ", ".join(map(C.nice, c["original"])) if isinstance(c["original"], list) else str(c["original"]),
                                "Corrected to": ", ".join(map(C.nice, c["corrected"])) if isinstance(c["corrected"], list) else str(c["corrected"]),
                                "Why": c["reason"]} for c in hc]))
    else:
        st.caption("No human corrections have been recorded yet.")
    st.markdown("**Hand-labelled golden set:** coming. About 20 posts labelled by hand without seeing the AI’s labels; this page will then show how often the engine agreed.")
    log = C.EXPORT / "evidence_log.md"
    if log.exists():
        entries = [e for e in log_entries(log.read_text(encoding="utf-8")) if re.search(r"Entry [5-9]|Entry \d{2}", e[0])]
        if entries:
            st.markdown("**Working notes, written as each problem happened**")
            for title, body in entries:
                with st.expander(title):
                    st.markdown(body)
    st.markdown("**Known biases and limitations**")
    for item in val.get("limitations", []):
        st.markdown(f"- {item}")


def render() -> None:
    over, posts, val = C.load_json("overview"), C.load_posts(), C.load_json("validation")
    ag, src, f = val.get("agreement", {}), over["sources"], over["funnel"]
    st.title("How the engine works, and how we checked the AI")
    st.markdown('<p class="sub">Six steps from public posts to findings. Every AI step was tested on a small sample and checked by a person before running in full.</p>',
                unsafe_allow_html=True)
    cols = st.columns(6, gap="small")
    for i, (col, (name, text)) in enumerate(zip(cols, STEPS), 1):
        col.markdown(f'<div class="step"><div class="dot">{i}</div><b>{name}</b><p>{text}</p></div>', unsafe_allow_html=True)
    st.write("")

    left, right = st.columns(2, gap="medium")
    with left, st.container(key="card_sources"):
        st.markdown("### Where the posts come from")
        rows = "".join(f"<tr><td>{ui.LONG[s].replace('Reddit (hand-picked threads)', 'Reddit (35 hand-picked threads)')}</td><td>{v['raw_pulled']:,}</td><td>{v['relevant']:,}</td></tr>"
                       for s, v in src.items() if v["raw_pulled"])
        st.markdown('<table class="src"><tr><th>Source</th><th>Collected</th><th>Analysed</th></tr>' + rows
                    + f'<tr class="total"><td>Total</td><td>{f["raw_pulled"]:,}</td><td>{f["relevant_tagged"]:,}</td></tr></table>', unsafe_allow_html=True)
    with right, st.container(key="card_checks"):
        st.markdown("### How we checked the AI")
        core_vals = [ag["fields"][k] for k in CORE if k in ag.get("fields", {})]
        agree = f"{sum(core_vals) / len(core_vals):.0f}%" if core_vals else "n/a"
        versions = max(len(val.get("relevance_pilot", [])), len(val.get("tagging_pilot", [])))
        market = int(posts.triggers_removed.apply(lambda t: "market_fall" in t).sum())
        golden = val.get("golden")
        t1, t2 = st.columns(2)
        t1.markdown(tile(agree, "agreement when two AI models labelled the same posts"), unsafe_allow_html=True)
        t2.markdown(tile(f"{versions} rounds", "of prompt versions compared after people read the AI’s first answers"), unsafe_allow_html=True)
        t3, t4 = st.columns(2)
        t3.markdown("<div style='height:.6rem'></div>" + tile(f"{market}", "wrong “market fell” labels removed by a rule"), unsafe_allow_html=True)
        t4.markdown("<div style='height:.6rem'></div>" + tile(f"{golden['agree']} / {golden['n']}" if golden else "[X / 20]",
                                                             "posts where the AI matched a person’s labels" + ("" if golden else " (coming)")), unsafe_allow_html=True)
        acc = val.get("accuracy_checks", {}).get("random")
        if acc:
            wrong, n = 100 * acc["wrong"] / acc["n"], acc["n"]
            st.markdown("<div style='height:.6rem'></div>" + tile(f"{wrong:.0f} in 100",
                        f"posts have a wrong reason tag in a random check of {n}; up to {100 * acc['wrong_with_borderline'] / n:.0f} counting borderline cases"),
                        unsafe_allow_html=True)
            st.markdown(f'<p style="color:#3a4352;font-size:.92rem;margin-top:.8rem">In the most severe complaints the rate was higher: '
                        f'{val["accuracy_checks"]["severe"]["wrong"]} of {val["accuracy_checks"]["severe"]["n"]} had a wrong reason. '
                        f'{ui.esc(val["accuracy_checks"].get("main_errors", "").capitalize())}</p>', unsafe_allow_html=True)
        st.markdown('<p style="color:#3a4352;font-size:.92rem;margin-top:.8rem">Every quote shown is checked to be the post’s exact words. '
                    'Usernames and personal numbers are removed.</p>', unsafe_allow_html=True)

    st.markdown("<hr style='border:none;border-top:1px solid #e3e7ee;margin:1.8rem 0 .6rem'>", unsafe_allow_html=True)
    st.markdown("### Keep in mind")
    st.markdown("- Unhappy people write more reviews than happy ones.\n"
                "- Posts rarely say a person’s age, income or where their money comes from; interviews fill that gap.\n"
                "- The Reddit threads were hand-picked for stopping and payment stories, so you can leave them out on the “What stops SIPs” page.\n"
                "- The AI can be wrong; the full record of mistakes and fixes is in the evidence log.")
    st.link_button("Open the evidence log →", EVIDENCE_LOG, type="tertiary")
    with st.expander("Full validation details"):
        full_details(posts, val, ag)
