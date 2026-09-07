# Class 7 - tests for the per-account baseline store

import sys
import math
import random
import statistics

sys.path.insert(0, "../src")

from baseline_store import (
    AccountState, BaselineStore, combine_severity,
    MIN_HISTORY, EWMA_ALPHA, to_space,
)

PASS, FAIL = 0, 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


def test_welford_matches_batch():
    print("\n[1] Welford online == batch statistics")
    random.seed(7)
    data = [random.lognormvariate(4, 1.1) for _ in range(5000)]

    st = AccountState("A")
    for i, x in enumerate(data):
        st.update(x, ts=float(i))

    batch_mean = statistics.fmean(data)
    batch_std = statistics.stdev(data)

    check("mean matches", math.isclose(st.mean, batch_mean, rel_tol=1e-9),
          f"online={st.mean!r} batch={batch_mean!r}")
    check("std matches", math.isclose(st.std, batch_std, rel_tol=1e-9),
          f"online={st.std!r} batch={batch_std!r}")
    print(f"        n={st.n}  mean={st.mean:.6f}  std={st.std:.6f}")


def test_naive_formula_fails():
    print("\n[2] Naive variance formula breaks where Welford does not")
    data = [1e9 + i * 0.001 for i in range(1000)]

    n = len(data)
    naive_var = sum(x * x for x in data) / n - (sum(data) / n) ** 2

    st = AccountState("B")
    for i, x in enumerate(data):
        st.update(x, ts=float(i))

    true_var = statistics.variance(data)

    naive_err = abs(naive_var - true_var) / true_var
    welford_err = abs(st.variance - true_var) / true_var

    check("naive formula returns a negative variance", naive_var < 0,
          f"naive={naive_var!r}")
    check("Welford stays within 0.1% of exact",
          welford_err < 1e-3, f"rel_err={welford_err:.2e}")
    check("Welford beats naive by many orders of magnitude",
          welford_err < naive_err / 1e6,
          f"welford={welford_err:.2e} naive={naive_err:.2e}")
    print(f"        exact var   = {true_var:.6e}")
    print(f"        naive var   = {naive_var:.6e}   rel err {naive_err:.2e}")
    print(f"        welford var = {st.variance:.6e}   rel err {welford_err:.2e}")
    print("        (residual Welford error is float64 input precision:")
    print("         1e9 + 0.001 is not exactly representable)")


def test_ewma_adapts_to_drift():
    print("\n[3] EWMA tracks behavioural drift, cumulative mean lags")
    st = AccountState("C")
    for i in range(500):
        st.update(50.0, ts=float(i))
    for i in range(500, 700):
        st.update(500.0, ts=float(i))

    check("EWMA moved close to the new level", st.ewma_mean > 400,
          f"ewma_mean={st.ewma_mean:.2f}")
    check("cumulative mean still lagging", st.mean < 250,
          f"mean={st.mean:.2f}")
    print(f"        cumulative mean = {st.mean:8.2f}")
    print(f"        ewma mean       = {st.ewma_mean:8.2f}   (alpha={EWMA_ALPHA})")
    print(f"        effective window ~ {int(1/EWMA_ALPHA)} transactions")


def test_cold_start():
    print("\n[4] Cold start falls back to the global baseline")
    s = BaselineStore(":memory:", global_mean=88.0, global_std=250.0, log_space=False)

    f = s.observe("NEW", 100.0, ts=0.0)
    check("brand new account is cold", f["account_warm"] is False)
    check("no per-account z offered", f["account_z"] is None)
    check("global z still provided", f["global_z"] is not None)

    for i in range(1, MIN_HISTORY + 1):
        f = s.observe("NEW", 100.0 + i, ts=float(i * 60))

    check(f"warm after {MIN_HISTORY} observations", f["account_warm"] is True,
          f"n={f['account_n']}")
    check("per-account z now offered", f["account_z"] is not None)
    print(f"        n={f['account_n']}  account_z={f['account_z']}  global_z={f['global_z']}")
    s.close()


def test_no_self_contamination():
    print("\n[5] A transaction does not contribute to its own baseline")
    s = BaselineStore(":memory:", global_mean=88.0, global_std=250.0, log_space=False)
    for i in range(200):
        s.observe("D", 50.0 + (i % 5), ts=float(i * 60))

    before = s.load("D")

    anomaly = 500.0
    f = s.observe("D", anomaly, ts=float(200 * 60))

    expected_z = (anomaly - before.mean) / before.effective_std
    check("z computed from pre-transaction state",
          math.isclose(f["account_z"], round(expected_z, 4), rel_tol=1e-6),
          f"got {f['account_z']} expected {round(expected_z, 4)}")
    check("anomaly is large against own history", f["account_z"] > 100,
          f"account_z={f['account_z']}")

    after = s.load("D")
    check("state did update afterwards", after.n == before.n + 1)

    expected_mean = before.mean + (anomaly - before.mean) / after.n
    check("mean updated by the Welford increment",
          math.isclose(after.mean, expected_mean, rel_tol=1e-12))

    print(f"        account mean before = {before.mean:.2f}  std = {before.effective_std:.2f}")
    print(f"        account_z for {anomaly:.0f}   = {f['account_z']:.2f}")
    print(f"        mean after          = {after.mean:.4f}")
    s.close()


