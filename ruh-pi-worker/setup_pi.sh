#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

sudo apt update
sudo apt install -y python3 python3-venv python3-pip ca-certificates

python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/pip install -r requirements-pi.txt

mkdir -p data/downloads logs
chmod 700 data logs

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created .env. Add your credentials before running the worker."
else
  chmod 600 .env
  echo ".env already exists; it was not overwritten."
fi

USER_NAME="$(whoami)"
PROJECT_DIR="$(pwd)"

echo
echo "Setup complete."
echo "1. Edit: nano ${PROJECT_DIR}/.env"
echo "2. Test: ${PROJECT_DIR}/venv/bin/python ${PROJECT_DIR}/run_cycle.py"
echo "3. Health: ${PROJECT_DIR}/venv/bin/python ${PROJECT_DIR}/healthcheck.py"
echo "4. Add this with: crontab -e"
echo "*/5 * * * * ${PROJECT_DIR}/venv/bin/python ${PROJECT_DIR}/run_cycle.py >> ${PROJECT_DIR}/logs/cron.log 2>&1"
