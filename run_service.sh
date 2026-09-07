#!/usr/bin/env bash
set -u

cd "$(dirname "$0")"

if [ -z "${VIRTUAL_ENV:-}" ] && [ -f "$HOME/myproject/bin/activate" ]; then
  source "$HOME/myproject/bin/activate"
fi

if ! python3 -c "import uvicorn, fastapi, joblib, pandas, requests" 2>/dev/null; then
  echo "missing packages. run:  source ~/myproject/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [ -f .env ]; then
  set -a; source .env; set +a
  echo "  env loaded  telegram=$([ -n "${TELEGRAM_BOT_TOKEN:-}" ] && echo yes || echo NO)"
else
  echo "  no .env found - alerts will not send"
fi

echo "  dashboard   http://127.0.0.1:8000/dashboard"
echo

cd src
exec python3 -m uvicorn scoring_service:app --host 127.0.0.1 --port 8000 --reload
