#!/usr/bin/env bash
# Apply migrations as the migration role. The long-running backend never
# receives that password. Bootstrap then runs as the application role.
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
user="${POSTGRES_MIGRATE_USER:-}"
password="${POSTGRES_MIGRATE_PASSWORD:-}"
if [ "${POPMES_ENV:-local}" = "production" ] && { [ -z "$user" ] || [ -z "$password" ]; }; then
  echo "Production refuses to migrate as the application superuser. Set POSTGRES_MIGRATE_USER and POSTGRES_MIGRATE_PASSWORD." >&2
  exit 1
fi
if [ -n "$user" ]; then
  echo "Migrating as ${user}."
  docker compose "${COMPOSE_ARGS[@]}" run --rm --no-deps --entrypoint python \
    -e POSTGRES_USER="$user" \
    -e POSTGRES_PASSWORD="$password" \
    -e POPMES_ENV=local \
    backend manage.py migrate --noinput
else
  echo "Local/CI migration uses the backend database user."
  docker compose "${COMPOSE_ARGS[@]}" run --rm --no-deps --entrypoint python \
    backend manage.py migrate --noinput
fi
docker compose "${COMPOSE_ARGS[@]}" run --rm --no-deps --entrypoint python \
  backend manage.py bootstrap
