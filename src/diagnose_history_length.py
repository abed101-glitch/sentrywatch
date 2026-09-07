# Class 7 - diagnostic: does short account history inflate the flag rate?

from __future__ import annotations

import os
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from baseline_store import BaselineStore, MIN_HISTORY
from simulate_stream import assign_accounts


def test_a_sweep(csv_path: str, rows: int, account_counts: list[int],
                 mode: str = "random", log_space: bool = False,
                 label: str = "TEST A — flag counts vs history length per account"
                 ) -> pd.DataFrame:
    print("=" * 74)
    print(label)
    print("=" * 74)

    df_raw = pd.read_csv(csv_path, nrows=rows)
    out = []

    for n_acc in account_counts:
        df = assign_accounts(df_raw, n_acc, mode)
        db = f"/tmp/diag_{n_acc}_{'log' if log_space else 'raw'}.db"
        if Path(db).exists():
            os.remove(db)

        store = BaselineStore(db,
                              global_mean=float(df["Amount"].mean()),
                              global_std=float(df["Amount"].std()),
                              log_space=log_space)

        split = len(df) // 2
        warm, score = df.iloc[:split], df.iloc[split:]
        store.warm_up(zip(warm["account_id"], warm["Amount"], warm["Time"]),
                      autocommit=False)
        store.commit()

        g_flag = a_flag = warm_n = 0
        g_caught = a_caught = 0
        for r in score.itertuples(index=False):
            f = store.observe(r.account_id, float(r.Amount), float(r.Time),
                              autocommit=False)
            if not f["account_warm"]:
                continue
            warm_n += 1
            if f["global_z"] > 3:
                g_flag += 1
                g_caught += int(r.Class)
            if f["account_z"] > 3:
                a_flag += 1
                a_caught += int(r.Class)
        store.commit()
        store.close()
        os.remove(db)

        hist = split / n_acc
        out.append({
            "accounts": n_acc,
            "history_per_account": round(hist),
            "scored_warm": warm_n,
            "global_flagged": g_flag,
            "account_flagged": a_flag,
            "ratio_acct_over_global": round(a_flag / g_flag, 2) if g_flag else None,
            "global_caught": g_caught,
            "account_caught": a_caught,
        })
        print(f"  {n_acc:5} accounts  ~{hist:6.0f} txns history   "
              f"global flags {g_flag:5}   account flags {a_flag:5}   "
              f"ratio {out[-1]['ratio_acct_over_global']}")

    return pd.DataFrame(out)


def test_b_bias(csv_path: str, rows: int, trials: int = 400,
                seed: int = 42) -> pd.DataFrame:
    print()
    print("=" * 74)
    print("TEST B — is the sample std downward-biased at small n?")
    print("=" * 74)
    print("  Drawing random samples straight from the Amount column.")
    print("  No accounts, no fraud labels — this isolates the estimator.")
    print()

    amounts = pd.read_csv(csv_path, nrows=rows, usecols=["Amount"])["Amount"].to_numpy()
    pop_std = amounts.std(ddof=1)
    pop_mean = amounts.mean()

    skew = float(((amounts - pop_mean) ** 3).mean() / pop_std ** 3)
    print(f"  population n     : {len(amounts):,}")
    print(f"  population mean  : {pop_mean:.2f}")
    print(f"  population std   : {pop_std:.2f}")
    print(f"  skewness         : {skew:.2f}   "
          f"({'heavy right tail' if skew > 2 else 'roughly symmetric'})")
    print()

    rng = np.random.default_rng(seed)
    rowsout = []
    print(f"  {'n':>7}  {'median std':>11}  {'ratio to pop':>13}  "
          f"{'P(z>3) implied':>15}")
    print("  " + "-" * 52)

    for n in [10, 30, 50, 100, 250, 500, 1000, 5000]:
        if n > len(amounts):
            continue
        stds = np.array([
            amounts[rng.integers(0, len(amounts), n)].std(ddof=1)
            for _ in range(trials)
        ])
        med = float(np.median(stds))
        ratio = med / pop_std
        eff_threshold = 3 * ratio
        rowsout.append({
            "n": n, "median_sample_std": round(med, 2),
            "ratio_to_population": round(ratio, 4),
            "effective_threshold_in_pop_sigma": round(eff_threshold, 3),
        })
        marker = "  <-- MIN_HISTORY" if n == MIN_HISTORY else ""
        print(f"  {n:>7}  {med:>11.2f}  {ratio:>13.3f}  "
              f"{eff_threshold:>15.2f}{marker}")

    return pd.DataFrame(rowsout)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="../data/creditcard.csv")
    p.add_argument("--rows", type=int, default=50_000)
    a = p.parse_args()

    if not Path(a.csv).exists():
        raise SystemExit(f"{a.csv} not found — see data/README.md")

    counts = [500, 250, 100, 50, 25]
    ta = test_a_sweep(a.csv, a.rows, counts, log_space=False)
    tb = test_b_bias(a.csv, a.rows)

    print()
    tc = test_a_sweep(
        a.csv, a.rows, counts, log_space=True,
        label="TEST C — the same sweep, with statistics kept in log1p space")

    print()
    print("=" * 74)
    print("VERDICT")
    print("=" * 74)

    first, last = ta.iloc[0], ta.iloc[-1]
    converging = (last["ratio_acct_over_global"] or 0) < (first["ratio_acct_over_global"] or 0)
    print(f"  Test A: raw-space flag ratio went {first['ratio_acct_over_global']} "
          f"(at ~{first['history_per_account']} txns history) -> "
          f"{last['ratio_acct_over_global']} (at ~{last['history_per_account']}).")
    print(f"          {'CONSISTENT with' if converging else 'DOES NOT support'} "
          "the short-history explanation.")

    r30 = tb[tb['n'] == 30]
    if len(r30):
        ratio30 = float(r30['ratio_to_population'].iloc[0])
        print(f"  Test B: at n=30 (MIN_HISTORY) the raw sample std is "
              f"{ratio30:.1%} of the population std,")
        print(f"          so a nominal z > 3 threshold behaves like "
              f"z > {3*ratio30:.2f} in population terms.")
        print(f"          {'CONFIRMED' if ratio30 < 0.9 else 'NOT CONFIRMED'}: "
              "the raw estimator is biased low at small n.")

    craw, clog = ta.iloc[0], tc.iloc[0]
    print(f"  Test C: at ~{craw['history_per_account']} txns of history, "
          f"account flags went {craw['account_flagged']} (raw) -> "
          f"{clog['account_flagged']} (log1p),")
    print(f"          against {craw['global_flagged']} global flags. "
          f"Ratio {craw['ratio_acct_over_global']} -> "
          f"{clog['ratio_acct_over_global']}.")
    fixed = (clog["ratio_acct_over_global"] or 9) < (craw["ratio_acct_over_global"] or 0)
    print(f"          {'FIX WORKS' if fixed else 'NO IMPROVEMENT'}: log space "
          "removes the excess flagging at short history.")
    print(f"          fraud caught {craw['account_caught']} (raw) -> "
          f"{clog['account_caught']} (log1p) of the same set.")

    ta.to_csv("../results/diag_history_sweep_raw.csv", index=False)
    tc.to_csv("../results/diag_history_sweep_log.csv", index=False)
    tb.to_csv("../results/diag_std_bias.csv", index=False)
    print()
    print("  Written: results/diag_history_sweep_raw.csv, "
          "diag_history_sweep_log.csv, diag_std_bias.csv")
