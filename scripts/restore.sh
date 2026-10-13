#!/usr/bin/env bash
# Explicitly replaces the target database and media; requires confirmation flag.
set -euo pipefail
if [ "$#" -ne 2 ] || [ "$2" != "--replace-current-data" ]; then
  echo 'Usage: bash scripts/restore.sh /absolute/backup/path --replace-current-data' >&2
  exit 1
fi
backup_source="$(cd "$1" && pwd)"
(cd "$backup_source" && sha256sum -c SHA256SUMS)
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
cleanup() {
  status=$?
  trap - EXIT
  if [ "$status" -ne 0 ]; then
    echo "Restore failed. Backend is stopped. Do not start it on a partial database." >&2
  fi
  ops_unlock
  exit "$status"
}
trap cleanup EXIT
docker compose "${COMPOSE_ARGS[@]}" stop backend
# Leave backend stopped if restore fails, to avoid writes into a partial restore.
docker compose "${COMPOSE_ARGS[@]}" exec -T database sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --exit-on-error --single-transaction' < "$backup_source/database.dump"
docker compose "${COMPOSE_ARGS[@]}" run --rm --no-deps -T --user root --entrypoint sh backend -c 'find /app/media -mindepth 1 -delete; tar -xzf - -C /app/media; chown -R app:app /app/media' < "$backup_source/media.tar.gz"
docker compose "${COMPOSE_ARGS[@]}" start backend
echo 'Restore complete. Verify orders and downloaded labels before resuming work.'
