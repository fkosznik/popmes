#!/usr/bin/env bash
# Apply Django migrations as the migration role when it is configured.
# The long-running backend does not receive this password.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  echo "Missing .env." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
user="${POSTGRES_MIGRATE_USER:-}"
password="${POSTGRES_MIGRATE_PASSWORD:-}"
if [ -z "$user" ]; then
  echo "POSTGRES_MIGRATE_USER is unset. Migrating with the backend database user."
  docker compose run --rm --no-deps --entrypoint python backend manage.py migrate --noinput
  exit 0
fi
if [ -z "$password" ]; then
  echo "Set POSTGRES_MIGRATE_PASSWORD before migrating as ${user}." >&2
  exit 1
fi
echo "Migrating as ${user}."
docker compose run --rm --no-deps --entrypoint python \
  -e POSTGRES_USER="$user" \
  -e POSTGRES_PASSWORD="$password" \
  backend manage.py migrate --noinput
