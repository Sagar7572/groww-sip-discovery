# Evidence Log notes

Working notes for the AI Evidence Log. Entries are added as they happen, not reconstructed later.

---

## Entry 1: Play Store keyword filter decision (2026-10-23)

**Context.** Play Store reviews are filtered by a free keyword step in code (`config.yaml` > `keywords`)
before any AI is used. The first run (6,000 newest English reviews + Hindi reviews) kept 163 of 8,786.

**What I checked.** 10 random kept reviews. 3 of 10 were off-topic and matched only on two Hindi keywords:
- "पैसा" (money): matched reviews about money in general, e.g. a Hindi complaint about money being deducted during Aadhaar verification.
- "निवेश" (investment): matched generic praise like "good app for investing in the share market".

**Decision.**
1. Removed the two Hindi keywords "पैसा" and "निवेश" because they are too broad and let in non-SIP reviews.
2. Kept "mutual fund" even though it lets in passing mentions ("easy to use for mutual funds, stocks..."). Reason: the keyword step should favour not missing things; the AI relevance filter (`pipeline/filter.py`) will remove passing mentions later.
3. Raised `play_store.max_reviews` from 6,000 to 30,000 per language so more history is covered (the filter keeps only ~2% of reviews, so more volume is needed for enough signal).

**Numbers (Play Store, pulled vs kept).**

| Run | Settings | Pulled | Kept |
|---|---|---|---|
| Before | 6,000 max, with 2 Hindi keywords | 8,786 | 163 |
| After | 30,000 max, Hindi keywords removed | 32,786 | 621 |

Kept reviews in the "after" run span 2018-12-16 to 2026-10-22.
The Hindi pull returned only 2,786 reviews in both runs, so it was not limited by max_reviews.
The English pull hit the 30,000 cap, so older English reviews are still not covered.

**Caveat.** The before/after kept counts are not a like-for-like test of the keyword change, because the volume pulled also changed. The effect of removing the Hindi keywords on its own was not measured.

**Known bias.** App-store reviews skew negative and short, and many 5-star reviews are generic praise.

---

## Entry 2: Volumes per source so far (2026-10-23)

| Source | Pulled | Kept | How "kept" is decided | Date range of kept items |
|---|---|---|---|---|
| Play Store | 32,786 | 621 | Keyword filter on review text | 2018-12-16 to 2026-10-22 |
| App Store | 500 | 31 | Keyword filter on title + text | Sep 2026 (sample seen; full range not yet checked) |
| TradingQ&A | 1,425 | 1,425 (1,418 saved after removing duplicates) | Not keyword-filtered: threads come from SIP-related searches, so every post in a matching thread is kept | 2014-12-11 to 2026-10-19 |
| YouTube | not run | | | |
| Reddit | not run | | | |

**Spot checks (5 random kept items each).**
- App Store: 2 relevant (a weekly-SIP feature request; a new-SIP autopay activation failure), 3 generic praise ("Excellent", "Excellent and awesome options", "best app for stocks and mutual funds"). Two of the generic ones were kept only because their *titles* mention mutual funds.
- TradingQ&A: 2 relevant (SIP auto-debit question; a person asking what happens if they pause a SIP after losing a job), 1 generic (transferring ELSS funds), 2 off-topic (a general comment on platforms; FD vs equities). TradingQ&A items come from threads on other platforms (mostly Zerodha) and are mostly replies (1,259 of 1,418), so the AI relevance filter will matter most here.

**Notes and biases.**
- App Store is capped by Apple's feed at about 500 recent reviews (10 pages), so it only covers recent months.
- The "kept" numbers are not comparable across sources: Play Store and App Store use a keyword filter, TradingQ&A does not.
- TradingQ&A is a Zerodha community, so posters are not necessarily Groww users.
- Keywords and code were not changed in this step.

---

## Entry 3: YouTube volumes (2026-10-24)

