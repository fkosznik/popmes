#!/usr/bin/env bash
# Consistent database + media snapshot. The backend is stopped briefly.
# Off-site copy runs only when restic is configured. This script never prints secrets.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
backup_root="${BACKUP_DIR:-./backups}"
mkdir -p "$backup_root"
chmod 700 "$backup_root"
backup_target="$backup_root/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$backup_target"
chmod 700 "$backup_target"
cleanup() { docker compose start backend >/dev/null || true; }
trap cleanup EXIT
docker compose stop backend
docker compose exec -T database sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_target/database.dump"
docker compose run --rm --no-deps -T --user root --entrypoint tar backend -C /app/media -czf - . > "$backup_target/media.tar.gz"
(cd "$backup_target" && sha256sum database.dump media.tar.gz > SHA256SUMS)
keep="${BACKUP_KEEP:-14}"
old_dirs=()
while IFS= read -r dir; do
  old_dirs+=("$dir")
done < <(find "$backup_root" -mindepth 1 -maxdepth 1 -type d | sort)
if [ "${#old_dirs[@]}" -gt "$keep" ]; then
  remove=$((${#old_dirs[@]} - keep))
  index=0
  while [ "$index" -lt "$remove" ]; do
    rm -rf "${old_dirs[$index]}"
    index=$((index + 1))
  done
fi
date -u +%Y-%m-%dT%H:%M:%SZ > "$backup_root/LAST_SUCCESS"
rm -f "$backup_root/LAST_FAILURE"
printf 'Local backup created: %s\n' "$backup_target"
offsite="${RESTIC_REPOSITORY:-}"
if [ -z "$offsite" ]; then
  echo "Off-site backup was not run. Set RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE to enable it."
  echo "not_configured" > "$backup_root/OFFSITE_STATUS"
  exit 0
fi
if [ -z "${RESTIC_PASSWORD_FILE:-}" ] || [ ! -f "$RESTIC_PASSWORD_FILE" ]; then
  echo "RESTIC_REPOSITORY is set but RESTIC_PASSWORD_FILE is missing. Local backup is kept." >&2
  echo "failed" > "$backup_root/OFFSITE_STATUS"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$backup_root/LAST_FAILURE"
  exit 1
fi
if ! command -v restic >/dev/null 2>&1; then
  echo "restic is not installed on this host. Local backup is kept; off-site copy was not made." >&2
  echo "restic_missing" > "$backup_root/OFFSITE_STATUS"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$backup_root/LAST_FAILURE"
  exit 1
fi
export RESTIC_PASSWORD_FILE
restic backup "$backup_target" --tag popmes
restic forget --tag popmes --prune \
  --keep-daily "${RESTIC_KEEP_DAILY:-14}" \
  --keep-weekly "${RESTIC_KEEP_WEEKLY:-8}" \
  --keep-monthly "${RESTIC_KEEP_MONTHLY:-12}"
date -u +%Y-%m-%dT%H:%M:%SZ > "$backup_root/OFFSITE_SUCCESS"
echo "ok" > "$backup_root/OFFSITE_STATUS"
echo "Off-site restic copy finished. The repository password file must stay outside that repository."
