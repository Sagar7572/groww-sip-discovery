"""Build golden set v2 (plain code, NO AI calls; no other data is changed).

    python -m eval.build_golden_v2 --list-nonenglish   # prints the non-English posts so translations can be written
    python -m eval.build_golden_v2                     # builds the sheet

Reads data/golden/old/ (the first sheet: keeps 8 posts by their '#'), data/golden/translations_v2.json (id -> literal translation).
Writes golden_set_v2.xlsx, golden_set_v2.csv and ai_answers_v2_hidden.json in data/golden/ (git-ignored).
"""
from __future__ import annotations

import csv
import json
import random
import re
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from eval.build_golden_sheet import OUT, REASON, SOURCE_NAMES, ai_answer, load_candidates, paths_excluded

SEED = 3031
KEEP = [3, 5, 7, 10, 12, 13, 17, 20]
SLOTS = {"pay": 4, "stop": 4, "returns": 4, "advice": 2, "regional": 2, "plain_q": 2, "praise": 1, "withdraw": 1}

ADVICE = re.compile(r"\b(you should|you can|i would (suggest|recommend)|i suggest|i recommend|better (to|if)|go for|"
                    r"don'?t worry|my advice|you need to|just (do|invest|start)|try (to|the)|make sure)\b", re.I)
WITHDRAW = re.compile(r"withdraw|redeem|redemption|refund|not (been )?credited|payout|money.{0,25}(stuck|not received)", re.I)
PRAISE = re.compile(r"\b(great|good|best|awesome|nice|love|excellent|easy|smooth|please add|kindly add|add (a|an|the)?\s?\w*\s?(option|feature)|request)\b", re.I)

HEAD = ["#", "Source", "Year", "Link", "Post (exactly as written)", "Context (thread question / video title)",
        "In plain English", "1. About SIPs?", "2. Writer's own experience?", "3. What kind of story?",
        "4. Main reason they give", "My note"]
Q3 = ["Payment or app failure", "Own choice to stop or pause", "No stop story", "Unclear"]
Q4 = ["Autopay/payment problem", "Confusing numbers (NAV/XIRR)", "Returns too small", "Expected faster growth",
      "Money is tight", "Needs money/goal changed", "Influenced by others", "Distrusts platform",
      "Hard to use app", "Market fell", "Life event", "Switching fund", "Something else", "None given"]


def classes(p: dict) -> set[str]:
    trig, text = set(p["triggers"]), p["full_text"]
    own = not ADVICE.search(text)
    c = set()
    if own and (p["action"] == "instalment_failed" or p["lapse_type"] == "involuntary"):
        c.add("pay")
    if own and p["lapse_type"] == "voluntary" and p["action"] in ("stopped", "paused", "reduced", "considering_stop"):
        c.add("stop")
    if own and trig & {"confusing_numbers", "underwhelming_returns", "expectation_mismatch"} and p["lapse_type"] != "involuntary":
        c.add("returns")
    if p["source"] in ("tradingqna", "youtube", "reddit") and ADVICE.search(text) and p["action"] == "none":
        c.add("advice")
    if p["language"] != "en":
        c.add("regional")
    if p["action"] == "none" and "?" in text and trig <= {"none", "other"} and p["lapse_type"] == "not_applicable" and not WITHDRAW.search(text):
        c.add("plain_q")
    if p["action"] == "none" and trig <= {"none", "other"} and PRAISE.search(text) and "?" not in text and not WITHDRAW.search(text):
        c.add("praise")
    if WITHDRAW.search(text) and p["action"] in ("none", "instalment_failed") and p["lapse_type"] != "voluntary":
        c.add("withdraw")
    return c


def select() -> list[dict]:
    old_ids = json.load(open(OUT / "old/ai_answers_hidden.json"))["items"]
    # App Store has only 3 unused posts, so its 2 dropped posts may come back (needed for "2 from every source")
    dropped = {v["id"] for k, v in old_ids.items() if int(k) not in KEEP and not v["id"].startswith("app_store")}
    kept_ids = [old_ids[str(k)]["id"] for k in KEEP]
    excluded = paths_excluded() | dropped
    allc = {p["id"]: p for p in load_candidates(paths_excluded(), min_words=4)}  # kept posts are looked up here
    kept = [allc[i] for i in kept_ids]
    cands = [p for p in load_candidates(excluded, min_words=4) if p["id"] not in kept_ids]
    for p in kept + cands:
        p["_c"] = classes(p)
    # give each kept post a slot (try every assignment; posts that fit nothing take any free slot at the end)
    slot_list = [s for s, n in SLOTS.items() for _ in range(n)]
    def assign(i, free):
        """Backtracking: give each kept post a free slot it fits; returns the slots left over or None."""
        if i == len(kept):
            return free
        for j, s_ in enumerate(free):
            if s_ in kept[i]["_c"] and s_ not in free[:j]:
                r = assign(i + 1, free[:j] + free[j + 1:])
                if r is not None:
                    return r
        return None
    left = assign(0, slot_list)
    if left is None:  # some kept post fits no slot: allow it to take any slot
        left = slot_list[:]
        for k in kept:
            fit = [s_ for s_ in left if s_ in k["_c"]]
            left.remove(fit[0] if fit else left[-1])
    rng = random.Random(SEED)
    for _ in range(20000):
        pool_used, new = set(), []
        for s in left:
            pool = [p for p in cands if s in p["_c"] and p["id"] not in pool_used]
            if not pool:
                break
            p = rng.choice(pool)
            pool_used.add(p["id"])
            new.append(p)
        else:
            rows = kept + new
            if all(sum(r["source"] == s for r in rows) >= 2 for s in SOURCE_NAMES):
                rng.shuffle(rows)
                return rows
    sys.exit("Could not satisfy the mix.")


