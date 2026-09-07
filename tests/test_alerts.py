# Class 8 - tests for the alerting layer

import os
import sys

os.environ["ALERT_COOLDOWN_SECONDS"] = "2"
os.environ["MAX_ALERTS_PER_HOUR"] = "5"
os.environ["ALERT_CHANNELS"] = "telegram"

sys.path.insert(0, "../src")

import time
import alerts
from alerts import format_alert, make_dedup_key, dispatch_alert, describe_amount

PASS, FAIL = 0, 0
SENT = []


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


def stub_senders():
    SENT.clear()
    alerts.send_telegram = lambda t: (SENT.append(("telegram", t)),
                                      {"channel": "telegram", "ok": True})[1]
    alerts.send_email = lambda s, p, h: (SENT.append(("email", s)),
                                         {"channel": "email", "ok": True})[1]


WARM = {"severity": "high", "account_id": "ACC-1042", "account_warm": True,
        "account_mean": 380.50, "account_z": 17.4, "global_z": 17.6,
        "account_n": 214, "txn_count_1h": 2, "ml_flagged": True,
        "ml_score": -0.0812, "baseline_drift": 0.3, "reason": "large amount"}

COLD = {"severity": "medium", "account_id": "ACC-9999", "account_warm": False,
        "account_mean": None, "account_z": None, "global_z": 4.2,
        "account_n": 7, "txn_count_1h": 1, "ml_flagged": False,
        "ml_score": 0.14, "baseline_drift": None, "reason": "large amount"}

TESTING = {"severity": "high", "account_id": "ACC-3311", "account_warm": True,
           "account_mean": 62.00, "account_z": -1.8, "global_z": -0.3,
           "account_n": 430, "txn_count_1h": 19, "ml_flagged": False,
           "ml_score": 0.09, "baseline_drift": 0.1, "reason": "velocity"}


def test_warm_message_uses_account_context():
    print("\n[1] A warm account is described against its own history")
    body = format_alert(WARM, {"Amount": 4500.0})["telegram_text"]
    check("states the account's typical spend", "380.50" in body)
    check("expresses the anomaly as a multiple", "11.8x" in body, body)
    check("says 'above' for a positive z", "above" in body)
    check("mentions the isolation forest", "Isolation Forest" in body)
    check("no raw 'z_score' jargon", "z_score" not in body)


def test_cold_message_explains_fallback():
    print("\n[2] A cold account says why it used the global baseline")
    body = format_alert(COLD, {"Amount": 900.0})["telegram_text"]
    check("states the history count", "7 transactions of history" in body, body)
    check("names the global baseline", "global baseline" in body)
    check("no fake per-account claim", "normally spends" not in body)


def test_card_testing_does_not_blame_the_amount():
    print("\n[3] Card testing points at velocity, not the amount")
    body = format_alert(TESTING, {"Amount": 3.0})["telegram_text"]
    check("says the amount is not the concern",
          "not the concern" in body, body)
    check("uses 'below' for a negative z", "below" in body, body)
    check("no nonsense multiple like 0.0x", "0.0x" not in body, body)
    check("velocity is reported", "19 transactions in the last hour" in body)


def test_sigma_direction():
    print("\n[4] Sigma direction is never contradictory")
    up = describe_amount({**WARM, "account_z": 5.0}, {"Amount": 4500.0})
    down = describe_amount({**WARM, "account_z": -5.0}, {"Amount": 10.0})
    import re
    check("positive z -> above", any("above" in l for l in up))
    check("negative z -> below", any("below" in l for l in down))
    bad = [l for l in down + up if re.search(r"-\d+(\.\d+)?\s*sigma", l)]
    check("a negative number never precedes 'sigma'", not bad, str(bad))


