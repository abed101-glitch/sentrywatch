# Real-Time Anomaly and Fraud Detection Pipeline

**CSE 299, Section 13** · Abed Gazi (2132538642) · 11 classes over 10 weeks

An event-driven fraud detection pipeline: transactions arrive at an n8n webhook, are scored
by a Python service combining an Isolation Forest with per-account behavioural baselines,
and high-severity anomalies trigger throttled real-time alerts.

> **Deviation from the proposal.** The original plan was 10 classes. Class 7 was added to
> implement the per-account rolling statistics the proposal's architecture section
> specifies but which nothing through Class 6 actually did — the z-score was global.
> Everything from the original Class 7 onward shifts by one. Total is now 11 classes.

---

## Status

| Class | Deliverable | Code | n8n | Diary |
|---|---|:--:|:--:|:--:|
| 1 | Domain + dataset chosen | — | — | done |
| 2 | Feature set v1 | done | — | done |
| 3 | Rule-based detector | done | — | done |
| 4 | ML anomaly model | done | — | **skeleton** |
| 5 | Live event ingestion | — | **missing export** | **skeleton** |
| 6 | End-to-end scoring pipeline | done | done | done |
| 7 | **Per-account baselines** *(added)* | done | — | **skeleton** |
| 8 | Real-time alerts | done | done | **skeleton** |
| 9 | Automation + dashboard + landing page | done | done | **skeleton** |
| 10 | **Escalation policy** | done | — | **skeleton** |
| 11 | Final demo + report | — | — | — |

**Three things to close before Class 8:**

1. Fill the `_SKELETON` diaries (Classes 4, 5, 7, 8, 9, 10) and drop the suffix
2. Export your Class 5 webhook workflow from n8n → `n8n/class05_webhook_ingestion.json`
3. Copy `creditcard.csv` into `data/` and run `train_model.py` so `model.joblib` lives here

---

## Layout

```
CSE299_Project/
├── data/            creditcard.csv + model.joblib + baselines.db  (gitignored)
├── notebooks/       one runnable notebook per class (2, 3, 4, 7)
├── src/             training, scoring service, baselines, alerting, simulators
├── tests/           96 tests — baseline store (66) + alerting (30)
├── n8n/             exported workflow JSON per class
├── diaries/         one .docx per class
├── docs/            proposal, Class 8 notes, original source material
├── results/         metrics_progression.md — the evaluation table
└── screenshots/     n8n canvas captures for the report
```

## Setup

```bash
python3 -m venv myproject
source myproject/bin/activate
pip install -r requirements.txt
```

Get `creditcard.csv` from Kaggle (see `data/README.md`), then:

```bash
cd src
python train_model.py ../data/creditcard.csv     # writes model.joblib
```

## Running the pipeline

Three processes. Each needs its own terminal.

```bash
# 1 — scoring + alerting service
cd src
set -a && source ../.env && set +a
uvicorn scoring_service:app --host 127.0.0.1 --port 8000 --reload

# 2 — n8n
npx n8n                                          # http://localhost:5678

# 3 — fire test transactions
cd src
python send_test_transactions.py --scenario mixed
```

Import `n8n/class08_score_route_alert.json` into n8n. One placeholder to fix: the
Google Sheet ID. Full setup — BotFather token, chat ID — is in `docs/CLASS8_NOTES.md`.

Verify your bot before touching n8n:

```bash
cd src && python alerts.py --test    # sends a real Telegram message
cd src && python alerts.py           # preview all message shapes, sends nothing
```

## Architecture

```
transaction ──▶ n8n Webhook ──▶ /score ──▶ Switch (severity)
                                  │           ├─ high   ──▶ /alert ──┐
                                  ▼           ├─ medium ──▶ /alert ──┤──▶ Telegram
                        Isolation Forest      └─ normal ──▶ (no alert)│
                        + per-account z                               ▼
                        + velocity                        Google Sheet (AlertLog)
```

Every event reaches the sheet — sent, suppressed, and normal. That's deliberate: without
the normal rows there's no denominator for the Class 9 precision calculation.

