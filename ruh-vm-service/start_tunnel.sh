#!/bin/bash

BASE_DIR="$HOME/ruh-vm-service"
LOG_DIR="$BASE_DIR/logs"
TOKEN_FILE="$HOME/.cloudflared/ruh-notice-token"

mkdir -p "$LOG_DIR"

# Do nothing if cloudflared is already running with our token file
if pgrep -f "cloudflared tunnel run.*ruh-notice-token" > /dev/null; then
    exit 0
fi

nohup cloudflared tunnel run \
    --token-file "$TOKEN_FILE" \
    >> "$LOG_DIR/cloudflared.log" 2>&1 &

echo $! > "$BASE_DIR/data/run/cloudflared.pid"
