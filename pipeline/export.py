"""Export: build the compact files the dashboard reads, in data/export/.

The dashboard never reads raw or scraped data and never calls any scraper. Refresh it daily with:

    python -m pipeline.export

Files written (all small enough to commit to GitHub):
    posts.jsonl         one line per tagged, relevant post: text, link, tags, theme, quote_display
    embeddings.npy      one vector per post (free local fastembed model), used by "Ask the data"
    embedding_ids.json  which post each vector belongs to (vectors are cached, only new posts are embedded)
    overview.json       volumes, funnel, date coverage, progress, models
    opportunities.json  ranked opportunity areas with scores, branches and example quotes
    themes.json         clusters found by embedding the posts (themes the codebook did not name)
    validation.json     pilot comparisons, inter-model agreement, limitations
    evidence_log.md     copy of docs/evidence_log_notes.md (the AI corrections shown on the validation page)

Privacy: only text that was already scrubbed in collect/common.py is exported. Quotes flagged unreliable
are exported as null (`quote_display`), and the dashboard shows only `quote_display`.
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np

from collect.common import RAW_DIR, ROOT
from pipeline.clean import PROCESSED_DIR, staff_ids
from pipeline.subthemes import AREAS, group_needs, label_problem_areas, name_themes
from pipeline.tag import (CODEBOOK_FILE, MAIN_WINDOW_FROM, PILOT_FILE, TAG_PROMPT_VERSION, TAGGERS,
                          field_values, load_codebook, load_jsonl, results_for, sample_items)

EXPORT_DIR = ROOT / "data" / "export"
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RELEVANCE_PILOT_FILE = PROCESSED_DIR / "pilot_ids.json"
MAX_TEXT_CHARS = 1500        # long comments are cut in the exported file
MIN_GROUP = 15               # groups smaller than this are shown as "low confidence"

# ---------------------------------------------------------------------------
# Assumptions behind the opportunity score. They are judgements, written down here so they can be
# challenged and edited; the dashboard prints them next to the table, and shows the ranking with all
# weights equal as a sensitivity check.
# ---------------------------------------------------------------------------
# Metric-tree branch of each stated trigger (docs/metric_tree.md): A getting going, B involuntary lapse,
# C voluntary lapse, D disengagement, E recovery.
TRIGGER_BRANCH = {
    "mandate_payment_issue": "B", "app_experience": "A", "cash_flow_strain": "C", "irregular_income": "C",
    "life_event": "C", "underwhelming_returns": "C", "market_fall": "C", "expectation_mismatch": "C",
    "confusing_numbers": "C", "trust_concern": "C", "social_influence": "C", "goal_change": "C",
    "fund_switching": "C", "tax_or_lockin": "C", "disengaged_forgot": "D",
}
BRANCH_NAMES = {"A": "A. Getting going", "B": "B. Involuntary lapse", "C": "C. Voluntary lapse",
                "D": "D. Disengagement", "E": "E. Recovery"}
# How directly a branch decides the 12-month metric: B stops the SIP without the person choosing, A decides
# whether the SIP starts working at all, C is the person's choice (harder to change), D is slow drift.
BRANCH_WEIGHT = {"A": 0.9, "B": 1.0, "C": 0.7, "D": 0.6, "E": 0.8}
# Can the product act on it without recommending funds and without fear / FOMO / urgency?
# yes = 1.0, partly = 0.5, no = 0.0, with the reason shown to readers.
SOLVABLE = {
    "mandate_payment_issue": ("yes", "Reliable debits, clear failure messages and easy fixes need no advice and no pressure."),
    "app_experience": ("yes", "Making SIPs easy to find, pause and change is a design fix."),
    "cash_flow_strain": ("partly", "Flexible debit dates or a pause that is easy to resume; no urgency messages."),
    "irregular_income": ("partly", "Flexible date or amount helps; the income itself cannot be changed."),
    "life_event": ("partly", "A graceful pause and easy restart; the event itself is outside the product."),
    "underwhelming_returns": ("partly", "Plain-language context on early results; cannot promise or recommend funds."),
    "market_fall": ("partly", "Calm, factual context; fear-based or urgency nudges are not allowed."),
    "expectation_mismatch": ("yes", "Setting honest expectations early is education, not advice."),
    "confusing_numbers": ("yes", "Explaining NAV, units and XIRR in plain words is not investment advice."),
    "trust_concern": ("partly", "Transparency helps; trust also depends on things outside the app."),
    "social_influence": ("partly", "Happens outside the app; only neutral, non-urgent information is allowed."),
    "goal_change": ("no", "Often a valid reason to withdraw; the product should only make restarting easy."),
    "fund_switching": ("no", "Addressing it would mean recommending funds, which is not allowed."),
    "tax_or_lockin": ("partly", "Plain explanation of lock-in and exit load; no tax advice."),
    "disengaged_forgot": ("yes", "Gentle, non-urgent progress summaries; no FOMO."),
}
SOLVABLE_WEIGHT = {"yes": 1.0, "partly": 0.5, "no": 0.0}
NOT_A_THEME = {"none", "other"}
CORRECTIONS_FILE = ROOT / "data" / "manual" / "corrections.csv"     # human corrections: id, field, corrected_value, reason
LIST_FIELDS = {"triggers", "checks", "outside"}                    # in the csv a list is written with | between values
# "Market fell" is kept only when the post uses market-fall language. In a check of every tagged market_fall post
# (docs/evidence_log_notes.md, Entry 10) the AI had used it for redemption delays, wrong amounts and trust complaints.
MARKET_WORDS = re.compile(r"\bmarkets?\b|crash|covid|corona|nifty|sensex|correction|\bdips?\b|volatil|\bbear|\bfell\b|"
                          r"\bfall(s|ing|en)?\b|\bdeclin|\bloss(es)?\b|negative|\bred\b|deep loss|\bdown\b.{0,20}\b(market|nav)\b", re.I)
# The sub-themes of "Hard to use the app" and the problems after stopping: branch and fixability are judgements
# written down here, like the ones above. (branch, fixable, reason)
SUB_AREA = {
    "autopay_setup": ("B", "yes", "Clear set-up steps and failure messages for autopay need no advice and no pressure."),
    "sip_controls": ("C", "yes", "An easy pause, skip, edit and cancel is a design fix."),
    "returns_display": ("D", "yes", "Showing portfolio and returns correctly and quickly is a design and engineering fix."),
    "app_bugs": ("A", "yes", "Fixing crashes, slowness and bad updates is engineering work."),
    "support": ("C", "partly", "Better support helps, but part of it is staffing outside the product."),
    "missing_feature": ("D", "partly", "Depends on the feature; some would need advice, which is not allowed."),
    "exit_delay": ("E", "yes", "Clear timelines and status tracking for money coming out need no advice."),
    "exit_amount": ("E", "yes", "Explaining NAV cut-off times and showing the expected amount is information, not advice."),
    "exit_hard": ("E", "yes", "An easy, working redemption flow is a design fix."),
}
FILLER = set("""hai hain h hi ka ki ke ko se mein me main mai mujhe mujhko mera meri mere apna apni nahi nhi na kya kyu kyun kaise
kaun kab bhi aur ye yeh wo woh to toh tha thi the rha rhi raha rahi rahe kar kr karo karna kare kiya ho hota hoga hogi hu hun
sakte sakta skta paise paisa aap aapko aapka apne apna diya dijiye baad hua gaya gya maine ab karte karke karne karta chahe sirf lie
dusre uske usko jitna katega matlab har jaygi hote hone vha jo bs bina plz k m v hum humne tum humara kuch kisi sath saath
bhai bhaiya sir sirji ji bro yaar abhi bas lekin par pr ya tak liye liya wala wali vo isme usme jab tab agar ek koi sab kuch
aanu anu und undu illa njan njaan ente enikku ithu athu oru ningal cheyyam cheyyan cheyyuka ee aa ennal pakshe alla aano ano
है हैं का की के को से में मैं नहीं क्या भी और ये तो था थी रहा रही कर हो ही पर ना एक
ആണ് ഉണ്ട് ഇല്ല ഞാൻ എന്റെ ഒരു ഈ ആ""".split())
LAPSE_ACTIONS = {"considering_stop", "paused", "reduced", "stopped", "instalment_failed"}
RECOVERY_WORDS = re.compile(r"\b(resume|resumed|resuming|restart|restarted|restarting|start(ed)? again|reactivat\w*)\b", re.I)


# ---------------------------------------------------------------------------
# loading tagged posts
# ---------------------------------------------------------------------------
def load_tagged() -> tuple[list[dict], dict]:
    """Current-prompt tag records from both taggers. gpt-oss-120b is the primary tagger for an item that both
    models tagged. Returns (records, extra) where extra holds per-tagger counts and the shared-item pairs."""
    by_tagger = {}
    staff = staff_ids()
    for name, cfg in TAGGERS.items():
        recs = [r for r in load_jsonl(PROCESSED_DIR / cfg["file"])
                if r.get("tag_prompt_version") == TAG_PROMPT_VERSION and r.get("model") == cfg["model"] and r["id"] not in staff]
        by_tagger[name] = {r["id"]: r for r in recs}
    primary = {}
    for name in ("gpt-oss-120b", "qwen"):
        for i, r in by_tagger[name].items():
            primary.setdefault(i, r)
    return list(primary.values()), by_tagger


def correct_triggers(text: str, triggers: list[str]) -> tuple[list[str], list[str]]:
    """Drop a 'market_fall' reason the post's own words do not support. Returns (triggers, removed)."""
    if "market_fall" not in triggers or MARKET_WORDS.search(text):
        return list(triggers), []
    kept = [t for t in triggers if t != "market_fall"]
    return (kept or ["other"]), ["market_fall"]


