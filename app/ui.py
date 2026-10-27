"""Design helpers for the simplified dashboard: styling, cards, quotes, plain-word labels and the shared calculations.

Colours: orange = payment or app failure, blue = the person's own choice, grey = unclear (colour-blind safe pair).
Quotes: only `quote_display` (the verified, exact words of the post) is ever shown as a quote. Long ones are cut with "...".
"""
from __future__ import annotations

import html
from datetime import datetime

import pandas as pd
import streamlit as st

import common as C
import nav

FAIL, CHOICE, UNCLEAR = "#b5530f", "#1f5fc4", "#c5cad3"
GREEN, GREEN_BG, ORANGE_BG = "#0f7b5a", "#e1f3ec", "#fdeadb"

SHORT = {"play_store": "Play Store", "app_store": "App Store", "tradingqna": "TradingQ&A", "youtube": "YouTube", "reddit": "Reddit"}
LONG = {"play_store": "Play Store reviews", "app_store": "App Store reviews", "tradingqna": "TradingQ&A forum",
        "youtube": "YouTube comments", "reddit": "Reddit (hand-picked threads)"}
KIND_OF = {"play_store": "App reviews", "app_store": "App reviews", "tradingqna": "Forum posts", "youtube": "Video comments", "reddit": "Reddit threads"}

PLAIN = {
    "mandate_payment_issue": "Autopay / payment problem", "social_influence": "Influenced by others",
    "confusing_numbers": "Confusing numbers (NAV, XIRR)", "goal_change": "Needs the money / goal changed",
    "cash_flow_strain": "Money is tight", "expectation_mismatch": "Expected faster growth", "underwhelming_returns": "Returns feel too small",
    "autopay_setup": "Mandate set-up problems in the app", "sip_controls": "Can't pause, skip or edit a SIP easily",
    "app_bugs": "App bugs and slowness", "returns_display": "Returns shown wrongly or slowly", "support": "Support is hard to reach",
    "missing_feature": "A feature the person wants is missing", "exit_delay": "Withdrawal is slow or stuck",
    "exit_hard": "Can't find or complete a withdrawal", "exit_amount": "Amount received differs from the app",
    "trust_concern": "Doesn't trust the platform", "market_fall": "Market fell", "disengaged_forgot": "Forgot or lost interest",
    "tax_or_lockin": "Tax, lock-in or exit load", "fund_switching": "Switching to another fund",
}
ACTION = {"instalment_failed": "Payment failed", "considering_stop": "Thinking of stopping", "paused": "Paused", "reduced": "Reduced the amount",
          "stopped": "Stopped", "continuing": "Still investing", "started": "Started a SIP", "increased": "Increased the amount"}


def plain(key: str) -> str:
    return PLAIN.get(str(key)) or C.nice(key)


def area_label(a: dict) -> str:
    return PLAIN.get(a["key"]) or (a.get("label") or C.nice(a["key"])).replace("App: ", "").capitalize()


def causes_of(opp: dict) -> list[dict]:
    """Causes ranked by number of posts. The 'not yet split' bucket is a to-do list for the AI, not a reason, so it is left out."""
    return sorted([a for a in opp.get("causes", []) if a["key"] != "app_unsplit"], key=lambda a: -a["n"])


def unsplit_of(opp: dict) -> int:
    return next((a["n"] for a in opp.get("causes", []) if a["key"] == "app_unsplit"), 0)


def area_id(a: dict) -> str:
    return f"{a['kind']}:{a['key']}"


def with_groups(opp: dict) -> list[dict]:
    """The ranked causes plus the combined groups (each group counts a post once), in one list ordered by posts."""
    return sorted(causes_of(opp) + list(opp.get("groups", [])), key=lambda a: -a["n"])


def area_posts(posts: pd.DataFrame, a: dict) -> pd.DataFrame:
    if a["kind"] == "group":
        return posts[posts.triggers.apply(lambda t: any(k in t for k in a["members"]))]
    if a["kind"] == "reason":
        return posts[posts.triggers.apply(lambda t: a["key"] in t)]
    return posts[posts.problem_area == a["key"]]


def lapse_split(df: pd.DataFrame) -> dict:
    """Stopped-SIP stories: payment or app failure vs the person's own choice (the rest are unclear or both)."""
    l = df[df.lapse_story]
    fail = int((l.involuntary & ~l.voluntary).sum())
    choice = int((l.voluntary & ~l.involuntary).sum())
    return {"n": len(l), "fail": fail, "choice": choice, "other": len(l) - fail - choice}


