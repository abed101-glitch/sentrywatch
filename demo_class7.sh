#!/usr/bin/env bash
set -u

if [ -z "${VIRTUAL_ENV:-}" ] && [ -f "$HOME/myproject/bin/activate" ]; then
  source "$HOME/myproject/bin/activate"
fi

if ! python3 -c "import numpy, pandas" 2>/dev/null; then
  echo "python is missing numpy/pandas. Activate the venv first:"
  echo "  source ~/myproject/bin/activate"
  exit 1
fi

BOLD=$'\033[1m'; DIM=$'\033[2m'; OFF=$'\033[0m'

pause () { echo; read -rp "${DIM}[ENTER]${OFF}" _; echo; }
say   () { echo; echo "${BOLD}$1${OFF}"; [ -n "${2:-}" ] && echo "${DIM}$2${OFF}"; echo; }

clear 2>/dev/null || true
cat <<'BANNER'
==========================================================
  CSE 299 - Class 7
  Per-Account Behavioural Baselines
  Abed Gazi (2132538642)
==========================================================
BANNER

say "THE PROBLEM" \
"Classes 2-6 compared every transaction to ONE global mean (93.27).
 A 900 charge scores z=3.25 whether it is a business that spends 900
 every week, or a student who has never spent over 40.
 The proposal promised per-account baselines. I had not built them."
pause

say "1/4  CORRECTNESS - 46 tests" \
"Streaming statistics must equal batch statistics.
 Watch test 2: the textbook variance formula returns a NEGATIVE number."
cd tests && python3 test_baseline_store.py; cd ..
pause

say "2/4  COST - can it run in real time?" \
"An accurate baseline that is slow is useless in a live pipeline."
cd src && python3 simulate_stream.py --benchmark; cd ..
pause

say "3/4  THE RESULT I DID NOT EXPECT" \
"Per-account flagged 994 vs global's 482 - double the false positives,
 and caught 2 frauds vs 0 out of 60. With n=60 that difference is noise.
 Twice the alerts, no gain. I did not accept that - I diagnosed it."
cd src && python3 simulate_stream.py --rows 50000 --accounts 500 --assign random; cd ..
pause

say "4/4  DIAGNOSIS AND FIX" \
"Hypothesis: amounts are heavy-tailed (skewness 11.9). The sample std of
 a heavy-tailed variable is biased LOW at small n - a short sample rarely
 contains the tail. Smaller denominator => inflated z => more flags.
 Test A: vary history length.  Test B: measure the bias directly.
 Test C: rerun with statistics kept on log1p(amount)."
cd src && python3 diagnose_history_length.py; cd ..
pause

cat <<'SUMMARY'
  DELIVERED
    - the per-entity baselining the proposal specified, 46 tests passing
    - 0.0082 ms/transaction, 127 bytes/account, storage O(accounts)
    - found a calibration bug nobody had noticed:
          z > 3 was actually firing at z ~ 1.69
    - fixed it by changing scale, not by adding data:

        detector              flags    rate     vs theoretical 0.135%
        global (raw)            482   1.928%          14.3x
        per-account (raw)       994   3.977%          29.5x
        per-account (log1p)      60   0.240%           1.8x

      94% fewer false positives. The per-account baseline is now BETTER
      calibrated than the global one it was competing against - and the
      global one was 14.3x off, which I never checked in Class 6.

    - flag ratio went FLAT across history length (0.12 -> 0.08),
      where raw drifted 2.06 -> 1.30. An account with 50 transactions is
      now judged the same as one with 1000. That flatness - not the lower
      number - is the evidence the bias is gone.

  NOT DELIVERED
    - any improvement in fraud detection. 2/60 raw, 0/60 log. Both zero.
      This matches my Class 2 finding: fraud in this dataset is not an
      amount anomaly. The signal is in V1-V28, as Class 4 showed.
      Refining the yardstick does not help when the quantity being
      measured does not separate the classes.

  LIMITATION I AM NOT HIDING
    - creditcard.csv has no account column, so account IDs are synthetic.
      This shows the machinery works and what it costs. It is NOT evidence
      of a recall improvement. I run both 'random' (the null case, where
      per-account adds nothing) and 'profiled' modes and report both.
SUMMARY
echo
echo "${BOLD}Questions?${OFF}"
echo
