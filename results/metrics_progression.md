# Evaluation: Detector Progression, Class 2 → Class 6

Every number here comes from a run recorded in a diary or notebook output.
Dataset: Kaggle Credit Card Fraud Detection — 284,807 transactions, 492 fraud (0.173%).

## Headline table

| Class | Detector | Features | Flagged | Caught | Recall | Precision |
|---|---|---|---:|---:|---:|---:|
| 2 | z-score > 3 | 1 | 4,076 | 11 / 492 | 2.24% | 0.27% |
| 3 | (z > 3 OR night) AND amt > median | 3 | 13,503 | 49 / 492 | 9.96% | 0.36% |
| 4a | Isolation Forest | 3 engineered | 480 | 1 / 492 | 0.20% | 0.21% |
| 4b | Isolation Forest | V1–V28 + Amount | — | — | — | — |
| **6** | **Isolation Forest (production)** | **V1–V28 + Amount + hour** | **~484** | **123 / 492** | **25.0%** | **25.4%** |

Row 4b ran in the notebook but its output was never captured — rerun
`notebooks/class04_isolation_forest.ipynb` to fill it in. It's the step that isolates
*hour*'s contribution, so it's worth having.

## False alarms per real fraud

The ratio that decides whether a business can actually run this:

| Detector | False alarms per catch |
|---|---:|
| Class 2 z-score | 370 |
| Class 3 rule | 275 |
| Class 4a (3 features) | 479 |
| **Class 6 production** | **2.9** |

## What the numbers actually say

**Precision improved 94x, from 0.27% to 25.4%.** That is the headline result of the project.

**It was not caused by adopting machine learning.** Class 4a *was* machine learning — the same
Isolation Forest, same contamination, same random seed — and it was the worst detector built,
below even the naive single-column z-score. The only difference between 4a and the production
model is which columns went in.

The cause was the feature set. Class 4a used `amount_zscore`, `hour`, `Amount` — and since
`amount_zscore` is a deterministic rescaling of `Amount`, that's really two independent signals,
one of which (amount) the Class 2 result had already shown to be weak. The V1–V28 PCA components
carry the discriminative information, and they were being ignored.

**Conclusion for the report: the features mattered more than the algorithm.** This is a stronger
finding than "we applied Isolation Forest and got 25% recall," because it's supported by a
controlled comparison — algorithm held constant, inputs varied.

## The rule-based ceiling

Class 3 was the best a hand-written rule got: 9.96% recall at 0.36% precision. Adding the night
feature nearly 5x'd recall over Class 2, which shows feature combination helps. But an `OR` rule
evaluates each condition independently and cannot represent interaction — a \$150 charge at 2am
may be routine for one account and alarming for another. That structural limit, not a tuning
problem, is what motivated the move to a model.

## Caveats to state in the written report

- **Precision and recall are measured on the training data.** Isolation Forest is unsupervised,
  so it never saw the `Class` labels, but the anomaly scores were still fit on these same rows.
  A held-out split would give a more defensible number. Worth doing before Class 9.
- **`contamination=0.0017` was set from the known fraud rate.** A real deployment doesn't know
  its fraud rate in advance, so this is mild information leakage. Sensitivity analysis across
  contamination values would strengthen the evaluation.
- **The z-score baseline is global, not per-account.** The Kaggle set has no user ID, so
  "unusually large" is relative to all 284,807 transactions rather than to one customer's
  history. Per-entity baselining — which is what the proposal describes — needs a dataset with
  account identifiers.
- **25% recall means 369 frauds are still missed.** Honest framing: this is a triage system
  that surfaces the most anomalous 0.17% for review, not a system that catches fraud.

---

# Class 7 — per-account baselines

Measured on 50,000 rows, 500 synthetic accounts, 24,996 warm-scored transactions
containing 60 frauds. Isolation Forest excluded (`ml_flagged=False`) to isolate the
baseline layer.

## The problem found

| Detector | Flags | Caught (of 60) | Rate | vs theoretical |
|---|---:|---:|---:|---:|
| Global z-score (raw) | 482 | 0 | 1.928% | 14.3x |
| Per-account z (raw) | 994 | 2 | 3.977% | 29.5x |
| **Per-account z (log1p)** | **60** | **0** | **0.240%** | **1.8x** |

A one-sided `z > 3` gate on normal data should flag 0.135% — about 34 of 24,996.
Both raw detectors are wildly miscalibrated. 0 vs 2 catches out of 60 is noise.

## Diagnosis — small-sample bias on heavy-tailed data

Amount skewness is **11.90**. The sample standard deviation of a heavy-tailed variable
is downward-biased at small n, because a short sample rarely contains the tail. Measured
directly by resampling the real `Amount` column:

| n | raw std ratio | effective threshold | log1p std ratio |
|---:|---:|---:|---:|
| 10 | 0.395 | z > 1.19 | 0.958 |
| **30** *(MIN_HISTORY)* | **0.562** | **z > 1.69** | **1.000** |
| 50 | 0.687 | z > 2.06 | 0.986 |
| 100 | 0.715 | z > 2.14 | 0.999 |
| 500 | 0.927 | z > 2.78 | 0.999 |
| 5000 | 0.983 | z > 2.95 | 0.999 |

