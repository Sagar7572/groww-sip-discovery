"""Shared helpers for the dashboard: loading the exported files, colours, charts, plain-language names.

The dashboard reads ONLY the files in data/export/ (written by `python -m pipeline.export`). It never scrapes.
Quotes: this app shows `quote_display` only; it is empty when a quote could not be verified.
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

EXPORT = Path(__file__).resolve().parent.parent / "data" / "export"

# Colour-blind-safe categorical colours (checked with the data-viz palette validator): blue and orange are the
# main pair. Never red against green. Greys are for "unclear / not stated".
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
GREY = "#9a9a96"
BRANCH_COLORS = {"A": AQUA, "B": ORANGE, "C": BLUE, "D": YELLOW, "E": MAGENTA}
SOURCE_COLORS = {"play_store": BLUE, "app_store": ORANGE, "tradingqna": AQUA, "youtube": YELLOW, "reddit": MAGENTA}
SOURCE_NAMES = {"play_store": "Play Store reviews", "app_store": "App Store reviews",
                "tradingqna": "TradingQ&A forum", "youtube": "YouTube comments", "reddit": "Reddit"}
STAGE_ORDER = ["before_start", "month_0_1", "month_1_3", "month_4_12", "over_12_months", "after_stop", "unclear"]
STAGE_NAMES = {"before_start": "Before starting", "month_0_1": "First month", "month_1_3": "Months 1-3",
               "month_4_12": "Months 4-12", "over_12_months": "Over a year", "after_stop": "After stopping",
               "unclear": "Not stated"}
NICE = {
    "mandate_payment_issue": "Autopay / payment problem", "app_experience": "Hard to use the app",
    "cash_flow_strain": "Money is tight", "irregular_income": "Irregular income", "life_event": "Life event",
    "underwhelming_returns": "Returns feel small", "market_fall": "Market fell", "expectation_mismatch": "Expected faster growth",
    "confusing_numbers": "Confusing numbers (NAV, XIRR)", "trust_concern": "Trust concern",
    "social_influence": "Influenced by others", "goal_change": "Goal changed / needs the money", "disengaged_forgot": "Forgot or lost interest",
    "fund_switching": "Switching to another fund", "tax_or_lockin": "Tax / lock-in / exit load", "other": "Something else", "none": "No reason given",
    "instalment_failed": "Instalment failed", "considering_stop": "Thinking of stopping", "stopped": "Stopped", "paused": "Paused",
    "reduced": "Reduced amount", "continuing": "Still investing", "started": "Started a SIP", "increased": "Increased amount",
    "voluntary": "Person chose to stop", "involuntary": "Stopped without the person choosing", "both": "Both", "not_applicable": "No lapse",
    "first_time": "First-time investor", "experienced": "Experienced investor", "unclear": "Not stated", "not_mentioned": "Not mentioned",
    "asked_friend_family": "Asked friends / family", "watched_youtube_finfluencer": "Watched YouTube / finfluencers",
    "posted_reddit_forum": "Posted on a forum", "searched_google": "Searched online", "asked_advisor": "Asked an advisor",
    "contacted_support": "Contacted support", "asked_ai_chatbot": "Asked an AI chatbot", "none_mentioned": "None mentioned",
    "daily_or_more": "Daily or more", "weekly": "Weekly", "monthly": "Monthly", "rarely": "Rarely", "only_when_worried": "Only when worried",
    "portfolio_value": "Portfolio value", "returns_percent": "Returns %", "profit_loss_amount": "Profit / loss amount",
    "autopay_setup": "Autopay / mandate set-up and changes", "sip_controls": "Cannot pause, skip, edit or cancel a SIP easily",
    "returns_display": "Portfolio and returns shown wrongly or slowly", "app_bugs": "App updates, bugs and slowness",
    "support": "Support is unreachable or unhelpful", "missing_feature": "A feature the person wants is missing",
    "exit_delay": "Redemption, withdrawal or refund is slow or stuck", "exit_amount": "Amount received differs from what the app showed",
    "exit_hard": "Cannot find or complete a redemption", "not_a_problem": "Not a problem post (praise, question, staff reply)",
    "nav": "NAV", "xirr": "XIRR", "statement_email": "Statement email", "market_news": "Market news",
}
STATUS_NOTE = "Not investment advice. This tool describes what public posts say; it does not recommend any fund, stock or action."


def nice_action(x) -> str:
    """sip_action wording: 'none' here means no SIP action was mentioned (not 'no reason')."""
    return "No SIP action mentioned" if str(x) == "none" else nice(x)


def nice(x) -> str:
    return NICE.get(str(x), STAGE_NAMES.get(str(x), str(x).replace("_", " ").capitalize()))


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_json(name: str) -> dict:
    path = EXPORT / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@st.cache_data(show_spinner=False)
def load_posts() -> pd.DataFrame:
    path = EXPORT / "posts.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["involuntary"] = df.lapse_type.isin(["involuntary", "both"]) | (df.action == "instalment_failed")
    df["voluntary"] = df.lapse_type.isin(["voluntary", "both"])
    df["lapse_story"] = df.lapse_type.isin(["voluntary", "involuntary", "both"]) | df.action.isin(
        ["considering_stop", "paused", "reduced", "stopped", "instalment_failed"])
    df["first_time"] = df.investor_type.eq("first_time")
    df["checking_stated"] = df.checking.ne("not_mentioned")
    df["checks_stated"] = df.checks.apply(lambda l: any(x != "not_mentioned" for x in l))
    df["outside_stated"] = df.outside.apply(lambda l: any(x != "none_mentioned" for x in l))
    df["irregular_income"] = df.triggers.apply(lambda t: "irregular_income" in t)
    df["year"] = pd.to_numeric(df.year, errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_embeddings():
    vec, ids = EXPORT / "embeddings.npy", EXPORT / "embedding_ids.json"
    if not (vec.exists() and ids.exists()):
        return None, []
    m = np.load(vec).astype(np.float32)
    m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
    return m, json.loads(ids.read_text())


def pct(n: float, d: float, digits: int = 0) -> str:
    return f"{100 * n / d:.{digits}f}%" if d else "n/a"


def explode_counts(df: pd.DataFrame, col: str, drop=()) -> pd.DataFrame:
    s = df[col].explode().dropna()
    s = s[~s.isin(drop)]
    out = s.value_counts().rename_axis("key").reset_index(name="n")
    out["label"] = out.key.map(nice)
    return out


QUOTES_SEEN: set = set()      # quotes already shown on the current page (reset at the start of each page)


def quotes_for(df: pd.DataFrame, n: int = 2, short: int = 200) -> list[dict]:
    """Verified quotes only (quote_display), short ones first, severe first, from different sources if possible."""
    c = df[df.quote_display.notna() & ~df.quote_display.isin(QUOTES_SEEN)].copy()
    c = c[c.quote_display.str.len().between(25, short)]
    c = c.sort_values(["severity", "quote_display"], ascending=[False, True], key=lambda s: s if s.name == "severity" else s.str.len())
    out, seen = [], set()
    for _, r in c.iterrows():
        if r.source in seen and len(c) > 2 * n:
            continue
        seen.add(r.source)
        QUOTES_SEEN.add(r.quote_display)
        out.append({"quote": r.quote_display, "source": r.source, "year": r.year, "url": r.url})
        if len(out) == n:
            break
    return out


def show_quotes(df: pd.DataFrame, n: int = 2) -> None:
    qs = quotes_for(df, n)
    if not qs:
        st.caption("No verified quotes for this group yet.")
    for q in qs:
        year = f", {int(q['year'])}" if pd.notna(q["year"]) else ""
        link = f" [open post]({q['url']})" if q.get("url") else ""
        st.markdown(f"> “{q['quote']}”  \n> <small>{SOURCE_NAMES.get(q['source'], q['source'])}{year}{link}</small>",
                    unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# charts (one axis, thin bars, rounded ends, values written on the bars, colour-blind safe)
# ---------------------------------------------------------------------------
def stacked_bar(data: pd.DataFrame, x: str, y: str, group: str, domain: list, range_: list, order: list | None = None,
                x_title: str = "", normalize: bool = False, horizontal: bool = True) -> alt.Chart:
    stack = "normalize" if normalize else True
    enc = dict(color=alt.Color(f"{group}:N", scale=alt.Scale(domain=domain, range=range_),
                               legend=alt.Legend(title=None, orient="bottom", columns=2, labelLimit=260, symbolType="square")),
               tooltip=[alt.Tooltip(f"{y}:N", title=""), alt.Tooltip(f"{group}:N", title=""), alt.Tooltip(f"{x}:Q")])
    if horizontal:
        ch = alt.Chart(data).mark_bar(stroke="white", strokeWidth=2, size=22).encode(
            y=alt.Y(f"{y}:N", sort=order, title=None, axis=alt.Axis(ticks=False, domain=False, labelLimit=240)),
            x=alt.X(f"{x}:Q", stack=stack, title=x_title or None, axis=alt.Axis(grid=False)), **enc)
        return ch.properties(height=34 * data[y].nunique() + 150)
    ch = alt.Chart(data).mark_bar(stroke="white", strokeWidth=2).encode(
        x=alt.X(f"{y}:N", sort=order, title=None), y=alt.Y(f"{x}:Q", stack=stack, title=x_title or None), **enc)
    return ch.properties(height=380)


def counts_frame(series: pd.Series, mapper=nice, top: int | None = None) -> pd.DataFrame:
    vc = series.value_counts()
    if top:
        vc = vc.head(top)
    return pd.DataFrame({"label": [mapper(k) for k in vc.index], "n": vc.values, "key": vc.index})


def with_pct_labels(df: pd.DataFrame, total: int) -> pd.DataFrame:
    df = df.copy()
    df["text_label"] = [f"{n:,}  ({100 * n / total:.0f}%)" if total else str(n) for n in df.n]
    return df


def hbar(df: pd.DataFrame, total: int | None = None, color: str = BLUE, title: str = "") -> alt.Chart:
    """Horizontal bars of counts with 'n (share)' written at the end of each bar."""
    d = with_pct_labels(df, total) if total else df.assign(text_label=df.n.map(lambda n: f"{n:,}"))
    base = alt.Chart(d).encode(y=alt.Y("label:N", sort=list(d.sort_values("n", ascending=False).label), title=None,
                                      axis=alt.Axis(labelLimit=280, ticks=False, domain=False)))
    bars = base.mark_bar(cornerRadiusEnd=4, size=16, color=color).encode(
        x=alt.X("n:Q", title=title or None, axis=alt.Axis(grid=False, labels=False, ticks=False, domain=False)),
        tooltip=[alt.Tooltip("label:N", title=""), alt.Tooltip("n:Q", title="posts")])
    text = base.mark_text(align="left", dx=5, fontSize=12).encode(x="n:Q", text="text_label:N")
    return (bars + text).properties(height=30 * len(d) + 50).configure_view(stroke=None)


def small_group_note(n: int) -> str:
    return " (low confidence: fewer than 15 posts)" if n < 15 else ""


REDDIT_NOTE = ("Reddit threads were picked because they mention stopping, failing or autopay, so they inflate the lapse and autopay counts; "
               "switch this on to see the same view without them.")


def reddit_toggle() -> bool:
    """One switch shared by the Opportunity and Metric-tree pages (same key, so it stays set when you move between them)."""
    on = st.toggle("Exclude curated Reddit", value=False, key="excl_reddit")
    st.caption(REDDIT_NOTE)
    return on