def test_per_account_beats_global():
    print("\n[6] Same amount, different accounts, different verdicts")
    s = BaselineStore(":memory:", global_mean=88.0, global_std=250.0, log_space=False)

    for i in range(200):
        s.observe("BIZ", random.gauss(900, 80), ts=float(i * 3600))
    for i in range(200):
        s.observe("STU", random.gauss(25, 6), ts=float(i * 3600))

    amount, ts = 900.0, float(300 * 3600)
    biz = s.features("BIZ", amount, ts)
    stu = s.features("STU", amount, ts)

    check("identical global z for both",
          biz["global_z"] == stu["global_z"],
          f"{biz['global_z']} vs {stu['global_z']}")
    check("normal for the big spender", abs(biz["account_z"]) < 3,
          f"account_z={biz['account_z']}")
    check("extreme for the small spender", stu["account_z"] > 10,
          f"account_z={stu['account_z']}")
    print(f"        global z (both)  = {biz['global_z']:.2f}")
    print(f"        BIZ account_z    = {biz['account_z']:.2f}   (mean {biz['account_mean']})")
    print(f"        STU account_z    = {stu['account_z']:.2f}   (mean {stu['account_mean']})")
    s.close()


def test_velocity():
    print("\n[7] Velocity detects card testing that amount checks miss")
    s = BaselineStore(":memory:", global_mean=88.0, global_std=250.0, log_space=False)
    for i in range(200):
        s.observe("E", random.gauss(60, 10), ts=float(i * 86400))

    base = float(200 * 86400)
    f = None
    for i in range(20):
        f = s.observe("E", 3.0, ts=base + i * 30)

    check("velocity counted", f["txn_count_1h"] >= 15, f"count={f['txn_count_1h']}")
    check("amount alone looks innocent", abs(f["account_z"]) < 10,
          f"account_z={f['account_z']}")

    args = dict(account_z=f["account_z"], global_z=f["global_z"],
                txn_count_1h=f["txn_count_1h"], ml_flagged=False,
                account_warm=f["account_warm"])

    legacy, reasons = combine_severity(**args, min_signals=1, require_ml=False)
    check("velocity alone alerted under the classes 6-9 policy",
          legacy in ("medium", "high"), f"sev={legacy}")

    shipped, why = combine_severity(**args, require_ml=True)
    check("velocity alone is silent under the class 10 policy",
          shipped == "normal", f"sev={shipped}")
    check("but it is still recorded as a reason",
          any("card testing" in r for r in reasons), reasons)

    print(f"        txn_count_1h={f['txn_count_1h']}  account_z={f['account_z']:.2f}")
    print(f"        classes 6-9: {legacy}   class 10: {shipped}")
    print(f"        {why}")
    s.close()


def test_persistence():
    print("\n[8] State persists across store restarts")
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "baselines.db")

    s1 = BaselineStore(path, global_mean=88.0, global_std=250.0, log_space=False)
    for i in range(120):
        s1.observe("F", 100.0 + i, ts=float(i * 60))
    n_before, mean_before = s1.load("F").n, s1.load("F").mean
    s1.close()

    s2 = BaselineStore(path, global_mean=88.0, global_std=250.0, log_space=False)
    st = s2.load("F")
    check("count survived", st.n == n_before, f"{st.n} vs {n_before}")
    check("mean survived", math.isclose(st.mean, mean_before, rel_tol=1e-12))
    print(f"        reopened: n={st.n} mean={st.mean:.2f} std={st.std:.2f}")
    print(f"        {s2.stats()}")
    s2.close()


def test_constant_account():
    print("\n[9] Zero-variance account stays finite AND readable")
    from baseline_store import Z_CAP

    s = BaselineStore(":memory:", global_mean=88.0, global_std=250.0, log_space=False)
    for i in range(100):
        s.observe("G", 42.0, ts=float(i * 60))

    f = s.features("G", 42.0, ts=99999.0)
    check("identical amount scores ~0", abs(f["account_z"]) < 1e-6,
          f"account_z={f['account_z']}")

    f2 = s.features("G", 4200.0, ts=99999.0)
    check("100x amount is finite", math.isfinite(f2["account_z"]),
          f"account_z={f2['account_z']}")
    check("and clamped to a readable magnitude", abs(f2["account_z"]) <= Z_CAP,
          f"account_z={f2['account_z']}")
    check("still clearly flagged as extreme", f2["account_z"] > 3)
    print(f"        std floor applied = {f2['account_std']}  (1% of mean 42.00)")
    print(f"        same amount z={f['account_z']}   100x amount z={f2['account_z']}")
    s.close()