def build(rows: list[dict]) -> None:
    tr = json.load(open(OUT / "translations_v2.json")) if (OUT / "translations_v2.json").exists() else {}
    wb = Workbook()
    ws = wb.active
    ws.title = "Label here"
    ws.append(HEAD)
    table = []
    for i, p in enumerate(rows, 1):
        r = [i, SOURCE_NAMES[p["source"]], int(p["year"]), p["link"] or "(no link)", p["full_text"], p["full_context"],
             tr.get(p["id"], "") if p["language"] != "en" else ""] + [""] * 5
        ws.append(r)
        table.append(r)
    navy, ans, ans_head, plain = (PatternFill("solid", fgColor=c) for c in ("1F3A5F", "FFF4C2", "F2B600", "E8EEF7"))
    for c in range(1, len(HEAD) + 1):
        cell = ws.cell(1, c)
        is_ans = 8 <= c <= 12
        cell.font = Font(bold=True, color="000000" if is_ans else "FFFFFF")
        cell.fill = ans_head if is_ans else navy
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for c, w in enumerate([5, 12, 7, 28, 70, 36, 40, 12, 16, 26, 30, 32], 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    for r in range(2, len(rows) + 2):
        for c in range(1, len(HEAD) + 1):
            cell = ws.cell(r, c)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if 8 <= c <= 12:
                cell.fill = ans
            elif c == 7:
                cell.fill = plain
        ws.row_dimensions[r].height = min(409, max(60, 15 * (len(rows[r - 2]["full_text"]) // 75 + 2)))
    ws.row_dimensions[1].height = 36
    ws.freeze_panes = "E2"

    # options are written directly inside each rule (no reference to another tab) so Google Sheets keeps them
    for col, vals in [("H", ["Yes", "No"]), ("I", ["Yes", "No", "Unclear"]), ("J", Q3), ("K", Q4)]:
        formula = '"' + ",".join(vals) + '"'
        assert len(formula) - 2 <= 255 and not any("," in v for v in vals), (col, len(formula))
        dv = DataValidation(type="list", formula1=formula, allow_blank=True, showErrorMessage=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{len(rows) + 1}")
    for c in range(1, len(HEAD) + 1):
        ws.column_dimensions[get_column_letter(c)].hidden = False

    hw = wb.create_sheet("How to decide")
    hw.append(["Question", "Answer", "What it means", "Short example"])
    for row in HOW:
        hw.append(list(row))
    for c in range(1, 5):
        hw.cell(1, c).font, hw.cell(1, c).fill = Font(bold=True, color="FFFFFF"), navy
    for c, w in enumerate([28, 32, 90, 48], 1):
        hw.column_dimensions[get_column_letter(c)].width = w
    for r in hw.iter_rows(min_row=2):
        for cell in r:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    hw.freeze_panes = "A2"
    ab = wb.create_sheet("About")
    for t in ABOUT:
        ab.append([t])
    ab.column_dimensions["A"].width = 140
    for r in ab.iter_rows():
        r[0].alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(OUT / "golden_set_v2.xlsx")
    with open(OUT / "golden_set_v2.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        w.writerows(table)
    hidden = {"seed": SEED, "note": "AI answers for the 20 posts. Do not open before labelling.",
              "items": {str(i): {"id": p["id"], **ai_answer(p)} for i, p in enumerate(rows, 1)}}
    json.dump(hidden, open(OUT / "ai_answers_v2_hidden.json", "w"), indent=1, ensure_ascii=False)


HOW = [
    ("1. About SIPs?", "Yes", "The post is about mutual funds or SIPs in some way: starting, continuing, stopping, payments, returns, the app, withdrawals, or being a new investor.", "\"My SIP got debited twice.\""),
    ("1. About SIPs?", "No", "Clearly nothing to do with mutual funds: only stocks, F&O, IPOs, demat or broker charges, spam, or praise with no content.", "\"Options trading here is superfast.\""),
    ("2. Writer's own experience?", "Yes", "The writer describes what happened to THEM.", "\"My SIP failed twice.\""),
    ("2. Writer's own experience?", "No", "A reply, advice or explanation to someone else, or a general statement.", "\"You should check if your mandate is active.\""),
    ("2. Writer's own experience?", "Unclear", "Cannot tell whether it is their own story.", "\"SIP not working.\""),
    ("3. What kind of story?", "Payment or app failure", "A debit failed, a mandate expired or was rejected, the bank or balance blocked it, or an app problem. The person did not intend to stop.", "\"Autopay failed 3 times and my SIP got cancelled.\""),
    ("3. What kind of story?", "Own choice to stop or pause", "The person chose to pause, reduce or stop (or is thinking of it).", "\"I stopped my SIP because returns were low.\""),
    ("3. What kind of story?", "No stop story", "No stopping, pausing or risk of it is mentioned: a question, praise, a request, advice.", "\"How do I download my statement?\""),
    ("3. What kind of story?", "Unclear", "Cannot tell from the post.", "\"My SIP is not showing.\" (could be either)"),
    ("4. Main reason they give", "(any reason on the list)", "Pick the ONE reason the writer themselves give as the biggest. Only the writer's own reasons, not advice to others. If more than one, pick the strongest. The AI does not rank its reasons, so a match means your reason is anywhere in the AI's list.", ""),
    ("4. Main reason they give", "Autopay/payment problem", "Autopay, e-mandate, UPI mandate, bank debit, failed instalment.", "\"SIP not deducted this month.\""),
    ("4. Main reason they give", "Confusing numbers (NAV/XIRR)", "Doesn't understand NAV, units, XIRR, absolute vs yearly returns or statements.", "\"Why does XIRR say 12% when I made 3%?\""),
    ("4. Main reason they give", "Returns too small", "Returns are small, flat or slower than hoped.", "\"Two years and only 4% gain.\""),
    ("4. Main reason they give", "Expected faster growth", "Expected quick or guaranteed growth; investing \"not working\".", "\"I thought SIP doubles money in a year.\""),
    ("4. Main reason they give", "Money is tight", "Expenses, EMI, rent, a tight month, irregular income.", "\"Can't afford 5k this month.\""),
    ("4. Main reason they give", "Needs money/goal changed", "Goal done or changed, or needs to withdraw now.", "\"Need the money for a house deposit.\""),
    ("4. Main reason they give", "Influenced by others", "A friend, family, finfluencer, YouTube or Reddit told them to start, stop or switch.", "\"A YouTuber said stop SIPs in small cap.\""),
    ("4. Main reason they give", "Distrusts platform", "Doubts about the platform, fund house or safety of money.", "\"Not sure my money is safe here.\""),
    ("4. Main reason they give", "Hard to use app", "Hard to find, change or pause a SIP; bugs; app errors.", "\"Can't find where to pause my SIP.\""),
    ("4. Main reason they give", "Market fell", "Portfolio red or loss because the market fell.", "\"Market crashed, everything is red.\""),
    ("4. Main reason they give", "Life event", "Job loss, job change, marriage, medical, relocation, studies.", "\"Lost my job in March.\""),
    ("4. Main reason they give", "Switching fund", "Stopping to move to a \"better\" fund.", "\"Stopped this one to start a flexi cap SIP.\""),
    ("4. Main reason they give", "Something else", "A reason that fits none of the above (including forgot, lost interest, tax or lock-in).", "\"Forgot it existed.\""),
    ("4. Main reason they give", "None given", "The writer gives no reason.", "\"Which SIP is best for beginners?\""),
    ("Golden rule", "", "Answer what the post says or clearly means. If it doesn't say, choose Unclear or None given. Don't guess.", ""),
]
ABOUT = [
    f"Picked by plain code (no AI calls), fixed random seed {SEED}. 8 posts were kept from the first sheet and 12 replaced; then 5 more (extra praise, a link-only post, 2 general questions) were swapped for first-person SIP stories, seed 3032.",
    "Left out: the 100 hand-checked posts, the relevance pilot (100), the tagging pilot (50), the 30-post two-model check, every post in corrections.csv and the 12 dropped posts. 2021 onward, relevant posts only.",
    "Mix: 12 own stories (4 payment failures, 4 chose to stop/pause/reduce, 4 returns confusion or disappointment), 4 hard cases (2 replies/advice, 2 Hinglish or regional), 4 others (2 plain questions, 1 praise or feature request, 1 withdrawal complaint); at least 2 from each of the 5 sources. The AI's tags were used only to find this mix. 'In plain English' is a literal translation for non-English posts, written without looking at the AI's answers.",
]


def fixed_rows() -> list[dict] | None:
    """If data/golden/v2_final_ids.json exists (the 20 ids in sheet order), use exactly those posts."""
    f = OUT / "v2_final_ids.json"
    if not f.exists():
        return None
    by_id = {p["id"]: p for p in load_candidates(paths_excluded(), min_words=1)}
    return [by_id[i] for i in json.load(open(f))]


def main() -> None:
    rows = fixed_rows() or select()
    if "--list-nonenglish" in sys.argv:
        for p in rows:
            if p["language"] != "en":
                print(f"{p['id']} [{p['language']}] {p['full_text']}\n")
        return
    build(rows)
    print("built; sources:", {s: sum(r['source'] == s for r in rows) for s in SOURCE_NAMES})


if __name__ == "__main__":
    main()
