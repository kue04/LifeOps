#!/usr/bin/env sh
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_ROOT="${FRONTEND_PATH:-$(cd "$ROOT/../lifeops-front" && pwd)}"
API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

echo "LifeOps local dev"
echo "API:      http://localhost:$API_PORT"
echo "Frontend: http://localhost:$FRONTEND_PORT"
echo

cleanup() {
  kill "$API_PID" "$FRONT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$ROOT" && python -m uvicorn api:app --reload --host 127.0.0.1 --port "$API_PORT") &
API_PID=$!

(cd "$FRONTEND_ROOT" && npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT") &
FRONT_PID=$!

wait
