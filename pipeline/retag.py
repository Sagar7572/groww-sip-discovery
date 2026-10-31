"""Targeted re-tag with prompt version t4 (see docs/evidence_log_notes.md, Entry 20).

Why: a random check found the AI tagging replies and advice as if they were the writer's own problem, and adding extra
reasons to angry complaints about loans, withdrawals or demat. t4 adds four rules and a new field, is_own_experience.

It does NOT touch data/processed/tags.jsonl or tags_qwen.jsonl (the t3 tags, which another job may still be writing).
Results go to data/processed/tags_t4_<tagger>.jsonl; pipeline/export.py lays them over the t3 reason / action / lapse
fields, and the hand corrections in data/manual/corrections.csv are applied on top of that.

Usage (from the project folder):
    python -m pipeline.retag --set test --tagger gpt-oss-120b     # the 100 hand-checked posts (this tagger's half)
    python -m pipeline.retag --set test --tagger qwen
    python -m pipeline.retag --report                              # t4 against the corrected answers
    python -m pipeline.retag --set all --tagger qwen --auto-resume # the posts that carry autopay / returns reasons
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from datetime import datetime

from pipeline import tag
from pipeline.clean import PROCESSED_DIR
from pipeline.tag import TAGGERS, load_jsonl

T4 = "t4"
TEST_IDS_FILE = PROCESSED_DIR / "retag_test_ids.json"        # {"severe": [...], "random": [...]}
GOLD_FILE = PROCESSED_DIR / "retag_gold.json"                # the corrected answers for those posts
ALL_IDS_FILE = PROCESSED_DIR / "retag_all_ids.json"
HEADLINE = {"mandate_payment_issue", "confusing_numbers", "underwhelming_returns", "expectation_mismatch"}


def t4_file(tagger: str):
    return PROCESSED_DIR / f"tags_t4_{tagger}.jsonl"


RULES = """
STOP-REASON RULES (version t4). These override everything above about stated_triggers (tr).
a) Only tag a stop reason the WRITER gives about THEIR OWN SIP or investing: why they stopped, paused, reduced, or are
   worried about continuing. If the text does not say that, tr = [none] (code for 'none').
b) A reply, advice or explanation to someone else ("returns are low in the first years", "there is no guarantee",
   a video link, a general opinion about SIPs) is NOT the writer's own experience: own = false, and tr = [none].
   Use own = true only when the writer describes their own SIP, money or account. Use unclear if you cannot tell.
c) Complaints about loans against funds, withdrawals / redemptions, demat switches, KYC, OTP or customer support get NO
   stop reason (tr = [none]) unless the writer says that it made them stop or pause their SIP.
d) 'Money not received' after a withdrawal or redemption is a withdrawal problem: it is NOT autopay / payment
   (mandate_payment_issue) and NOT a returns reason. tr = [none] unless rule c's exception applies.
