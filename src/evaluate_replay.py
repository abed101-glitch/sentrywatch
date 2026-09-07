# Class 9 - score the replay stream against the real fraud labels

from __future__ import annotations

import sys
import argparse
from pathlib import Path

import joblib
import pandas as pd

from replay import Replay
from baseline_store import BaselineStore, combine_severity

HERE = Path(__file__).resolve().parent

# Class 10
POLICIES = {
    "any 1 signal   (classes 6-9)": dict(min_signals=1, require_ml=False),
    "any 2 signals  (consensus)":   dict(min_signals=2, require_ml=False),
    "model required (class 10)":    dict(require_ml=True),
}


def main(n: int, db: str) -> None:
    model_path = HERE.parent / "data" / "model.joblib"
    if not model_path.exists():
        sys.exit(f"{model_path} not found")

    art = joblib.load(model_path)
    model, cols = art["model"], art["feature_cols"]
    gm, gs = art["mean_amount"], art["std_amount"]

    for p in (db, db + "-journal"):
        Path(p).unlink(missing_ok=True)

    replay = Replay()
    store = BaselineStore(db, global_mean=gm, global_std=gs)

    print(f"Replaying {n:,} real transactions from creditcard.csv")
    print(f"  stream: {replay.stats()['rows_in_stream']:,} rows, "
          f"{replay.stats()['real_frauds_in_stream']} real frauds")
    print()

    tp = fp = fn = tn = 0
    ml_tp = ml_fp = 0
    acc_tp = acc_fp = 0
    policy = {k: {"tp": 0, "fp": 0, "high": 0} for k in POLICIES}

    for i in range(n):
        tx = replay.next()
        row = {c: (tx["Time"] / 3600 % 24 if c == "hour" else tx.get(c, 0.0))
               for c in cols}
        X = pd.DataFrame([row])[cols]
        ml = bool(model.predict(X)[0] == -1)

        bf = store.observe(tx["account_id"], tx["Amount"], tx["Time"],
                           autocommit=False)
        sev, _ = combine_severity(bf["account_z"], bf["global_z"],
                                  bf["txn_count_1h"], ml, bf["account_warm"])

        flagged = sev != "normal"
        truth = bool(tx["true_fraud"])

        if flagged and truth:
            tp += 1
        elif flagged and not truth:
            fp += 1
        elif not flagged and truth:
            fn += 1
        else:
            tn += 1

        z = bf["account_z"] if bf["account_warm"] else bf["global_z"]
        if ml:
            ml_tp += truth
            ml_fp += not truth
        if z is not None and z > 3:
            acc_tp += truth
            acc_fp += not truth

        for name, kw in POLICIES.items():
            s, _ = combine_severity(bf["account_z"], bf["global_z"],
                                    bf["txn_count_1h"], ml, bf["account_warm"],
                                    **kw)
            if s != "normal":
                policy[name]["tp" if truth else "fp"] += 1
            if s == "high":
                policy[name]["high"] += 1

    store.commit()
    store.close()
    for p in (db, db + "-journal"):
        Path(p).unlink(missing_ok=True)

    frauds = tp + fn
    negatives = n - frauds
    TRUE_RATE = 492 / 284807          # the real fraud rate in the dataset

    def pr(label, hit, fps, total_fraud):
        rec = hit / total_fraud * 100 if total_fraud else 0
        prc = hit / (hit + fps) * 100 if (hit + fps) else 0

        # Precision depends on the base rate, and the stream over-samples fraud.
        # Rescale to the real 0.173% rate: recall and false-positive rate are
        # properties of the detector and carry over; the class balance does not.
        fpr = fps / negatives if negatives else 0
        exp_fraud = n * TRUE_RATE
        exp_tp = exp_fraud * (rec / 100)
        exp_fp = (n - exp_fraud) * fpr
        adj = exp_tp / (exp_tp + exp_fp) * 100 if (exp_tp + exp_fp) else 0

        print(f"  {label:24} caught {hit:>4}   flagged {hit+fps:>5}   "
              f"recall {rec:>5.1f}%   precision {prc:>5.1f}%   "
              f"(at real base rate: {adj:>4.1f}%)")
    print(f"  transactions scored     {n:,}")
    print(f"  real frauds present     {frauds}")
    print()
    print("  CONFUSION MATRIX (combined detector)")
    print(f"    true positives   {tp:>5}   caught real fraud")
    print(f"    false negatives  {fn:>5}   missed real fraud")
    print(f"    false positives  {fp:>5}   flagged a legitimate transaction")
    print(f"    true negatives   {tn:>5}   correctly left alone")
    print()
    print("  BY SIGNAL")
    pr("isolation forest only", ml_tp, ml_fp, frauds)
    pr("amount z > 3 only", acc_tp, acc_fp, frauds)
    pr("combined (what ships)", tp, fp, frauds)
    print()
    print("  ESCALATION POLICY (Class 10)")
    for name, c in policy.items():
        pr(name, c["tp"], c["fp"], frauds)
    print()
    print("    policy                          alerts   caught   false   high")
    for name, c in policy.items():
        print(f"    {name:30} {c['tp']+c['fp']:>6} {c['tp']:>8} "
              f"{c['fp']:>7} {c['high']:>6}")
    print()
    print(f"  Real labels from the Kaggle dataset. The stream over-samples fraud")
    print(f"  ({frauds/n*100:.2f}% here vs {TRUE_RATE*100:.3f}% in the population, "
          f"about {frauds/n/TRUE_RATE:.0f}x) so a demo shows some.")
    print("  Recall is unaffected by that. Precision is not - the bracketed figure")
    print("  rescales it to the real base rate and is the one to quote.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=3000)
    p.add_argument("--db", default="/tmp/eval_baselines.db")
    a = p.parse_args()
    main(a.n, a.db)