def build_posts(records: list[dict], by_tagger: dict) -> list[dict]:
    clean = {r["id"]: r for r in load_jsonl(PROCESSED_DIR / "clean.jsonl")}
    labels = results_for("v3")
    out = []
    for r in records:
        if r["status"] != "ok" or not r["tags"]["is_relevant"] or r["id"] not in clean:
            continue
        c, t = clean[r["id"]], r["tags"]
        seg = t["segment_signals"]
        both = r["id"] in by_tagger["gpt-oss-120b"] and r["id"] in by_tagger["qwen"]
        triggers, removed = correct_triggers(c["text"], t["stated_triggers"])
        out.append({
            "id": r["id"], "source": r["source"], "url": c.get("url"), "created_at": c.get("created_at"),
            "year": c.get("year"), "rating": c.get("rating"), "language": c.get("language"),
            "context": (c.get("context") or "")[:300], "text": c["text"][:MAX_TEXT_CHARS],
            "tagged_by": r.get("tagged_by", "gpt-oss-120b"), "second_tagger": both,
            "filter_label": labels[r["id"]]["relevant"] if r["id"] in labels else "not_filtered",
            "investor_type": t["investor_type"], "stage": t["journey_stage"], "action": t["sip_action"],
            "lapse_type": t["lapse_type"], "triggers": triggers, "triggers_removed": removed,
            "reason": t["underlying_reason"], "checking": t["checking_behaviour"],
            "checks": t["what_they_check"], "emotion": t["emotion"], "outside": t["outside_app_actions"],
            "income": seg["income_stability"], "age": seg["age_band"], "money": seg["money_source"],
            "influenced_by": seg["influenced_by"], "unmet_need": t["unmet_need"], "severity": t["severity"],
            # user-facing code must use quote_display only; it is null when the quote could not be verified
            "quote_display": r.get("quote_display"), "needs_review": bool(r.get("needs_review")),
        })
    return out


