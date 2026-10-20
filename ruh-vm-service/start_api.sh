#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"
mkdir -p logs data/run
PID_FILE="$BASE_DIR/data/run/api.pid"

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    echo "API already running with PID $PID"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

set -a
source "$BASE_DIR/.env"
set +a

nohup "$BASE_DIR/venv/bin/uvicorn" ingestion_api:app \
  --host "${API_HOST:-127.0.0.1}" \
  --port "${API_PORT:-8100}" \
  --workers 1 \
  >> "$BASE_DIR/logs/api.log" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
sleep 3
if kill -0 "$PID" 2>/dev/null; then
  echo "API started with PID $PID"
else
  echo "API failed to start. Check logs/api.log" >&2
  rm -f "$PID_FILE"
  exit 1
fi
