# Class 6-8 - scoring service with per-account baselines and alerting

import os
import time
import random
import threading
import joblib
import pandas as pd
from pathlib import Path
from fastapi import FastAPI
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


@app.post("/onboard")
def onboard(req: Onboard):
    slug = "".join(c for c in req.business.upper()
               if c.isalnum() and c.isascii())[:10] or "MERCHANT"
    account_id = f"{slug}-001"

    seeded = 0
    if req.backfill:
        now = time.time()
        n = max(0, min(int(req.backfill), 500))
        spread = 86400.0 * 30
        for i in range(n):
            amt = max(1.0, random.gauss(req.typical_order, req.typical_order * 0.28))
            BASELINES.observe(account_id, amt, now - spread + (i * spread / max(n, 1)),
                              autocommit=False)
            seeded += 1
        BASELINES.commit()

    warm = seeded >= baseline_store.MIN_HISTORY

    return {
        "account_id": account_id,
        "business": req.business,
        "seeded": seeded,
        "warm": warm,
        "min_history": baseline_store.MIN_HISTORY,
        "still_needed": max(0, baseline_store.MIN_HISTORY - seeded),
        "endpoint": "http://127.0.0.1:8000/score-checkout",
        "policy": ("model must flag before anything alerts"
                   if baseline_store.REQUIRE_ML
                   else "rule layer: any single signal alerts"),
        "note": ("Backfill is synthetic here, generated around the typical order value "
                 "you gave. A real onboarding would replay the merchant's own order "
                 "history through the same call, which is the only thing this is "
                 "standing in for."),
    }


@app.get("/checkout", response_class=HTMLResponse)
def checkout():
    return (Path(__file__).resolve().parent.parent / "landing" / "checkout.html").read_text()


@app.post("/score-checkout")
def score_checkout(tx: Transaction):
    data = tx.model_dump()
    bf = BASELINES.observe(data["account_id"], data["Amount"],
                           data.get("Time") or time.time())
    severity, reasons = combine_severity(
        account_z=bf["account_z"], global_z=bf["global_z"],
        txn_count_1h=bf["txn_count_1h"], ml_flagged=False,
        account_warm=bf["account_warm"], min_signals=1, require_ml=False,
    )
    verdict = {"high": "DECLINE", "medium": "REVIEW", "normal": "APPROVE"}[severity]
    return {
        "verdict": verdict,
        "severity": severity,
        "reasons": reasons,
        "account_id": data["account_id"],
        "amount": data["Amount"],
        "account_mean": bf["account_mean"],
        "account_std": bf["account_std"],
        "account_n": bf["account_n"],
        "account_warm": bf["account_warm"],
        "account_z": bf["account_z"],
        "global_z": bf["global_z"],
        "txn_count_1h": bf["txn_count_1h"],
        "model_scored": False,
        "model_note": ("The isolation forest is not scored here. It needs V1-V28, "
                       "which are PCA components from the research dataset and cannot "
                       "be computed from a live transaction. Only the rule layer - "
                       "per-account amount baseline and velocity - runs on real "
                       "merchant input."),
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
                alert = dispatch_alert(result, tx, deliver=False)
            EVENTS.record(result, alert)
            FEED["sent"] += 1
        except Exception as exc:
            print(f"[feed] {type(exc).__name__}: {exc}")
        time.sleep(FEED["interval"])


@app.post("/feed/start")
def feed_start(interval: float = 1.0):
    if FEED["on"]:
        return {"running": True, "already": True, "scored": FEED["sent"]}
    FEED["interval"] = max(0.2, min(interval, 10.0))
    FEED["on"] = True
    t = threading.Thread(target=_feed_loop, daemon=True)
    FEED["thread"] = t
    t.start()
    return {"running": True, "interval": FEED["interval"],
            "note": "replaying real transactions through the full scoring path"}


@app.post("/feed/stop")
def feed_stop():
    FEED["on"] = False
    return {"running": False, "scored": FEED["sent"]}


# Class 11
class AlertConfig(BaseModel):
    chat_id: str = ""


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
    return {"sent": bool(r.get("ok")), **cfg, "detail": r}


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