def apply_corrections(posts: list[dict]) -> tuple[list[dict], list[dict]]:
    """Apply the human corrections in data/manual/corrections.csv (columns: id, field, corrected_value, reason).
    Each applied correction keeps the original value, so it can be shown and audited. 'is_relevant' = no removes the post from
    every count. Returns (posts, log)."""
    import csv
    if not CORRECTIONS_FILE.exists():
        return posts, []
    byid = {p["id"]: p for p in posts}
    log, drop = [], set()
    with open(CORRECTIONS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            p, field = byid.get((row.get("id") or "").strip()), (row.get("field") or "").strip()
            raw = (row.get("corrected_value") or "").strip()
            if p is None or (field not in p and field != "is_relevant"):
                print(f"  correction skipped (post not in the relevant tagged posts, or unknown field): {row.get('id')} {field}")
                continue
            if field == "is_relevant":
                if raw.lower() in ("no", "false", "n", "0"):
                    drop.add(p["id"])
                    log.append({"id": p["id"], "source": p["source"], "url": p.get("url"), "field": "is_relevant", "original": "relevant",
                                "corrected": "not relevant", "reason": (row.get("reason") or "").strip(), "post": p["text"][:240]})
                continue
            old = p[field]
            new = [x.strip() for x in raw.split("|") if x.strip()] if field in LIST_FIELDS else (int(raw) if isinstance(old, int) else raw)
            p[field] = new
            p.setdefault("human_corrected", []).append(field)
            log.append({"id": p["id"], "source": p["source"], "url": p.get("url"), "field": field, "original": old, "corrected": new,
                        "reason": (row.get("reason") or "").strip(), "post": p["text"][:240]})
    return [p for p in posts if p["id"] not in drop], log


# ---------------------------------------------------------------------------
# embeddings and themes
# ---------------------------------------------------------------------------
def embed_posts(posts: list[dict]) -> np.ndarray | None:
    """One vector per post; vectors already computed are reused, so a daily refresh only embeds new posts."""
    try:
        from fastembed import TextEmbedding
    except ImportError:
        print("  fastembed is not installed: skipping embeddings (Ask the data and themes will be off)")
        return None
    ids_file, vec_file = EXPORT_DIR / "embedding_ids.json", EXPORT_DIR / "embeddings.npy"
    cache = {}
    if ids_file.exists() and vec_file.exists():
        old = np.load(vec_file)
        cache = dict(zip(json.loads(ids_file.read_text()), old))
    todo = [p for p in posts if p["id"] not in cache]
    if todo:
        print(f"  embedding {len(todo)} new posts with {EMBED_MODEL} (free, runs on this computer)")
        model = TextEmbedding(model_name=EMBED_MODEL)
        texts = [embed_text(p) for p in todo]
        for p, v in zip(todo, model.embed(texts, batch_size=32)):
            cache[p["id"]] = np.asarray(v, dtype=np.float32)
    mat = np.stack([cache[p["id"]] for p in posts]) if posts else np.zeros((0, 384), dtype=np.float32)
    return mat


def embed_text(p: dict) -> str:
    return (f"{p['context']} || {p['text']}" if p["context"] and p["source"] == "tradingqna" else p["text"])[:1000]


def strip_filler(text: str) -> str:
    """Remove links and Hindi / Hinglish / Malayalam filler words, so themes are grouped by what is being said
    and not by which language it is said in."""
    text = re.sub(r"https?://\S+", " ", text)
    words = re.findall(r"[\w']+", text)
    return " ".join(w for w in words if w.lower() not in FILLER)


def embed_for_themes(posts: list[dict]) -> np.ndarray | None:
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return None
    texts = [strip_filler(embed_text(p)) or p["text"][:300] for p in posts]
    model = TextEmbedding(model_name=EMBED_MODEL)
    return np.stack([np.asarray(v, dtype=np.float32) for v in model.embed(texts, batch_size=32)])


def find_themes(posts: list[dict], emb: np.ndarray | None, k: int = 10) -> dict:
    """Group posts by meaning (k-means on embeddings of the text with filler words removed) and name each group:
    its most distinctive words, and a short plain-English name written by the AI."""
    if emb is None or len(posts) < 4 * k:
        return {"clusters": [], "note": "Not enough tagged posts yet to find themes."}
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    norm = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)
    labels = KMeans(n_clusters=k, n_init=10, random_state=7).fit_predict(norm)
    stop = {"sip", "mutual", "fund", "funds", "groww", "app", "invest", "investment", "user", "usr", "https", "com",
            "www", "youtube", "watch", "just", "like", "get", "can", "will", "would", "one", "also"} | FILLER
    cluster_docs = [strip_filler(" ".join(posts[i]["text"] for i in range(len(posts)) if labels[i] == c)) for c in range(k)]
    vec = TfidfVectorizer(stop_words="english", max_features=4000, ngram_range=(1, 2), min_df=1)
    vec.fit(cluster_docs)
    tfidf = vec.transform(cluster_docs).toarray()
    terms = np.array(vec.get_feature_names_out())
    clusters, to_name = [], []
    for c in range(k):
        idx = [i for i in range(len(posts)) if labels[i] == c]
        words = [t for t in terms[np.argsort(-tfidf[c])] if not any(w in stop for w in t.split())][:5]
        centre = norm[idx].mean(axis=0)
        order = sorted(idx, key=lambda i: -float(norm[i] @ centre))
        named = sum(1 for i in idx if any(t not in NOT_A_THEME for t in posts[i]["triggers"]))
        top_trig = Counter(t for i in idx for t in posts[i]["triggers"] if t not in NOT_A_THEME).most_common(3)
        clusters.append({
            "cluster": c, "label": ", ".join(words), "size": len(idx), "share": round(len(idx) / len(posts), 3),
            "with_named_trigger": round(named / len(idx), 3),
            "avg_severity": round(float(np.mean([posts[i]["severity"] for i in idx])), 2),
            "example_ids": [posts[i]["id"] for i in order[:3]], "top_triggers": top_trig,
        })
        to_name.append({"group": c, "keywords": words, "triggers": [t for t, _ in top_trig],
                        "examples": [posts[i]["text"] for i in order[:4]], "member_ids": [posts[i]["id"] for i in idx]})
        for i in idx:
            posts[i]["theme"] = c
    names = name_themes(to_name)
    for cl in clusters:
        cl["name"] = names.get(cl["cluster"])
    clusters.sort(key=lambda c: -c["size"])
    return {"clusters": clusters, "k": k, "named_by_ai": sum(1 for c in clusters if c["name"]),
            "note": "Themes are groups of posts that mean similar things, found automatically after removing Hindi, Hinglish "
                    "and Malayalam filler words. Each name is written by an AI model from the group's words and example posts. "
                    "A theme where few posts have a named reason is one the codebook did not anticipate."}


