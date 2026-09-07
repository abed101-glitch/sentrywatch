"""
Class 6 — scoring service.


"""
import joblib
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

app = FastAPI(title="Fraud Scoring Service")
artifact = joblib.load("model.joblib")
MODEL = artifact["model"]
FEATURE_COLS = artifact["feature_cols"]
MEAN_AMOUNT = artifact["mean_amount"]
STD_AMOUNT = artifact["std_amount"]


class Transaction(BaseModel):
    model_config = ConfigDict(extra="allow")  # tolerate extra n8n fields
    Time: float
    Amount: float
    # V1..V28 arrive as extra fields and get pulled out dynamically below


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/score")
def score(tx: Transaction):
    data = tx.model_dump()

    row = {}
    for col in FEATURE_COLS:
        if col == "hour":
            row["hour"] = (data["Time"] / 3600) % 24
        else:
            row[col] = data.get(col, 0.0)

    X = pd.DataFrame([row])[FEATURE_COLS]

    z = (data["Amount"] - MEAN_AMOUNT) / STD_AMOUNT
    ml_raw = MODEL.predict(X)[0]          # -1 anomaly, 1 normal
    ml_score = MODEL.decision_function(X)[0]  # lower = more anomalous
    ml_flagged = ml_raw == -1

    # Combine both signals into one severity for n8n to route on
    if ml_flagged and z > 3:
        severity = "high"
    elif ml_flagged or z > 3:
        severity = "medium"
    else:
        severity = "normal"

    reasons = []
    if z > 3:
        reasons.append(f"amount z-score {z:.2f} (unusually large amount)")
    if ml_flagged:
        reasons.append(f"isolation forest anomaly score {ml_score:.3f}")

    return {
        "severity": severity,
        "z_score": round(float(z), 3),
        "ml_flagged": bool(ml_flagged),
        "ml_score": round(float(ml_score), 4),
        "reason": "; ".join(reasons) if reasons else "no anomaly detected",
    }
