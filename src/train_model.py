"""
Class 6 — train and persist the fraud detection model.

"""
import sys
import json
import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

FEATURE_COLS = [f"V{i}" for i in range(1, 29)] + ["Amount", "hour"]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hour"] = (df["Time"] / 3600) % 24
    return df


def main(csv_path: str):
    df = pd.read_csv(csv_path)
    df = build_features(df)

   
    mean_amount = float(df["Amount"].mean())
    std_amount = float(df["Amount"].std())

    X = df[FEATURE_COLS]

    
    model = IsolationForest(
        n_estimators=200,
        contamination=0.0017,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X)

    df["ml_flag"] = model.predict(X)  # -1 = anomaly, 1 = normal

    if "Class" in df.columns:
        fraud_caught = df[(df["ml_flag"] == -1) & (df["Class"] == 1)].shape[0]
        total_flagged = df[df["ml_flag"] == -1].shape[0]
        total_fraud = df[df["Class"] == 1].shape[0]
        recall = fraud_caught / total_fraud * 100 if total_fraud else 0
        precision = fraud_caught / total_flagged * 100 if total_flagged else 0
        print(f"Fraud caught: {fraud_caught}/{total_fraud}  "
              f"Recall: {recall:.2f}%  Precision: {precision:.2f}%  "
              f"Total flagged: {total_flagged}")

    joblib.dump(
        {
            "model": model,
            "feature_cols": FEATURE_COLS,
            "mean_amount": mean_amount,
            "std_amount": std_amount,
        },
        "model.joblib",
    )
    print("Saved model.joblib")


if __name__ == "__main__":
    csv = sys.argv[1] if len(sys.argv) > 1 else "creditcard.csv"
    main(csv)
