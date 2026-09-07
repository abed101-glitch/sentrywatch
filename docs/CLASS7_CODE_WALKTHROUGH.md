# Class 7 — explaining the code out loud

Six stops, ~8 minutes. Line numbers are exact. Open `src/baseline_store.py` and go.

The text in quotes is what you say. Don't read it word for word — read it a few times
tonight until it's yours, then say it in your own words.

---

# STOP 1 — the problem, before any code

**Say this before opening anything:**

> "Up to Class 6 my z-score was global. I compared every transaction to the average of all
> 284,807 rows, which is 93.27. So a 900 charge gets z = 3.25 — and it gets that same 3.25
> whether it came from a business that spends 900 every week, or a student who's never
> spent over 40. One yardstick for everybody. My proposal said I'd build per-account
> baselines and I hadn't. That's what this class is."

**If he asks "so why not just group by account?"**

> "That works in a notebook. But in the live pipeline transactions arrive one at a time, I
> can't hold all the history in memory, and I need an answer in milliseconds. So the
> statistics have to be updated incrementally."

That sentence is your bridge to the code. Now open the file.

---

# STOP 2 — `baseline_store.py`, lines 77–95 · the Welford core

Scroll to `def update`. **This is the most important thing you show him.**

```python
78        self.n += 1
79        delta = amount - self.mean
80        self.mean += delta / self.n
81        self.m2 += delta * (amount - self.mean)
```

**Say:**

> "This is Welford's algorithm. Four lines, and it keeps the exact running mean and
> variance while storing only three numbers — the count, the mean, and this M2 term. It
> never stores the transactions themselves.
>
> Line 79, delta is how far this transaction is from the current mean. Line 80 nudges
> the mean by delta divided by n — so the hundredth transaction moves the mean by a
> hundredth of its distance.
>
> Line 81 is the subtle one. Notice it uses `amount - self.mean` **again**, but `self.mean`
> was just updated on the line above. So the first delta is the distance from the *old*
> mean and this one is the distance from the *new* mean. Multiplying those two together is
> what accumulates the squared deviation correctly."

**Point at line 54, `variance`:**

> "Then variance is just M2 over n minus 1, whenever I need it."

### The follow-up he'll ask: "why not the normal formula?"

**Say:**

> "That's `E[x²] − E[x]²`, and I did try it first because it looks perfect for streaming —
> just a running sum and a running sum of squares. It's numerically broken.
>
> If your values are around a billion, then `E[x²]` is about 10¹⁸ and `E[x]²` is *also*
> about 10¹⁸. A float64 only holds about 16 significant digits. So you're subtracting two
> numbers that agree in the first 15 digits, and everything left over is rounding error.
> It's called catastrophic cancellation.
>
> I have a test for it — it returns **negative 128** when the true variance is 0.083.
> Variance can't be negative. Take the square root and you get NaN, and then every z-score
> in the system is broken."

**Then jump to `tests/test_baseline_store.py` line 47 and run it if you want the proof
on screen.**

---

# STOP 3 — lines 222–226 · why the order matters

```python
222    def observe(self, account_id, amount, ts, autocommit=True):
224        feats = self.features(account_id, amount, ts)     # score FIRST
225        st = self.load(account_id)
226        st.update(to_space(amount, self.log_space), ts)   # update SECOND
```

**Say:**

> "This is a bug I had and fixed. My first version updated the account and *then* scored
> the transaction. That means every transaction contributed to its own baseline — so a
> huge fraudulent charge would pull the mean up and partly hide itself before I measured it.
>
> Line 224 computes the features against the history as it was *before* this transaction.
> Only then, line 226, do I fold it in.
>
> The reason I care is that this failure is completely silent. Nothing crashes, no
> exception — the numbers are just quietly wrong. So there's a regression test at line 113
> that asserts the z-score matches the pre-transaction state exactly."

---

# STOP 4 — lines 14, 31–35 · the fix, and how I found it

Scroll to `LOG_SPACE` on line 31 and `to_space` on line 34.

**Say:**

> "This is the interesting part of the class. When I first ran it, per-account scoring
> flagged 994 transactions where the global one flagged 482. Double the false positives —
> and it caught 2 frauds out of 60 versus 0. With 60 frauds, 0 versus 2 is noise. So I'd
> doubled the alerts for nothing.
>
> My hypothesis was that transaction amounts are heavy-tailed. Skewness is 11.9 — most
> amounts are small, a few are enormous. If each account only has about 50 transactions of
> history, you probably never sample one of the huge ones, so the standard deviation looks
> smaller than it really is.
>
> And the z-score *divides* by that standard deviation. Too small a denominator means every
> z-score comes out inflated, so more of them cross the threshold."