# ---------------------------------------------------------------------------
# opportunity ranking
# ---------------------------------------------------------------------------
def is_lapse_story(p: dict) -> bool:
    return p["lapse_type"] in ("voluntary", "involuntary", "both") or p["action"] in LAPSE_ACTIONS


def pick_quotes(items: list[dict], n: int = 2) -> list[dict]:
    """Example quotes: verified quotes only (quote_display), short, highest severity first, different sources."""
    cands = [p for p in items if p["quote_display"] and 25 <= len(p["quote_display"]) <= 220]
    cands.sort(key=lambda p: (-p["severity"], len(p["quote_display"])))
    out, used = [], set()
    for p in cands:
        if p["source"] in used and len(cands) > n * 2:
            continue
        used.add(p["source"])
        out.append({"id": p["id"], "quote": p["quote_display"], "source": p["source"], "url": p["url"]})
        if len(out) == n:
            break
    return out


def side_of(p: dict) -> str:
    return AREAS.get(p.get("problem_area"), ("none",))[0]


def make_area(key: str, label: str | None, items: list[dict], branch: str, solv: str, why: str, n_all: int, kind: str) -> dict:
    """`label` is None for stated reasons: the dashboard then uses its plain-language name for the key."""
    sev = float(np.mean([p["severity"] for p in items]))
    return {
        "key": key, "kind": kind, "label": label, "n": len(items), "share_of_tagged": round(len(items) / n_all, 4),
        "avg_severity": round(sev, 2), "branch": branch, "branch_name": BRANCH_NAMES[branch],
        "branch_weight": BRANCH_WEIGHT[branch], "solvable": solv, "solvable_why": why,
        "solvable_weight": SOLVABLE_WEIGHT[solv], "score": round(len(items) * sev * BRANCH_WEIGHT[branch] * SOLVABLE_WEIGHT[solv], 2),
        "score_equal_weights": round(len(items) * sev, 2), "low_confidence": len(items) < MIN_GROUP,
        "lapse_story_share": round(sum(is_lapse_story(p) for p in items) / len(items), 3),
        "sources": dict(Counter(p["source"] for p in items)), "quotes": pick_quotes(items),
    }


