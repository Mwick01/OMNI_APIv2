# RUH Notice Bot — Raspberry Pi Worker

This package performs only the home-network side of the system:

1. Logs in to the active FOSMIS portal (`/fosmis/`) only.
2. Scans the notice tables every five minutes.
3. Stores every notice identity in local SQLite before downloading.
4. Downloads new notice files atomically.
5. Keeps unsent notices in a durable outbox.
6. Uploads pending notices to the GCP receiver when it is available.

It does **not** run OpenAI, WhatsApp, deadlines, or the main VM database.

## New-notice detection

The final decision is based on a deterministic `notice_key`, not only the date.
The key is a SHA-256 hash of:

- portal/source
- normalized title
- website date/time
- normalized download URL

### First successful run

The worker scans up to `SCAN_ROW_LIMIT` rows. Notices inside
`INITIAL_LOOKBACK_HOURS` are queued. Older visible rows are inserted as
`baseline_ignored`; this prevents the first run from sending a large historical
backlog and prevents those same rows from appearing as new later.

### Later runs

Every visible row is checked. A row whose key is already in SQLite is ignored.
An unseen key is queued even if its website timestamp is duplicated or older
than the previous newest timestamp. The portal's latest timestamp is still
remembered for diagnostics, but it is not the sole duplicate rule.

## Failure behaviour

- FOSMIS unavailable: cursor is not advanced; portal retry backoff is recorded.
- Power loss during download: only a `.part` file exists; the notice stays queued.
- VM unavailable: files remain `pending_upload`/`upload_failed` in SQLite.
- VM stores a notice but the reply is lost: the Pi retries with the same
  `Idempotency-Key`; the VM must return a duplicate acknowledgement.
- A prior cycle is still running: the new cycle exits without overlap.

## Install on the Pi

Copy/extract this directory to the Pi, then:

```bash
cd ~/ruh-pi-worker
chmod +x setup_pi.sh
./setup_pi.sh
nano .env
```

Fill `SITE_USERNAME` and `SITE_PASSWORD`. Leave `VM_INGEST_URL` and
`PI_API_TOKEN` blank until the GCP receiver is built.

Test manually:

```bash
./venv/bin/python run_cycle.py
./venv/bin/python healthcheck.py
```

Inspect logs:

```bash
tail -f logs/pi-worker.log
```

## Schedule every five minutes

Run:

```bash
crontab -e
```

Add the exact line printed by `setup_pi.sh`, similar to:

```cron
*/5 * * * * /home/YOUR_USER/ruh-pi-worker/venv/bin/python /home/YOUR_USER/ruh-pi-worker/run_cycle.py >> /home/YOUR_USER/ruh-pi-worker/logs/cron.log 2>&1
```

Check cron output:

```bash
tail -f ~/ruh-pi-worker/logs/cron.log
```

## Useful SQLite checks

```bash
sudo apt install -y sqlite3
sqlite3 data/pi_state.db \
  "SELECT status, COUNT(*) FROM notice_outbox GROUP BY status;"
```

Recent queued notices:

```bash
sqlite3 -header -column data/pi_state.db \
  "SELECT id, source, date_on_site, status, substr(title,1,60) AS title FROM notice_outbox ORDER BY id DESC LIMIT 20;"
```

Portal state:

```bash
sqlite3 -header -column data/pi_state.db "SELECT * FROM portal_state;"
```

## Resetting the first-run baseline

Do this only if you deliberately want a fresh bootstrap:

```bash
rm -f data/pi_state.db data/pi_state.db-shm data/pi_state.db-wal
```

The next run will again treat older visible rows as the baseline.

## Scan performance tuning

The worker remembers the newest successfully staged website timestamp per portal. On later runs it rechecks an overlap window and stops after several consecutive older rows:

```env
SCAN_OVERLAP_HOURS=24
EARLY_STOP_OLD_ROWS=10
SCAN_ROW_LIMIT=200
```

`SCAN_OVERLAP_HOURS` protects against duplicate timestamps and slightly late postings. `EARLY_STOP_OLD_ROWS` avoids stopping on a single out-of-order row. Notice keys remain the final duplicate authority. Portal staging is committed in one SQLite transaction per scan. Timing logs show fetch, parse, DB, and total durations for each portal.