| Item | Number |
|---|---|
| Search queries | 6 (5 videos each) |
| Videos found | 27 (30 results; a few appeared in more than one search) |
| Comments pulled | 5,837 (5,831 saved after removing duplicates/empty texts) |
| Top-level comments / replies | 4,235 / 1,596 |
| Date range | 2019-01-30 to 2026-10-24 |
| Kept | 5,831. No keyword filter: comments are kept because they sit under SIP-related videos |
| Daily quota used | roughly 600 (6 searches x 100) plus up to ~270 for comment pages, so about 900 of 10,000 free units (estimate; not read from Google's console) |

**Spot check (5 random comments).** 2 relevant (money safety question; "safe and you can withdraw anytime" under a Groww SIP tutorial), 3 generic ("Right", a request for an SWP video, a one-line SIP safety question). Many comments are very short, in Hindi, Hinglish or other Indian languages (one was Malayalam).

**Notes and biases.**
- Comments reply to a video, not to Groww, so many are about the video's creator or advice, not about the app.
- Like TradingQ&A, nothing is keyword-filtered here, so the AI relevance filter will do the cutting.
- Only 27 videos: results depend heavily on which videos YouTube search returned.

---

## Entry 4: Cleaning funnel (2026-10-24)

Script: `pipeline/clean.py` (plain code, no AI). Output: `data/processed/clean.jsonl`; everything removed is kept with a reason in `data/processed/dropped.jsonl`.

**Funnel per source** (Reddit not yet collected).

| Source | Raw | After dedupe | Final | 2021+ | Older |
|---|---|---|---|---|---|
| App Store | 31 | 31 | 28 | 28 | 0 |
| Play Store | 621 | 613 | 613 | 603 | 10 |
| TradingQ&A | 1,418 | 1,403 | 1,324 | 804 | 520 |
| YouTube | 5,831 | 4,688 | 3,806 | 3,651 | 155 |
| **Total** | **7,901** | **6,735** | **5,771** | **5,086** | **685** |

**Language of the final 5,771 (rule-based guess):** English 3,887; Hinglish 1,665; Hindi 147; other 72 (Malayalam, Tamil etc. or emoji-only).
Most Hinglish is YouTube (1,622 of 3,806).

**Rules and why.**
- *Duplicates:* exact match ignoring case and punctuation, then near-duplicates at 90% similarity (rapidfuzz) for texts of 20+ characters. The first copy stays. Removed 1,166 items, 1,143 of them YouTube, mostly repeated spam such as "sip" (170 times), "sip part 2" (162) and "mind blowing" (126+). These add counts without adding information, which would distort frequency numbers later.
- *Short texts:* items under 6 words are dropped unless they contain a SIP keyword from `config.yaml`. Why: one-line replies like "Thanks", "Right", "Very good advice" carry nothing the AI can tag, and each one would cost an AI request. The keyword exception protects short but useful lines like "sip skipped again". Dropped 964 items.
- *Context:* TradingQ&A replies carry the thread's original question (first 300 characters) and YouTube comments carry the video title, so the AI can read a short reply in context. 1,163 of 1,165 TradingQ&A replies found their question.
- *Year:* taken from the date. Everything is kept; 2021 onward (5,086 items) is the main analysis window, 685 older items are reported separately.

**Spot check of 5 dropped short items.** "Looking forward to it." / "And need more knowledge" / "Very Good Advice Thank you" (nothing lost); "1000 se suru karna hai" (start with 1000, a weak signal but too thin to tag); a YouTube link with "ye video dekho sir" (no content). No clearly useful item lost in this sample of 5. This is a small sample.

**Limitations.**
- The language guess is a simple rule and misses some Hinglish written without common marker words (e.g. "sip me agar auto payment lagane ka charge padta h" was labelled English). The AI tagging step can correct language later.
- Deduping counts a repeated comment once, so a very common one-line complaint is counted once. The dropped file keeps the removed copies if exact repeat counts are needed.

---

## Entry 5: AI output corrected - relevance filter pilot (2026-10-24)

**Setup.** `pipeline/filter.py`, 100 mixed-source items (5 App Store, 25 Play Store, 35 TradingQ&A, 35 YouTube), 15 items per request, Groq free tier.

**Model change.** The planned model `llama-3.1-8b-instant` was no longer available on the Groq account ("model not found"; the account's model list no longer included it). Switched to `openai/gpt-oss-20b`, the smallest chat model listed, with reasoning effort set to low. This changes the quality and token cost of every later result, so it is recorded here.

**Prompt v1 results.** 54 yes / 46 no / **0 unsure**. The model never used "unsure", so borderline items were pushed into yes or no, the opposite of the rule "better to keep a borderline item than lose it".

**What I reviewed and what I found wrong in v1** (my judgement after reading the items):

| Item | v1 said | Verdict on review |
|---|---|---|
| TradingQ&A reply: "Demat account AMC is Rs.300/year..." | yes, "asks about mutual fund charges" | **Wrong.** It is about demat account charges, no mutual fund; the reason is not in the text. Should be no. |
| Play Store: bank account blocked after a Groww transaction | yes, "SIP blocked due to account issue" | **First judged wrong, then corrected.** Re-reading the full text, it says "my EMI and SIP payments cannot be processed", so yes is defensible and the reason is grounded. I had judged it from a shortened view. Kept as a note, not an AI error. |
| TradingQ&A: SIP of 10K/month for 12-15 years, would tax-loss harvesting help | yes, "tax harvesting for SIP" | **Debatable, not clearly wrong.** The person is a long-term SIP investor and the reason matches the text; the topic is tax, not continuation. |
| YouTube: "Is it a good time to invest lumpsome?" | no | **Wrong.** A mutual fund timing question from a possibly new investor; should be yes or unsure. |
| YouTube: "I invested at a bank in a PSU scheme, how do I see my investment in the app?" | no | **Wrong.** An investor asking where to see their investment; should be yes or unsure. |

So of the 3 "wrong yes" items I first listed, 1 was clearly wrong, 1 was debatable and 1 was my own misreading. Both wrongly-"no" items were real errors.

**What we changed (prompt v2, v1 kept in the file for comparison).**
- Worked examples for yes, no and unsure.
- Demat / stock / bank-account / F&O / IPO items with no mutual fund or SIP angle = no.
- A confused or first-time investor asking about mutual funds, lumpsum vs SIP, timing, or where to see their investment = yes or unsure, never no.
- Reasons may only describe what the text says; an unsure answer must start with "unsure:".
- Texts cut to their first 150 words and context to 25 words (v1 used 700 and 200 characters). For the real run, 2021+ items are processed first.

**v2 result on the same 100 items.** 53 yes / 45 no / **2 unsure**. 11 items changed label.
- Fixed: demat AMC item (now no), lumpsum question (now unsure), a "Nippon fund choice" question (now unsure), and the YouTube comment that v1 had wrongly called "SIP stopping discussion" (now no).
- **Not fixed:** the PSU/where-to-see-my-investment item is still "no" (v2 reason: "viewing investment, no SIP"), which breaks the new rule.
- **New problems in v2:**
  - Two Hindi Play Store reviews flipped from no to yes with reasons that add things the text does not say ("started SIP", "mutual fund investing, app learning" for a review about the share market).
  - A question about whether money put in one time will give more return after 5 years flipped from yes to no ("lump sum question, no SIP"), against the new "never no" rule.
- "Unsure" went from 0 to 2 of 100, still low.

**Token cost.** v1: 14,765 tokens for the 100 items. v2: 17,376 (+18%), not lower. The longer v2 system prompt (about 2,570 characters, sent with every request) added more than the shorter item text saved, because most items are already short.

**Lesson.** A small model needs examples and an explicit "unsure" path, but extra rules can add new errors (invented reasons on Hindi text), so every prompt change has to be checked on the same labelled items. These 100 items are my own quick judgement, not the formal golden set.

### Entry 5 (continued): prompt v3 and the safety net (2026-10-24)

**Decision.** The filter's job is recall: a wrong "no" loses data for good, while a wrong "yes" is caught later by the detailed tagging step. This was agreed as the last tuning round.

**What changed in v3.**
- Prompt trimmed to 5 short examples (4 plus one "where do I see my investment" example).
- New rules: "when in doubt between no and unsure, choose unsure"; a reason may not mention SIP unless the text does.
- 25 items per request instead of 15 (the long prompt is sent fewer times).
- **Safety net (plain code, no AI):** if the model says "no" but the text contains one of sip, mutual fund, mf, lumpsum/lumpsome, mandate, autopay, nav, redeem/redemption, first investment, beginner AND is a question or a first-person experience, the label becomes "unsure" and the record is marked `rescued_by_rule = true` (the model's own answer is kept in `model_relevant`).

**Results on the same 100 items.**

| | yes | no | unsure | tokens per item |
|---|---|---|---|---|
| v1 | 54 | 46 | 0 | 148 |
| v2 | 53 | 45 | 2 | 174 |
| v3 | 61 | 31 | 8 | 135 |

- The safety net rescued 6 items (all Play Store reviews that mention mutual funds or SIP in a first-person or praise-with-info way). All 6 were generic-praise type, so it worked as designed but caught no strong case.
- v3 fixed items v2 got wrong: the PSU "where do I see my investment" question (now yes), the lumpsum question stays unsure, the one-time-investment return question (now yes), the KYC-for-mutual-fund-account complaint (now yes), the Flipkart/Paytm mutual fund platform thread (now yes).
- v3 also over-keeps: "Sip sir ji" and "ha sir long term le sakte hai" are now "yes". That is acceptable for a recall-first filter; the tagging step will drop them.

**Remaining "no" items that are clearly wrong (3 of 100, checked against full text).**
1. YouTube: "Mana investment to Kar diya. Par kitna saal ka Kiya kaha Pata chala ga" (I made the investment, but where will I find how many years I chose?). A confused investor asking where to see their investment. Reason given: "investment vague, no MF".
2. Play Store: "...u have not updated exit load for all MF and certain are updated incorrectly, portfolio graph has incorrect mapping, reported 3 months still not resolved...". About mutual fund data in the app. Reason given, "app issues, no mutual fund", contradicts the text. The safety net missed it because it has no first-person word or question mark.
3. YouTube: "Nippon me invest karna best rahega ki nahi" (is investing in Nippon a good idea?). The v3 rule says "which fund" questions must not be "no". It got "no, investment query, no SIP". The text has no mutual fund / SIP keyword, so the safety net could not see it.

Borderline "no" items that are arguable but not counted as clearly wrong: a fund giving "solid 20%+ yoy" (reason "stocks only" is shaky), a question on using the app on a new phone, a retirement-calculator reply, a feature request to track EPFO/PPF/mutual funds in one place, and a discussion of midcap growth rates.

**Acceptance rule and outcome.** The rule was: no more than 2 clearly wrong "no" items out of 100, otherwise do not start the full run. v3 has 3, so the full run was **not** started automatically; the owner decides next. All of this judging was done by the same person (the assistant) who built the prompt, so it is a development check, not the formal golden-set agreement.

### Entry 5 (continued): safety net 2 and the start of the full run (2026-10-24)

**Safety net 2 (plain code, no AI).** After v3, three clearly wrong "no" items remained. The owner approved a second rule: a model "no" becomes "unsure" if the text has (a) a fund-house name (names that are also banks or companies, such as HDFC, SBI, ICICI, Axis, Kotak or Tata, only count when a fund word like fund / invest / AMC / scheme / ETF is also in the text), (b) "invest..." inside a question (English or Hinglish), or (c) "MF" or "mutual fund" together with a complaint word (problem, not updated, incorrect, failed...). Records are marked `rescued_by_rule = true` and `rescue_rule` says which rule fired; the model's own label stays in `model_relevant`.

**Applied to the existing 100 pilot results (no new AI calls).** It rescued all 3 wrong items (the "where is my investment" question, the mutual fund exit-load complaint, the Nippon fund-choice question) and **no other item** (3 rescued in total). Pilot after both rules: 61 yes / 28 no / 11 unsure; 9 items rescued by rules (6 by rule 1, 3 by rule 2). A copy of the results before this change is in `data/processed/relevance.backup_before_rule2.jsonl`.

**Caveat: pilot accuracy is optimistic.** Prompt v3, safety net 1 and safety net 2 were all tuned on the same 100 pilot items, and rule 2 was written to fit the three errors found in them. So the "0 wrong 'no' left in the pilot" result says nothing about how well the filter works on new items. The independent hand-labelled golden set will measure the real accuracy (including the share of wrong "no" items). The fact that rule 2 caught no extra items on the other 97 is only a weak sign that it does not over-fire.

**Full run started** with prompt v3 + both safety nets, model `openai/gpt-oss-20b`, 25 items per request. Order: 2021+ items first (newest year first); within each group TradingQ&A and the app stores before YouTube; older and undated items last. It stops cleanly when Groq's daily allowance (200K tokens) runs out and is rerun on later days. No more relevance-prompt tuning after this point.

---

## Entry 6: Tagging pilot, AI output rejected and corrected (2026-10-24)

Script: `pipeline/tag.py`, model `openai/gpt-oss-120b` (separate Groq allowance from the filter), 10 items per request, whole codebook in one fixed system prompt, compact JSON with numbered answer codes mapped back to codebook names. Pilot: 50 items already kept (yes/unsure) by the relevance filter, spread across sources (18 Play Store, 14 TradingQ&A, 10 YouTube, 8 App Store).

**Run 1 (tagging prompt t1) and what was wrong.**
- The model judged **36 of the 50** items "not relevant" (it was allowed to answer only `rel: 0` and skip the other fields). Reading them, most were clearly relevant: "unable to setup autopay for SIP", a SIP showing a loss after 23 months, "redemption payment is long process", a mismatch in mutual fund holdings between Groww and CAMS, "harassment at the time of payment of Mutual fund Lumpsum". **I rejected this output.**
- Causes: (1) the codebook's `is_relevant` question is narrow (starting / continuing / pausing / stopping a SIP) and the model applied it literally; (2) the early exit made "skip" the cheap answer. A relevant item wrongly dropped at this stage would be lost for good, the same risk as a wrong "no" in the filter.
- 2 of 50 items failed validation: the model used code 5 for `money_source`, which has only 4 options (it copied "5 = unclear" from the neighbouring field `age_band`).
- 17% of evidence quotes were not exact substrings of the text.

**What we changed (prompt t2; t1 results kept in `tags.jsonl` for comparison).**
- No early exit: every field is always filled; `is_relevant` is only a flag. `rel = 0` is allowed only if the item clearly has nothing to do with mutual funds / SIP. The prompt states a broader meaning of relevance than the codebook's short wording (the codebook file itself was not changed).
- In the four segment fields, "unclear" is now always code 0, so codes no longer clash.
- `journey_stage` and `sip_action` must be unclear / none unless the text says it; the quote must be one continuous piece with no "..." joins.

**Run 2 (t2) on the same 50 items.**
- 47 relevant, 3 judged not relevant (generic app praise), 0 failed. The 3 look reasonable.
- Tokens: 536 per item (347 prompt, 189 output), i.e. 26,798 tokens for 50 items. Run 1 used 31,592 (632 per item, including retries).
- Quote check (free, in code): 5 of 47 quotes (11%) are not an exact substring. Causes seen: "..." joins, a dropped "[USER]" placeholder, and one quote copied from the context (the forum question) instead of the reply.
- Reason check (free, in code): 0 of 47 underlying reasons mention SIP / mandate / returns without the text doing so.
- Prompt caching: Groq does report `cached_tokens` in the usage block (`prompt_tokens_details`), but only on some requests: 2,560 of 17,328 prompt tokens (15%) in run 2 and 4,608 of 24,284 (19%) in run 1. It is not reliable enough to plan around.

**Quality observations (not yet tuned, to be measured on the golden set).**
- Most filter-kept items carry little lapse information: of the 47, `sip_action` is "none" for 35, `journey_stage` is unclear for 41, `lapse_type` is not_applicable for 41, and 35 have no stated trigger. The clearest signal is mandate / payment problems (7 items with that trigger, 5 `instalment_failed` / involuntary).
- `confidence` is nearly useless: minimum 0.8, mean 0.86. It cannot be used to pick items for a second opinion.
- In run 1 the model over-inferred (for example "please refund my deducted amount of SIP" was tagged journey_stage after_stop / sip_action stopped, which the text does not say). Run 2 mostly fixed this by saying "unclear" much more often; the cost may now be too many "unclear" answers, which only the golden set can tell.

**Estimated cost of the full job** (about 536 tokens per item, 200K tokens per day = about 370 items a day; the number of relevant items is projected from the filter's results so far and may still change): all relevant items (about 4,200) would take about 11 days; the sample (all TradingQ&A and app stores plus about 800 YouTube comments, about 2,000 items) about 5.5 days.

### Entry 6 (continued): prompt t3, bugs found on the way, and why the tagging run was not started (2026-10-24)

**Decisions taken before t3.** Scope for tagging = the sample: all TradingQ&A and app store (App Store + Play Store) items the filter keeps, plus about 800 random 2021+ YouTube items. Priority order: items mentioning stop / pause / cancel / band / skip / failed / bounce / mandate / autopay / loss / negative / red (plus their inflections) go first.

**`confidence` is uninformative.** Across the pilot it is never below 0.8 (mean 0.86). It will not be used to pick items for a second opinion or to rank anything.

**Changes in t3.**
- Tag what the text states or plainly implies; "unclear" only when the text gives nothing. Quote = one continuous exact span, no "...", copied from the item text, not from the context line.
- 20 items per request (was 10).
- `codebook.yaml` is now version 0.2 so the codebook is the single source of truth: the `is_relevant` wording is broader (any mutual fund / SIP matter; false only for clearly unrelated items) and there are 3 new worked examples (a loss after 23 months -> underwhelming returns; "how do I see an investment bought elsewhere in this app" -> confused; repeated bounced instalments -> involuntary lapse). The old file is saved as `data/processed/codebook.v0.1.backup.yaml`.
- **Caveat:** two of the new examples are paraphrases of two pilot items (the 23-month loss item and the "where do I see my investment" item). So the fact that those two items now come out better is NOT an independent test.
- Free code fix: if a quote is not an exact substring, the closest matching span of the text (rapidfuzz) replaces it; `quote_original`, `quote_repaired`, `quote_repair_score` and `quote_from_context` are saved.

**Bugs and failures found while running t3 (all mine, all logged).**
1. *Every answer numbered 1.* All worked examples showed `"i": 1`, and with 20 items the model copied that into every entry. My code matched answers to items by that number, so most items showed "no answer" and, worse, an answer could be attached to the wrong item. **All 50 t3 records from that run were discarded** (backup: `data/processed/tags.backup_before_t3_fix.jsonl`). Fix: examples are explained as single items; the prompt says to number items 1, 2, 3...; the code uses the model's numbers only if they are distinct and in range, falls back to the order of answers only if there is exactly one per item, and retries any missing items.
2. *Request too large.* Groq's 8,000 tokens-per-minute limit also applies to a single request, and a 20-item batch of long texts was rejected (HTTP 413, "requested 8037"). Fix: the code splits an oversized batch in half and retries.
3. *Missing items.* In one test the model answered only 15 of 20 items. The retry for missing items now handles this. Output of the model is not fully repeatable even at temperature 0.

**t2 vs t3 on the same 50 items (t3 after the fixes; 49 relevant, 1 not relevant, 0 failed).**

| Share answered "unclear / none" | t2 | t3 |
|---|---|---|
| investor_type | 91% | 80% |
| journey_stage | 87% | 65% |
| sip_action | 74% | 73% |
| lapse_type | 89% | 84% |
| stated_triggers | 74% | 45% |
| underlying_reason | 83% | 53% |
| unmet_need | 85% | 80% |
| segment fields | 98-100% | 100% |

- Quote mismatch (the model's own quotes, before repair): t2 5 of 47 (11%); t3 7 of 49 (14%). **The target was under 3%, so it was missed.** Causes seen in the 7: the model dropped the "[USER]" placeholder (1), joined pieces with "..." despite the instruction (3), and wrote text that is not in the item at all (e.g. "MF sip auto pay not working", while the item says "app quality has deteriorated vastly, app crashing..." ) (2-3). The repaired quote is real text from the item, but it does not prove the tag: where the model invented words, the tag (e.g. a mandate / payment trigger) may rest on something the text does not say. Repair scores for those were 65-80 out of 100.
- Reason check: 0 of 49 reasons mention SIP / mandate / returns without the text doing so.
- The two under-tagged items: the 23-month loss item now has triggers underwhelming_returns + expectation_mismatch, emotion disappointed, severity 2 (fixed, but see the caveat above). The "where do I see my investment" item now has emotion confused, but triggers are still "none" and the reason "unclear" (half fixed).
- Tokens per item: t2 536; t3 644 in the last clean run (12,888 tokens for 20 items); 800 when the wasted calls of the 20-vs-15 and retry cases are included (40,031 tokens for 50 items).
- Cached tokens reported by Groq in that last run: 3,328 of 8,376 prompt tokens (40%), so caching does sometimes help, but it is not predictable.
- Lapse types now show more variety: not_applicable 32, unclear 9, involuntary 5, voluntary 2, both 1. Top triggers: none 22, app_experience 12, mandate_payment_issue 8, other 8.

**Outcome.** The agreed condition for starting the sample run automatically was quotes under 3% mismatched and both items fixed. Quotes missed it (14%) and one item is only half fixed, so the run was **not** started; the owner decides.

**Estimate for the sample** (about 2,030 items: roughly 450 Play Store, 770 TradingQ&A, 15 App Store, 800 YouTube; the first three still depend on the filter finishing): at 644-800 tokens per item and 200K tokens a day, about 250-310 items a day, so about 6.5-8 days.

---

## Entry 7: Two taggers, inter-model check, and the tagging run (2026-10-24)

**Setup decided by the owner.**
- Quote handling (code only, no extra AI calls): a quote that is not an exact substring is replaced by the longest exact piece (if the model joined pieces with "...") or else by the closest matching span (rapidfuzz). If the repair score is below 80, the quote is marked `quote_unreliable` and `needs_review`; the item is kept, but `quote_display` is empty and **nothing user-facing may show an unreliable quote** (user-facing code must read `quote_display`, never `evidence_quote` or `quote_original`). On the 50 pilot items: 7 quotes repaired (4 by longest exact piece, 3 by closest span), 2 flagged unreliable.
- Priority items (words stop, pause, cancel, band, skip, failed, bounce, mandate, autopay, loss, negative, red, redeem and their inflections) are tagged first, straight from the cleaned data without waiting for the relevance filter, because the tag prompt flags relevance itself. 591 priority items were in scope at start; 28 of them had already been judged "no" by the filter and are tagged anyway, which costs about 2% of the run.
- Two taggers run in parallel, each on its own Groq allowance and its own output file: `openai/gpt-oss-120b` (reasoning effort low, `data/processed/tags.jsonl`) and `qwen/qwen3.8-27b` (reasoning off, `data/processed/tags_qwen.jsonl`). Items are split between them by a fixed random split on the item id, so neither model gets a special kind of item. Every record says `tagged_by`.
- The relevance filter was restarted in the background at the same time.

**Inter-model check (same 30 items tagged by both models; 29 usable, 1 Qwen item failed validation).**
- `is_relevant`: 29 of 29 agree.
- Exact agreement on the 29 items both call relevant: all fields 83%; the six core fields (stage, sip_action, lapse_type, triggers, emotion, severity) 70%.

| Field | Exact agreement |
|---|---|
| sip_action | 86% |
| investor_type | 83% |
| outside_app_actions | 83% |
| severity | 79% |
| emotion | 72% |
| journey_stage | 66% |
| lapse_type | 66% (90% if "unclear" and "not_applicable" are treated as the same) |
| stated_triggers | 52% exact, 57% overlap |
| segment fields | 97-100% (almost always unclear) |

- Where they differ that matters: gpt-oss-120b flagged 5 of the 29 items as involuntary lapse / failed instalment, Qwen only 3 (it said sip_action "none" for an autopay set-up failure and for multiple mandates being debited separately). So Qwen likely under-detects involuntary-lapse signals, which is one of the key branches of the metric tree; counts of involuntary lapse must be read with this in mind (and by tagger).
- Other differences are mostly judgement calls: emotion (hopeful vs calm_confident), severity (2 vs 3), trigger "other" vs a named trigger.
- Quotes: Qwen's own quotes were better (2 of 29 not exact against 5 of 29 for gpt-oss-120b).
- Limits of this check: only 29 items; the items come from the pilot that the prompt was tuned on; and agreement between two models does not mean either is right. The hand-labelled golden set will measure accuracy against a human.

**Segment fields are almost always unclear in public posts.** In the pilot, income_stability, age_band and money_source were "unclear" for 100% of items and influenced_by for about 97-100%. Public reviews and comments rarely state income, age or where the money comes from. So the engine will not report segment findings from these four fields. It uses **proxies** that posts do reveal: the irregular-income trigger, the first-time-investor flag (`investor_type`), the source (app store / forum / YouTube), and the journey stage. Real segment differences (income stability, age, source of money, who influenced the person) will be **validated through interviews** later, outside this engine.

---

## Entry 8: Dashboard choices that change how the numbers should be read (2026-10-24)

The hosted dashboard (`app/streamlit_app.py`) reads only the files built by `pipeline/export.py`. Decisions worth knowing before quoting any figure from it:

- **Opportunity score** = number of posts x average severity (1-3) x branch weight x "fixable within our rules" weight. The weights are judgements written down in `pipeline/export.py` (branch: A 0.9, B 1.0, C 0.7, D 0.6, E 0.8; fixable: yes 1.0, partly 0.5, no 0.0), shown on the page, and the page also shows each area's rank if the weights are ignored. Areas the product cannot fix within the rules (for example fund switching) score zero by design.
- **Lapse stories** = posts where a SIP stopped, is at risk, or a payment failed. "Failure, not the person's choice" and "the person's own choice" are shown as exclusive groups in the headline, because a post can be tagged both ways; the branch cards on the metric-tree page include the overlap and say so.
- **Voluntary vs involuntary by tagger:** wherever involuntary lapse is counted, the dashboard shows the combined figure and each tagger's figure, because in the 30-post check Qwen found fewer payment failures than gpt-oss-120b (4 vs 6 of 30 on the final count). Each tagger sees a different random half of the posts, so differences between them mix model differences with chance.
- **Quotes:** the dashboard shows `quote_display` only, which is empty for quotes that could not be verified (repair score under 80). A quote is not repeated twice on the same page.
- **"Ask the data":** posts are embedded with a free local multilingual model. The "the data doesn't cover this" cut-off (best match below 0.36) was set by trying 12 test questions: off-topic ones scored 0.14-0.34, on-topic ones 0.34-0.65, so the cut-off errs towards saying the data does not cover a question. Answers must tie every sentence to a numbered post; code removes any sentence without a valid citation (the first live test of this page produced a closing sentence with no citation, which is now removed). Limits: 10 questions per session and 150 a day across visitors (the daily counter resets when the hosted app restarts). A question asking what to buy or do ("Should I buy Nifty ETF now?") returned "The data doesn't cover this" in the test and nothing is presented as advice.
- **Screenshots checked:** each page was opened in a real browser and read. Two layout problems found and fixed that way: charts were squashed (the chart height includes the axis and legend), and one chart was sorted alphabetically instead of by score.
- **Secrets:** while preparing the public repository a real key was found inside `.env.example` (a copy of `.env`). It was blanked before anything was committed; the `.env` file itself is ignored by git.

---

## Entry 9: Finding. Whether a SIP lapse is a failure or a choice depends on the source (2026-10-24)

An earlier version of the metric-tree page said, in its headline, that failures the person did not choose were about two thirds of lapse stories. Splitting the same posts by source shows that this was an artefact of which sources contribute lapse stories, not a general fact. Snapshot of 347 relevant tagged posts (420 tagged), 65 of them lapse stories (a SIP stopped, is at risk, or a payment failed):

| Source | Lapse stories | Failure, not the person's choice | The person's own choice |
|---|---|---|---|
| Play Store reviews | 30 | 73% | 23% |
| TradingQ&A forum | 16 | 50% | 38% |
| YouTube comments | 17 | 18% | 71% |
| App Store reviews | 2 | low confidence (under 15) | low confidence |
| All combined | 65 | 52% | 38% |

- The headline is now "Whether a lapse is a failure or a choice depends on the source: 73% of lapse stories in Play Store reviews are failures, 71% of those in YouTube comments are the person's own choice", the chart shows the split source by source with the number of lapse stories in each label, and a warning says the combined row must not be read as a general fact.
- A likely reason (not tested): people with a failed payment go to the app store to complain, while YouTube comments react to videos about whether to stop. Which one is closer to the truth for all first-time investors is unknown; interviews or app data would be needed.
- Consequence for the opportunity ranking: the "autopay / payment problem" area is driven mostly by Play Store and App Store reviews and should be read with that source mix in mind.

---

## Entry 10: AI correction. The tagger used "market fell" for posts that are not about the market (2026-10-24)

**What the AI said.** In the dashboard the examples shown under "market fell" were about redemption delays, wrong amounts, a duplicate order and trust, not about markets. Of the 347 relevant tagged posts, 23 carried the reason `market_fall`.

**Check.** I read all 23 (the planned sample of 20 was not possible to take at random, so every one was read; the 23 are all that exist). Findings: 7 clearly wrong (redemption not credited for days or weeks, redemption blocked on a loan, a duplicate order, a missing "international funds" section, a MF Prime switch complaint, a "different amount arrived" complaint), 2 arguable (the app showed a value that dropped after redeeming, or dropped without a visible reason: a price move the person did not understand), and 14 right (Covid crash, small caps in loss, "exited in panic", and so on) apart from one wrong tag that is left: a post about a displayed 11% gain turning into an 11% loss at redemption, which contains the word "loss". So about 10 of 23 (43%) were wrong or doubtful.

**Why it happened.** The codebook describes `market_fall` as "Portfolio red, market crash, loss". The model read "loss" and "redeem" in a complaint about money not arriving as a loss event. The tagging prompt was not told that money-out problems are a different thing.

**Correction.** Applied in code at export time (`correct_triggers` in `pipeline/export.py`), not by re-tagging, because re-tagging would spend several days of the free daily allowance and mix two prompt versions:
1. `market_fall` is kept only if the post's own words contain market or loss language (market, crash, Covid, Nifty, correction, dip, volatility, fell/falling, loss, negative, red).
2. It is also dropped from any post the second AI pass places under "getting money out" (redemption, withdrawal, refund).
Result: 9 of the 23 tags were removed (the 7 clearly wrong, plus the 2 arguable ones); 14 remain, 1 of which is still wrong and cannot be caught by a word rule. The removed posts now rank in the new "after stopping" table. Every post keeps a `triggers_removed` field, so the correction can be audited.
**Still to do:** add "not for redemption delays, wrong amounts or support complaints" to the `market_fall` line of the codebook (v0.3) the next time the tagging prompt is changed; it was not changed now because both taggers are mid-run.

---

## Entry 11: AI pass added to split "Hard to use the app", and a second ranking table (2026-10-24)

**Why.** "Hard to use the app" was ranked as one area (68 of 347 posts) but mixed autopay set-up, pause and cancel controls, display of returns, app bugs and complaints about getting money out. It could not be acted on as one thing, and redemption problems are not a cause of stopping at all.

**What was done.** A small extra AI pass (openai/gpt-oss-120b, same free tier, 5 requests) read 122 candidate posts (every post with the reason "hard to use the app" plus every post whose text mentions redemption, withdrawal or refund) and put each into one of: autopay/mandate set-up and changes, cannot pause/skip/edit/cancel, portfolio/returns shown wrongly, app updates/bugs/slowness, support, missing feature, three kinds of money-out problem, or "not a problem" (praise, plain question, staff reply). Keyword rules were tried first and rejected: they missed real complaints ("redemption payment is long process") and caught praise and replies from staff.
- The ranking is now two tables. **Causes:** the stated reasons, with "hard to use the app" replaced by its sub-themes. **After stopping:** problems getting money out (28 posts: slow or stuck 11, cannot find or complete a redemption 10, amount differs from what the app showed 7). A post about getting money out is ranked only in the second table.
- Result: the top cause is the stated reason "Autopay / payment problem" (50 posts), then "App: autopay / mandate set-up and changes" (13), which overlaps with it. The old number-one area, "hard to use the app", no longer exists as one row.
- **Hand check of the AI labels:** 24 randomly chosen labelled posts were read. 19 right, 3 right problem with a doubtful sub-type (for example "cheated me with my redemption" put under "cannot complete a redemption"), 2 wrong (plain questions labelled as problems: a Malayalam question about switching funds, and a forum question about another broker's redemption procedure). That is about 80% exact, which is good enough to rank areas but not to count single posts.
- 13 of the 68 "hard to use the app" posts were judged praise, plain questions or staff replies and are not ranked.
- The extra branch and "fixable" weights for the new rows are judgements, written in `SUB_AREA` in `pipeline/export.py` and shown on the page.
- Noticed on the way: replies written by a platform's staff on TradingQ&A are among the tagged "relevant" posts. They are mostly labelled "not a problem" by this pass, but they are not yet removed from the other counts. To decide with the user.

---

## Entry 12: Credibility fixes before publishing (2026-10-24)

- **One meaning of "tagged" and "relevant" on every page.** *Tagged* = the AI tagger has read the post and filled in the codebook (420 now). *Relevant* = a tagged post that the tagger confirmed is about SIPs or first-time mutual fund investing (347 now); every count, chart, quote and answer uses relevant tagged posts only. The earlier, cheaper step is now always called the "quick filter" so that "relevant" cannot mean two things. The banner, overview, funnel, volumes table and explorer all use these words and the explorer says in one line that it shows relevant posts only (347 of 420).
- **Q4 of the nine questions showed "0 posts" above a chart with 4 and 4.** The count used only the "how often do you check" field, the chart used the "what do you look at" field. Both fields now count, the headline number is the posts that fill in either, and the denominators of the two charts are their own fields.
- **Quotes on the nine-questions page** were sometimes taken from a fallback group (for example all posts) when the group for that question was empty. Each question now takes quotes only from posts the tagger marked for that question's field, and shows "No verified quotes" when there are none.
- **Segments page.** Low confidence is now based on the number of lapse stories (under 15) in the group, not the number of posts. The one-row irregular-income table was replaced by a single line (0 of 347 posts gave irregular income as a reason).
- **Themes.** Hindi, Hinglish and Malayalam filler words are removed before the posts are embedded and grouped, and each theme has a short plain-English name written by an AI model. Reading the example posts of all 10 themes against their names, the names fit, with one weak case ("Autopay issues for SIPs" for a group that is mostly people praising the autopay feature). First attempt left Hindi words ("sakte", "paise", "aap") in a group's top words; the filler list was extended and the groups rebuilt.
- **Deployment.** Only `data/export/` is committed. `data/processed/` (cleaned text of every collected post, AI labels, logs) stays on the laptop and is git-ignored; it was also removed from the local commit history, which had not been pushed.