def rank_table(areas: list[dict]) -> list[dict]:
    areas.sort(key=lambda a: -a["score"])
    for rank, a in enumerate(areas, 1):
        a["rank"] = rank
    for rank, a in enumerate(sorted(areas, key=lambda a: -a["score_equal_weights"]), 1):
        a["rank_equal_weights"] = rank
    top = max((a["score"] for a in areas), default=1) or 1
    for a in areas:
        a["score_index"] = round(100 * a["score"] / top)
    return areas


RETURNS_GROUP = ("confusing_numbers", "underwhelming_returns", "expectation_mismatch")


def combined_group(posts: list[dict], exit_ids: set, n_all: int) -> tuple[list[dict], dict]:
    """'Making sense of returns': posts that give ANY of three related reasons, each post counted once. Same rules as the
    ranked causes (posts about getting money out are left out). Also compares it with autopay, overall and for first-timers."""
    in_group = lambda p: any(t in p["triggers"] for t in RETURNS_GROUP)
    pool = [p for p in posts if p["id"] not in exit_ids]
    items = [p for p in pool if in_group(p)]
    first = [p for p in pool if p.get("investor_type") == "first_time"]
    autopay = lambda d: sum("mandate_payment_issue" in p["triggers"] for p in d)
    area = []
    if items:
        a = make_area("making_sense_of_returns", "Making sense of returns", items, TRIGGER_BRANCH["underwhelming_returns"],
                      *SOLVABLE["underwhelming_returns"], n_all, "group")
        a["members"] = list(RETURNS_GROUP)
        area = [a]
    compare = {"group_unique": len(items), "group_sum_of_parts": sum(t in p["triggers"] for p in pool for t in RETURNS_GROUP),
               "autopay": autopay(pool), "posts": len(pool),
               "first_time_posts": len(first), "first_time_group": sum(in_group(p) for p in first), "first_time_autopay": autopay(first)}
    return area, compare


def opportunities(posts: list[dict], label_info: dict) -> dict:
    """Two ranked tables. Causes: why people stop or never get going (the stated reasons, with 'Hard to use the app'
    split into sub-themes). After stopping: problems getting money out (redemption, withdrawal, refund). A post about
    getting money out is ranked in the second table only, so nothing is counted twice across the tables."""
    n_all = len(posts)
    exit_posts = [p for p in posts if side_of(p) == "after_stop"]
    exit_ids = {p["id"] for p in exit_posts}
    causes = []
    for trig, branch in TRIGGER_BRANCH.items():
        if trig == "app_experience":
            continue
        items = [p for p in posts if trig in p["triggers"] and p["id"] not in exit_ids]
        if items:
            solv, why = SOLVABLE[trig]
            causes.append(make_area(trig, None, items, branch, solv, why, n_all, "reason"))
    app = [p for p in posts if "app_experience" in p["triggers"] and p["id"] not in exit_ids]
    for key, (side, label, _) in AREAS.items():
        if side != "cause":
            continue
        items = [p for p in app if p.get("problem_area") == key]
        if items:
            branch, solv, why = SUB_AREA[key]
            causes.append(make_area(key, "App: " + label[0].lower() + label[1:], items, branch, solv, why, n_all, "app_sub_theme"))
    unsplit = [p for p in app if not p.get("problem_area")]
    if unsplit:
        causes.append(make_area("app_unsplit", "App: not yet split into sub-themes", unsplit, "A", *SOLVABLE["app_experience"], n_all, "app_sub_theme"))
    not_problem = [p for p in app if p.get("problem_area") == "not_a_problem"]
    after = []
    for key, (side, label, _) in AREAS.items():
        if side != "after_stop":
            continue
        items = [p for p in exit_posts if p["problem_area"] == key]
        if items:
            branch, solv, why = SUB_AREA[key]
            after.append(make_area(key, label, items, branch, solv, why, n_all, "after_stop"))
    groups, group_compare = combined_group(posts, exit_ids, n_all)
    return {
        "causes": rank_table(causes), "after_stop": rank_table(after), "n_tagged": n_all,
        "groups": groups, "group_compare": group_compare,
        "app_posts_total": sum(1 for p in posts if "app_experience" in p["triggers"]),
        "app_posts_not_ranked": len(not_problem),
        "exit_posts": len(exit_posts), "label_info": label_info,
        "assumptions": {"branch_weight": BRANCH_WEIGHT, "solvable_weight": SOLVABLE_WEIGHT,
                        "formula": "score = number of posts x average severity (1-3) x branch weight x fixable weight"},
    }


