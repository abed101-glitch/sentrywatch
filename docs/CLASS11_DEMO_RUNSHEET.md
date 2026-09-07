# Class 11 — demo run sheet

Print this. Follow it top to bottom. Nothing here is improvised.

---

## 20 minutes before

Three terminals. Do this before anyone is watching.

```bash
# terminal 1 — the service
cd ~/Downloads/CSE299_Project
rm -f data/baselines.db data/events.db      # clean slate
bash run_service.sh

# terminal 2 — n8n
npx n8n                                     # http://localhost:5678

# terminal 3 — checks
curl http://127.0.0.1:8000/health
```

`/health` must show `"require_ml": true`. If it doesn't, the service is running old
code — kill it and restart.

In n8n: import `n8n/class09_automated_pipeline.json`, open **Send Telegram Alert**,
re-select the credential (the import writes `REPLACE_ME`), then **Activate**.

**Then leave it running for four minutes.** `MIN_HISTORY = 30`, so until each account
has 30 transactions everything says "learning" and scores against the global baseline —
the Class 7 work is invisible. Four minutes of warm-up makes the `Typical` column fill in.

Open in tabs, in this order:

1. `http://127.0.0.1:8000/`  ← **start here** (landing page)
2. `http://127.0.0.1:8000/setup`
3. `http://127.0.0.1:8000/checkout`
4. n8n canvas
5. `http://127.0.0.1:8000/dashboard`
6. Telegram
7. VS Code with `src/` open

---

## The demo — 11 minutes

### 1. Walk the client journey *(3 min)*

**Landing page** — `/`

> "This is what a business owner would find. It says what the product does."

Scroll to the form, then click **Set it up yourself**.

**Setup page** — `/setup`

> "Four steps. Name the business, and import whatever order history they already have."

Leave the defaults, click **Create account**.

> "That just wrote a real namespace into the baseline store and ran 35 orders through
> the same function the live pipeline uses. Step two is the whole integration —
> one HTTP call in their checkout handler."

Point at the code snippet. Then click **Open the checkout**.

**Checkout** — `/checkout`

> "This is the live product. When a customer pays, the merchant's server calls my
> service and **waits** for a verdict before the payment goes through."

The account is already warm from setup, so go straight to **Normal purchase** → APPROVE. Then **Unusually large** → REVIEW.

> "Same 9,800 charge would be routine for a business account and alarming for this
> one. That's the Class 7 work — it's judged against its own history, not a global
> average."

Then **Card-testing burst**. Twelve charges of one or two pounds.

> "Every one of those looks innocent on its own. It's the rate that gives it away."

Point at the grey note at the bottom of the page.

> "And it's honest about what isn't running. The model needs V1–V28, which no real
> merchant can compute. Only the rule layer scores this page. I'll come back to that."

### 2. Move to the n8n canvas *(1 min)*

> "This is running right now. I'm not going to type anything. It fires every ten
> seconds on its own."

Point at the nodes left to right. Say what each does in one sentence. Stop on
**Route by Severity** — three outputs, and normal events still get logged.

> "The normal ones matter. Without them I have no denominator for precision."

### 3. Switch to the dashboard *(2 min)*

Let a few rows land. Point at the purple cards.

> "Recall and precision, computed live. Not estimated — the real fraud label comes
> through with each transaction, so the dashboard is scoring itself."

Point at the **Real?** column. Wait for a `FRAUD` row.

If it was caught: *"That's a true positive."*
If it was missed: **say so.** *"That one got past it. Recall is about a third — most fraud
still gets through, and I'd rather show you that than hide it."*

### 4. Show where the numbers come from *(2 min)*

```bash
cd src && python evaluate_replay.py --n 3000
```

While it runs, say what it's doing. When the table appears, go straight to the
**escalation policy** block.

> "Three policies on the same data. Requiring two signals catches zero fraud."

### 5. The Class 10 finding *(2 min)*

