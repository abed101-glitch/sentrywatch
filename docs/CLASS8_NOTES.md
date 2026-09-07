# Class 8 — Real-Time Alerting

**Deliverable:** real-time alerts for high-severity anomalies
Channel: **Telegram** (email code retained but off by default)

---

## What changed from Class 7

Class 7's Switch node routed by severity but nothing was connected to its outputs. Class 8
connects them — and uses the per-account context Class 7 produced.

**Before** (what a Class 6 alert would have said):

```
[!!] HIGH SEVERITY ANOMALY
Amount:  4500
z-score: 17.638
```

**After:**

```
[!!] HIGH SEVERITY

Amount:  4,500.00
Account: ACC-1042
Time:    2026-08-10 06:10 UTC

This account normally spends about 380.50.
This one is 11.8x that - 17.4 sigma above its own baseline.

- Isolation Forest flagged it (score -0.0812)
```

`17.4 sigma` is what a statistician needs. `11.8x this account's normal` is what the shop
owner needs. Class 7 made the second sentence possible.

---

## On the hosting question

Sending a Telegram message is an **outbound** HTTPS request from your machine to
`api.telegram.org` — like loading a webpage. Nothing needs to reach in. It works on
localhost with no tunnel, no ngrok, no public URL.

Hosting is only required for the reverse direction: a Telegram **Trigger**, where Telegram
must POST to your machine. Class 8 doesn't do that.

Worth one line in the report — it's a real architectural distinction between push and pull
integrations, not just a config detail.

---

## Setup (~2 minutes)

### 1. Create the bot

1. Open Telegram, message **@BotFather**, send `/newbot`, follow the prompts
2. Copy the token it gives you — looks like `8123456789:AAF...`
3. **Send any message to your new bot.** A bot cannot start a conversation with you, and
   skipping this makes step 4 return an empty list
4. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and copy
   `result[0].message.chat.id`

### 2. Configure

```bash
cd ~/Downloads/CSE299_Project
cp .env.example .env      # fill in the two Telegram values
set -a && source .env && set +a
```

### 3. Verify before touching n8n

```bash
cd src && python alerts.py --test
```

A Telegram message should arrive within seconds. Debug here, not inside n8n — a Python
traceback tells you far more than n8n's error panel.

To preview all three message shapes without sending anything:

```bash
python alerts.py
```

### 4. n8n

Import `n8n/class08_score_route_alert.json`. One placeholder to fix: the Google Sheet ID
on the **Log to Dashboard Sheet** node.

Sheet header row:

```
timestamp | severity | amount | account_id | account_warm | account_n | account_typical |
account_z | global_z | z_basis | txn_count_1h | ml_flagged | ml_score | reason |
alert_sent | suppressed | suppression_reason | dedup_key
```

### 5. Demo

```bash
export ALERT_COOLDOWN_SECONDS=20      # or the burst demo looks like nothing happened
cd src
python send_test_transactions.py --scenario single
python send_test_transactions.py --scenario burst
```

---

## The concept: alert fatigue

The sending code is one HTTP POST. The engineering problem is deciding **when not to send**.

At `contamination=0.0017` on 284,807 transactions, the model flags roughly 484 events. If
every flag became a phone notification you'd have muted the channel by lunch — and **an
alerting system nobody reads is worse than none**, because it costs money and creates a
false sense of coverage.

Three filters sit between "anomalous" and "phone buzzes":

**1. Severity threshold.** Only `high` and `medium` alert. `normal` is logged silently.

**2. Per-incident cooldown (5 min default).** The dedup key is
`account + severity + which signals fired` — deliberately **not** the transaction ID,
because then every event is unique and the cooldown never triggers. A card being tested
with 50 small charges in two minutes is **one incident**, not 50 alerts.

Measured: 6 events on one account → **1 alert, 5 suppressed**.

When the cooldown expires the next alert reports what it absorbed, so nothing disappears
silently:

> `+3 similar events suppressed during cooldown`

**3. Global hourly cap (20 default).** A circuit breaker for the failure that actually
hurts: model drift or a malformed feed makes *everything* look anomalous. Without the cap,
one bad afternoon permanently destroys trust in the channel. It trades a few missed alerts
for the channel staying credible — and fires with an explicit message telling you to check
the dashboard, so the cap is itself a signal.

Measured: 6 distinct accounts with the cap at 3 → **3 alerts, 3 blocked**.

**Suppressed ≠ discarded.** Every suppressed event still writes a row with
`suppressed=true` and the reason. Silent suppression you cannot audit is a debugging
nightmare, and it would corrupt the Class 10 recall numbers — you could not distinguish
"the model missed it" from "the throttle ate it."

---

## Design decisions worth defending

**Throttle state lives in Python, not n8n.** Each n8n execution is independent with no
natural place for cross-execution state. The scoring service is already a long-running
process holding the model and the baselines. Tradeoff: it's in-memory, so it resets on
restart and won't work across multiple workers — production answer is Redis. State this as
a limitation rather than leaving it to be found.

**Routing lives in n8n, sending lives in Python.** The Switch node makes the severity
policy *visible on the canvas*, where a non-developer could change it. Message formatting
and throttling stay in Python where they're testable. Policy in n8n, mechanism in Python.

**The message is prose, not a metrics dump.** When an alert wakes someone at 2am,
"z = 17.4" is not an answer. Every branch of the message maps to a sentence a human can act
on — including the cold-start case, which says *why* it fell back to the global baseline
rather than silently doing so.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `getUpdates` returns `{"ok":true,"result":[]}` | You never messaged the bot. Do that first. |
| Telegram 400 "can't parse entities" | An underscore or asterisk in your data breaks Markdown. Drop `parse_mode` in `alerts.py`. |
| `credentials not configured` | `.env` not sourced into the shell running uvicorn. |
| n8n `ECONNREFUSED 127.0.0.1:8000` | n8n in Docker — use `http://host.docker.internal:8000`. |
| Alerts stop after ~20 | Global cap working as designed. `curl localhost:8000/alert-stats`. |
| Sheet columns all `undefined` | The Extract Transaction node isn't wired in. |

---

## Carries into Class 9

Class 9 is the dashboard and landing page. The `AlertLog` sheet is already the data source,
and `/alert-stats` gives live throttle numbers. The most interesting panel will be
**alerts sent vs events suppressed** — that ratio is what shows the system is usable rather
than noisy.