**Policy in n8n, mechanism in Python.** The Switch node makes the severity routing visible
on the canvas where a non-developer could change it. Message formatting, throttling and
retries stay in Python where they're testable.

## Result

| Detector | Recall | Precision | False alarms per catch |
|---|---:|---:|---:|
| Class 2 — z-score alone | 2.24% | 0.27% | 370 |
| Class 3 — combined rule | 9.96% | 0.36% | 275 |
| Class 4a — IF, 3 engineered features | 0.20% | 0.21% | 479 |
| **Class 6 — IF, V1–V28 + Amount + hour** | **25.0%** | **25.4%** | **2.9** |

Precision improved 94x — but *not* by adopting machine learning. Class 4a was the same
Isolation Forest with the same seed and was the worst detector built. The gain came from
feeding it the PCA components instead of three hand-made features. **The features mattered
more than the algorithm.** Full analysis and caveats: `results/metrics_progression.md`.

## Class 7 — per-account baselines

Classes 2–6 judged every transaction against one global mean. A 900 charge scores z=3.25
whether it comes from a business that spends 900 weekly or a student who has never spent
over 40. Class 7 gives each account its own baseline, maintained incrementally.

- **Welford's algorithm** — exact streaming mean/variance in O(1) memory per account.
  Matches batch statistics to 9 decimal places using 3 stored numbers instead of 5,000.
  The naive `E[x²]−E[x]²` returns a *negative* variance on realistic magnitudes; there's
  a test demonstrating it.
- **EWMA** (α=0.05) — a second, recency-weighted baseline so accounts that genuinely
  change aren't flagged forever. The gap between the two is a drift signal.
- **Cold start** — under 30 observations an account falls back to the global baseline.
  This is why the Class 6 global z-score is kept rather than replaced.
- **Velocity** — transactions per hour catches card testing, where every individual
  charge looks innocent by design.

Measured cost: **0.0082 ms/transaction**, ~121,000 txn/s, **127 bytes per account**.
Storage is O(accounts), not O(transactions). Adds ~1% to scoring cost.

### The finding

Per-account scoring initially flagged **994** transactions against global's **482** — double
the false positives, no detection gain. Diagnosed rather than accepted:

Amounts are heavy-tailed (skewness **11.90**), and the sample std of a heavy-tailed variable
is downward-biased at small n. At `MIN_HISTORY = 30` the measured std was **56.2%** of true,
so the nominal `z > 3` gate was really firing at **`z ≈ 1.69`**.

Fix: keep the statistics on `log1p(amount)`, which is approximately normal and therefore
nearly unbiased even at n=30.

| Detector | Flags | Rate | vs theoretical (0.135%) |
|---|---:|---:|---:|
| Global (raw) | 482 | 1.928% | 14.3x |
| Per-account (raw) | 994 | 3.977% | 29.5x |
| **Per-account (log1p)** | **60** | **0.240%** | **1.8x** |

