#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$BASE_DIR/data/run/api.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "No API PID file"
  exit 0
fi
PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  for _ in {1..20}; do
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.5
  done
  kill -9 "$PID" 2>/dev/null || true
fi
rm -f "$PID_FILE"
echo "API stopped"