# ---------------------------------------------------------------------------
# overview, validation
# ---------------------------------------------------------------------------
def overview(posts: list[dict], records: list[dict], by_tagger: dict) -> dict:
    staff = staff_ids()
    all_clean = load_jsonl(PROCESSED_DIR / "clean.jsonl")
    clean = [r for r in all_clean if r["id"] not in staff]
    summary = json.loads((RAW_DIR / "collection_summary.json").read_text()) if (RAW_DIR / "collection_summary.json").exists() else {}
    labels = {i: v for i, v in results_for("v3").items() if i not in staff}
    queue = sample_items()
    tagged_ids = {r["id"] for r in records}
    ok_ids = {r["id"] for r in records if r["status"] == "ok"}
    sources = {}
    for src in ("play_store", "app_store", "tradingqna", "youtube", "reddit"):
        c = [r for r in clean if r["source"] == src]
        kept = [i for i, v in labels.items() if v["source"] == src and v["relevant"] in ("yes", "unsure")]
        dates = sorted(r["created_at"][:10] for r in c if r.get("created_at"))
        sources[src] = {
            "raw_pulled": summary.get(src, {}).get("pulled"), "raw_kept_by_keywords": summary.get(src, {}).get("kept"),
            "clean": len(c), "filter_labelled": sum(1 for v in labels.values() if v["source"] == src),
            "filter_kept": len(kept), "tagged": sum(1 for r in records if r["status"] == "ok" and r["source"] == src),
            "relevant": sum(1 for p in posts if p["source"] == src),
            "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
            "by_year": dict(sorted(Counter(r["year"] for r in c if r.get("year")).items())),
        }
    stamps = [r["tagged_at"] for r in records if r.get("tagged_at")] + [v["labelled_at"] for v in labels.values() if v.get("labelled_at")]
    return {
        "as_of": (max(stamps)[:10] if stamps else datetime.now(timezone.utc).date().isoformat()),
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "sources": sources,
        "staff_excluded": len(all_clean) - len(clean),
        "funnel": {
            "raw_pulled": sum(s["raw_pulled"] or 0 for s in sources.values()),
            "clean": len(clean), "filter_labelled": len(labels),
            "filter_kept": sum(1 for v in labels.values() if v["relevant"] in ("yes", "unsure")),
            "in_tagging_queue": len(queue), "tag_attempted": len(tagged_ids),
            "tagged_ok": len(ok_ids), "relevant_tagged": len(posts), "tagged_not_relevant": len(ok_ids) - len(posts),
        },
        # the two words used in the same way on every page of the dashboard
        "definitions": {
            "tagged": "A post the AI tagger has read and filled in the codebook for (it can still turn out not to be about SIPs).",
            "relevant": "A tagged post that the tagger confirmed is about starting, continuing, pausing or stopping a SIP, or first-time mutual fund investing. "
                        "Every count, chart, quote and answer in the dashboard uses relevant tagged posts only.",
            "staff": "TradingQ&A replies written by the platform's own staff are not investors: they are left out of every count and kept only as context for the thread.",
            "quick_filter": "An earlier, cheaper AI step that screens all cleaned posts. It decides which posts get tagged; it is not the same as 'relevant'.",
        },
        "by_tagger": {n: {"tagged": len([1 for r in d.values() if r["status"] == "ok"]),
                          "failed": len([1 for r in d.values() if r["status"] != "ok"])} for n, d in by_tagger.items()},
        "models": [
            {"stage": "Relevance filter", "model": "openai/gpt-oss-20b (Groq, free tier)", "job": "Says yes / no / unsure: is this post about SIP or mutual fund investing? Two plain-code safety nets turn risky 'no' answers into 'unsure'."},
            {"stage": "Tagging", "model": "openai/gpt-oss-120b (Groq, free tier)", "job": "Fills in the codebook for each post: journey stage, what happened to the SIP, voluntary or involuntary, stated triggers, deeper reason, emotion, severity, an exact quote."},
            {"stage": "Second tagger", "model": "qwen/qwen3.8-27b (Groq, free tier)", "job": "Tags a different random half of the posts in parallel, and the same 30 posts as the first tagger for an agreement check."},
            {"stage": "Themes and search", "model": "paraphrase-multilingual-MiniLM (fastembed, free, local)", "job": "Turns each post into numbers so similar posts can be grouped (themes) and found ('Ask the data')."},
        ],
        "relevance_progress": {"labelled": len(labels), "of": len(clean)},
    }


def need_quote(items: list[dict], theme: str) -> list[dict]:
    """One verified quote per theme: the quote that shares the most words with what the AI wrote as that post's unmet need
    and with the theme name, so the quote illustrates the need and not just any complaint."""
    words = lambda t: {w for w in re.findall(r"[a-z]{4,}", (t or "").lower()) if w not in {"need", "needs", "with", "that", "this", "from", "clear", "better"}}
    cands = [p for p in items if p["quote_display"] and 25 <= len(p["quote_display"]) <= 220]
    if not cands:
        return []
    best = max(cands, key=lambda p: (len(words(p["quote_display"]) & (words(p["unmet_need"]) | words(theme))), p["severity"], -len(p["quote_display"])))
    return [{"id": best["id"], "quote": best["quote_display"], "source": best["source"], "url": best["url"]}]


