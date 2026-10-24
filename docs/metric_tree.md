# Draft metric tree: 12-month SIP continuation (v0.1)

**Business metric:** % of first-time mutual fund investors whose first SIP started in month M
who still have an active SIP in month M+12.
**Active** = at least one *successful* instalment in the last 30 days (any SIP, not only the first).

## The tree

```
12-month active rate
│
├── A. Getting going (month 0–1)
│     ├── Mandate / autopay set up successfully
│     └── First instalment succeeds
│
├── B. Involuntary lapse — SIP stops without the user deciding
│     ├── Insufficient balance on the debit date (date ≠ when money arrives)
│     ├── Mandate fails, expires or is rejected
│     ├── Bank account / salary account changed
│     └── Failed instalments not noticed or not easy to fix
│
├── C. Voluntary lapse — the user chooses to stop
│     ├── Cash-flow strain / irregular income → pause → never resumed
│     ├── Expectation gap: early returns look "too small" or red
│     ├── Doesn't understand what they see (NAV, units, XIRR, statements)
│     ├── Social influence: friend / finfluencer says stop or switch
│     ├── Fund switching (stop to restart elsewhere → gap)
│     └── Life event / goal change → withdrawal
│
├── D. Disengagement — the SIP keeps running only while nothing goes wrong
│     ├── Stops opening the app; doesn't notice a failure or pause
│     └── Low sense of progress toward a goal
│
└── E. Recovery — users who lapse but come back within the window
      ├── Pause ends and SIP resumes
      └── Restarts after a failed instalment
```

## Product outcomes that move the metric

| Outcome | Branch | Leading indicator (measurable early) |
|---|---|---|
| More first instalments succeed | A | % of new SIPs with a successful first debit |
| Fewer failed debits, faster fixes | B | Failed-instalment rate; % fixed within 7 days |
| Pauses end in resumption, not cancellation | C, E | % of pauses followed by a successful instalment within 60 days |
| Investors understand early results | C | % who view a red/flat month and still invest next month |
| Fewer stops right after an outside influence | C | Stop rate after viewing market-news / "SIP loss" content |
| Stay engaged with a goal | D | Monthly active viewers of their own SIP |

## Open questions for the discovery engine

1. How big is **involuntary (B)** vs **voluntary (C)** lapse in what people say?
2. Which **month** do problems cluster in (1–3 vs 4–12)?
3. Which **segment** (income stability, age, money source, influencer) over-indexes on each branch?
4. When people say "market fell", what is the **underlying** reason?

This tree is a draft. It gets revised after the discovery results.