A failed SIP debit, a rejected mandate, an autopay that did not run or an instalment that did not go through IS
mandate_payment_issue when the writer says it happened to them. Returns reasons (underwhelming_returns,
expectation_mismatch, confusing_numbers) need the writer to say THEIR OWN returns are small, slower than expected or
confusing. Never copy a reason from the examples unless the item says it.
"""

OWN_FIELD = {
    "type": "one",
    "question": "Does the writer describe THEIR OWN SIP, money or account experience (true), or is it a reply, advice, "
                "explanation or general opinion to someone else (false)? Decide this first.",
    "options": {"true": "the writer's own experience", "false": "a reply, advice, explanation or general opinion",
                "unclear": "cannot tell"},
}

# worked examples for the new rules (compact: only the fields that matter; the rest are filled with 'not stated')
NEW_EXAMPLES = [
    {"text": "No guarantee of returns, ham sirf ummid rakhte hain. It depends on the market ultimately.",
     "tags": {"is_relevant": True, "is_own_experience": "false", "sip_action": "none", "lapse_type": "not_applicable",
              "stated_triggers": ["none"], "severity": 1}},
    {"text": "For autopay use this video, it will pay automatically every month: youtube.com/watch?v=abc",
     "tags": {"is_relevant": True, "is_own_experience": "false", "sip_action": "none", "lapse_type": "not_applicable",
              "stated_triggers": ["none"], "severity": 1}},
    {"text": "I took a loan against my mutual fund and closed it, but support says they are checking for 4 days. Worst app.",
     "tags": {"is_relevant": True, "is_own_experience": "true", "sip_action": "none", "lapse_type": "not_applicable",
              "stated_triggers": ["none"], "emotion": "frustrated", "severity": 3,
              "underlying_reason": "unclear", "unmet_need": "quick closure of a loan against funds"}},
    {"text": "Redemption shows processed but the money has not reached my bank even after 30 days.",
     "tags": {"is_relevant": True, "is_own_experience": "true", "sip_action": "none", "lapse_type": "not_applicable",
              "stated_triggers": ["none"], "emotion": "frustrated", "severity": 3,
              "underlying_reason": "unclear", "unmet_need": "withdrawals that arrive on time"}},
    {"text": "My mutual funds were moved to demat without my consent and now I pay brokerage.",
     "tags": {"is_relevant": True, "is_own_experience": "true", "sip_action": "none", "lapse_type": "not_applicable",
              "stated_triggers": ["none"], "emotion": "frustrated", "severity": 3,
              "underlying_reason": "unclear", "unmet_need": "no changes to my holdings without my consent"}},
    {"text": "Third time my SIP did not get deducted this month, the mandate shows failed. I am stopping it.",
     "tags": {"is_relevant": True, "is_own_experience": "true", "sip_action": "stopped", "lapse_type": "involuntary",
              "stated_triggers": ["mandate_payment_issue"], "emotion": "frustrated", "severity": 3}},
]


def t4_codebook() -> dict:
    cb = copy.deepcopy(tag.load_codebook())
    cb["version"] = 0.3
    fields = {}
    for name, spec in cb["fields"].items():
        if name == "stated_triggers":
            fields["is_own_experience"] = OWN_FIELD
        fields[name] = spec
    cb["fields"] = fields
    for ex in cb["examples"]:
        ex["tags"].setdefault("is_own_experience", "true" if ex["tags"].get("is_relevant", True) else "unclear")
    cb["examples"] = cb["examples"] + NEW_EXAMPLES
    return cb


def prepare() -> tuple[dict, dict]:
    tag.SHORT["is_own_experience"] = "own"
    cb = t4_codebook()
    maps = tag.build_maps(cb)
    base = tag.build_system_prompt

    def with_rules(cb_, maps_):
        text = base(cb_, maps_)
        return text.replace("\nCODEBOOK (version", RULES + "\nCODEBOOK (version", 1)
    tag.build_system_prompt = with_rules
    tag.TAG_PROMPT_VERSION = T4
    return cb, maps


def items_for(ids: list[str], tagger: str, split: bool = True) -> list[dict]:
    clean = {r["id"]: r for r in load_jsonl(tag.CLEAN_FILE)}
    rel = tag.results_for("v3")
    return [{**clean[i], "relevance": rel[i]["relevant"] if i in rel else "yes"} for i in ids
            if i in clean and (not split or tag.tagger_of(i) == tagger)]


def target_ids(which: str) -> list[str]:
    if which == "test":
        t = json.loads(TEST_IDS_FILE.read_text())
        return t["severe"] + t["random"]
    done = set(json.loads(TEST_IDS_FILE.read_text())["severe"] + json.loads(TEST_IDS_FILE.read_text())["random"])
    return [i for i in json.loads(ALL_IDS_FILE.read_text()) if i not in done]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["test", "all", "golden"])
    ap.add_argument("--tagger", default="gpt-oss-120b", choices=sorted(TAGGERS))
    ap.add_argument("--auto-resume", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.report:
        from pipeline.retag_report import report
        report()
        return
    if not args.set:
        ap.print_help()
        return
    cb, maps = prepare()
    tag.use_tagger(args.tagger)
    tag.TAGS_FILE = t4_file(args.tagger)
    if args.set == "golden":  # the 20 golden-set posts, all by one tagger, into data/golden/ (not mixed into the other t4 files)
        tag.TAGS_FILE = PROCESSED_DIR.parent / "golden" / f"tags_t4_golden_{args.tagger}.jsonl"
        items = items_for(json.loads((PROCESSED_DIR.parent / "golden" / "v2_final_ids.json").read_text()), args.tagger, split=False)
    else:
        items = items_for(target_ids(args.set), args.tagger)
    print(f"[{args.tagger}] t4 re-tag, set={args.set}: {len(items)} posts for this tagger")
    while True:
        client = tag.run(items, cb, maps)
        if not client.stopped or not args.auto_resume or client.interrupted:
            break
        wait = max((client.stop_wait or 900) + 90, 120)
        print(f"Auto-resume: waiting {wait / 60:.0f} minutes for Groq's stated reset, then continuing "
              f"(resumes about {datetime.fromtimestamp(time.time() + wait):%H:%M}). Press Ctrl+C to stop.")
        try:
            time.sleep(wait)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