def test_log_space_removes_small_sample_bias():
    print("\n[10] log space removes the small-sample std bias")
    import statistics
    rng = random.Random(11)

    pop = [rng.lognormvariate(3.2, 1.4) for _ in range(60_000)]
    pop_raw_std = statistics.stdev(pop)
    pop_log_std = statistics.stdev([math.log1p(x) for x in pop])

    def median_sample_std(vals, n, trials=300):
        out = []
        for _ in range(trials):
            s = [vals[rng.randrange(len(vals))] for _ in range(n)]
            out.append(statistics.stdev(s))
        return statistics.median(out)

    raw_ratio = median_sample_std(pop, MIN_HISTORY) / pop_raw_std
    log_ratio = median_sample_std([math.log1p(x) for x in pop],
                                  MIN_HISTORY) / pop_log_std

    check(f"raw estimator is biased low at n={MIN_HISTORY}", raw_ratio < 0.75,
          f"ratio={raw_ratio:.3f}")
    check(f"log estimator is near-unbiased at n={MIN_HISTORY}",
          0.93 < log_ratio < 1.07, f"ratio={log_ratio:.3f}")
    check("log space is a large improvement", log_ratio > raw_ratio + 0.2,
          f"raw={raw_ratio:.3f} log={log_ratio:.3f}")
    print(f"        raw  std ratio at n={MIN_HISTORY}: {raw_ratio:.3f}")
    print(f"        log1p std ratio at n={MIN_HISTORY}: {log_ratio:.3f}")


def test_log_space_still_detects_outliers():
    print("\n[11] log space still separates a genuine outlier")
    rng = random.Random(12)
    s = BaselineStore(":memory:", global_mean=88.0, global_std=250.0, log_space=True)
    for i in range(200):
        s.observe("H", rng.gauss(50, 12), ts=float(i * 3600))

    normal = s.features("H", 55.0, ts=99999.0)
    big = s.features("H", 5000.0, ts=99999.0)

    check("space reported as log1p", big["space"] == "log1p")
    check("a normal amount stays under threshold", abs(normal["account_z"]) < 3,
          f"z={normal['account_z']}")
    check("a 100x amount is flagged", big["account_z"] > 3,
          f"z={big['account_z']}")
    check("and the z is readable, not astronomical", big["account_z"] < 100,
          f"z={big['account_z']}")
    check("typical amount reported in currency units",
          40 < normal["account_mean"] < 60, f"mean={normal['account_mean']}")
    print(f"        account typical spend : {normal['account_mean']}")
    print(f"        z for 55              : {normal['account_z']}")
    print(f"        z for 5000            : {big['account_z']}")
    s.close()


def test_space_mismatch_is_refused():
    print("\n[12] Reopening a db in the wrong space is refused")
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "space.db")

    s = BaselineStore(path, global_mean=88.0, global_std=250.0, log_space=False)
    for i in range(50):
        s.observe("I", 100.0 + i, ts=float(i * 60))
    s.close()

    raised = False
    try:
        BaselineStore(path, global_mean=88.0, global_std=250.0, log_space=True)
    except ValueError as e:
        raised = True
        msg = str(e)
    check("mismatch raises rather than silently misreading", raised)
    if raised:
        check("error explains the fix", "BASELINE_LOG_SPACE" in msg)
        print(f"        {msg.splitlines()[0]}")

    ok = BaselineStore(path, global_mean=88.0, global_std=250.0, log_space=False)
    check("reopening in the original space works", ok.load("I").n == 50)
    ok.close()


def test_to_space_roundtrip():
    print("\n[13] to_space transform")
    check("log1p handles zero", math.isclose(to_space(0.0, True), 0.0))
    check("log1p handles negatives defensively",
          math.isfinite(to_space(-5.0, True)))
    check("raw mode is identity", to_space(123.45, False) == 123.45)
    check("log1p is monotonic", to_space(10, True) < to_space(100, True) < to_space(1000, True))
    print(f"        log1p: 0 -> {to_space(0,True):.4f}   "
          f"100 -> {to_space(100,True):.4f}   5000 -> {to_space(5000,True):.4f}")


