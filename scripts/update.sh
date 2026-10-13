#!/usr/bin/env bash
# Update this checkout to a specific commit or tag. Does not restore the database
# and does not upgrade the PostgreSQL major version.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" = "" ] || [ "${2:-}" != "--verified" ]; then
  echo "Usage: bash scripts/update.sh <tag-or-commit> --verified" >&2
  echo "Pass --verified only after the required GitHub checks for that revision are green." >&2
  exit 1
fi
target="$1"
lock_dir="${PWD}/.update.lock"
if ! mkdir "$lock_dir" 2>/dev/null; then
  echo "Another update holds ${lock_dir}. Wait until it finishes." >&2
  exit 1
fi
cleanup() { rmdir "$lock_dir" 2>/dev/null || true; }
trap cleanup EXIT
if [ ! -f .env ]; then
  echo "Missing .env. Refusing to update." >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "The working tree has local changes. Commit or remove them before updating." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
if [ "${DEBUG:-0}" = "1" ]; then
  echo "DEBUG=1. Refusing to update a production checkout with debug enabled." >&2
  exit 1
fi
if [ -z "${DJANGO_SECRET_KEY:-}" ] || [ -z "${POSTGRES_PASSWORD:-}" ]; then
  echo ".env is missing DJANGO_SECRET_KEY or POSTGRES_PASSWORD." >&2
  exit 1
fi
git fetch --tags origin
if ! git rev-parse --verify --quiet "${target}^{commit}" >/dev/null; then
  echo "Cannot resolve ${target}." >&2
  exit 1
fi
current="$(git rev-parse HEAD)"
resolved="$(git rev-parse "${target}^{commit}")"
mkdir -p updates
printf '%s current=%s target=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current" "$resolved" >> updates/history.log
echo "Building images for ${resolved} before stopping the application."
git checkout --detach "$resolved"
files=(-f compose.yaml)
if [ "${USE_HTTPS:-0}" = "1" ]; then
  files+=(-f compose.https.yaml)
fi
docker compose "${files[@]}" build
echo "Stopping the backend so backup and migrations see a quiet database."
docker compose "${files[@]}" stop backend
if ! bash scripts/backup.sh; then
  echo "Backup failed. Backend is stopped. Restore the previous code with:" >&2
  echo "  git checkout ${current} && docker compose ${files[*]} up -d" >&2
  echo "Do not run restore unless you intend to discard writes made after the last good backup." >&2
  exit 1
fi
# backup.sh starts the backend again. Stop it before migrating.
docker compose "${files[@]}" stop backend
if ! bash scripts/migrate.sh; then
  echo "Migration failed. The new code is checked out and the backend is stopped." >&2
  echo "The database was not restored. A backup was written before the migration." >&2
  echo "Code rollback (does not undo migrations):" >&2
  echo "  git checkout ${current}" >&2
  echo "  docker compose ${files[*]} up -d" >&2
  echo "Database rollback is a separate, explicit restore of that backup." >&2
  echo "Restoring it discards every write made after the backup." >&2
  exit 1
fi
docker compose "${files[@]}" up -d
echo "Waiting for health checks."
if ! docker compose "${files[@]}" up -d --wait --wait-timeout 180; then
  echo "Containers did not become healthy." >&2
  echo "Inspect: docker compose ${files[*]} ps && docker compose ${files[*]} logs --tail 80" >&2
  echo "Code rollback: git checkout ${current} && docker compose ${files[*]} up -d --build" >&2
  echo "That does not return the database to the backup. Run scripts/restore.sh only when you accept losing later writes." >&2
  exit 1
fi
if ! curl -fsS --max-time 10 "http://127.0.0.1:${APP_PORT:-8080}/api/health/" >/dev/null; then
  echo "Health endpoint did not answer on 127.0.0.1:${APP_PORT:-8080}." >&2
  exit 1
fi
echo "Update finished. Running ${resolved}. Previous revision ${current}."
echo "PostgreSQL major version was not changed."
