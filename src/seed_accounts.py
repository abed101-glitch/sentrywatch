# Class 8 - seed accounts with real history so demo alerts show computed values

from __future__ import annotations

import sys
import random
import argparse

import requests

API = "http://127.0.0.1:8000"


def txn(amount: float, account: str, ts: float) -> dict:
    d = {"Time": ts, "Amount": round(amount, 2), "account_id": account}
    for i in range(1, 29):
        d[f"V{i}"] = 0.0
    return d


def seed(account: str, mean: float, sd: float, n: int, api: str = API,
         seed_val: int = 42) -> dict:
    rng = random.Random(seed_val)
    for i in range(n):
        amount = max(1.0, rng.gauss(mean, sd))
        requests.post(f"{api}/score", json=txn(amount, account, float(i * 3600)),
                      timeout=10)
    r = requests.get(f"{api}/account/{account}", timeout=10)
    return r.json()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--api", default=API)
    p.add_argument("--n", type=int, default=60)
    a = p.parse_args()

    try:
        requests.get(f"{a.api}/health", timeout=3)
    except Exception:
        sys.exit(f"service not reachable at {a.api}")

    profiles = [
        ("ACC-BIZ", 900.0, 80.0, "business account"),
        ("ACC-STU", 25.0, 6.0, "student account"),
    ]

    print(f"Seeding {a.n} real transactions per account through POST /score")
    print("-" * 62)
    for acct, mean, sd, label in profiles:
        info = seed(acct, mean, sd, a.n, a.api)
        print(f"  {acct}  ({label})")
        print(f"    transactions seen : {info['transactions_seen']}")
        print(f"    warm              : {info['warm']}")
        print(f"    typical amount    : {info['typical_amount']}")
        print(f"    space             : {info['space']}")
        print()
    print("These baselines were computed by the service, not typed in.")