def kind_of_group(df: pd.DataFrame, min_stories: int = 5) -> str:
    s = lapse_split(df)
    if s["fail"] + s["choice"] < min_stories:
        return "unclear"
    return "fail" if s["fail"] >= s["choice"] else "choice"


COLOUR = {"fail": FAIL, "choice": CHOICE, "unclear": UNCLEAR}


def pct(n: float, d: float) -> int:
    return round(100 * n / d) if d else 0


# ---------------------------------------------------------------------------
# quotes
# ---------------------------------------------------------------------------
def latin_share(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    return sum(c.isascii() for c in letters) / len(letters) if letters else 0.0


def cut(s: str, n: int = 150) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "…"


def year_of(v) -> str:
    return f", {int(v)}" if pd.notna(v) else ""


# Words a quote should contain to be a fair example of a reason (the AI's label can be off for a single post).
HINTS = {"mandate_payment_issue": ["autopay", "auto pay", "mandate", "debit", "payment", "enach", "nach", "bank", "rejected", "failed", "cancel"],
         "autopay_setup": ["autopay", "auto pay", "mandate", "enach", "nach", "upi", "activation", "activate", "setup", "set up"],
         "confusing_numbers": ["nav", "xirr", "return", "number", "profit", "loss", "statement", "percent", "%", "cagr"],
         "expectation_mismatch": ["expect", "return", "growth", "profit", "year", "month"],
         "underwhelming_returns": ["return", "profit", "loss", "growth", "year", "negative", "less"],
         "cash_flow_strain": ["money", "salary", "expense", "afford", "emi", "income", "paisa", "pese", "pesa", "tight"],
         "social_influence": ["friend", "told", "advice", "advised", "youtube", "suggest", "recommend", "family", "heard"],
         "goal_change": ["need", "withdraw", "redeem", "goal", "house", "wedding", "emergency", "paisa", "pese", "nikal"],
         "sip_controls": ["pause", "skip", "edit", "cancel", "stop", "modify", "change", "amount", "date"],
         "exit_delay": ["redeem", "redemption", "withdraw", "delay", "days", "credit", "refund", "stuck"],
         "exit_hard": ["redeem", "redemption", "withdraw", "option", "how", "unable", "cannot", "can't"],
         "exit_amount": ["redeem", "redemption", "withdraw", "received", "amount", "less", "credited", "nav"]}


def soft_lower(s: str) -> str:
    """Lower-case a label for use inside a sentence, keeping acronyms such as NAV, XIRR and SIP."""
    return " ".join(w if sum(ch.isupper() for ch in w) >= 2 else w.lower() for w in s.split(" "))


def sentence_case(s: str) -> str:
    return s[:1].upper() + s[1:]


def pct_text(n: int, d: int) -> str:
    p = 100 * n / d if d else 0
    return "under 1%" if 0 < p < 0.5 else f"{round(p)}%"


def pick_quotes(df: pd.DataFrame, n: int = 1, maxlen: int = 150, latin: bool = True, hints: list[str] | None = None) -> list[dict]:
    """Verified quotes only. Prefers English or Hinglish (Latin script), serious ones, around 90 characters, from different sources.
    With `hints`, prefers quotes that contain one of those words (so an example fits the reason it illustrates)."""
    c = df[df.quote_display.notna()].copy()
    c = c[~c.quote_display.isin(C.QUOTES_SEEN) & (c.quote_display.str.len() >= 30)]
    if latin:
        c = c[c.quote_display.map(latin_share) >= 0.85]
    if hints:
        fit = c[c.quote_display.str.lower().map(lambda t: any(h in t for h in hints))]
        if len(fit) >= n:
            c = fit
    if c.empty:
        return []
    c["_d"] = (c.quote_display.str.len() - 90).abs()
    c = c.sort_values(["severity", "_d"], ascending=[False, True])
    out, seen = [], set()
    for _, r in c.iterrows():
        if r.source in seen and len(c) > 2 * n:
            continue
        seen.add(r.source)
        C.QUOTES_SEEN.add(r.quote_display)
        out.append({"text": cut(r.quote_display, maxlen), "source": r.source, "year": r.year, "url": r.url})
        if len(out) == n:
            break
    return out


def quote_html(q: dict, extra: str = "") -> str:
    link = f' · <a href="{html.escape(q["url"])}" target="_blank">open post</a>' if isinstance(q.get("url"), str) and q["url"] else ""
    return (f'<div class="qbox">“{html.escape(q["text"])}”<div class="qsrc">{SHORT.get(q["source"], q["source"])}{year_of(q.get("year"))}'
            f'{html.escape(extra)}{link}</div></div>')


def show_quotes(df: pd.DataFrame, n: int = 2, maxlen: int = 150) -> None:
    qs = pick_quotes(df, n, maxlen)
    if not qs:
        st.caption("No verified English or Hinglish quote for this group yet. Posts in other scripts are in Ask & browse.")
    for q in qs:
        st.markdown(quote_html(q), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# small html pieces
# ---------------------------------------------------------------------------
def esc(s) -> str:
    return html.escape(str(s))


def label(text: str, colour: str = "#5b6574") -> str:
    return f'<div class="lab" style="color:{colour}">{esc(text)}</div>'


def big(number: str, unit: str = "", colour: str = "#161c28") -> str:
    return f'<div class="big" style="color:{colour}">{esc(number)}<span class="unit"> {esc(unit)}</span></div>'


def split_bar(s: dict, height: int = 22) -> str:
    """Orange = failure, blue = own choice, grey = unclear; the larger of failure and choice carries its percentage."""
    n = max(s["n"], 1)
    parts = [(s["fail"], FAIL, "failure"), (s["choice"], CHOICE, "own choice"), (s["other"], UNCLEAR, "")]
    top = max(parts[:2], key=lambda p: p[0])
    segs = []
    for v, col, name in parts:
        if not v:
            continue
        w = 100 * v / n
        txt = f"{pct(v, n)}% {name}" if (v, col) == (top[0], top[1]) and w >= 22 else ""
        segs.append(f'<div class="seg" style="width:{w:.1f}%;background:{col}" title="{pct(v, n)}% {name or "unclear"}">{txt}</div>')
    return f'<div class="sbar" style="height:{height}px">{"".join(segs)}</div>'


def chip(text: str, kind: str = "grey") -> str:
    return f'<span class="chip chip-{kind}">{esc(text)}</span>'


def go(text: str, page: str, key: str, **state) -> None:
    """A link-style button that opens another page, optionally pre-setting what it shows."""
    if st.button(f"{text} →", key=key, type="tertiary"):
        st.session_state.update(state)
        st.switch_page(nav.PAGES[page])


def banner(over: dict, posts: pd.DataFrame) -> None:
    when = datetime.strptime(over["as_of"], "%Y-%m-%d").strftime("%-d %b %Y") if over.get("as_of") else "n/a"
    st.markdown(f'<div class="banner">Based on {len(posts):,} relevant public posts from {posts.source.nunique()} sources · updated {when} · '
                "Not investment advice</div>", unsafe_allow_html=True)


CSS = """
<style>
:root { --ink:#161c28; --mute:#5b6574; --line:#e3e7ee; --soft:#f4f6fa; --blue:#1f5fc4; }
html, body, [data-testid="stAppViewContainer"] { background:#fff; }
.block-container { max-width: 1180px; padding-top: 4.2rem; padding-bottom: 4rem; }
h1 { font-size: 2.5rem !important; line-height: 1.12 !important; letter-spacing: -0.02em; font-weight: 800 !important; color: var(--ink); margin-bottom: .3rem; }
h2, h3 { letter-spacing: -0.01em; color: var(--ink); font-weight: 750 !important; }
.sub { color: var(--mute); font-size: 1.12rem; line-height: 1.5; margin: 0 0 1.4rem; max-width: 46rem; }
.banner { background: var(--soft); border-bottom: 1px solid var(--line); color: var(--mute); font-size: .88rem;
          padding: 9px 16px; margin: 0 -1rem 1.6rem; border-radius: 6px; }
.lab { font-size: .78rem; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; margin-bottom: .2rem; }
.big { font-size: 3.1rem; font-weight: 800; line-height: 1.05; letter-spacing: -0.03em; }
.big .unit { font-size: 1.05rem; font-weight: 500; color: var(--mute); letter-spacing: 0; }
.lead { font-size: 1.18rem; font-weight: 700; line-height: 1.35; color: var(--ink); margin: .55rem 0 .8rem; }
.qbox { background: var(--soft); border-radius: 10px; padding: 11px 14px; margin: .35rem 0; color: #2a3342; font-size: .97rem; line-height: 1.45; }
.qsrc { color: var(--mute); font-size: .8rem; margin-top: 4px; }
.qsrc a { color: var(--blue); }
.sbar { display: flex; border-radius: 7px; overflow: hidden; background: var(--soft); width: 100%; }
.seg { color: #fff; font-size: .78rem; font-weight: 700; padding: 0 8px; display: flex; align-items: center; white-space: nowrap; overflow: hidden; }
.chip { display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: .78rem; font-weight: 650; margin: 2px 4px 2px 0; }
.chip-grey { background: #eef0f4; color: #3a4352; }
.chip-green { background: @GREEN_BG@; color: @GREEN@; }
.chip-orange { background: @ORANGE_BG@; color: @FAIL@; }
.legend span.sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin: 0 5px 0 12px; }
.bar-track { background: #eef0f4; border-radius: 5px; height: 14px; width: 100%; }
.bar-fill { height: 14px; border-radius: 5px; }
.num { font-weight: 800; color: var(--ink); text-align: right; white-space: nowrap; }
.num span { font-weight: 500; color: var(--mute); }
.step { background: var(--soft); border-radius: 14px; padding: 14px 14px 12px; min-height: 178px; }
.step .dot { width: 26px; height: 26px; border-radius: 50%; background: var(--blue); color: #fff; font-weight: 800; font-size: .85rem;
             display: flex; align-items: center; justify-content: center; margin-bottom: 8px; }
.step b { font-size: 1.02rem; } .step p { margin: .25rem 0 0; color: #3a4352; font-size: .88rem; line-height: 1.4; }
.tile { background: var(--soft); border-radius: 12px; padding: 14px 16px; min-height: 118px; }
.tile .t { font-size: 1.9rem; font-weight: 800; color: var(--blue); line-height: 1.1; }
.tile .d { color: #3a4352; font-size: .88rem; line-height: 1.35; margin-top: 4px; }
table.src { width: 100%; border-collapse: collapse; font-size: .95rem; }
table.src th { text-align: right; color: var(--mute); font-size: .8rem; font-weight: 700; padding: 6px 8px; border-bottom: 2px solid var(--line); }
table.src td { text-align: right; padding: 9px 8px; border-bottom: 1px solid var(--line); }
table.src th, table.src td { border-left: 0 !important; border-right: 0 !important; }
table.src th:first-child, table.src td:first-child { text-align: left; }
table.src tr.total td { font-weight: 800; border-bottom: none; }
.post { border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; background: #fff; height: 100%; }
.post .txt { font-size: 1rem; color: var(--ink); line-height: 1.45; margin-bottom: 8px; }
.post .meta { color: var(--mute); font-size: .82rem; }
.flow { color: var(--ink); font-size: 1.05rem; } .flow b { font-size: 1.5rem; letter-spacing: -0.02em; }
/* cards: bordered containers that stretch to the same height in a row */
[class*="st-key-card"] { border-radius: 16px !important; border: 1px solid var(--line) !important; padding: 1.1rem 1.25rem !important; background: #fff; }
[data-testid="stHorizontalBlock"] { align-items: stretch; }
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] { height: 100%; }
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-card"]) { height: 100%; }
[data-testid="stLayoutWrapper"] > [class*="st-key-card"] { height: 100%; }
/* link-style buttons */
button[kind="tertiary"] { color: var(--blue) !important; font-weight: 700 !important; padding-left: 0 !important; }
.st-key-reasons button[kind="tertiary"] { color: var(--ink) !important; justify-content: flex-start; text-align: left; padding: 0 !important; min-height: 0; }
.st-key-reasons button[kind="tertiary"] p { font-weight: 700 !important; font-size: .95rem !important; line-height: 1.25; }
[data-testid="stTopNavLink"], header { background: #fff; }
@media (max-width: 640px) { h1 { font-size: 1.8rem !important; } .big { font-size: 2.4rem; } .banner { margin: 0 -.5rem 1rem; } }
</style>
"""
for _k, _v in {"@GREEN_BG@": GREEN_BG, "@GREEN@": GREEN, "@ORANGE_BG@": ORANGE_BG, "@FAIL@": FAIL}.items():
    CSS = CSS.replace(_k, _v)




def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
