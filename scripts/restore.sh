#!/usr/bin/env bash
# Explicitly replaces the target database and media; requires confirmation flag.
set -euo pipefail
if [ "$#" -ne 2 ] || [ "$2" != "--replace-current-data" ]; then
  echo 'Usage: bash scripts/restore.sh /absolute/backup/path --replace-current-data' >&2
  exit 1
fi
backup_source="$(cd "$1" && pwd)"
(cd "$backup_source" && sha256sum -c SHA256SUMS)
cd "$(dirname "$0")/.."
docker compose stop backend
# Leave backend stopped if restore fails, to avoid writes into a partial restore.
docker compose exec -T database sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --exit-on-error --single-transaction' < "$backup_source/database.dump"
docker compose run --rm --no-deps -T --user root --entrypoint sh backend -c 'find /app/media -mindepth 1 -delete; tar -xzf - -C /app/media; chown -R app:app /app/media' < "$backup_source/media.tar.gz"
docker compose start backend
echo 'Restore complete. Verify orders and downloaded labels before resuming work.'
