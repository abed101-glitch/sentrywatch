"""
Class 7 — demo driver.

"""
import sys
import json
import time
import random
import argparse

import requests

DEFAULT_URL = "http://localhost:5678/webhook/transaction"


def make_tx(amount: float, account: str = "ACC-1042", anomalous: bool = False) -> dict:
    """Build a creditcard.csv-shaped row. V1..V28 are the PCA features."""
    if anomalous:
       
        v = {f"V{i}": round(random.gauss(0, 1) * 6, 4) for i in range(1, 29)}
    else:
        v = {f"V{i}": round(random.gauss(0, 1), 4) for i in range(1, 29)}
    return {
        "Time": float(random.randint(0, 172_800)),
        "Amount": float(amount),
        "account_id": account,
        **v,
    }


SCENARIOS = {
    
    "single": [make_tx(4200.00, "ACC-1042", anomalous=True)],

    
    "burst": [make_tx(3800.00, "ACC-7777", anomalous=True) for _ in range(6)],

   
    "mixed": (
        [make_tx(round(random.uniform(5, 90), 2), f"ACC-{i:04d}") for i in range(6)]
        + [make_tx(2600.00, "ACC-3311", anomalous=True)]
        + [make_tx(round(random.uniform(10, 60), 2), "ACC-0002")]
        + [make_tx(5100.00, "ACC-8890", anomalous=True)]
    ),
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--scenario", default="single", choices=sorted(SCENARIOS))
    p.add_argument("--delay", type=float, default=1.0,
                   help="seconds between transactions")
    args = p.parse_args()

    txs = SCENARIOS[args.scenario]
    print(f"Sending {len(txs)} transaction(s) [{args.scenario}] -> {args.url}\n")

    for i, tx in enumerate(txs, 1):
        try:
            r = requests.post(args.url, json=tx, timeout=20)
            try:
                body = json.dumps(r.json(), separators=(",", ":"))[:180]
            except Exception:
                body = r.text[:180]
            print(f"  [{i}/{len(txs)}] amount={tx['Amount']:>8.2f} "
                  f"acct={tx['account_id']}  HTTP {r.status_code}  {body}")
        except requests.exceptions.ConnectionError:
            print(f"  [{i}] CONNECTION REFUSED — is n8n running, and is the "
                  f"workflow Active (or 'Listen for test event' clicked)?")
            sys.exit(1)
        except Exception as e:
            print(f"  [{i}] error: {e}")
        time.sleep(args.delay)

    print("\nDone. Check Telegram, your inbox, and the AlertLog sheet.")
    print("Throttle state:  curl http://localhost:8000/alert-stats")


if __name__ == "__main__":
    main()