**Give him the number:**

> "I measured it directly. At 30 transactions — which is my MIN_HISTORY, line 14 — the
> sample standard deviation is 56% of the true value. So my 'flag anything above z = 3'
> rule was actually firing at about **z = 1.69**. I'd specified one threshold and the code
> was behaving like a completely different one, and there was no way to see that by reading
> it."

**Then line 34:**

```python
34    def to_space(amount, log_space):
35        return math.log1p(max(amount, 0.0)) if log_space else amount
```

> "The fix is one line. The problem wasn't how much data I had, it was the scale.
> `log1p(amount)` of a lognormal variable is approximately **normal**, and the sample
> standard deviation of a normal variable is nearly unbiased even at small n. So the ratio
> goes from 0.562 to 1.000 at n=30 — the bias just disappears.
>
> `log1p` rather than `log` because the dataset has rows where Amount is zero, and log of
> zero is minus infinity.
>
> I made it a toggle rather than replacing the old path, so the before-and-after comparison
> is still reproducible."

---

# STOP 5 — lines 139–147 · the guard I added

Scroll to the `want = "log1p"` check at line 139, inside `_init_schema`.

**Say:**

> "Adding log space created a hazard. If I open a database that was written with raw
> amounts and read it as log space, the stored means get silently misinterpreted and every
> z-score is wrong — with nothing failing. So I record which space the database was built
> in and refuse to open it under a different one. The error message tells you how to fix it."

Short stop. It shows you thought about the failure mode, not just the feature.

---

# STOP 6 — `scoring_service.py` lines 83–95 · how it plugs in

```python
83    bf = BASELINES.observe(
84        account_id=account_id,
85        amount=float(data["Amount"]),
86        ts=float(data["Time"]),
87    )
89    severity, reasons = combine_severity(
90        account_z=bf["account_z"],
91        global_z=bf["global_z"],
92        txn_count_1h=bf["txn_count_1h"],
93        ml_flagged=bool(ml_flagged),
94        account_warm=bf["account_warm"],
95    )
```

**Say:**

> "In the service, the Isolation Forest from Class 6 still runs — that's `ml_flagged`. What
> Class 7 adds is `account_z` and `txn_count_1h` alongside it, and `combine_severity`
> merges them into one verdict.
>
> Note `global_z` is still there. That's deliberate. A brand new account has no history —
> with three transactions, one big purchase makes the standard deviation enormous and
> nothing ever looks unusual again. So below 30 observations the store refuses to give a
> per-account score and falls back to the global one from Class 6. That's the cold start
> problem, and it's why I added to Class 6 rather than replacing it."

**If he asks about `combine_severity` (line 268):**

> "It's a plain rule, not a second model. That's on purpose — when an alert wakes somebody
> at 2am, 'the ensemble said 0.83' is not an answer. Every branch in there maps to a
> sentence a human can read."

---

# The last thing you say

Don't let him ask it first. Volunteer it:

> "One thing I should say — this did **not** improve fraud detection. 2 out of 60 before,
> 0 out of 60 after. Both are basically zero.
>
> That's consistent with what I found in Class 2: fraud in this dataset isn't an amount
> anomaly. The z-score rule back then caught 11 out of 492. The real signal is in the V1
> to V28 PCA columns, which is what my Class 4 result showed.
>
> So what this class actually gave me is the infrastructure my proposal specified, and a
> calibration bug I didn't know I had — including that my Class 6 *global* baseline is 14
> times off the theoretical flag rate, which I'd never checked either. Refining the
> yardstick doesn't help when the thing you're measuring doesn't separate the classes."

**Also volunteer the synthetic accounts** before he spots it:

> "And I should flag — the dataset has no account column, which is exactly why I was using
> a global z-score for five classes. So the account IDs in my simulation are synthetic.
> What that validates is the machinery and its cost, not a recall improvement. I built a
> 'random' mode as the null case, where accounts are interchangeable and per-account should
> add nothing, so I'm not only showing the flattering configuration."

---

# If you blank

Three sentences that always work:

1. "Global baseline treats everyone the same. Per-account gives each account its own."
2. "Streaming means I can't store history, so Welford updates the mean and variance in three numbers."
3. "It flagged twice as much for no gain, I found out why, and the fix was taking the log."

And if he points at a line you don't recognise: **read it out loud and work through it.**
Thinking in front of him is fine. Bluffing isn't, and he'll know.
