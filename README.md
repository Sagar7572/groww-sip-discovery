# Groww SIP Discovery Engine

An AI-powered engine that collects public conversations about SIPs and first-time
investing in India, tags each one against a fixed codebook, and turns the tags into
ranked opportunity areas for **12-month SIP continuation**.

```
collect  ->  clean  ->  tag (AI)  ->  count & cluster  ->  rank  ->  validate  ->  dashboard
```

## Folder layout

```
groww-sip-discovery/
├── collect/          data collectors (run these on your laptop)
├── pipeline/         cleaning (done), AI tagging, theme clustering, scoring (next)
├── eval/             hand-labelled golden set + agreement script       (next step)
├── app/              Streamlit dashboard (reads data/export only)
├── data/export/      compact files the dashboard reads (built by pipeline/export.py)
├── docs/             metric tree and notes
├── data/raw/         collected data lands here
├── data/processed/   cleaned data, AI labels, logs and backups: stays on your laptop, NOT committed
├── data/manual/      hand-picked Reddit threads (if no Reddit API)
├── codebook.yaml     the labels the AI fills in for every post
└── config.yaml       search keywords and limits
```

---

## Step 1: one-time setup (about 15 minutes)

1. **Install Python 3.11 or newer** from python.org.
   On Windows, tick **"Add Python to PATH"** during installation.
2. **Unzip this folder** somewhere easy, e.g. `Documents\groww-sip-discovery`.
3. **Open a terminal in the folder.**
   Windows: open the folder in File Explorer, click the address bar, type `cmd`, press Enter.
   Mac: right-click the folder > *New Terminal at Folder*.
4. **Create a virtual environment and install the packages** (copy-paste, one line at a time):

   Windows
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements-pipeline.txt
   ```
   Mac / Linux
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-pipeline.txt
   ```
5. **Add your keys.** Copy `.env.example`, rename the copy to `.env`, open it in Notepad
   and paste your YouTube key after `YOUTUBE_API_KEY=`. Add Reddit keys only if Reddit approved you.
   Never share this file.

## Step 2: collect the data

With the terminal still open in the folder (and `.venv` activated):

```
python -m collect.run_all
```

That runs every source. To run just one: `python -m collect.run_all play_store`
(names: `play_store`, `app_store`, `tradingqna`, `youtube`, `reddit`).

It takes roughly 10–20 minutes. If one source fails, the others still run and the
summary at the end tells you which one failed. Just send me the error text.

## Step 3: clean the data

After collecting, run (with `.venv` activated):

```
python -m pipeline.clean
```

No AI is used. It merges everything in `data/raw/`, then:

1. removes exact and near-duplicate texts (e.g. the same comment posted 170 times),
2. drops items under 6 words unless they mention a SIP keyword from `config.yaml`,
3. adds `year`, `language` (en / hi / hinglish / other, a simple rule-based guess) and
   `context` (TradingQ&A replies get their thread's original question; YouTube comments
   get the video title; app reviews get nothing).

It prints a table per source (raw, after dedupe, final, 2021+ vs older, by language) and 5 random
dropped short items so you can check nothing useful is lost. Output:
`data/processed/clean.jsonl` (kept) and `data/processed/dropped.jsonl` (dropped, with reason).
The settings (6 words, 90% similarity, 2021 window) are constants at the top of `pipeline/clean.py`.

## Step 4: AI relevance filter

Needs `GROQ_API_KEY` in `.env`. It asks a small free Groq model whether each cleaned item is about
SIP / mutual-fund investing (yes / no / unsure; "unsure" is kept).

```
python -m pipeline.filter --pilot 100    # try 100 mixed items first and print a report
python -m pipeline.filter --report       # print the pilot report again
python -m pipeline.filter --all          # full run; safe to stop and run again, it resumes
```

Results are saved item by item in `data/processed/relevance.jsonl`. The current prompt is v3; the
model's "no" answers are upgraded to "unsure" by two plain-code safety nets (see `docs/evidence_log_notes.md`,
Entry 5). `model_relevant` keeps the model's own answer. If Groq's daily limit is
reached the run stops with a message; run the same command the next day.

## Step 5: AI tagging

Fills in the codebook (`codebook.yaml`) for each item. Two free Groq models share the work, each with its own
daily allowance, so run each in its own terminal (or in the background):

```
python -m pipeline.tag --tagger gpt-oss-120b --all
python -m pipeline.tag --tagger qwen --all
```

Priority items (stop, pause, cancel, failed, mandate, autopay, loss...) go first. Each run is safe to stop and
rerun: it skips finished items and stops by itself when the daily allowance is used up. Results:
`data/processed/tags.jsonl` and `data/processed/tags_qwen.jsonl` (each record says `tagged_by`).
Quotes that could not be verified are flagged `quote_unreliable` and must not be shown to users (use `quote_display`).

## Step 6: the dashboard (the Discovery Engine front-end)

The dashboard is `app/streamlit_app.py`. It reads **only** the small files in `data/export/`, never the raw data, and never scrapes.

Build the files it needs from everything processed so far (safe to run any time, takes about a minute):

