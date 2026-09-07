# Class 7 — what he'll ask, and what to say

Read this once, then close it. If you're reading from it during the demo it stops
sounding like your work.

---

## Before you walk in

```bash
cd ~/Downloads/CSE299_Project
source ~/myproject/bin/activate
bash demo_class7.sh          # do a full dry run at least once
```

Check these:

- [ ] `(myproject)` shows in your prompt — without it numpy fails and you look unprepared
- [ ] Terminal font size up. He has to read `56.2%` from across a desk.
- [ ] Notebook `class07_per_account_baselines.ipynb` open in a browser tab, already run
- [ ] Close Slack, mail, notifications
- [ ] The demo runs offline. No wifi dependency, no n8n needed.

---

## The four things you must actually understand

Not memorise — understand. If he asks a follow-up and you fold, the honest framing
elsewhere loses its credibility too.

### 1. Welford's algorithm

*What it does:* computes mean and variance from a stream, one value at a time, keeping
only three numbers (`n`, `mean`, `M2`) instead of the whole history.

```
n    += 1
delta = x - mean
mean += delta / n
M2   += delta * (x - mean)      # this uses the UPDATED mean
variance = M2 / (n - 1)
```

*Why the last line matters:* the first `delta` is the distance from the old mean, the
second from the new one. Multiplying them accumulates the squared deviation without ever
forming a large sum of squares.

### 2. Why `E[x²] − E[x]²` fails

Catastrophic cancellation. With values around 10⁹, `E[x²]` is about 10¹⁸ and `E[x]²` is
also about 10¹⁸. Float64 holds ~16 significant digits, so subtracting two numbers that
agree in the first 15 digits leaves you with rounding noise. In the test it produced
**−128** where the true variance was 0.083. Variance can't be negative; `sqrt` of it is
NaN; every downstream z-score is destroyed.

### 3. Why the standard deviation was too small

Amounts are heavy-tailed — skewness 11.90. Most transactions are small, a few are huge.
If you only sample 30 transactions from that distribution, you probably don't draw any of
the huge ones, so the spread *looks* tighter than it is.

Measured: at n=30 the sample std was **56.2%** of the true value. z-score divides by that
std, so a too-small denominator inflates every z. A nominal `z > 3` gate was really firing
at `z ≈ 1.69`.

### 4. Why log fixes it

`log1p(amount)` of a lognormal-ish variable is approximately **normal** — the long tail
gets compressed. And the sample std of a *normal* variable is nearly unbiased even at
small n. So the estimator stops caring how much history an account has.

`log1p` not `log` because the dataset has `Amount = 0` rows and `log(0) = −∞`.

---

## Questions he will probably ask

**"Why did you add a class? Your proposal said 10."**
The proposal's architecture section promised rolling statistics per account in a
lightweight database. Nothing I'd built through Class 6 did that — my z-score was global.
It was the one place the implementation visibly diverged from what I'd proposed, so I
closed it. Alerting moved to Class 8. The README documents the deviation.

**"Why not `df.groupby('account').mean()`?"**
That works in a notebook. In a live pipeline transactions arrive one at a time, I can't
hold all history in memory, and I need an answer in milliseconds. Streaming needs an
incremental estimator, which is why Welford.

**"Did it improve fraud detection?"**
No. 2 of 60 in raw space, 0 of 60 in log space — both indistinguishable from zero. Fraud
in this dataset isn't an amount anomaly. My Class 2 result already showed that: the
z-score rule caught 11 of 492. The signal is in V1–V28, which is what Class 4 proved. You
can refine the yardstick all you like; it doesn't help if the thing you're measuring
doesn't separate the classes.

**"Then what did this class achieve?"** ← *the one that matters*
Three things. The infrastructure the proposal specified, with 43 tests and a measured cost
of 0.0082 ms per transaction. A calibration bug I didn't know I had — `z > 3` was firing
at `z ≈ 1.69`, and the global baseline from Class 6 turns out to be 14.3x off the
theoretical flag rate too, which I'd never checked. And independent confirmation of my
Class 2 finding from a completely different angle.

**"Your account IDs are fake. Isn't the whole thing meaningless?"**
The dataset has no account column — that's *why* Classes 2–6 used a global z-score. What
the synthetic data validates is the machinery and its cost, not a recall improvement, and
I say that in the diary rather than leaving it implied. I deliberately built a `random`
mode as the null case, where accounts are interchangeable and per-account should add
nothing, so I'm not only reporting the flattering configuration. Real validation needs
PaySim or IEEE-CIS, which have genuine account IDs. That's in my future work.

**"How do you know the bias is actually gone?"**
The flag ratio went flat. In raw space it drifted 2.06 → 1.30 as history grew from 50 to
1,000 transactions — the detector behaved differently depending on account age. In log
space it's 0.12 → 0.08, essentially constant. The level dropping could be a threshold
artefact. The flatness can't be.

**"Where does 0.135% come from?"**
The tail probability of a normal distribution beyond 3 standard deviations, one-sided.
It's what a `z > 3` rule *should* flag. Mine was flagging 3.98%, so I knew something was
wrong before I knew what.

**"Why 30 for MIN_HISTORY? Why alpha = 0.05?"**
Chosen by reasoning, not tuned — 30 is the conventional small-sample threshold, and
alpha = 0.05 gives an effective window of about 20 transactions. That's a genuine
limitation and it's listed as one. The Test B table actually gives me evidence to revisit
30 if I stayed in raw space; in log space it matters much less, which is part of the point.

**"Why SQLite?"**
It's a single file, no server, and the row size is fixed per account. Fine at this scale.
The limitation is that it's single-writer, so a multi-worker deployment would need Redis
or Postgres. I've noted it.

**"What's the velocity feature for?"**
Card testing — a stolen card gets validated with lots of tiny charges before the real
fraud. Every individual charge looks innocent by design, so no per-transaction amount
check can catch it. Counting transactions per account per hour can. In my test, 20 charges
of 3.00 in ten minutes scored z = −2.76 on amount, completely innocent, but
`txn_count_1h = 19` raised it to medium.

**"What happens if I delete the database?"**
Every account goes cold and falls back to the global baseline until it accumulates 30
transactions again. Nothing crashes — that's what the cold-start path is for.

---

## Two he might ask that you should just concede

**"Are these metrics on training data?"**
Yes, and that's a real weakness. The Isolation Forest never saw the labels — it's
unsupervised — but it was fit on the same rows I'm measuring on. A held-out split is in my
plan for the evaluation class.

**"Explain this line."** (points at random code)
If you don't know, say so and read it out loud. Working it out in front of him is fine.
Bluffing is not, and he will be able to tell.

---

## The closing line

> "The class delivered the per-entity baselining my proposal specified, found and fixed a
> calibration bug I didn't know I had, and confirmed that the amount feature is the
> limitation rather than the algorithm. It did not improve recall, and I'd rather report
> that than construct a comparison that flatters it."

That answer is stronger than a manufactured win, because it's the answer of someone who
tested their own work instead of hoping nobody would.
