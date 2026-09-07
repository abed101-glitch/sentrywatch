# Classes 7 & 8 — what I did, and what to answer

---

# CLASS 7 — Per-Account Behavioural Baselines

## In one sentence

> "Up to Class 6 I compared every transaction to one global average. Class 7 gives each
> account its own baseline, computed incrementally so it works on a live stream."

## What I actually built

1. **Welford's algorithm** — running mean and variance from a stream, three numbers per
   account, never storing the transactions
2. **EWMA** — a second recency-weighted baseline, so accounts that genuinely change don't
   get flagged forever
3. **Cold start** — under 30 transactions an account falls back to the global baseline
4. **Velocity** — transactions per hour, which catches card testing
5. **SQLite store** — 127 bytes per account, survives restarts

## The story arc (this is what makes it a real class)

Built it → measured it → **it was worse** → diagnosed why → fixed it → re-measured → said
honestly that detection still didn't improve.

## Numbers to know

| | |
|---|---|
| Speed | 0.0082 ms/transaction, ~121,000 txn/s |
| Storage | 127 bytes/account, O(accounts) not O(transactions) |
| Tests | 46 passing |
| The bug | at n=30 the sample std was **56.2%** of true → `z>3` fired at **`z≈1.69`** |
| The fix | log1p → std ratio 0.562 → **1.000** |
| Result | 994 flags → **60**. 94% fewer false positives |
| Skewness | 11.90 (heavy right tail) |

## Q&A

**"What is Welford's algorithm?"**
> Running mean and variance from a stream. Four lines. You keep count, mean, and M2. Each
> new value nudges the mean by delta over n, and M2 accumulates the deviation. Variance is
> M2 over n minus 1. O(1) memory — I never store the transactions.

**"Why not just E[x²] − E[x]²?"**
> I tried it. It's numerically broken. With values around a billion, both terms are around
> 10¹⁸ and float64 only holds 16 digits, so you're subtracting two numbers that agree in
> the first 15. My test returns **negative 128** where the true variance is 0.083. Negative
> variance means sqrt gives NaN and every z-score downstream breaks.

**"Why not groupby?"**
> Works in a notebook. In a live pipeline transactions arrive one at a time, I can't hold
> all history in memory, and I need an answer in milliseconds.

**"Why keep the global z-score?"**
> Cold start. A new account with three transactions has a meaningless standard deviation —
> one big purchase makes it enormous and nothing looks unusual again. Below 30 observations
> I fall back to global. So Class 7 adds to Class 6 rather than replacing it.

**"What's EWMA for?"**
> Welford gives a lifetime average, but people change. EWMA weights recent transactions
> more. I tested an account that moved from 50 to 500 — EWMA reached 499.98 while the
> cumulative mean was still at 178.57. Judging against the cumulative mean would flag every
> normal transaction from then on. The gap between the two is itself a drift signal.

**"Did it improve fraud detection?"** ← *say no clearly*
> No. 2 of 60 in raw space, 0 of 60 in log space — both indistinguishable from zero. Fraud
> in this dataset isn't an amount anomaly. My Class 2 result already showed that: the
> z-score rule caught 11 of 492. The signal is in V1–V28, which is what Class 4 proved.

**"Then what was the point?"** ← *the one that matters*
> Three things. The per-entity baselining my proposal specified, with 46 tests and 0.0082 ms
> per transaction. A calibration bug I didn't know I had — `z > 3` was firing at `z ≈ 1.69`,
> and my Class 6 *global* baseline turns out to be 14.3x off the theoretical rate too, which
> I'd never checked. And independent confirmation of my Class 2 finding from a new angle.

**"How do you know the bias is gone?"**
> The flag ratio went flat. In raw space it drifted 2.06 → 1.30 as history grew from 50 to
> 1,000 transactions — the detector behaved differently depending on account age. In log
> space it's 0.12 → 0.08, essentially constant. A lower number could be a threshold
> artefact. Flatness can't be.

**"Your account IDs are fake."** ← *volunteer this, don't wait*
> Yes. The dataset has no account column — that's *why* I used a global z-score for five
> classes. What the synthetic data validates is the machinery and its cost, not a recall
> improvement. I built a `random` mode as the null case, where accounts are interchangeable
> and per-account should add nothing, so I'm not only showing the flattering configuration.
> Real validation needs PaySim or IEEE-CIS.

