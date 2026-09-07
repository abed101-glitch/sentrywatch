# SentryWatch — 5 minute script

11 slides. **Open the live URL two minutes before you start** so Render is awake.

Bold = say it roughly like this. Italic = what to do.

---

## PART 1 · Introduction and problem — 1 minute

### Slide 1 — SentryWatch  *(20s)*

> "SentryWatch is a real-time fraud detection service. A shop makes one HTTP call at
> checkout, and gets back approve, review or decline **before** the card is charged.
>
> It's built on 284,807 real transactions, it catches about a third of fraud, and it's
> covered by 96 automated tests. It's deployed — I'll show you the live site at the end."

*Don't read the stats. Let them sit there.*

### Slide 2 — Fraud is rare  *(40s)*

> "This is the number that shaped every decision in the project. Fraud is **0.173%** of
> transactions. That red sliver is the fraud — and I've drawn it eight times wider than
> reality, otherwise you literally couldn't see it.
>
> Which means a model that just says 'not fraud' every single time is **99.83% accurate**.
> And completely useless.
>
> So accuracy is the wrong measure. Everything I report from here is recall and
> precision, measured against real labels."

*Point at the red sliver, then at 99.83%. That contrast is the whole slide.*

---

## PART 2 · Technical — 3 to 3.5 minutes

### Slide 3 — What runs  *(30s)*

> "Four pieces. The shop's own checkout calls my scoring API. The API combines a machine
> learning model with a per-account baseline and a throttle. Every event is logged with
> its true label. Alerts go out on Telegram, one per incident.
>
> From the merchant's side it's four lines of code. They already have a checkout — I'm
> adding one check inside it."

*Point at the code block. Don't read it line by line.*

### Slide 4 — One yardstick per customer  *(45s)*

> "This is the core idea, and it's the part I'd defend most.
>
> Before Class 7, every amount was compared to **one global average** across all 284,807
> transactions. So a 900 charge scores identically whether it's a wholesaler or a student.
>
> After, every account carries its own running mean and variance. That same 900 charge is
> routine for one and a 53-sigma outlier for the other.
>
> And it's cheap. Welford's algorithm stores three numbers per account — the count, the
> running mean, and the sum of squares. **127 bytes.** No transaction is ever stored,
> so storage grows with customers, not with traffic."

*Point at n / mean / M² as you say "three numbers."*

### Slide 5 — Automated with n8n  *(35s)*

> "None of this is run by hand. In n8n, a schedule node fires every ten seconds and pulls
> the next real transaction. It's scored, routed by severity, checked against the
> throttle, and delivered to Telegram.
>
> The split matters: **policy lives in n8n**, where the Switch node makes the severity
> thresholds visible on a canvas — someone who doesn't write code could change them.
> **Mechanism lives in Python**, where it's covered by tests."

*If your n8n canvas is open, switch to it here for five seconds.*

### Slide 6 — LIVE DEMO  *(75s)*

*Click the Checkout button on the slide.*

> "This is hosted, not my laptop."

1. *Setup page* — **"Create account. That imports 35 orders, so it knows what normal looks like."**
2. *Checkout, Normal purchase* — **"APPROVE."**
3. *Unusually large* — **"REVIEW. 53 sigma against this account's own history."**
4. *Card-testing burst* — **"Twelve tiny charges. Each one innocent. It's the rate that gives it away."**
5. *Dashboard, Start live feed* — **"Recall and precision, computed live. Real Kaggle data with real fraud labels, so the dashboard is scoring itself."**

*If something fails, say what the error means and move on. Don't debug.*

### Slide 7 — Results  *(30s)*

> "34.1% of real fraud caught. 30.0% precision at the real base rate. Four false alarms
> per three thousand orders. Under a hundredth of a millisecond added to checkout.
>
> The confusion matrix is honest: 30 caught, **58 missed**. Most fraud still gets through.
>
> And note there are two precision figures. My demo stream over-samples fraud about
> 17 times, otherwise a demo runs 96 minutes between frauds. Precision depends on class
> balance; recall doesn't. So 30.0% is rescaled to the real rate — that's the one I quote."

*Say "58 missed" clearly. Volunteering the weakness is what makes the rest credible.*

### Slide 8 — The policy experiment  *(40s)*

> "Then I tested how alerts escalate. Classes 6 to 9 alerted on any single signal —
> 34% recall but only 17.7% precision.
>
> The obvious fix is to require two signals to agree. **That catches zero fraud.**
>
> Here's why, and it's just arithmetic from the previous week's output: the model flagged
> 34, the amount rule flagged 5, and together they flagged 38. So exactly one transaction
> triggered both — and it wasn't fraud.
>
> So instead I made the model necessary. Same recall, false alarms halved, precision up
> to 30%."

*Point at the code strip. This is your strongest slide.*

---

## PART 3 · Conclusion — 45 seconds

### Slide 9 — Four times wrong  *(30s)*

> "Stepping back — four separate times in this project, the change that sounded obviously
> right made things worse, and only a measurement told me.
>
> Applying machine learning gave worse recall than a single z-score. Per-account baselines
> didn't detect more fraud. Combining signals cut precision. Requiring consensus would
> have caught nothing.
>
> I didn't plan that as the theme. But it's the result I'd defend — the detector is
> almost a byproduct."

### Slide 10 — It's live  *(15s)*

> "It's deployed on Render from GitHub. Everything I showed runs from that URL — landing
> page, setup, checkout, dashboard. The code is public."

*Click a button if there's time.*

### Slide 11 — Thank you

> "Thank you. Happy to take questions."

---

## The five questions you'll get

**"Only 34%?"**
> "No, it isn't good enough to stop fraud, and I wouldn't claim it is. It's triage — it
> surfaces the most anomalous orders for a human to look at. What I'd defend is that the
> number is honest and reproducible."

**"Is this real data?"**
> "Kaggle Credit Card Fraud. 284,807 real transactions, 492 labelled frauds. Amounts,
> features and labels are all original. The account IDs are mine, because the dataset has
> no account column, and I say so on the dashboard."

**"Why two precision numbers?"**
> "Precision depends on the class balance, and my demo stream over-samples fraud about 17
> times so a demo isn't 96 minutes long. 30.0% is rescaled to the real 0.173% rate.
> Recall isn't affected by base rate, so 34.1% carries over unchanged."

**"Could a real business use this?"**
> "The pipeline, yes — one POST from their checkout. The model, no. V1 to V28 are PCA
> components from an anonymised research dataset; no merchant can compute them. It would
> have to be retrained on features they actually have — device, IP, card BIN, account
> history. The Class 7 baseline layer transfers as-is."

**"What would you do next?"**
> "A held-out test split. Everything so far is measured on the rows the model was fit on.
> It's unsupervised so it never saw the labels, but a proper split would be stronger."

---

## Timing check

| Part | Slides | Target |
|---|---|---|
| Introduction and problem | 1–2 | **1:00** |
| Technical and implementation | 3–8 *(demo at 6)* | **3:35** |
| Conclusion | 9–11 | **0:45** |

If you're running long, cut slide 3 to fifteen seconds and trim the burst step in the demo.
