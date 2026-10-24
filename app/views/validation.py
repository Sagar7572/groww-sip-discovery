"""Page 8: how the quality of the engine's work was checked, what went wrong, and what the limits are."""
from __future__ import annotations

import re

import altair as alt
import pandas as pd
import streamlit as st

import common as C


def log_entries(md: str) -> list[tuple[str, str]]:
    parts = re.split(r"\n(?=#{2,3} Entry )", md)
    out = []
    for p in parts:
        m = re.match(r"#{2,3} (Entry [^\n]+)", p)
        if m:
            out.append((m.group(1), p.split("\n", 1)[1].strip()))
    return out


def render(over: dict, posts: pd.DataFrame) -> None:
    val = C.load_json("validation")
    ag = val.get("agreement", {})
    core = ["journey_stage", "sip_action", "lapse_type", "stated_triggers", "emotion", "severity"]
    st.title("The engine checks its own work, and the checks caught real errors: the AI's first prompts were wrong in ways we found and fixed")
    st.write("Quality is checked in four ways: (1) the same sample is tried with several prompts and the changes are read by a person, "
             "(2) code verifies every quote against the post, (3) a second AI model tags the same posts, and (4) a small set of posts labelled by hand will measure real accuracy (coming).")

    st.subheader("1. Relevance filter: three prompts tried on the same 100 posts")
    rel = pd.DataFrame(val.get("relevance_pilot", []))
    if len(rel):
        st.dataframe(rel.rename(columns={"prompt": "Prompt", "yes": "Yes", "no": "No", "unsure": "Unsure", "rescued_by_rules": "Turned from no to unsure by code rules"}),
                     hide_index=True, width="stretch")
        st.caption("The first prompt never said \"unsure\" (0 of 100), so borderline posts were forced into yes or no. The final prompt favours keeping a post, "
                   "because a wrongly dropped post is lost for good, while a wrongly kept one is caught at the tagging step. "
                   "These rules were tuned on the same 100 posts, so accuracy here is optimistic; the hand-labelled set will measure the real figure.")

    st.subheader("2. Tagging: three prompts tried on the same 50 posts")
    tag = pd.DataFrame(val.get("tagging_pilot", []))
    if len(tag):
        st.dataframe(tag.rename(columns={"prompt": "Prompt", "items": "Posts", "failed": "Failed", "judged_relevant": "Judged relevant",
                                         "judged_not_relevant": "Judged not relevant", "quote_mismatch_pct": "Quotes not an exact copy (%)",
                                         "tokens_per_item": "Tokens per post"}), hide_index=True, width="stretch")
        st.caption("The first prompt let the model skip posts: it called 36 of 50 posts \"not relevant\", including clear SIP problems. That output was rejected and the prompt was changed.")

    fields = ag.get("fields", {})
    core_avg = sum(fields[k] for k in core if k in fields) / max(len([k for k in core if k in fields]), 1)
    st.subheader(f"3. Two AI models tagged the same {ag.get('n_items', 0)} posts: they gave the identical answer on {core_avg:.0f}% of the six core fields")
    if fields:
        d = pd.DataFrame([{"field": C.nice(k), "agree": v, "core": k in {"journey_stage", "sip_action", "lapse_type", "stated_triggers", "emotion", "severity"}} for k, v in fields.items()])
        d["kind"] = d.core.map({True: "Core field", False: "Other field"})
        d["text"] = d.agree.map(lambda v: f"{v}%")
        base = alt.Chart(d).encode(y=alt.Y("field:N", sort=list(d.sort_values("agree", ascending=False).field), title=None, axis=alt.Axis(ticks=False, domain=False, labelLimit=240)))
        bars = base.mark_bar(cornerRadiusEnd=4, size=14).encode(x=alt.X("agree:Q", title="% of posts where both models gave the identical answer", scale=alt.Scale(domain=[0, 105]), axis=alt.Axis(grid=False)),
                                                                color=alt.Color("kind:N", scale=alt.Scale(domain=["Core field", "Other field"], range=[C.BLUE, "#9ab9e0"]), legend=alt.Legend(title=None, orient="bottom")))
        st.altair_chart((bars + base.mark_text(align="left", dx=5, fontSize=12).encode(x="agree:Q", text="text:N")).properties(height=24 * len(d) + 120), width="stretch")
        inv = ag.get("involuntary_flagged", {})
        st.caption(f"Where they differ matters: the second model found payment failures in {inv.get('qwen', '?')} of these posts, the first in {inv.get('gpt-oss-120b', '?')}. "
                   "The segment fields look like they agree only because both say \"not stated\" almost every time. Agreement between two models is not accuracy: "
                   "both can be wrong in the same way.")

    st.subheader("4. Hand-labelled golden set")
    st.info("To be added: about 20 posts, picked across sources and themes, labelled by hand without seeing the AI's tags. "
            "This page will then show how often the engine agreed with the person, field by field, and list the cases where it failed.")

    st.subheader("Where AI output was rejected or corrected")
    corr = val.get("corrections", [])
    if corr:
        st.table(pd.DataFrame(corr).rename(columns={"what_ai_did": "What the AI did", "correction": "What was changed", "why": "Why"}))
    hc = val.get("human_corrections", [])
    st.subheader("Corrections made by a person")
    if hc:
        st.caption("Each row is a tag the AI got wrong and a person corrected by hand (the list is a file, data/manual/corrections.csv, applied every time the data is exported). "
                   "The dashboard uses the corrected value everywhere.")
        st.table(pd.DataFrame([{"Post (start of text)": c["post"][:140] + ("..." if len(c["post"]) > 140 else ""), "Field": c["field"],
                                "AI said": ", ".join(map(C.nice, c["original"])) if isinstance(c["original"], list) else str(c["original"]),
                                "Corrected to": ", ".join(map(C.nice, c["corrected"])) if isinstance(c["corrected"], list) else str(c["corrected"]),
                                "Why": c["reason"]} for c in hc]))
    else:
        st.caption("No human corrections have been recorded yet.")
    log = (C.EXPORT / "evidence_log.md")
    if log.exists():
        entries = [e for e in log_entries(log.read_text(encoding="utf-8")) if re.search(r"Entry [5-9]|Entry \d{2}", e[0])]
        if entries:
            st.caption("The full working notes, written as each problem happened:")
            for title, body in entries:
                with st.expander(title):
                    st.markdown(body)

    st.subheader("Biases and limitations")
    for item in val.get("limitations", []):
        st.markdown(f"- {item}")
    mix = posts.source.value_counts()
    st.caption("Source mix of the relevant tagged posts: " + ", ".join(f"{C.SOURCE_NAMES.get(s, s)} {100 * k / len(posts):.0f}%" for s, k in mix.items()) + ".")
