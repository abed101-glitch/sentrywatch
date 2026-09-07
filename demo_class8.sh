#!/usr/bin/env bash
set -u

if [ -z "${VIRTUAL_ENV:-}" ] && [ -f "$HOME/myproject/bin/activate" ]; then
  source "$HOME/myproject/bin/activate"
fi

PY=python3
if ! $PY -c "import requests" 2>/dev/null; then
  echo "python is missing 'requests'. Activate the venv first:"
  echo "  source ~/myproject/bin/activate"
  exit 1
fi

API=http://127.0.0.1:8000
BOLD=$'\033[1m'; DIM=$'\033[2m'; GRN=$'\033[32m'; RED=$'\033[31m'; OFF=$'\033[0m'

pause () { echo; read -rp "${DIM}[ENTER]${OFF}" _; echo; }
say   () { echo; echo "${BOLD}$1${OFF}"; [ -n "${2:-}" ] && echo "${DIM}$2${OFF}"; echo; }

txn () {
  printf '{"Time":50000,"Amount":%s,"account_id":"%s"' "$1" "$2"
  for i in $(seq 1 28); do printf ',"V%d":0' "$i"; done
  printf '}'
}

fire () {
  curl -s -X POST "$API/score-and-alert" -H "Content-Type: application/json" \
    -d "$(txn "$1" "$2")" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin); a = r['alert']
mark = '$GRN'+'ALERT SENT'+'$OFF' if a['sent'] else '$DIM'+'suppressed'+'$OFF'
extra = a.get('suppression_reason','')[:52] if a['suppressed'] else ''
roll  = f\"  (rolled up {a['rolled_up_events']} suppressed)\" if a.get('rolled_up_events') else ''
print(f\"    {r['severity']:>6}  {mark}{roll}  {extra}\")
"
}

clear 2>/dev/null || true
cat <<'BANNER'
==========================================================
  CSE 299 - Class 8
  Real-Time Alerting
  Abed Gazi (2132538642)
==========================================================
BANNER

if ! curl -s --max-time 3 "$API/health" > /dev/null; then
  echo "${RED}Service not running on $API${OFF}"
  echo "Start it in another terminal:"
  echo "  cd ~/Downloads/CSE299_Project/src"
  echo "  set -a && source ../.env && set +a"
  echo "  uvicorn scoring_service:app --host 127.0.0.1 --port 8000 --reload"
  exit 1
fi
echo "  service: up"
echo

say "THE PROBLEM" \
"Class 7 gave me per-account baselines but the Switch node in n8n
 had nothing connected to its outputs. Nobody was being told anything.

 And a Class 6 alert would have said only:   z-score: 17.638
 Which tells the shop owner nothing they can act on."
pause

say "1/4  BUILDING REAL ACCOUNT HISTORY" \
"Every number after this is computed by the service, not typed in.
 Sending 60 ordinary transactions each to two accounts with different
 spending habits."
cd src && python3 seed_accounts.py --n 60; cd ..
pause

say "SAME AMOUNT, TWO ACCOUNTS" \
"A 900 charge against each. The global z-score is identical for both -
 it cannot tell them apart. The per-account baseline can."
for acct in ACC-BIZ ACC-STU; do
  printf "  %-8s " "$acct"
  curl -s -X POST "$API/score" -H "Content-Type: application/json" \
    -d "$(txn 900 $acct)" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(f\"typical={r['account_mean']:>8}  global_z={r['global_z']:>6}  \"
      f\"account_z={r['account_z']:>8}  -> {r['severity']}\")
"
done
pause

say "2/4  ONE REAL ALERT   >>> WATCH THE PHONE <<<" \
"A 4,500 charge on the business account, whose real baseline the service
 just learned. The message quotes that computed figure."
fire 4500 ACC-BIZ
echo
echo "${DIM}    ...phone should have buzzed.${OFF}"
pause

say "3/4  THE SAME INCIDENT FIVE TIMES   >>> WATCH THE PHONE <<<" \
"Card testing fires many charges in seconds. Every one is anomalous.
 If each became a notification I would mute the channel by lunch -
 and an alerting system nobody reads is worse than none.

 Five identical transactions, one second apart:"
ACC=ACC-BURST-$RANDOM
for i in 1 2 3 4 5; do
  printf "  event %d:" "$i"
  fire 4500 "$ACC"
done
echo
echo "${BOLD}    5 events in. 1 alert out. The phone buzzed once.${OFF}"
pause

say "4/4  SUPPRESSED IS NOT DISCARDED" \
"Waiting out the 20s cooldown, then sending the same thing again.
 The next alert reports what it absorbed while it was quiet."
for s in 20 15 10 5; do printf "\r    %2ds remaining " "$s"; sleep 5; done
printf "\r                      \r"
printf "  after cooldown:"
fire 4500 "$ACC"
pause

say "THROTTLE STATE" ""
curl -s "$API/alert-stats" | python3 -m json.tool
echo
cat <<'SUMMARY'
  THREE FILTERS BETWEEN "ANOMALOUS" AND "PHONE BUZZES"

    1. severity threshold   only high/medium alert; normal is logged
    2. per-incident cooldown keyed on account + which signals fired,
                            NOT the transaction id - otherwise every
                            event is unique and it never triggers
    3. global hourly cap    circuit breaker for model drift

  Every suppressed event is still logged with its reason. Silent
  suppression I cannot audit would corrupt the Class 10 evaluation -
  I could not tell "the model missed it" from "the throttle ate it".

  30 tests cover this. 76 across the project.
SUMMARY
echo
echo "${BOLD}Questions?${OFF}"
echo
