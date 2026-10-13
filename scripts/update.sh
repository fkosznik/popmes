#!/usr/bin/env bash
# Update this checkout to a specific commit. Does not restore the database
# and does not upgrade the PostgreSQL major version.
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/ops-common.sh"
ops_root
if [ "${1:-}" = "" ] || [ "${2:-}" != "--verified" ]; then
  echo "Usage: bash scripts/update.sh <tag-or-commit> --verified" >&2
  exit 1
fi
target="$1"
ops_lock
cleanup() { ops_unlock; }
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
compose_args
if [ "${DEBUG:-0}" = "1" ]; then
  echo "DEBUG=1. Refusing to update a production checkout with debug enabled." >&2
  exit 1
fi
if [ "${POPMES_ENV:-local}" = "production" ]; then
  if [ -z "${POSTGRES_APP_USER:-}" ] || [ -z "${POSTGRES_APP_PASSWORD:-}" ] || [ -z "${POSTGRES_MIGRATE_USER:-}" ] || [ -z "${POSTGRES_MIGRATE_PASSWORD:-}" ]; then
    echo "Production update requires the restricted application and migration roles." >&2
    exit 1
  fi
fi
git fetch --tags origin
if ! git rev-parse --verify --quiet "${target}^{commit}" >/dev/null; then
  echo "Cannot resolve ${target}." >&2
  exit 1
fi
current="$(git rev-parse HEAD)"
resolved="$(git rev-parse "${target}^{commit}")"
repo_slug="$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"
if ! command -v gh >/dev/null 2>&1; then
  echo "gh is not available, so CI for ${resolved} cannot be verified." >&2
  exit 1
fi
checks="$(gh api --jq '.check_runs[] | [.name, .conclusion, .head_sha] | @tsv' "repos/${repo_slug}/commits/${resolved}/check-runs" || true)"
for required in quality application; do
  conclusion="$(printf '%s\n' "$checks" | awk -F '\t' -v name="$required" -v sha="$resolved" '$1 == name && $3 == sha { print $2; exit }')"
  if [ "$conclusion" != "success" ]; then
    echo "Required check ${required} for ${resolved} is '${conclusion:-missing}', not success." >&2
    exit 1
  fi
done
mkdir -p updates
printf '%s current=%s target=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current" "$resolved" >> updates/history.log
one_container() {
  local service="$1" ids count
  if ! ids="$(docker compose "${COMPOSE_ARGS[@]}" ps -aq "$service")"; then
    echo "Cannot list the ${service} container. Update stopped before services were stopped." >&2
    exit 1
  fi
  count="$(printf '%s\n' "$ids" | grep -c . || true)"
  if [ "$count" -ne 1 ]; then
    echo "Need exactly one ${service} container, found ${count}. Update stopped before services were stopped." >&2
    exit 1
  fi
  printf '%s\n' "$ids" | head -n 1
}
backend_cid="$(one_container backend)"
frontend_cid="$(one_container frontend)"
if ! backend_image="$(docker inspect --format '{{.Image}}' "$backend_cid")" || [ -z "$backend_image" ]; then
  echo "Cannot read the image of the running backend container. Update stopped before services were stopped." >&2
  exit 1
fi
if ! frontend_image="$(docker inspect --format '{{.Image}}' "$frontend_cid")" || [ -z "$frontend_image" ]; then
  echo "Cannot read the image of the running frontend container. Update stopped before services were stopped." >&2
  exit 1
fi
attempt_dir="updates/$(date -u +%Y%m%dT%H%M%SZ)-$$-${RANDOM}"
mkdir "$attempt_dir"
write_atomic "$attempt_dir/backend.image" "$backend_image"
write_atomic "$attempt_dir/frontend.image" "$frontend_image"
write_atomic "$attempt_dir/checkout" "$current"
restore_hint() {
  echo "Rollback uses the images recorded in ${attempt_dir}. It does not restore the database and does not undo migrations." >&2
  echo "  git checkout --detach ${current}" >&2
  echo "  docker tag ${backend_image} popmes-backend:latest" >&2
  echo "  docker tag ${frontend_image} popmes-frontend:latest" >&2
  echo "  docker compose ${COMPOSE_ARGS[*]} up -d --no-build" >&2
}
rollback_code() {
  git checkout --detach "$current" >/dev/null
  docker tag "$backend_image" popmes-backend:latest
  docker tag "$frontend_image" popmes-frontend:latest
  POPMES_LOCK_HELD=1 docker compose "${COMPOSE_ARGS[@]}" up -d --no-build
}
echo "Building images for ${resolved} before stopping the application."
echo "Running containers stay on ${backend_image} and ${frontend_image} until this update replaces them."
git checkout --detach "$resolved"
if ! docker compose "${COMPOSE_ARGS[@]}" build; then
  echo "Build failed. The running images were not replaced." >&2
  rollback_code || true
  echo "Backend was left on the image recorded before the build. Database was not restored." >&2
  restore_hint
  exit 1
fi
echo "Stopping the backend so backup and migrations see a quiet database."
docker compose "${COMPOSE_ARGS[@]}" stop backend
if ! POPMES_KEEP_BACKEND_STOPPED=1 POPMES_LOCK_HELD=1 bash scripts/backup.sh; then
  echo "Backup failed. The backend is still stopped. No migration was started." >&2
  restore_hint
  exit 1
fi
if ! POPMES_LOCK_HELD=1 bash scripts/migrate.sh; then
  echo "Migration failed. The backend is stopped. The database was not restored." >&2
  echo "Code rollback does not undo migrations." >&2
  restore_hint
  exit 1
fi
if ! docker compose "${COMPOSE_ARGS[@]}" up -d --no-build --wait --wait-timeout 180; then
  echo "Containers did not become healthy. Backend may be running and failing its check." >&2
  restore_hint
  echo "Do not restore the database unless you accept losing writes made after the backup." >&2
  exit 1
fi
url="$(health_url)"
if ! curl -fsS --max-time 10 "$url" >/dev/null; then
  echo "Health endpoint did not answer at ${url}." >&2
  echo "Containers were started. Rollback uses the recorded images and does not restore the database." >&2
  restore_hint
  exit 1
fi
echo "Update finished. Running ${resolved}. Previous checkout ${current}."
echo "Previous images are recorded in ${attempt_dir}."
echo "PostgreSQL major version was not changed."