> "Class 9 measured that combining signals made precision worse. The obvious fix is to
> require two signals to agree. I checked what that would flag before writing it — the
> model flagged 34, the amount rule flagged 5, together 38. So only one transaction
> triggered both, and it wasn't fraud. Consensus would have caught nothing.
>
> So instead the model is necessary and the other signals only raise priority. Recall
> stays at 34.1%, false alarms halve."

### 6. Telegram *(1 min)*

Show a real alert on your phone. Point at the account's learned baseline in the message.

> "It quotes what's normal *for this account*. That's the Class 7 work."

---

## If something breaks

| Problem | Do this |
|---|---|
| Dashboard says "service unreachable" | Service died. `bash run_service.sh` in terminal 1. Keep talking. |
| n8n node shows red | Click it, read the error out loud, say what it means. This reads as competence. |
| No Telegram message | Expected — the throttle suppresses repeats. Show the `Suppressed` node and explain the cooldown. |
| Everything says "learning" | Not warmed up. Explain cold start: under 30 transactions it falls back to the global baseline. |
| Nothing at all works | `python evaluate_replay.py --n 3000` needs only Python. Fall back to it. |
| Checkout says "could not reach the service" | The service is down. Restart it; the page recovers on the next click. |
| Checkout always says APPROVE | Account isn't warm. Click **Teach it a baseline** first. |
| Setup says "could not reach the service" | Service is down. Restart; the page retries on the next click. |

**Do not debug live for more than 30 seconds.** Move to the next thing and come back.

---

## The five questions you will get

**"Is this real data?"**
Yes. Kaggle Credit Card Fraud — 284,807 real transactions, 492 labelled frauds. Amounts,
V1–V28 and the labels are original. Account IDs are mine, because the dataset has no
account column, and frauds are over-sampled so a demo doesn't run 96 minutes between them.

**"Why is precision two different numbers?"**
Precision depends on the class balance and my stream over-samples fraud about 17×. The
figure I quote — 30.0% — is rescaled to the real 0.173% rate. Recall isn't affected by
base rate, so 34.1% carries over unchanged.

**"Only 34%? That's not very good."**
No, it isn't. 58 of 88 frauds got through. This is triage — it surfaces the most anomalous
transactions for review. What I'd defend is that the number is honest and reproducible.

**"How would a customer put transactions in?"**
Their checkout handler makes one POST and reads the verdict — that's the snippet on the
setup page, and the checkout demo runs exactly it. No CSV, no import. Importing history
is a one-time thing at onboarding so the baseline isn't cold on day one; after that it
learns from live traffic.

**"Is the setup page real or a mockup?"**
Real. Creating an account writes a namespace into `baselines.db`, and importing history
runs those orders through the same `observe()` call the live pipeline uses. The one
shortcut is that the imported orders are generated around the typical value you type,
because I don't have a real merchant's order file — that's the only thing standing in.

**"Could a business actually use this?"**
The pipeline, yes — one POST from their checkout. The model, no. V1–V28 are PCA components
from an anonymised dataset; nobody can compute them from a live transaction. It would be
retrained on features a merchant actually has. The Class 7 baseline layer transfers as-is.

**"What would you do next?"**
A held-out test split. Everything so far is measured on the rows the model was fit on —
unsupervised, so it never saw the labels, but a proper split would be stronger.

---

## Files, if asked

| Ask | Open |
|---|---|
| "show me the code" | `src/baseline_store.py` — Welford's at line ~77, policy at ~271 |
| "show me the database" | `sqlite3 -header -column data/events.db`, then the confusion-matrix query |
| "show me the tests" | `cd tests && python test_baseline_store.py` — 66 pass |
| "how does the dashboard connect" | `dashboard.html:126` → `scoring_service.py:229` → `event_log.py:126` |

---

## Last thing

Close on the sentence from the final slide. Say it slowly:

> **The detector is a byproduct. The measurements are the project.**