At `MIN_HISTORY = 30` the denominator was 56% of its true value, so the nominal `z > 3`
rule was really firing at `z ≈ 1.69`.

## Confirmation — flag ratio vs history length

| History/account | Global | Per-acct raw | ratio | Per-acct log1p | ratio |
|---:|---:|---:|---:|---:|---:|
| ~50 | 482 | 994 | 2.06 | 60 | 0.12 |
| ~100 | 482 | 815 | 1.69 | 42 | 0.09 |
| ~250 | 482 | 703 | 1.46 | 37 | 0.08 |
| ~500 | 482 | 664 | 1.38 | 41 | 0.09 |
| ~1000 | 482 | 625 | 1.30 | 40 | 0.08 |

**The flatness is the evidence, not the level.** Raw drifts 2.06 → 1.30 as history grows;
log1p sits at 0.12 → 0.08. An account with 50 transactions is now judged the same way as
one with 1,000.

## Cost

0.0082 ms/transaction · 121,230 txn/s · 127 bytes/account · storage O(accounts), not
O(transactions). ~1% added to scoring cost.

## What Class 7 delivered — and what it did not

**Delivered:** the per-entity baselining the proposal specified, 43 passing tests, and a
94% false-positive reduction after the log-space fix — leaving the per-account baseline
*better calibrated than the global one it replaced* (1.8x vs 14.3x theoretical).

**Not delivered:** any improvement in fraud detection. 2/60 raw, 0/60 log — both
indistinguishable from zero. This is consistent with Class 2: fraud here is not an amount
anomaly (fraud mean 122 vs normal 88; the Class 2 z-rule caught 11/492). The signal is in
V1–V28, as Class 4 demonstrated. **Refining the yardstick doesn't help when the quantity
being measured doesn't separate the classes.**

A calibration bug was found and fixed. The feature remains the limitation.

---

# Class 9 — live evaluation against real labels

The pipeline no longer generates transactions. n8n pulls real rows from
`creditcard.csv` via `/next-transaction`, and the true `Class` label rides along,
so recall and precision are computed against ground truth as the stream runs.

Reproduce with `cd src && python evaluate_replay.py --n 3000`.

## Result — 3,000 real transactions, 88 real frauds

| Detector | Caught | Flagged | Recall | Precision (stream) | **Precision (real base rate)** |
|---|---:|---:|---:|---:|---:|
| Isolation Forest alone | 30 | 34 | **34.1%** | 88.2% | **30.0%** |
| amount z > 3 alone | 0 | 5 | 0% | 0% | 0% |
| Combined (what ships) | 30 | 38 | 34.1% | 78.9% | **17.7%** |

Confusion matrix for the combined detector: **TP 30 · FN 58 · FP 8 · TN 2,904**.

## Why two precision columns

The replay over-samples fraud — **2.93%** in the stream versus **0.173%** in the
population, about **17x**. Precision depends on the class balance, so the stream
figure is inflated. Recall does not, so 34.1% carries over unchanged.

The final column rescales precision to the real base rate using the measured
recall and false-positive rate. **That is the number to quote.**

## Consistency check

Class 6 measured 25.0% recall / 25.4% precision in batch. This measures 34.1% /
30.0% streaming, by a completely different route — one-at-a-time scoring, live
baselines, real labels. Two independent measurements landing in the same range is
evidence both are sound.

## The finding: combining signals made it worse

Every fraud the system caught was caught by the **Isolation Forest alone**.
Adding the amount z-score and velocity contributed **4 extra false alarms and
zero extra catches** — identical recall, precision cut from 30.0% to 17.7%.

`combine_severity` escalates on a single signal: one signal → medium, and medium
alerts. So a weak signal firing alone is enough to notify someone. The measurement
says that costs precision and buys nothing.

This is the same shape as Class 4 and Class 7: the intuitive move —
*more features*, *per-account baselines*, *combine the signals* — was measured
rather than assumed, and in each case the measurement disagreed with the intuition.

**Class 10 follows directly:** require two signals to escalate, and re-measure.

## Two bugs found by running this

**Velocity was firing on shuffled timestamps.** The replay shuffles rows but each
row carries its original `Time`, so "transactions in the last hour" was comparing
random points across a two-day span. Velocity fired on ~1,100 of 3,000 events;
combined precision read **4.4%**. Fixed by issuing monotonic arrival times spaced
120s apart, so with 8 accounts each sees ~3.75 transactions per hour — under the
threshold of 10. False positives fell from **1,112 to 8**.

**The Isolation Forest had been scoring zeros.** The old n8n generator sent
`V1..V28` as all-zero placeholders. The model — trained on exactly those PCA
components — was being fed constants throughout Class 9's first version. The
replay supplies the real features, and this is the first measurement where the
Class 4 model actually contributes.

