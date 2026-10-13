#!/usr/bin/env bash
# Restore the newest local backup into a separate Compose project.
# Removes only that project's containers and volumes. Does not touch the
# running popmes project or its data.
set -euo pipefail
cd "$(dirname "$0")/.."
project="${RESTORE_PROJECT:-popmesrestoretest}"
if [ "$project" = "popmes" ]; then
  echo "Refusing to restore into the main Compose project." >&2
  exit 1
fi
backup_root="${BACKUP_DIR:-./backups}"
backup_path="$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
if [ -z "${backup_path:-}" ]; then
  echo "No local backup directory found." >&2
  exit 1
fi
(cd "$backup_path" && sha256sum -c SHA256SUMS)
tmp="$(mktemp -d)"
cleanup() {
  docker compose -p "$project" -f "$tmp/compose.yaml" down -v >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT
password="${RESTORE_TEST_PASSWORD:-restore-test-password}"
cat > "$tmp/compose.yaml" <<EOF
services:
  database:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: popmes
      POSTGRES_USER: popmes
      POSTGRES_PASSWORD: ${password}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U popmes -d popmes"]
      interval: 2s
      timeout: 5s
      retries: 30
EOF
docker compose -p "$project" -f "$tmp/compose.yaml" up -d --wait
docker compose -p "$project" -f "$tmp/compose.yaml" exec -T database \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error' \
  < "$backup_path/database.dump"
docker compose -p "$project" -f "$tmp/compose.yaml" exec -T database \
  psql -U popmes -d popmes -c "SELECT COUNT(*) FROM django_migrations;"
echo "Isolated restore check passed for ${backup_path}."
echo "Media from that backup was not loaded into the main application."