def test_dedup_key():
    print("\n[5] Dedup key groups incidents, not transactions")
    k1 = make_dedup_key(WARM, {"Amount": 4500.0})
    k2 = make_dedup_key(WARM, {"Amount": 9999.0})
    k3 = make_dedup_key({**WARM, "account_id": "ACC-0001"}, {"Amount": 4500.0})
    k4 = make_dedup_key({**WARM, "txn_count_1h": 19}, {"Amount": 4500.0})
    check("same account + signals -> same key", k1 == k2)
    check("different account -> different key", k1 != k3)
    check("different signal pattern -> different key", k1 != k4)


def test_burst_is_one_alert():
    print("\n[6] A burst on one account produces one alert")
    stub_senders()
    alerts.throttle = alerts.AlertThrottle(cooldown=2, max_per_hour=50)
    results = [dispatch_alert(TESTING, {"Amount": 3.0}) for _ in range(6)]
    sent = sum(1 for r in results if r["sent"])
    supp = sum(1 for r in results if r["suppressed"])
    check("exactly one alert sent", sent == 1, f"sent={sent}")
    check("the rest suppressed", supp == 5, f"suppressed={supp}")
    check("only telegram used", all(c == "telegram" for c, _ in SENT), str(SENT))
    check("suppression reason is recorded",
          all(r.get("suppression_reason") for r in results if r["suppressed"]))
    print(f"        6 events -> {sent} alert, {supp} suppressed")


def test_rollup_reported():
    print("\n[7] Suppressed events are rolled up into the next alert")
    stub_senders()
    alerts.throttle = alerts.AlertThrottle(cooldown=1, max_per_hour=50)
    for _ in range(4):
        dispatch_alert(WARM, {"Amount": 4500.0})
    time.sleep(1.1)
    r = dispatch_alert(WARM, {"Amount": 4500.0})
    check("rollup count carried", r["rolled_up_events"] == 3,
          f"rolled_up={r['rolled_up_events']}")
    body = SENT[-1][1]
    check("rollup shown in the message", "suppressed during cooldown" in body)
    print(f"        rolled up {r['rolled_up_events']} suppressed events")


def test_global_cap():
    print("\n[8] Global cap stops a flood from model drift")
    stub_senders()
    alerts.throttle = alerts.AlertThrottle(cooldown=0, max_per_hour=3)
    results = [dispatch_alert({**WARM, "account_id": f"ACC-{i}"}, {"Amount": 4500.0})
               for i in range(6)]
    sent = sum(1 for r in results if r["sent"])
    check("capped at the limit", sent == 3, f"sent={sent}")
    blocked = [r for r in results if not r["sent"]]
    check("cap is the stated reason",
          all("global cap" in r["suppression_reason"] for r in blocked))
    print(f"        6 distinct accounts -> {sent} alerts (cap 3)")


def test_unconfigured_credentials():
    print("\n[9] Missing credentials fail loudly, not silently")
    import importlib
    importlib.reload(alerts)
    r = alerts.send_telegram("x")
    check("telegram reports not configured", r["ok"] is False)
    check("error names the cause", "credentials" in r.get("error", ""))
    print(f"        {r}")


def test_default_channel_is_telegram_only():
    print("\n[10] Default channel set")
    import importlib
    importlib.reload(alerts)
    check("telegram is enabled", "telegram" in alerts.ALERT_CHANNELS)
    check("email is off by default", "email" not in alerts.ALERT_CHANNELS,
          str(alerts.ALERT_CHANNELS))
    print(f"        ALERT_CHANNELS = {alerts.ALERT_CHANNELS}")


if __name__ == "__main__":
    for t in [test_warm_message_uses_account_context,
              test_cold_message_explains_fallback,
              test_card_testing_does_not_blame_the_amount,
              test_sigma_direction,
              test_dedup_key,
              test_burst_is_one_alert,
              test_rollup_reported,
              test_global_cap,
              test_unconfigured_credentials,
              test_default_channel_is_telegram_only]:
        t()

    print("\n" + "=" * 58)
    print(f"  {PASS} passed, {FAIL} failed")
    print("=" * 58)
    sys.exit(1 if FAIL else 0)