def unmet_needs(posts: list[dict]) -> dict:
    """The AI-written unmet needs grouped into 6-8 plain-English themes, with a count and one verified quote each.
    The quote comes from a post that is itself in the theme."""
    themes, assign, info = group_needs(posts)
    for p in posts:
        p["need_theme"] = themes[assign[p["id"]]] if p["id"] in assign else None
    rows = []
    for idx, name in enumerate(themes):
        items = [p for p in posts if assign.get(p["id"]) == idx]
        if not items:
            continue
        rows.append({"theme": name, "n": len(items), "share_of_needs": round(len(items) / max(info["grouped"], 1), 3),
                     "example_need": sorted((p["unmet_need"] for p in items), key=len)[len(items) // 2],
                     "quotes": need_quote(items, name), "avg_severity": round(float(np.mean([p["severity"] for p in items])), 2)})
    rows.sort(key=lambda r: (r["theme"] == "Something else", -r["n"]))
    return {"themes": rows, **info}


def per_field_agreement(by_tagger: dict) -> dict:
    a, b = by_tagger["gpt-oss-120b"], by_tagger["qwen"]
    both = [i for i in a if i in b and a[i]["status"] == "ok" and b[i]["status"] == "ok"
            and a[i]["tags"]["is_relevant"] and b[i]["tags"]["is_relevant"]]
    stats = defaultdict(lambda: [0, 0])
    for i in both:
        x, y = field_values(a[i]["tags"]), field_values(b[i]["tags"])
        for k in x:
            if k == "is_relevant":
                continue
            sx = set(x[k]) if isinstance(x[k], list) else {x[k]}
            sy = set(y[k]) if isinstance(y[k], list) else {y[k]}
            stats[k][0] += sx == sy
            stats[k][1] += 1
    inv = lambda d, i: d[i]["tags"]["lapse_type"] in ("involuntary", "both") or d[i]["tags"]["sip_action"] == "instalment_failed"
    return {"n_items": len(both), "fields": {k: round(100 * ok / tot) for k, (ok, tot) in stats.items()},
            "involuntary_flagged": {"gpt-oss-120b": sum(inv(a, i) for i in both), "qwen": sum(inv(b, i) for i in both)}}


def validation(by_tagger: dict) -> dict:
    # --- relevance filter pilot: same 100 items under prompts v1, v2, v3 (v3 includes the safety nets)
    ids = json.loads(RELEVANCE_PILOT_FILE.read_text()) if RELEVANCE_PILOT_FILE.exists() else []
    rel = {v: results_for(v) for v in ("v1", "v2", "v3")}
    relevance_rows = []
    for v, label in (("v1", "v1: first prompt"), ("v2", "v2: examples + rules"), ("v3", "v3: recall-first + safety nets")):
        c = Counter(rel[v][i]["relevant"] for i in ids if i in rel[v])
        relevance_rows.append({"prompt": label, "yes": c["yes"], "no": c["no"], "unsure": c["unsure"],
                               "rescued_by_rules": sum(1 for i in ids if i in rel[v] and rel[v][i].get("rescued_by_rule"))})
    # --- tagging pilot: same 50 items under t1, t2, t3
    pilot = set(json.loads(PILOT_FILE.read_text())) if PILOT_FILE.exists() else set()
    recs = [r for r in load_jsonl(PROCESSED_DIR / TAGGERS["gpt-oss-120b"]["file"]) if r["id"] in pilot]
    tag_rows = []
    static = {"t1": ("t1: first prompt", 632), "t2": ("t2: no early exit", 536), "t3": ("t3: tag what is implied", 644)}
    for v, (label, tokens) in static.items():
        rs = [r for r in recs if r.get("tag_prompt_version") == v]
        ok = [r for r in rs if r["status"] == "ok"]
        relv = [r for r in ok if r["tags"]["is_relevant"]]
        qs = [r for r in relv if r.get("quote_exact") is not None]
        tag_rows.append({
            "prompt": label, "items": len(rs), "failed": len(rs) - len(ok), "judged_relevant": len(relv),
            "judged_not_relevant": len(ok) - len(relv),
            "quote_mismatch_pct": round(100 * sum(1 for r in qs if not r["quote_exact"]) / len(qs)) if qs else None,
            "tokens_per_item": tokens,
        })
    return {
        "relevance_pilot": relevance_rows, "relevance_pilot_n": len(ids), "tagging_pilot": tag_rows,
        "agreement": per_field_agreement(by_tagger),
        "corrections": [
            {"what_ai_did": "Relevance prompt v1 never answered 'unsure' (0 of 100) and labelled a demat-charge reply as a mutual fund question.",
             "correction": "Prompt v2 with worked examples, then v3 'when in doubt choose unsure' plus two plain-code safety nets.",
             "why": "A wrong 'no' loses data for good; a wrong 'yes' is caught by the tagging step."},
            {"what_ai_did": "Tagging prompt t1 let the model skip items: it called 36 of 50 relevant posts 'not relevant', e.g. 'unable to setup autopay for SIP'.",
             "correction": "Prompt t2/t3: no early exit; relevance is only a flag; broader relevance wording in the codebook (v0.2).",
             "why": "The codebook's narrow wording plus a cheap 'skip' answer made the model drop real SIP problems."},
            {"what_ai_did": "In t3 every answer came back numbered '1', so answers could attach to the wrong post; 50 records were discarded.",
             "correction": "Matching now trusts the model's numbers only when they are valid, otherwise uses order, and retries missing items.",
             "why": "Wrong post-to-tag matches would silently corrupt every count."},
            {"what_ai_did": "14% of the model's evidence quotes were not an exact copy of the post (some contained words that were not there).",
             "correction": "Quotes are repaired in code; if the repair is not close enough (score under 80) the quote is flagged and never shown.",
             "why": "A quote shown to a reader must be real text from the post."},
            {"what_ai_did": "The tagger used the reason 'market fell' for 23 posts; on reading all 23, 7 were clearly wrong (redemption delays, a duplicate order, a missing app section, a wrong amount) and 2 were arguable.",
             "correction": "Code now keeps 'market fell' only when the post uses market or loss language, and drops it from posts the AI placed under getting money out. 9 tags were removed; one more wrong tag that a word rule cannot catch was then corrected by hand (see the corrections below).",
             "why": "Counting redemption and trust complaints as 'the market fell' would have fed the framing the brief warns against."},
            {"what_ai_did": "In the second AI pass that sorts 'hard to use the app' posts into sub-themes, 2 of 24 hand-checked labels were wrong (plain questions labelled as problems) and 3 had a doubtful sub-type.",
             "correction": "Kept, with the accuracy stated; posts the AI judged to be praise, questions or staff replies are not ranked.",
             "why": "A label that is 80% exact is fine for ranking areas but not for counting single posts."},
            {"what_ai_did": "The 'confidence' field was never below 0.8.", "correction": "Not used anywhere in the analysis.",
             "why": "A score that never varies cannot tell good tags from bad ones."},
        ],
        "limitations": [
            "App-store reviews skew negative and short; many are generic praise.",
            "TradingQ&A is a Zerodha community, so posters are not necessarily Groww users.",
            "YouTube comments are noisy: very short, many in Hindi or Hinglish, and they react to the video, not to Groww.",
            "Reddit is a curated sample, not all of Reddit: 35 threads chosen by keyword from search results in three subreddits, collected through a third-party scraper (Apify), so it is neither complete nor random.",
            "Results are partial: tagging is still running, one free daily allowance at a time.",
            "Whether a SIP lapse is a failure or the person's choice depends heavily on the source (roughly three quarters failures in Play Store reviews, mostly own choice in YouTube comments), so no single split is a general fact.",
            "Age, income and source of money are almost never stated in public posts, so segment findings use proxies and are validated through interviews.",
            "First-time-investor status and journey stage are often only inferable, so 'unclear' is common.",
            "The two taggers differ (70% exact agreement on the six core fields in a 29-post check); the second one under-detects payment failures.",
            "Opportunity scores rest on written-down judgements (branch weights, solvable weights); a sensitivity view is shown.",
        ],
    }


# ---------------------------------------------------------------------------
def main() -> None:
    import argparse
    from pipeline import subthemes
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-for-ai", type=int, default=0, metavar="MINUTES",
                    help="if the free Groq models are at their daily limit, keep retrying for this long (for labels and theme names)")
    subthemes.WAIT_MINUTES = ap.parse_args().wait_for_ai
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    records, by_tagger = load_tagged()
    posts = build_posts(records, by_tagger)
    print(f"{len(posts)} tagged relevant posts ({len(records)} tag records from both taggers)")
    areas, label_info = label_problem_areas(posts)
    for p in posts:
        p["problem_area"] = areas.get(p["id"])
        # a post about getting money out (redemption delay, wrong amount) is not about the market falling
        if AREAS.get(p["problem_area"], ("",))[0] == "after_stop" and "market_fall" in p["triggers"]:
            p["triggers"] = [t for t in p["triggers"] if t != "market_fall"] or ["other"]
            p["triggers_removed"] = sorted(set(p["triggers_removed"]) | {"market_fall"})
    print(f"  problem areas: {label_info['labelled']} of {label_info['candidates']} candidate posts labelled "
          f"({label_info['new_this_run']} new, {label_info['failed_this_run']} not labelled this run)")
    posts, human = apply_corrections(posts)
    print(f"  human corrections applied: {len(human)}")
    emb = embed_posts(posts)
    themes = find_themes(posts, embed_for_themes(posts))
    needs = unmet_needs(posts)
    opp = opportunities(posts, label_info)
    # the Reddit threads were picked for stop / failure / autopay words, so the dashboard can also show the ranking without them
    opp["without_reddit"] = opportunities([p for p in posts if p["source"] != "reddit"], label_info)
    over = overview(posts, records, by_tagger)
    val = validation(by_tagger)
    val["human_corrections"] = human

    with open(EXPORT_DIR / "posts.jsonl", "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    if emb is not None:
        np.save(EXPORT_DIR / "embeddings.npy", emb.astype(np.float16))
        (EXPORT_DIR / "embedding_ids.json").write_text(json.dumps([p["id"] for p in posts]))
    for name, data in (("overview", over), ("unmet_needs", needs), ("opportunities", opp), ("themes", themes), ("validation", val)):
        (EXPORT_DIR / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    shutil.copy(ROOT / "docs" / "evidence_log_notes.md", EXPORT_DIR / "evidence_log.md")
    f = over["funnel"]
    print(f"Exported to {EXPORT_DIR.relative_to(ROOT)}: data as of {over['as_of']}; "
          f"{f['tagged_ok']} tagged, {f['relevant_tagged']} of them relevant; "
          f"{len(opp['causes'])} cause areas, {len(opp['after_stop'])} after-stopping areas; {len(themes['clusters'])} themes.")


if __name__ == "__main__":
    main()
