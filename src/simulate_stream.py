# Class 7 - replay the dataset as a transaction stream

from __future__ import annotations

import os
import time
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from baseline_store import BaselineStore, combine_severity, MIN_HISTORY


def assign_accounts(df: pd.DataFrame, n_accounts: int, mode: str,
                    seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = df.copy()

    if mode == "random":
        df["account_id"] = [f"ACC-{i:05d}"
                            for i in rng.integers(0, n_accounts, len(df))]
        return df

    levels = rng.lognormal(mean=3.6, sigma=1.0, size=n_accounts)
    idx = rng.integers(0, n_accounts, len(df))
    df["account_id"] = [f"ACC-{i:05d}" for i in idx]

    global_mean = df["Amount"].mean()
    ratio = df["Amount"].to_numpy() / max(global_mean, 1e-9)
    df["Amount"] = np.round(levels[idx] * ratio, 2)
    return df


def run(csv_path: str, rows: int, n_accounts: int, mode: str,
        db_path: str, warmup_frac: float = 0.5) -> dict:
    print(f"Loading {csv_path} ...")
    df = pd.read_csv(csv_path, nrows=rows)
    df = assign_accounts(df, n_accounts, mode)
    print(f"  {len(df):,} rows, {df['account_id'].nunique():,} synthetic accounts "
          f"(mode={mode})")

    if Path(db_path).exists():
        os.remove(db_path)

    store = BaselineStore(db_path,
                          global_mean=float(df["Amount"].mean()),
                          global_std=float(df["Amount"].std()))

    split = int(len(df) * warmup_frac)
    warm, score = df.iloc[:split], df.iloc[split:]

    t0 = time.perf_counter()
    store.warm_up(zip(warm["account_id"], warm["Amount"], warm["Time"]),
                  autocommit=False)
    store.commit()
    warm_secs = time.perf_counter() - t0
    print(f"  warm-up: {len(warm):,} rows in {warm_secs:.1f}s "
          f"({len(warm)/max(warm_secs,1e-9):,.0f} rows/s)")
    print(f"  {store.stats()}")

    results, t0 = [], time.perf_counter()
    for r in score.itertuples(index=False):
        f = store.observe(r.account_id, float(r.Amount), float(r.Time),
                          autocommit=False)
        sev, reasons = combine_severity(
            account_z=f["account_z"], global_z=f["global_z"],
            txn_count_1h=f["txn_count_1h"], ml_flagged=False,
            account_warm=f["account_warm"])
        results.append({
            "Class": r.Class, "severity": sev,
            "account_z": f["account_z"], "global_z": f["global_z"],
            "warm": f["account_warm"], "txn_count_1h": f["txn_count_1h"],
        })
    store.commit()
    score_secs = time.perf_counter() - t0
    res = pd.DataFrame(results)

    per_txn_ms = score_secs / max(len(score), 1) * 1000
    print(f"  scoring: {len(score):,} rows in {score_secs:.1f}s "
          f"({per_txn_ms:.3f} ms/txn, {len(score)/max(score_secs,1e-9):,.0f} txn/s)")

    warm_rows = res[res["warm"]]
    out = {
        "mode": mode, "rows": len(df), "accounts": n_accounts,
        "scored": len(res), "warm_scored": len(warm_rows),
        "fraud_in_scored": int(res["Class"].sum()),
        "warmup_rows_per_sec": round(len(warm) / max(warm_secs, 1e-9)),
        "score_ms_per_txn": round(per_txn_ms, 4),
        "db_size_kb": round(Path(db_path).stat().st_size / 1024, 1),
    }

    if len(warm_rows) and warm_rows["Class"].sum():
        for label, col in [("global", "global_z"), ("account", "account_z")]:
            flagged = warm_rows[warm_rows[col] > 3]
            caught = int(flagged["Class"].sum())
            total = int(warm_rows["Class"].sum())
            out[f"{label}_flagged"] = len(flagged)
            out[f"{label}_caught"] = caught
            out[f"{label}_recall"] = round(caught / total * 100, 2) if total else 0.0
            out[f"{label}_precision"] = (round(caught / len(flagged) * 100, 2)
                                         if len(flagged) else 0.0)
    store.close()
    return out


def benchmark(db_path: str = "../data/bench.db") -> None:
    print("\nBenchmark: baseline store throughput\n" + "-" * 44)
    if Path(db_path).exists():
        os.remove(db_path)
    store = BaselineStore(db_path, global_mean=88.0, global_std=250.0)
    rng = np.random.default_rng(0)
    n, n_acc = 50_000, 1_000

    accounts = [f"ACC-{i:05d}" for i in rng.integers(0, n_acc, n)]
    amounts = rng.lognormal(4, 1, n)

    t0 = time.perf_counter()
    for i in range(n):
        store.observe(accounts[i], float(amounts[i]), float(i * 10),
                      autocommit=False)
    store.commit()
    secs = time.perf_counter() - t0

    size_kb = Path(db_path).stat().st_size / 1024
    print(f"  transactions   : {n:,}")
    print(f"  accounts       : {n_acc:,}")
    print(f"  total time     : {secs:.2f}s")
    print(f"  per transaction: {secs/n*1000:.4f} ms")
    print(f"  throughput     : {n/secs:,.0f} txn/s")
    print(f"  db size        : {size_kb:.1f} KB "
          f"({size_kb*1024/n_acc:.0f} bytes/account)")
    print(f"  {store.stats()}")
    store.close()
    os.remove(db_path)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="../data/creditcard.csv")
    p.add_argument("--rows", type=int, default=50_000)
    p.add_argument("--accounts", type=int, default=500)
    p.add_argument("--assign", choices=["random", "profiled"], default="profiled")
    p.add_argument("--db", default="../data/baselines_sim.db")
    p.add_argument("--benchmark", action="store_true")
    a = p.parse_args()

    if a.benchmark:
        benchmark()
    else:
        if not Path(a.csv).exists():
            raise SystemExit(f"{a.csv} not found — see data/README.md")
        out = run(a.csv, a.rows, a.accounts, a.assign, a.db)
        print("\nSummary")
        print("-" * 44)
        for k, v in out.items():
            print(f"  {k:24} {v}")
        print("\nNOTE: account IDs are synthetic. These numbers show the")
        print("      mechanism running, not a validated recall improvement.")