## Caveats

- **Account IDs are still assigned round-robin.** The dataset has no account
  column. Amounts, features and labels are original; grouping is not.
- **Frauds are over-sampled** for demo pacing. Handled above for precision;
  raw counts are not population rates.
- **Still measured on training data.** The Isolation Forest was fit on these rows.
  Unsupervised, so it never saw the labels — but a held-out split would be
  stronger.
- **n = 3,000 with 88 frauds.** Wide confidence intervals. Worth rerunning at
  `--n 20000` for the report.

---

## Still to measure (Class 10)

- Precision/recall on a held-out test split
- Threshold sensitivity: how the numbers move as contamination varies
- End-to-end latency: webhook → score → alert delivered
- Alert volume: sent vs. suppressed, from the `AlertLog` sheet

---

# Class 10 — choosing the escalation policy

Class 9 measured that combining signals *cost* precision and caught nothing extra.
Class 10 tests the fix. Three policies, same 3,000-transaction stream, same labels.

Reproduce with `cd src && python evaluate_replay.py --n 3000`.

## The three policies

| Policy | Rule | Used in |
|---|---|---|
| **any 1 signal** | amount OR velocity OR model → alert | classes 6–9 |
| **any 2 signals** | require consensus between any two | the obvious fix |
| **model required** | no model flag → silent; other signals only raise to high | **class 10** |

## Result — 3,000 real transactions, 88 real frauds

| Policy | Alerts | Caught | False | Recall | Precision (real base rate) |
|---|---:|---:|---:|---:|---:|
| any 1 signal | 38 | 30 | 8 | 34.1% | 17.7% |
| any 2 signals | **1** | **0** | 1 | **0%** | **0%** |
| **model required** | **34** | **30** | **4** | **34.1%** | **30.0%** |

## The consensus policy is a disaster, and the reason is measurable

Requiring two signals catches **zero fraud**. Not fewer — none.

The signals barely overlap. The model flagged 34 transactions, the amount rule
flagged 5, and the union was 38 — so only **1** transaction triggered both, and
it was not fraud. Requiring agreement between detectors that agree on almost
nothing means requiring nothing to fire at all.

This is worth stating plainly: **the intuitive fix to Class 9's finding was also
wrong, and for a reason the Class 9 numbers already contained.** 34 + 5 − 38 = 1.
The answer was sitting in the previous class's output table.

## What actually works

Make the model **necessary**. The weak signals stop being able to raise an alert
on their own, and instead only escalate a model-flagged transaction to high.

- **Recall is unchanged at 34.1%** — every fraud the system ever caught was
  caught by the model, so nothing is lost.
- **False alarms drop 8 → 4**, and precision at the real base rate goes
  **17.7% → 30.0%**, a 70% improvement.
- The amount and velocity signals are still computed, still logged, still shown
  on the dashboard. They just no longer wake anyone up by themselves.

## Why this is not "deleting the features"

A signal can be useless as a *trigger* and useful as *context*. Velocity never
caught fraud alone, but "model flagged it AND 20 transactions this hour" is a
different alert from "model flagged it" — it goes out as high instead of medium,
and the analyst sees why. The Class 7 baselines still explain every alert in
terms of the account's own history.

The change is to what escalates, not to what is measured.

## Honest limits

- **Recall is still 34.1%.** 58 of 88 frauds went undetected. This is triage,
  not prevention.
- **Precision improved by removing false alarms, not by finding more fraud.**
  Both matter, but they are different achievements and should not be conflated.
- The conclusion depends on the model being the only useful signal *on this
  dataset*. On data where amount actually separates fraud, the policy would need
  re-measuring — which is the point of having the switch be one env var.

## The pattern, four for four

| Class | The intuitive move | What the measurement said |
|---|---|---|
| 4 | apply machine learning | 0.20% recall — worse than a z-score |
| 7 | per-account baselines detect more | no detection gain; found a calibration bug instead |
| 9 | combining signals is safer | precision 30.0% → 17.7%, zero extra catches |
| 10 | require consensus | recall 34.1% → 0% |

Every time, the change that sounded obviously right was wrong, and only a
measurement said so. **That is the actual result of this project.** The detector
is a byproduct.

## Bug found during the Class 10 demo run

The dashboard showed 10 events across 8 accounts — at most 2 transactions per
account — but the velocity column read **4 and 5**.

`/replay/reset` rewound the row position, and arrival time was computed as
`position x 120s`, so **the clock went backwards**. The baseline store still held
the first run's timestamps in its velocity window, and the second run's events
landed on top of them and were counted twice.

Fix: the arrival clock is now separate from the row position. `reset()` rewinds
which row comes next; time only ever moves forward. Regression test added.

This is the second time the velocity window has been wrong for the same
underlying reason — Class 9's shuffled timestamps caused 1,112 false positives.
Both bugs came from feeding a time-window calculation a clock that wasn't
monotonic. Anything that reasons over a time window needs its clock guaranteed,
not assumed.
