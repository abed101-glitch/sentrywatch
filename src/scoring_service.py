# Class 6-8 - scoring service with per-account baselines and alerting

import os
import math
import time
import random
import threading
import joblib
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel, ConfigDict

from fastapi.responses import HTMLResponse

import alerts as alerts_mod
from alerts import dispatch_alert, format_alert, make_dedup_key, throttle
import baseline_store
from baseline_store import BaselineStore, combine_severity
from event_log import EventLog
from replay import Replay

app = FastAPI(title="Fraud Scoring + Alerting Service")
EVENTS = EventLog()
REPLAY = Replay()

HERE = Path(__file__).resolve().parent


def _find_model() -> Path:
    env = os.getenv("MODEL_PATH")
    candidates = ([Path(env)] if env else []) + [
        HERE.parent / "data" / "model.joblib",
        HERE / "model.joblib",
        Path.home() / "model.joblib",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise SystemExit(
        "model.joblib not found. Looked in:\n  "
        + "\n  ".join(str(c) for c in candidates)
        + "\n\nEither put it in data/, or set MODEL_PATH, or regenerate it:\n"
        "    cd src && python train_model.py ../data/creditcard.csv"
    )


MODEL_PATH = _find_model()
print(f"[scoring_service] loading model from {MODEL_PATH}")
artifact = joblib.load(MODEL_PATH)
MODEL = artifact["model"]
FEATURE_COLS = artifact["feature_cols"]
MEAN_AMOUNT = artifact["mean_amount"]
STD_AMOUNT = artifact["std_amount"]


BASELINES = BaselineStore(
    db_path=os.getenv("BASELINE_DB", str(HERE.parent / "data" / "baselines.db")),
    global_mean=MEAN_AMOUNT,
    global_std=STD_AMOUNT,
)


ALERTABLE = set(
    os.getenv("ALERTABLE_SEVERITIES", "high,medium").split(",")
)


class Transaction(BaseModel):
    model_config = ConfigDict(extra="allow")  # tolerate extra n8n fields
    Time: float
    Amount: float
    true_fraud: int | None = None
    


class ScoredTransaction(BaseModel):
    """What n8n posts to /alert: the original tx plus the score result."""
    model_config = ConfigDict(extra="allow")
    severity: str
    reason: str = ""
    z_score: float = 0.0
    ml_flagged: bool = False
    ml_score: float = 0.0


@app.get("/health")
def health():
    return {
        "status": "ok",
        "alertable": sorted(ALERTABLE),
        "policy": {
            "require_ml": baseline_store.REQUIRE_ML,
            "escalate_at": baseline_store.ESCALATE_AT,
            "description": ("model must flag before anything alerts; other "
                            "signals only raise it to high"
                            if baseline_store.REQUIRE_ML else
                            f"any {baseline_store.ESCALATE_AT} signal(s) alert"),
        },
    }


def _score(data: dict) -> dict:
    """
    Class 6 gave every transaction the same yardstick: a global z-score over all
    284,807 training rows. Class 7 adds the account's own history, which is the
    comparison that actually carries meaning, plus velocity — a signal no
    single-transaction check can see.

    The global z-score is still computed and still used, because a brand new
    account has no history to compare against.
    """
    row = {}
    for col in FEATURE_COLS:
        if col == "hour":
            row["hour"] = (data["Time"] / 3600) % 24
        else:
            row[col] = data.get(col, 0.0)

    X = pd.DataFrame([row])[FEATURE_COLS]

    ml_raw = MODEL.predict(X)[0]              # -1 anomaly, 1 normal
    ml_score = MODEL.decision_function(X)[0]  # lower = more anomalous
    ml_flagged = ml_raw == -1

    
    account_id = str(data.get("account_id") or data.get("user_id") or "unknown")
    bf = BASELINES.observe(
        account_id=account_id,
        amount=float(data["Amount"]),
        ts=float(data["Time"]),
    )

    severity, reasons = combine_severity(
        account_z=bf["account_z"],
        global_z=bf["global_z"],
        txn_count_1h=bf["txn_count_1h"],
        ml_flagged=bool(ml_flagged),
        account_warm=bf["account_warm"],
    )
    if ml_flagged:
        reasons = [r if "isolation forest" not in r
                   else f"isolation forest anomaly score {ml_score:.3f}"
                   for r in reasons]

    return {
        "severity": severity,
        
        "z_score": round(float(bf["account_z"] if bf["account_warm"]
                               else bf["global_z"]), 3),
        "z_basis": "account" if bf["account_warm"] else "global",
        "ml_flagged": bool(ml_flagged),
        "ml_score": round(float(ml_score), 4),
        "reason": "; ".join(reasons) if reasons else "no anomaly detected",
       
        "account_id": account_id,
        "account_z": bf["account_z"],
        "global_z": bf["global_z"],
        "account_mean": bf["account_mean"],
        "account_std": bf["account_std"],
        "account_n": bf["account_n"],
        "account_warm": bf["account_warm"],
        "txn_count_1h": bf["txn_count_1h"],
        "seconds_since_last": bf["seconds_since_last"],
        "baseline_drift": bf["baseline_drift"],
    }


def _kaggle_score(amount: float, ts: float) -> dict:
    """
    Actually run the trained isolation forest against a real checkout order.

    A live checkout order only has an Amount and a timestamp - it has none
    of the V1-V28 PCA features the model was trained on, because those come
    from the original bank data behind credit.csv, not from a storefront.
    So this finds the closest real transaction in credit.csv by amount and
    borrows ITS feature vector, then scores that real, dataset-sourced
    vector through the same model used everywhere else in this pipeline.
    That is the actual "compare against credit.csv" step.
    """
    match = REPLAY.nearest(amount)
    row = {c: match[c] for c in FEATURE_COLS if c != "hour"}
    row["hour"] = (ts / 3600) % 24
    X = pd.DataFrame([row])[FEATURE_COLS]

    ml_raw = MODEL.predict(X)[0]                      # -1 anomaly, 1 normal
    ml_score = float(MODEL.decision_function(X)[0])    # lower = more anomalous

    # decision_function has no fixed range; squash it into a 0-100 risk score.
    risk_pct = round(100 / (1 + math.exp(ml_score * 12)), 1)

    return {
        "ml_flagged": bool(ml_raw == -1),
        "ml_score": round(ml_score, 4),
        "risk_pct": risk_pct,
        "matched_amount": round(float(match["Amount"]), 2),
        "matched_was_fraud": bool(match["true_fraud"]),
        "rows_compared": len(REPLAY._rows),
    }


@app.post("/score")
def score(tx: Transaction):
    """
    Class 6 behaviour, plus pre-built alert text.

    n8n can drop {{ $json.alert_body }} straight into a Telegram node
    instead of building the message with an expression.
    """
    data = tx.model_dump()
    result = _score(data)

    msg = format_alert(result, data)
    result["should_alert"] = result["severity"] in ALERTABLE
    result["dedup_key"] = make_dedup_key(result, data)
    result["alert_title"] = msg["email_subject"]
    result["alert_body"] = msg["telegram_text"]
    result["alert_html"] = msg["email_html"]
    return result


@app.post("/alert")
def alert(scored: ScoredTransaction):
    """
    Send the alert for an already-scored transaction.

    n8n's Switch node decides WHETHER to call this; the service decides
    whether the alert is a duplicate worth suppressing.
    """
    data = scored.model_dump()
    result = {
        "severity": data["severity"],
        "reason": data.get("reason", ""),
        "z_score": data.get("z_score", 0.0),
        "ml_flagged": data.get("ml_flagged", False),
        "ml_score": data.get("ml_score", 0.0),
    }

    if result["severity"] not in ALERTABLE:
        return {"sent": False, "suppressed": True,
                "suppression_reason": f"severity '{result['severity']}' is not alertable"}

    return dispatch_alert(result, data)


@app.post("/score-and-alert")
def score_and_alert(tx: Transaction, deliver: bool = True):
    data = tx.model_dump()
    result = _score(data)
    result["Amount"] = data.get("Amount")
    result["true_fraud"] = data.get("true_fraud")

    if result["severity"] not in ALERTABLE:
        alert = {"sent": False, "would_send": False, "suppressed": False,
                 "suppression_reason": "severity below threshold", "message": None}
    else:
        alert = dispatch_alert(result, data, deliver=deliver)

    EVENTS.record(result, alert)
    return {**result, "alert": alert}


@app.get("/next-transaction")
def next_transaction():
    return REPLAY.next()


@app.get("/replay-stats")
def replay_stats():
    return REPLAY.stats()


@app.post("/replay/reset")
def replay_reset():
    REPLAY.reset()
    return {"reset": True, "arrival_clock": REPLAY.stats()["arrival_clock"],
            "note": "row position rewound; arrival clock keeps moving forward "
                    "so the velocity window stays correct"}


# Class 11
@app.get("/", response_class=HTMLResponse)
def landing():
    return (HERE.parent / "landing" / "index.html").read_text()


@app.get("/setup", response_class=HTMLResponse)
def setup_page():
    return (HERE.parent / "landing" / "setup.html").read_text()


class Onboard(BaseModel):
    model_config = ConfigDict(extra="allow")
    business: str
    typical_order: float = 45.0
    backfill: int = 0
    source: str = "kaggle"          # kaggle | synthetic


@app.post("/onboard")
def onboard(req: Onboard):
    slug = "".join(c for c in req.business.upper()
                   if c.isalnum() and c.isascii())[:10] or "MERCHANT"
    account_id = f"{slug}-001"
    n = max(0, min(int(req.backfill), 2000))

    if n and req.source == "synthetic":
        amounts = [max(1.0, random.gauss(req.typical_order, req.typical_order * 0.28))
                   for _ in range(n)]
        note = ("Backfill generated around the typical order value you gave. "
                "Use the Kaggle option to seed from real transaction amounts instead.")
    elif n:
        pool = real_amounts()
        amounts = random.Random(42).sample(pool, min(n, len(pool)))
        note = (f"Seeded from {len(pool):,} real transaction amounts in the Kaggle "
                "Credit Card Fraud dataset - the same rows the model was trained on. "
                "Fraudulent rows are excluded, because a baseline is what NORMAL "
                "looks like. Nothing is generated.")
    else:
        amounts, note = [], ("No history imported - the account is cold and will fall "
                             "back to the global baseline until it has "
                             f"{baseline_store.MIN_HISTORY} orders.")

    seed_account(account_id, amounts)
    return {**baseline_summary(account_id, amounts),
            "business": req.business, "source": req.source if n else "none",
            "note": note}


@app.post("/onboard/upload")
async def onboard_upload(file: UploadFile = File(...), business: str = Form("Merchant")):
    """Seed a baseline from the merchant's own order history."""
    slug = "".join(c for c in business.upper()
                   if c.isalnum() and c.isascii())[:10] or "MERCHANT"
    account_id = f"{slug}-001"

    raw = (await file.read(4_000_000)).decode("utf-8", errors="replace")
    import csv as _csv, io as _io
    rdr = _csv.DictReader(_io.StringIO(raw))
    if not rdr.fieldnames:
        return {"ok": False, "error": "that file has no header row"}

    wanted = ("amount", "total", "value", "price", "sum", "grand_total")
    col = next((c for c in rdr.fieldnames
                if c and c.strip().lower() in wanted), None)
    if col is None:
        return {"ok": False,
                "error": "no amount column found - expected one named "
                         "Amount, Total, Value or Price. Found: "
                         + ", ".join(f for f in rdr.fieldnames if f)[:120]}

    amounts, skipped = [], 0
    for row in rdr:
        try:
            v = float(str(row[col]).replace(",", "").replace("$", "").strip())
            if v > 0:
                amounts.append(v)
        except (TypeError, ValueError):
            skipped += 1
        if len(amounts) >= 2000:
            break

    if not amounts:
        return {"ok": False, "error": f"no usable numbers in column '{col}'"}

    seed_account(account_id, amounts)
    return {"ok": True, **baseline_summary(account_id, amounts),
            "business": business, "source": "upload", "column": col,
            "skipped": skipped,
            "note": (f"Seeded from {len(amounts):,} rows of your own history "
                     f"(column '{col}'). Every future order on this account is "
                     "scored against these numbers.")}


@app.get("/checkout", response_class=HTMLResponse)
def checkout():
    return (Path(__file__).resolve().parent.parent / "landing" / "checkout.html").read_text()


@app.post("/score-checkout")
def score_checkout(tx: Transaction, alert: bool = True):
    """
    What a merchant's checkout calls, on Pay Now.

    Flow: capture the order -> run it through the trained isolation forest
    (scored against a real feature vector pulled from credit.csv) -> combine
    that with the account's own baseline (also seeded from real Kaggle
    amounts) -> only once that final verdict exists, send it to Telegram.
    """
    data = tx.model_dump()
    account_id = str(data.get("account_id") or "unknown")
    amount = float(data["Amount"])
    ts = data.get("Time") or time.time()

    # A cold account has nothing meaningful to be compared against, so seed it
    # from the real dataset first. load() is read-only - checking warmth must
    # not itself add a data point.
    seeded = 0
    if not BASELINES.load(account_id).is_warm:
        pool = real_amounts()
        seeded = seed_account(
            account_id,
            random.Random(42).sample(pool, min(baseline_store.MIN_HISTORY * 4,
                                               len(pool))))

    bf = BASELINES.observe(account_id, amount, ts)

    # Step 2-5: activate the Kaggle-trained model and compare against credit.csv.
    model_error = None
    try:
        kaggle = _kaggle_score(amount, ts)
    except Exception as exc:
        model_error = f"{type(exc).__name__}: {exc}"
        kaggle = {"ml_flagged": False, "ml_score": 0.0, "risk_pct": None,
                  "matched_amount": None, "matched_was_fraud": None,
                  "rows_compared": 0}

    severity, reasons = combine_severity(
        account_z=bf["account_z"], global_z=bf["global_z"],
        txn_count_1h=bf["txn_count_1h"], ml_flagged=kaggle["ml_flagged"],
        account_warm=bf["account_warm"], min_signals=1, require_ml=False,
    )
    if model_error:
        # Never report "safe" when the model step itself failed.
        severity = "medium" if severity == "normal" else severity
        reasons = reasons + [f"model comparison failed - {model_error}"]

    verdict = {"high": "DECLINE", "medium": "REVIEW", "normal": "APPROVE"}[severity]
    # The header has to match the verdict. Calling a REVIEW "FRAUD DETECTED"
    # next to a 3% risk score reads as if the service is arguing with itself.
    fraud_result = {"DECLINE": "FRAUD", "REVIEW": "SUSPICIOUS",
                    "APPROVE": "NOT FRAUD"}[verdict]
    headline = {"DECLINE": "🚨 FRAUD DETECTED",
                "REVIEW": "⚠️ FLAGGED FOR REVIEW",
                "APPROVE": "✅ TRANSACTION SAFE"}[verdict]

    result = {
        "severity": severity,
        "reason": "; ".join(reasons) or "nothing unusual about this transaction",
        "z_score": round(float(bf["account_z"] or 0.0), 3),
        "z_basis": "account" if bf["account_warm"] else "global",
        "ml_flagged": kaggle["ml_flagged"], "ml_score": kaggle["ml_score"],
        "account_id": account_id,
        "account_z": bf["account_z"], "global_z": bf["global_z"],
        "account_mean": bf["account_mean"], "account_std": bf["account_std"],
        "account_n": bf["account_n"], "account_warm": bf["account_warm"],
        "txn_count_1h": bf["txn_count_1h"],
        "baseline_drift": bf["baseline_drift"], "Amount": amount,
    }

    # Step 6-7: only now, with a final result in hand, tell Telegram.
    if not alert:
        outcome = {"sent": False, "would_send": False, "suppressed": False,
                   "suppression_reason": "alerts disabled for this request",
                   "message": None}
    elif model_error:
        outcome = {"sent": False, "would_send": False, "suppressed": False,
                   "suppression_reason": "model comparison failed - not sending a "
                                          "result until it can be trusted",
                   "message": None}
    else:
        risk = (f"{kaggle['risk_pct']}%  (model only - the verdict also uses "
                "this account's baseline and velocity)"
                if kaggle["risk_pct"] is not None else "n/a")
        matched = (f"${kaggle['matched_amount']:,.2f}"
                   + (" (a real fraud case)" if kaggle["matched_was_fraud"] else " (a real normal case)")
                   if kaggle["matched_amount"] is not None else "n/a")
        typical = (f"${bf['account_mean']:,.2f}" if bf.get("account_mean")
                   else "still learning")
        text = (
            f"{headline}\n\n"
            f"Amount: ${amount:,.2f}\n"
            f"Account: {account_id}\n"
            f"Item/note: {data.get('item') or 'n/a'}\n"
            f"Status: {fraud_result} ({verdict})\n"
            f"Risk score: {risk}\n"
            f"Reason: {result['reason']}\n"
            f"Typical for this account: {typical}\n"
            f"Compared against (credit.csv): {matched}\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        tg = alerts_mod.send_telegram(text)
        outcome = {
            "sent": bool(tg.get("ok")), "would_send": True, "suppressed": False,
            "delivery_error": None if tg.get("ok") else tg.get("error"),
            "message": text, "delivered_by": "service",
        }

    EVENTS.record(result, outcome)

    return {
        "verdict": verdict, "severity": severity, "reasons": reasons,
        "fraud_result": fraud_result,
        "account_id": account_id, "amount": amount,
        "account_mean": bf["account_mean"], "account_std": bf["account_std"],
        "account_n": bf["account_n"], "account_warm": bf["account_warm"],
        "account_z": bf["account_z"], "global_z": bf["global_z"],
        "txn_count_1h": bf["txn_count_1h"],
        "baseline": {
            "source": "Kaggle Credit Card Fraud dataset (credit.csv), non-fraud rows only",
            "seeded_now": seeded,
            "orders_behind_it": bf["account_n"],
        },
        "model": {
            "scored": model_error is None,
            "flagged": kaggle["ml_flagged"],
            "risk_pct": kaggle["risk_pct"],
            "matched_amount": kaggle["matched_amount"],
            "matched_was_fraud": kaggle["matched_was_fraud"],
            "rows_compared": kaggle["rows_compared"],
            "error": model_error,
        },
        "alert": {
            "attempted": bool(alert and not model_error),
            "sent": bool(outcome.get("sent")),
            "suppressed": bool(outcome.get("suppressed")),
            "reason": (outcome.get("suppression_reason")
                       or outcome.get("delivery_error")),
            "message": outcome.get("message"),
        },
        "model_scored": model_error is None,
        "model_note": ("The isolation forest is run for real: it's scored against a "
                       "feature vector borrowed from the closest-amount real "
                       "transaction in credit.csv, since a live checkout order has "
                       "no V1-V28 PCA columns of its own. Combined with the account's "
                       "own baseline (also seeded from real Kaggle amounts) and "
                       "velocity to reach the final verdict."
                       if model_error is None else
                       f"Model comparison failed, so this was NOT marked safe: {model_error}"),
    }


# Class 11
FEED = {"on": False, "thread": None, "sent": 0, "interval": 1.0}


def _feed_loop():
    while FEED["on"]:
        try:
            tx = REPLAY.next()
            result = _score(tx)
            result["Amount"] = tx.get("Amount")
            result["true_fraud"] = tx.get("true_fraud")
            if result["severity"] not in ALERTABLE:
                alert = {"sent": False, "would_send": False, "suppressed": False,
                         "suppression_reason": "severity below threshold",
                         "message": None}
            else:
                alert = dispatch_alert(result, tx, deliver=True)
            EVENTS.record(result, alert)
            FEED["sent"] += 1
        except Exception as exc:
            print(f"[feed] {type(exc).__name__}: {exc}")
        time.sleep(FEED["interval"])


@app.post("/feed/start")
def feed_start(interval: float = 1.0, warm: bool = True):
    if FEED["on"]:
        return {"running": True, "already": True, "scored": FEED["sent"]}

    warmed = 0
    if warm:
        # Without this every account is cold for its first 30 events, the z-score
        # falls back to the global baseline, and the dashboard shows 30 rows of
        # "learning" before anything interesting can happen.
        pool = real_amounts()
        rng = random.Random(7)
        for i in range(REPLAY.n_accounts):
            acct = f"CARD-{i:02d}"
            seed_account(acct, rng.sample(pool, baseline_store.MIN_HISTORY * 2))
            warmed += 1

    FEED["interval"] = max(0.2, min(interval, 10.0))
    FEED["on"] = True
    t = threading.Thread(target=_feed_loop, daemon=True)
    FEED["thread"] = t
    t.start()
    return {"running": True, "interval": FEED["interval"], "warmed_accounts": warmed,
            "alerts": alerts_mod.alert_config(),
            "note": ("replaying real transactions through the full scoring path"
                     + (f"; {warmed} accounts pre-warmed from real history" if warmed
                        else "; accounts start cold"))}


@app.post("/feed/stop")
def feed_stop():
    FEED["on"] = False
    return {"running": False, "scored": FEED["sent"]}


# Class 11
class AlertConfig(BaseModel):
    chat_id: str = ""


# Class 11 - seed a baseline from the REAL dataset instead of generating numbers
_REAL_AMOUNTS: list[float] = []


def real_amounts() -> list[float]:
    global _REAL_AMOUNTS
    if not _REAL_AMOUNTS:
        import csv as _csv
        from replay import DEFAULT_CSV
        vals = []
        with open(DEFAULT_CSV, newline="") as f:
            for row in _csv.DictReader(f):
                if row.get("Class") == "1":
                    continue          # a baseline is what NORMAL looks like
                try:
                    vals.append(float(row["Amount"]))
                except (TypeError, ValueError):
                    continue
        _REAL_AMOUNTS = vals
    return _REAL_AMOUNTS


def seed_account(account_id: str, amounts: list[float]) -> int:
    now = time.time()
    spread = 86400.0 * 30
    n = len(amounts)
    for i, amt in enumerate(amounts):
        BASELINES.observe(account_id, max(0.01, float(amt)),
                          now - spread + (i * spread / max(n, 1)), autocommit=False)
    BASELINES.commit()
    return n


def baseline_summary(account_id: str, amounts: list[float]) -> dict:
    import statistics as _st
    warm = len(amounts) >= baseline_store.MIN_HISTORY
    return {
        "account_id": account_id,
        "seeded": len(amounts),
        "warm": warm,
        "min_history": baseline_store.MIN_HISTORY,
        "still_needed": max(0, baseline_store.MIN_HISTORY - len(amounts)),
        "typical": round(_st.median(amounts), 2) if amounts else None,
        "mean": round(_st.mean(amounts), 2) if amounts else None,
        "largest": round(max(amounts), 2) if amounts else None,
        "endpoint": "/score-checkout",
        "policy": ("model must flag before anything alerts"
                   if baseline_store.REQUIRE_ML else "rule layer"),
    }


@app.get("/telegram/link")
def telegram_link():
    """
    Give the browser a one-time deep link. The visitor taps it, Telegram opens,
    they press Start, and their chat id arrives here - nothing to look up.
    """
    who = alerts_mod.bot_username()
    if not who.get("ok"):
        return {"ok": False, "error": who.get("error")}
    code = f"sw{random.randint(10**9, 10**10 - 1)}"
    return {
        "ok": True,
        "code": code,
        "bot": who["username"],
        "url": f"https://t.me/{who['username']}?start={code}",
    }


@app.get("/telegram/status")
def telegram_status(code: str):
    r = alerts_mod.find_start(code)
    if not r.get("ok"):
        return {"connected": False, "error": r.get("error")}
    if not r.get("found"):
        return {"connected": False, "waiting": True}

    alerts_mod.set_chat_id(r["chat_id"])
    sent = alerts_mod.send_telegram(
        f"*Connected.*\nHello {r['name']} - SentryWatch will send fraud alerts here.\n"
        "Each one quotes what is normal for that account, and repeats inside the "
        "same incident are rolled up."
    )
    return {"connected": True, "name": r["name"],
            "greeted": bool(sent.get("ok")), **alerts_mod.alert_config()}


@app.get("/alert-config")
def alert_config_get():
    return alerts_mod.alert_config()


@app.post("/alert-config")
def alert_config_set(cfg: AlertConfig):
    alerts_mod.set_chat_id(cfg.chat_id)
    return alerts_mod.alert_config()


@app.post("/alert-test")
def alert_test():
    cfg = alerts_mod.alert_config()
    if not cfg["can_deliver"]:
        return {"sent": False, **cfg,
                "error": ("bot token missing on the server" if not cfg["token_configured"]
                          else "no chat id set")}
    r = alerts_mod.send_telegram(
        "*SentryWatch is connected.*\n"
        "This is a test message from the live service. "
        "Real alerts will quote the account's own learned baseline."
    )
    return {"sent": bool(r.get("ok")), **cfg,
            "error": None if r.get("ok") else r.get("error"),
            "detail": r}


@app.get("/feed/status")
def feed_status():
    return {"running": FEED["on"], "scored": FEED["sent"],
            "interval": FEED["interval"]}


@app.get("/events")
def events(limit: int = 40):
    return {"summary": EVENTS.summary(), "events": EVENTS.recent(limit)}


@app.post("/events/clear")
def events_clear():
    EVENTS.clear()
    return {"cleared": True}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return (HERE / "dashboard.html").read_text()


@app.get("/baseline-stats")
def baseline_stats():
    """Class 7 — how many accounts are tracked, and how many are warm enough to trust."""
    return BASELINES.stats()


@app.get("/account/{account_id}")
def account_detail(account_id: str):
    """Inspect one account's learned baseline. Useful when an alert looks wrong."""
    import math
    st = BASELINES.load(account_id)
    
    back = (lambda v: math.expm1(v)) if BASELINES.log_space else (lambda v: v)
    return {
        "account_id": account_id,
        "transactions_seen": st.n,
        "warm": st.is_warm,
        "space": "log1p" if BASELINES.log_space else "raw",
        "typical_amount": round(back(st.mean), 2),
        "recent_typical_amount": round(back(st.ewma_mean), 2),
        "lifetime_mean_in_space": round(st.mean, 4),
        "lifetime_std_in_space": round(st.effective_std, 4),
        "recent_std_in_space": round(st.effective_ewma_std, 4),
        "txn_in_velocity_window": len(st.recent_ts),
    }


@app.get("/alert-stats")
def alert_stats():
    """Feeds the Class 8 dashboard — how noisy is the alerting actually?"""
    return {
        "cooldown_seconds": throttle.cooldown,
        "max_alerts_per_hour": throttle.max_per_hour,
        "alerts_sent_last_hour": len(throttle._recent),
        "active_dedup_keys": len(throttle._last_sent),
        "currently_suppressed": dict(throttle.suppressed_count),
    }