---

# CLASS 8 — Real-Time Alerting

## In one sentence

> "Class 7's Switch node routed by severity but nothing was connected to its outputs.
> Class 8 connects them — and writes the alert in language the person reading it can act on."

## What I actually built

1. **Telegram delivery** — outbound only, no hosting needed
2. **Account-aware messages** — using Class 7's baselines
3. **Per-incident cooldown** — keyed on account + signal pattern
4. **Global hourly cap** — circuit breaker for model drift
5. **Suppression logging** — every suppressed event still recorded with its reason

## The before/after that sells it

Before: `z-score: 17.638`

After:
```
This account normally spends about 380.50.
This one is 11.8x that - 17.4 sigma above its own baseline.
```

> "17.4 sigma is what a statistician needs. 11.8 times this account's normal is what the
> shop owner needs. Class 7's baselines are what made the second sentence possible."

## Numbers to know

| | |
|---|---|
| Burst test | 5 identical events → **1 alert, 4 suppressed** |
| Global cap | 6 accounts, cap 3 → **3 alerts, 3 blocked** |
| Tests | 30 for alerting, **76 across the project** |
| Model flag volume | ~484 of 284,807 at contamination 0.0017 |

## Q&A

**"Doesn't Telegram need hosting?"**
> No. Sending is an *outbound* HTTPS request from my machine to api.telegram.org, like
> loading a webpage. Nothing needs to reach in, so it works on localhost with no tunnel.
> Hosting is only needed for the reverse direction — a Telegram Trigger, where Telegram has
> to POST to my machine. Same distinction applies to Slack webhooks and SMTP.

**"Why suppress alerts at all?"**
> My model flags about 484 of 284,807 transactions. If every flag became a notification I'd
> have muted the channel by lunch — and an alerting system nobody reads is worse than none,
> because it costs money and creates a false sense of coverage.

**"How does the deduplication work?"**
> The key is account plus severity plus which signals fired. Deliberately **not** the
> transaction ID — if it were, every event would be unique and the cooldown would never
> trigger. A card tested with 50 small charges in two minutes is one incident, not 50 alerts.

**"Aren't you just hiding alerts?"** ← *section 4 of the demo answers this*
> No. Every suppressed event is written to the log with its reason, and when the cooldown
> expires the next alert reports how many it absorbed. Silent suppression I couldn't audit
> would corrupt my Class 10 evaluation — I'd have no way to tell "the model missed it" from
> "the throttle ate it".

**"What's the global cap for?"**
> Model drift. If a bad data feed makes everything look anomalous, the cooldown won't help
> because each event has a different key. The cap stops the flood before it permanently
> destroys trust in the channel. And it fires with a message naming the cap, so the cap is
> itself a signal to go check the dashboard.

**"Why is the throttle in Python and not n8n?"**
> Each n8n execution is independent with no natural place for state across runs. The scoring
> service is already a long-running process holding the model and the baselines. The
> tradeoff is it's in-memory, so it resets on restart and won't work across multiple
> workers — production answer is Redis. That's a stated limitation.

**"Why keep routing in n8n then?"**
> The Switch node makes the severity policy visible on the canvas, where someone who isn't a
> developer could change it. Policy in n8n, mechanism in Python.

**"What bugs did you hit?"** ← *good answer, have it ready*
> Two in the message wording, both only visible on a card-testing example. A small amount
> printed as "0.0x higher", and a negative z-score printed as "-1.8 sigma above", which is
> self-contradictory. The code was correct and the output was still nonsense — so I added
> tests that assert on the wording, not just the numbers.

---

# THE LINK BETWEEN THE TWO CLASSES

If he asks why these are two classes and not one:

> "Class 7 produced the signal, Class 8 delivers it. And Class 8 is only useful *because* of
> Class 7 — without per-account baselines the alert can only say 'z-score 17.6'. With them
> it says '11.8 times this account's normal', which is something the person receiving it can
> act on."

# THE THREE SENTENCES IF YOU BLANK

1. Class 7: "Global baseline treats everyone the same. Per-account gives each account its own."
2. Class 8: "Sending is one HTTP POST. The engineering is deciding when *not* to send."
3. Both: "I found a calibration bug I didn't know I had, and I'm reporting that detection
   didn't improve rather than dressing it up."
