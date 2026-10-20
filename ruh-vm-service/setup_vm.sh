#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [[ ! -d venv ]]; then
  if ! python3 -m venv venv 2>/dev/null; then
    echo "python3 -m venv failed; trying user-installed virtualenv"
    python3 -m pip install --user virtualenv
    python3 -m virtualenv venv
  fi
fi

./venv/bin/python -m pip install --upgrade pip
./venv/bin/pip install -r requirements-vm.txt
mkdir -p data/uploads data/staging data/run logs
chmod +x start_api.sh stop_api.sh ensure_api.sh worker_cycle.py healthcheck.py
./venv/bin/python -c "import database; database.init_db(); print('Database initialized:', database.DB_PATH)"

USER_NAME="$(whoami)"
echo
echo "Setup complete. Edit: $BASE_DIR/.env"
echo "Then start API: $BASE_DIR/start_api.sh"
echo
echo "Add these lines using: crontab -e"
echo "@reboot sleep 20 && $BASE_DIR/start_api.sh >> $BASE_DIR/logs/startup.log 2>&1"
echo "*/2 * * * * $BASE_DIR/ensure_api.sh >> $BASE_DIR/logs/watchdog.log 2>&1"
echo "* * * * * flock -n $BASE_DIR/data/run/cron-worker.lock $BASE_DIR/venv/bin/python $BASE_DIR/worker_cycle.py >> $BASE_DIR/logs/cron-worker.log 2>&1"
