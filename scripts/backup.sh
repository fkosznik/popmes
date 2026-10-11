#!/usr/bin/env bash
# Consistent database + media snapshot. The backend is stopped briefly.
set -euo pipefail
cd "$(dirname "$0")/.."
backup_root="${BACKUP_DIR:-./backups}"
mkdir -p "$backup_root"
backup_target="$backup_root/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$backup_target"
chmod 700 "$backup_target"
trap 'docker compose start backend >/dev/null' EXIT
docker compose stop backend
docker compose exec -T database sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_target/database.dump"
docker compose run --rm --no-deps -T --user root --entrypoint tar backend -C /app/media -czf - . > "$backup_target/media.tar.gz"
(cd "$backup_target" && sha256sum database.dump media.tar.gz > SHA256SUMS)
printf 'Backup created: %s\nCopy this directory outside the application host.\n' "$backup_target"
