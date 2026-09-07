#!/usr/bin/env bash
# Class 11 - front end only: landing, setup, checkout, dashboard. No n8n needed.
set -e

cd "$(dirname "$0")"

if [ -z "$VIRTUAL_ENV" ]; then
  for v in myproject ~/myproject .venv venv; do
    if [ -f "$v/bin/activate" ]; then
      # shellcheck disable=SC1090
      source "$v/bin/activate"
      echo "venv: $VIRTUAL_ENV"
      break
    fi
  done
fi

if ! python -c "import uvicorn" 2>/dev/null; then
  echo "uvicorn not found. Activate your venv first, or:  pip install -r requirements.txt"
  exit 1
fi

[ -f .env ] && { set -a; source .env; set +a; }

if lsof -ti tcp:8000 >/dev/null 2>&1; then
  echo "Port 8000 is already in use. Stop the old service first:"
  echo "    kill \$(lsof -ti tcp:8000)"
  exit 1
fi

echo
echo "  landing    http://127.0.0.1:8000/"
echo "  setup      http://127.0.0.1:8000/setup"
echo "  checkout   http://127.0.0.1:8000/checkout"
echo "  dashboard  http://127.0.0.1:8000/dashboard"
echo
echo "  Ctrl-C to stop."
echo

( sleep 2; open http://127.0.0.1:8000/ 2>/dev/null || true ) &

cd src
exec uvicorn scoring_service:app --host 127.0.0.1 --port 8000 --reload