```
python -m pipeline.export
```

Run the dashboard on your own computer:

```
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

For "Ask the data" locally the Groq key is read from `.env` (never printed). Pages: overview and how it works, opportunity ranking,
the nine brief questions, metric tree, segments and sources, evidence explorer, ask the data, validation and limitations.

### Reddit through Apify (paid per result, so it has cost guards)

Reddit's own API needs approval, so Reddit is collected with the Apify actor `trudax/reddit-scraper-lite` ($4.00 per 1,000 results). Put `APIFY_TOKEN` in `.env`.

```
python -m collect.reddit_apify --pricing                       # price and spending so far; runs nothing
python -m collect.reddit_apify --stage posts                   # step 1: posts only (no comments), about 150 posts
python -m collect.reddit_apify --stage shortlist               # step 2: free, plain code: keep posts about stopping / failing / etc.
python -m collect.reddit_apify --stage comments --approved     # step 3: 15 comments for the shortlisted threads, within the budget
```

`budget_total_usd` in `config.yaml` is the limit for all runs together; a ledger (`data/raw/apify_reddit_ledger.json`) adds them up and no run starts if
it could pass the limit. Your own thread URLs can go in `data/manual/reddit_threads.txt` (one per line); they are fetched first.
Usernames are never saved: author fields are dropped and usernames inside text and links are masked before anything is written.
If a run finishes on Apify but the script stopped, `--recover <run id> <label>` takes it over without paying again.

### Staff replies and human corrections

- TradingQ&A replies written by the platform's own staff are excluded from every count. If you collect TradingQ&A again, run
  `python -m collect.tradingqna_flags` once afterwards (it re-reads only the staff / moderator / admin true-false flags, never usernames).
- To correct a wrong AI tag by hand, add a row to `data/manual/corrections.csv` (columns `id, field, corrected_value, reason`; write a list with `|`
  between values, for example `underwhelming_returns|trust_concern`). It is applied at every export and listed on the Validation page.
- If the free Groq models are at their daily limit when you export, add `--wait-for-ai 30` and the export keeps retrying for up to 30 minutes
  (it needs them for the problem-area labels, theme names and unmet-need themes; results are cached in `data/processed/`).

### Running the AI steps over several days (free daily limits)

Each free model has its own daily allowance that rolls over 24 hours. These commands wait for Groq's stated reset time and
carry on by themselves, so you can leave them running (each in its own terminal):

```
python -m pipeline.filter --all --auto-resume
python -m pipeline.tag --tagger gpt-oss-120b --all --auto-resume
python -m pipeline.tag --tagger qwen --all --auto-resume
```

### Daily refresh and redeploy (one routine)

```
python -m pipeline.export
git add data/export docs
git commit -m "Refresh data"
git push
```

Only `data/export/` is committed (plus code and docs). `data/processed/` and `data/raw/` stay on your laptop and are git-ignored, so the
cleaned text of every collected post is not published; `data/export/posts.jsonl` holds only the relevant tagged posts the dashboard shows
(text already scrubbed of usernames and personal numbers). To rebuild the processed data on another computer, run the pipeline
commands above from the collect step onward.

The hosted app updates itself a minute or two after the push (Streamlit Community Cloud watches the repository).
Before every `git add`, check with `git status` that `.env` is not listed. It is ignored by `.gitignore`, and the file `.env.example`
must stay empty of real keys.

### Deploying on Streamlit Community Cloud (free)

1. Put the project on GitHub (public repository, for example `groww-sip-discovery`, with no personal name in it).
2. Go to share.streamlit.io, sign in with GitHub, click **Create app**, pick the repository, branch `main`, and **Main file path** `app/streamlit_app.py`.
3. Open **Advanced settings** and paste this into **Secrets** (use your own key; it stays private, it is not in the repository):

   ```
   GROQ_API_KEY = "paste-your-groq-key-here"
   ```
4. Choose the **App URL** (a custom subdomain without your name, for example `groww-sip-discovery`) and click **Deploy**.
5. Free apps go to sleep after about 12 hours without visitors; the first visit afterwards takes a minute to wake it.

## Step 7: send the results

Upload every file inside `data/raw/` to the chat (the `.jsonl` files and
`collection_summary.json`).

---

## Reddit without the API

If Reddit hasn't approved your API access, collect the best threads by hand:

1. Copy `data/manual/reddit_manual_template.csv` and name the copy `reddit_manual.csv`.
2. Open it in Excel or Google Sheets. Add **one row per post or comment**:
   the thread link, subreddit, thread title, `post` or `comment`, the date, and the text.
3. **Copy the text only, never the username.**
4. Aim for 30–50 rich threads, e.g. searches like *"stopped my SIP"*, *"first SIP negative"*,
   *"SIP autopay failed"* on r/IndiaInvestments, r/mutualfunds, r/personalfinanceindia.
5. Save as CSV and run `python -m collect.run_all reddit`.

## Privacy

- Usernames and author handles are never stored.
- PAN numbers, emails, phone numbers, long account-like numbers and @handles are
  replaced with placeholders like `[PAN]` before anything is saved.
- Only public posts are collected.
