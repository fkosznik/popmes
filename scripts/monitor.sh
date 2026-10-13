#!/usr/bin/env bash
# Host checks for one VM: health, disk, and the age of the last backup.
# Prints status lines only. Does not print secrets. Exit 1 when something is wrong.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
fail=0
url="${MONITOR_URL:-http://127.0.0.1:${APP_PORT:-8080}/api/health/}"
if ! curl -fsS --max-time 10 "$url" >/dev/null; then
  echo "health: down ${url}"
  fail=1
else
  echo "health: ok"
fi
threshold="${DISK_ALERT_PERCENT:-90}"
usage="$(df -P . | awk 'NR==2 {gsub("%","",$5); print $5}')"
if [ "$usage" -ge "$threshold" ]; then
  echo "disk: ${usage}% used (threshold ${threshold}%)"
  fail=1
else
  echo "disk: ${usage}% used"
fi
backup_root="${BACKUP_DIR:-./backups}"
now=$(date -u +%s)
stamp="$backup_root/LAST_SUCCESS"
max_age_hours="${BACKUP_MAX_AGE_HOURS:-30}"
if [ ! -f "$stamp" ]; then
  echo "backup: no LAST_SUCCESS"
  fail=1
else
  # GNU date on the VM. macOS date cannot parse this; the check is for the server.
  then=$(date -u -d "$(cat "$stamp")" +%s 2>/dev/null || echo 0)
  age_hours=$(( (now - then) / 3600 ))
  if [ "$then" -eq 0 ] || [ "$age_hours" -ge "$max_age_hours" ]; then
    echo "backup: last success is ${age_hours}h old"
    fail=1
  else
    echo "backup: last success ${age_hours}h ago"
  fi
fi
status="unknown"
if [ -f "$backup_root/OFFSITE_STATUS" ]; then
  status="$(cat "$backup_root/OFFSITE_STATUS")"
fi
echo "offsite: ${status}"
if [ "$status" != "ok" ] && [ "$status" != "not_configured" ]; then
  fail=1
fi
if [ "${OFFSITE_REQUIRED:-0}" = "1" ] && [ "$status" != "ok" ]; then
  echo "offsite: required but last attempt is ${status}"
  fail=1
fi
if [ "$status" = "ok" ]; then
  offsite_stamp="$backup_root/OFFSITE_SUCCESS"
  if [ ! -f "$offsite_stamp" ]; then
    echo "offsite: status ok without a success timestamp"
    fail=1
  else
    offsite_then=$(date -u -d "$(cat "$offsite_stamp")" +%s 2>/dev/null || echo 0)
    offsite_age=$(( (now - offsite_then) / 3600 ))
    if [ "$offsite_then" -eq 0 ] || [ "$offsite_age" -ge "$max_age_hours" ]; then
      echo "offsite: last success is ${offsite_age}h old"
      fail=1
    fi
  fi
fi
if [ -n "${ALERT_WEBHOOK_URL:-}" ] && [ "$fail" -ne 0 ]; then
  curl -fsS --max-time 10 -H "Content-Type: text/plain" --data "POPMES monitor failed on $(hostname)" "$ALERT_WEBHOOK_URL" >/dev/null || true
fi
exit "$fail"