94% fewer false positives, and the per-account baseline ends up *better calibrated than the
global one it replaced*. The flag ratio also went flat across history length (0.12 → 0.08,
vs raw's 2.06 → 1.30) — an account with 50 transactions is now judged like one with 1,000.
That stability is the real evidence the bias is gone.

**It did not improve fraud detection.** 2/60 raw, 0/60 log — both noise. Consistent with
Class 2: fraud here isn't an amount anomaly. A calibration bug was found and fixed; the
feature remains the limitation.

```bash
cd tests  && python test_baseline_store.py          # 43 tests
cd src    && python simulate_stream.py --benchmark
cd src    && python diagnose_history_length.py      # tests A, B, C
```

Set `BASELINE_LOG_SPACE=0` to reproduce the raw-space behaviour.

> **Honest caveat.** `creditcard.csv` has no account column, so account IDs in the
> simulation are synthetic. This shows the machinery works and what it costs — it does
> **not** show improved recall on real per-account data. `simulate_stream.py` provides
> both `--assign random` (the null case, where per-account adds nothing) and
> `--assign profiled`; report both.

## Class 8 — real-time alerting

Class 7's Switch node routed by severity but nothing was connected to its outputs. Class 8
connects them, and writes the alert in the language of the person reading it.

Before (raw): `z-score: 17.638`

After:

```
[!!] HIGH SEVERITY

Amount:  4,500.00
Account: ACC-1042

This account normally spends about 380.50.
This one is 11.8x that - 17.4 sigma above its own baseline.

- Isolation Forest flagged it (score -0.0812)
```

`17.4 sigma` is what a statistician needs; `11.8x this account's normal` is what a shop
owner needs. Class 7's baselines are what make the second sentence possible.

**Alert fatigue is the real problem.** Sending is one HTTP POST; deciding *when not to send*
is the engineering. At `contamination=0.0017` the model flags ~484 of 284,807 events — enough
to get the channel muted by lunch, and an alerting system nobody reads is worse than none.

Three filters, each measured:

| Filter | Behaviour | Measured |
|---|---|---|
| Severity threshold | only `high`/`medium` alert | `normal` logged silently |
| Per-incident cooldown | keyed on account + signal pattern, not transaction ID | 6 events → **1 alert, 5 suppressed** |
| Global hourly cap | circuit breaker for model drift | 6 accounts, cap 3 → **3 alerts, 3 blocked** |

Suppressed events are still logged with the reason. Silent suppression would corrupt the
Class 10 recall numbers — you couldn't tell "the model missed it" from "the throttle ate it".

**Telegram needs no hosting.** Sending is an *outbound* HTTPS call to `api.telegram.org`;
nothing reaches in. Only a Telegram *Trigger* would need a public URL.

```bash
cd tests && python test_alerts.py       # 30 tests
cd src   && python alerts.py            # preview messages, sends nothing
```

## Class 9 — automated, on real data, scored against ground truth

n8n runs on a 10-second schedule and pulls **real rows from `creditcard.csv`** —
real amounts, real V1–V28, and the real `Class` label. Nothing is generated. The
service scores, throttles and logs; n8n delivers the Telegram alert.

Because the labels ride along, the dashboard computes **recall and precision live**.

### Measured on 3,000 real transactions (88 real frauds)

| Detector | Recall | Precision (stream) | Precision (real base rate) |
|---|---:|---:|---:|
| Isolation Forest alone | **34.1%** | 88.2% | **30.0%** |
| amount z > 3 alone | 0% | 0% | 0% |
| Combined (ships today) | 34.1% | 78.9% | **17.7%** |

Confusion matrix (combined): TP 30 · FN 58 · FP 8 · TN 2,904

**Quote the last column.** The replay over-samples fraud (2.93% vs 0.173%, ~17x)
so demos aren't 96 minutes apart. That inflates precision but not recall, so the
figure is rescaled to the real base rate.

**Consistency check:** Class 6 measured 25.0% / 25.4% in batch. This gives
34.1% / 30.0% streaming, by a completely different route. Two independent
measurements in the same range.

### The finding

**Every fraud caught was caught by the Isolation Forest alone.** The amount and
velocity signals added 4 false alarms and zero catches — same recall, precision
cut from 30.0% to 17.7%. `combine_severity` escalates on one signal, and the
measurement says that costs precision and buys nothing.

Third time in this project the intuitive move lost to the measurement — after
Class 4 (features beat algorithms) and Class 7 (per-account didn't improve
detection). Class 10 tested that and found it would catch nothing — see below.

### Two bugs the real data exposed

The old generator sent `V1..V28` as **all zeros** — the Isolation Forest was
scoring 28 constants and the pipeline still looked fine.

Velocity fired on **shuffled timestamps**, giving 1,112 false positives and 4.4%
precision. Monotonic arrival times fixed it: **1,112 → 8**.

```bash
cd src && python evaluate_replay.py --n 3000     # the table above
curl localhost:8000/replay-stats                 # what's in the stream
open http://127.0.0.1:8000/dashboard             # live, with ground truth
```

## Class 10 — choosing what is allowed to raise an alert

Class 9 measured that combining signals hurt: precision 30.0% -> 17.7%, zero extra
catches. The obvious fix is to require two signals before escalating. **That would
have caught zero fraud**, and Class 9's own numbers already said so: the model
flagged 34, the amount rule flagged 5, the union was 38 — so `34 + 5 - 38 = 1`
transaction triggered both, and it wasn't fraud.

The fix that works is to make the model **necessary**. Amount and velocity can no
longer alert on their own; they only escalate a model-flagged transaction to high.

| Policy | Alerts | Caught | False | Recall | Precision (real base rate) |
|---|---:|---:|---:|---:|---:|
| any 1 signal *(classes 6-9)* | 38 | 30 | 8 | 34.1% | 17.7% |
| any 2 signals *(consensus)* | 1 | 0 | 1 | **0%** | 0% |
| **model required** *(ships)* | 34 | **30** | **4** | **34.1%** | **30.0%** |

**Recall doesn't move.** Every fraud this system ever caught was caught by the
model, so removing the weak signals as triggers costs nothing — and false alarms
halve. The signals are still computed, logged and shown; they just don't wake
anyone up alone.

```bash
cd src && python evaluate_replay.py --n 3000     # all three policies
curl localhost:8000/health                       # shows the active policy
REQUIRE_ML=0 ESCALATE_AT=1 bash run_service.sh   # revert to the old behaviour
```

### Four for four

| Class | The intuitive move | What measurement said |
|---|---|---|
| 4 | apply machine learning | 0.20% recall — worse than a z-score |
| 7 | per-account baselines detect more | no gain; found a calibration bug |
| 9 | combining signals is safer | precision 30.0% -> 17.7%, zero extra catches |
| 10 | require consensus | recall 34.1% -> **0%** |

Every time, the obvious change was wrong and only a measurement said so. That's
the result of this project; the detector is a byproduct.

## The client journey

Three pages, all served by the scoring service so there is no separate front end to host.

| URL | Page | What it does |
|---|---|---|
| `/` | landing | marketing copy, lead form posting to the n8n webhook |
| `/setup` | onboarding | names the business, imports order history, hands back the integration snippet |
| `/checkout` | the product | a merchant checkout that scores inline and returns APPROVE / REVIEW / DECLINE |
| `/dashboard` | operations | live recall and precision against real fraud labels |

`/setup` is not a mockup: it writes a real account namespace into `baselines.db` and runs
the imported orders through the same `observe()` call the live pipeline uses. The snippet
it returns is the real endpoint with the real payload.

**What a checkout page cannot do** is score the Isolation Forest, because that needs
V1-V28 — PCA components no merchant can compute. Only the rule layer runs there, and the
page says so on screen instead of hiding it.

## Files by class

| Class | Artifacts |
|---|---|
| 1 | `diaries/Class01_Diary.docx` |
| 2 | `notebooks/class02_features.ipynb` · `diaries/Class02_Diary.docx` |
| 3 | `notebooks/class03_rule_detector.ipynb` · `diaries/Class03_Diary.docx` |
| 4 | `notebooks/class04_isolation_forest.ipynb` · `src/train_model.py` |
| 5 | *(n8n export missing)* |
| 6 | `src/scoring_service_class6.py` · `n8n/class06_score_and_route.json` · `diaries/Class06_Diary.docx` |
| 7 | `src/baseline_store.py` · `src/simulate_stream.py` · `tests/test_baseline_store.py` · `src/diagnose_history_length.py` · `notebooks/class07_per_account_baselines.ipynb` |
| 8 | `src/alerts.py` · `tests/test_alerts.py` · `n8n/class08_score_route_alert.json` · `docs/CLASS8_NOTES.md` |
| 9 | `src/replay.py` · `src/event_log.py` · `src/evaluate_replay.py` · `src/dashboard.html` · `landing/index.html` · `n8n/class09_*.json` |
| 10 | `src/baseline_store.py` (`combine_severity`) · `src/evaluate_replay.py` · `tests/test_baseline_store.py` |

`src/scoring_service_class6.py` is kept as the Class 6 snapshot — `src/scoring_service.py`
is the current version with baselines and alerting. Useful for showing progression.
