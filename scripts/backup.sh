#!/usr/bin/env bash
# Consistent database + media snapshot.
# A normal backup resumes the application before a long off-site upload.
# During an update, POPMES_KEEP_BACKEND_STOPPED=1 leaves the backend stopped.
# This script never prints secrets.
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/ops-common.sh"
ops_root
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
compose_args
ops_lock
backend_was_running=0
if docker compose "${COMPOSE_ARGS[@]}" ps --status running --services 2>/dev/null | grep -qx backend; then
  backend_was_running=1
fi
resumed=0
resume_backend() {
  if [ "${POPMES_KEEP_BACKEND_STOPPED:-0}" = "1" ]; then
    return
  fi
  if [ "$backend_was_running" = "1" ] && [ "$resumed" = "0" ]; then
    docker compose "${COMPOSE_ARGS[@]}" start backend >/dev/null || true
    resumed=1
  fi
}
cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ -n "${backup_root:-}" ] && [ -f "$backup_root/LOCAL_STATUS" ]; then
    local_state="$(sed -n '1p' "$backup_root/LOCAL_STATUS" 2>/dev/null || true)"
    if [ "$local_state" = "running" ]; then
      mark_local failed || true
    fi
  fi
  resume_backend
  ops_unlock
  exit "$status"
}
trap cleanup EXIT
backup_root="${BACKUP_DIR:-./backups}"
mkdir -p "$backup_root"
chmod 700 "$backup_root"
require_positive_int BACKUP_KEEP "${BACKUP_KEEP:-14}"
keep="${BACKUP_KEEP:-14}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_target="$backup_root/$stamp"
# Two backups in the same second must not share a directory.
if ! mkdir "$backup_target" 2>/dev/null; then
  backup_target="$backup_root/${stamp}-$$"
  mkdir "$backup_target"
fi
chmod 700 "$backup_target"
mark_local() {
  local when
  when="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  write_atomic "$backup_root/LOCAL_STATUS" "${1}"$'\n'"${when}"
}
mark_offsite() {
  local when
  when="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  write_atomic "$backup_root/OFFSITE_STATUS" "$1"
  write_atomic "$backup_root/OFFSITE_ATTEMPT" "$when"
}
fail_local() {
  mark_local "$1"
  echo "Local backup failed (${1}). The previous successful copy was kept." >&2
  exit 1
}
fail_offsite() {
  mark_offsite "$1"
  write_atomic "$backup_root/LAST_FAILURE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "Off-site backup failed ($1). The previous successful off-site copy was kept." >&2
  exit 1
}
mark_local running
docker compose "${COMPOSE_ARGS[@]}" stop backend
if ! docker compose "${COMPOSE_ARGS[@]}" exec -T database sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_target/database.dump"; then
  rm -rf "$backup_target"
  echo "pg_dump failed. Backend state: stopped=$([ "${POPMES_KEEP_BACKEND_STOPPED:-0}" = 1 ] && echo yes || echo no)." >&2
  fail_local dump_failed
fi
if ! docker compose "${COMPOSE_ARGS[@]}" run --rm --no-deps -T --user root --entrypoint tar backend -C /app/media -czf - . > "$backup_target/media.tar.gz"; then
  rm -rf "$backup_target"
  echo "Media archive failed." >&2
  fail_local media_failed
fi
if ! (cd "$backup_target" && sha256sum database.dump media.tar.gz > SHA256SUMS && sha256sum -c SHA256SUMS >/dev/null); then
  rm -rf "$backup_target"
  echo "Checksum failed. The incomplete directory was removed." >&2
  fail_local checksum_failed
fi
old_dirs=()
while IFS= read -r dir; do
  [ "$dir" = "$backup_target" ] && continue
  old_dirs+=("$dir")
done < <(find "$backup_root" -mindepth 1 -maxdepth 1 -type d | sort)
# Keep this copy plus the newest previous copies. Never delete the copy just made.
if [ "${#old_dirs[@]}" -ge "$keep" ]; then
  remove=$((${#old_dirs[@]} - keep + 1))
  index=0
  while [ "$index" -lt "$remove" ]; do
    rm -rf "${old_dirs[$index]}"
    index=$((index + 1))
  done
fi
write_atomic "$backup_root/LAST_SUCCESS" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mark_local ok
printf 'Local backup created: %s\n' "$backup_target"
resume_backend
offsite="${RESTIC_REPOSITORY:-}"
if [ -z "$offsite" ]; then
  mark_offsite "not_configured"
  echo "Off-site backup was not run. Set RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE to enable it."
  exit 0
fi
mark_offsite "running"
if [ -z "${RESTIC_PASSWORD_FILE:-}" ] || [ ! -f "$RESTIC_PASSWORD_FILE" ]; then
  fail_offsite "password_missing"
fi
if ! command -v restic >/dev/null 2>&1; then
  fail_offsite "restic_missing"
fi
require_positive_int RESTIC_KEEP_DAILY "${RESTIC_KEEP_DAILY:-14}"
require_positive_int RESTIC_KEEP_WEEKLY "${RESTIC_KEEP_WEEKLY:-8}"
require_positive_int RESTIC_KEEP_MONTHLY "${RESTIC_KEEP_MONTHLY:-12}"
export RESTIC_PASSWORD_FILE
if ! restic backup "$backup_target" --tag popmes; then
  fail_offsite "backup_failed"
fi
if ! restic forget --tag popmes --prune \
  --keep-daily "${RESTIC_KEEP_DAILY:-14}" \
  --keep-weekly "${RESTIC_KEEP_WEEKLY:-8}" \
  --keep-monthly "${RESTIC_KEEP_MONTHLY:-12}" \
  --keep-last 1; then
  fail_offsite "prune_failed"
fi
write_atomic "$backup_root/OFFSITE_SUCCESS" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mark_offsite "ok"
echo "Off-site restic copy finished. The password file must stay outside that repository."