def test_thread_safety():
    print("\n[14] Usable from a worker thread (FastAPI runs sync endpoints off-main)")
    import threading, tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "threads.db")
    s = BaselineStore(path, global_mean=88.0, global_std=250.0)

    errors = []

    def worker(tag):
        try:
            for i in range(50):
                s.observe(f"ACC-{tag}", 100.0 + i, ts=float(i * 60))
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check("no cross-thread sqlite error", not errors, str(errors[:1]))
    st = s.stats()
    check("all writes landed", st["transactions_seen"] == 200,
          f"seen={st['transactions_seen']}")
    check("all accounts created", st["accounts"] == 4, f"accounts={st['accounts']}")
    print(f"        4 threads x 50 observations -> {st['transactions_seen']} rows, "
          f"{st['accounts']} accounts")
    s.close()


def test_escalation_policy():
    print("\n[15] Class 10 escalation policy")

    def sev(z, vel, ml, **kw):
        return combine_severity(z, z, vel, ml, True, **kw)[0]

    legacy = dict(min_signals=1, require_ml=False)
    check("legacy: model alone alerts",
          sev(0.0, 0, True, **legacy) == "medium")
    check("legacy: amount alone alerts",
          sev(9.0, 0, False, **legacy) == "medium")
    check("legacy: velocity alone alerts",
          sev(0.0, 20, False, **legacy) == "medium")
    check("legacy: two signals go high",
          sev(9.0, 0, True, **legacy) == "high")

    consensus = dict(min_signals=2, require_ml=False)
    check("consensus: model alone is silent",
          sev(0.0, 0, True, **consensus) == "normal")
    check("consensus: two signals alert",
          sev(9.0, 0, True, **consensus) == "medium")
    check("consensus: three signals go high",
          sev(9.0, 20, True, **consensus) == "high")

    ml_req = dict(require_ml=True)
    check("class 10: no model flag is silent however odd the amount",
          sev(99.0, 20, False, **ml_req) == "normal")
    check("class 10: model alone alerts",
          sev(0.0, 0, True, **ml_req) == "medium")
    check("class 10: model plus one signal goes high",
          sev(9.0, 0, True, **ml_req) == "high")
    check("class 10: model plus velocity goes high",
          sev(0.0, 20, True, **ml_req) == "high")

    check("class 10 keeps every catch the model makes",
          sev(0.0, 0, True, **ml_req) != "normal"
          and sev(0.0, 0, True, **legacy) != "normal")

    _, why = combine_severity(99.0, 99.0, 0, False, True, require_ml=True)
    check("suppressed events still explain themselves",
          any("not escalated" in r for r in why), why)

    import os
    check("policy is env-overridable",
          "REQUIRE_ML" in open(
              os.path.join(os.path.dirname(__file__), "..", "src",
                           "baseline_store.py")).read())


def test_replay_clock_never_goes_backwards():
    print("\n[16] Replay reset must not rewind the arrival clock")
    import importlib.util, os
    spec = importlib.util.spec_from_file_location(
        "replay", os.path.join(os.path.dirname(__file__), "..", "src", "replay.py"))
    replay_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay_mod)

    import threading
    r = replay_mod.Replay.__new__(replay_mod.Replay)
    r._pos = 0
    r._clock = 0
    r._lock = threading.RLock()
    r.seconds_between = 120.0
    r.n_accounts = 8

    def tick():
        r._pos += 1
        r._clock += 1
        return float(r._clock * r.seconds_between)

    first = [tick() for _ in range(10)]
    replay_mod.Replay.reset(r)
    second = [tick() for _ in range(10)]

    check("clock keeps rising across a reset", second[0] > first[-1],
          f"{first[-1]} -> {second[0]}")
    check("no arrival time is reused", not (set(first) & set(second)))
    check("row position did rewind", r._pos == 10, f"pos={r._pos}")

    s = BaselineStore(":memory:", global_mean=88.0, global_std=250.0,
                      log_space=False)
    for t in first + second:
        f = s.observe("CARD-00", 50.0, ts=t)
    check("velocity is not inflated by the replayed run",
          f["txn_count_1h"] <= 20, f"count={f['txn_count_1h']}")
    print(f"        run 1 ended at t={first[-1]}, run 2 started at t={second[0]}")
    print(f"        txn_count_1h after both runs = {f['txn_count_1h']}")
    s.close()


if __name__ == "__main__":
    random.seed(42)
    for t in [test_welford_matches_batch, test_naive_formula_fails,
              test_ewma_adapts_to_drift, test_cold_start,
              test_no_self_contamination, test_per_account_beats_global,
              test_velocity, test_persistence, test_constant_account,
              test_log_space_removes_small_sample_bias,
              test_log_space_still_detects_outliers,
              test_space_mismatch_is_refused,
              test_to_space_roundtrip,
              test_thread_safety,
              test_escalation_policy,
              test_replay_clock_never_goes_backwards]:
        t()

    print("\n" + "=" * 58)
    print(f"  {PASS} passed, {FAIL} failed")
    print("=" * 58)
    sys.exit(1 if FAIL else 0)
