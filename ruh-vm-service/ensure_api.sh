#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"
mkdir -p data/run logs
exec 9>"$BASE_DIR/data/run/api-watchdog.lock"
flock -n 9 || exit 0

set -a
source "$BASE_DIR/.env"
set +a
PORT="${API_PORT:-8100}"
PID_FILE="$BASE_DIR/data/run/api.pid"

if curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  exit 0
fi

if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    # Process exists but is unhealthy. Restart it.
    "$BASE_DIR/stop_api.sh" || true
  else
    rm -f "$PID_FILE"
  fi
fi

"$BASE_DIR/start_api.sh"
