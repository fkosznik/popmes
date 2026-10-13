#!/usr/bin/env bash
# Create popmes_migrate and popmes_app on an existing data volume.
# Does not delete data, rename the current superuser, or change POSTGRES_USER
# inside the database container. Run this before pointing the app at popmes_app.
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/ops-common.sh"
ops_root
if [ ! -f .env ]; then
  echo "Missing .env. Run python3 scripts/setup.py first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
app_user="${POSTGRES_APP_USER:-popmes_app}"
migrate_user="${POSTGRES_MIGRATE_USER:-popmes_migrate}"
database="${POSTGRES_DB:-popmes}"
if [ -z "${POSTGRES_APP_PASSWORD:-}" ] || [ -z "${POSTGRES_MIGRATE_PASSWORD:-}" ]; then
  echo "Set POSTGRES_APP_PASSWORD and POSTGRES_MIGRATE_PASSWORD in .env first." >&2
  exit 1
fi
case "${app_user}${migrate_user}${database}" in
  *[!A-Za-z0-9_]*)
    echo "Role and database names may contain only letters, digits and underscores." >&2
    exit 1
    ;;
esac
if [ "$app_user" = "${POSTGRES_USER:-popmes}" ] || [ "$migrate_user" = "${POSTGRES_USER:-popmes}" ]; then
  echo "The application and migration roles must be different from POSTGRES_USER." >&2
  exit 1
fi
echo "Creating roles ${migrate_user} and ${app_user} in database ${database}."
echo "The existing superuser is left in place. No rows are deleted."
compose_args
ops_lock
cleanup() {
  status=$?
  trap - EXIT
  ops_unlock
  exit "$status"
}
trap cleanup EXIT
docker compose "${COMPOSE_ARGS[@]}" exec -T \
  -e APP_USER="$app_user" \
  -e MIGRATE_USER="$migrate_user" \
  -e APP_DB="$database" \
  -e APP_PASSWORD="$POSTGRES_APP_PASSWORD" \
  -e MIGRATE_PASSWORD="$POSTGRES_MIGRATE_PASSWORD" \
  database sh -c 'psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$APP_DB" -v app_user="$APP_USER" -v migrate_user="$MIGRATE_USER" -v app_db="$APP_DB" -v app_password="$APP_PASSWORD" -v migrate_password="$MIGRATE_PASSWORD" -f /usr/local/share/popmes/roles.sql'
echo "Roles are ready. Point the backend at ${app_user} only after this command succeeds."
echo "Backup and restore keep using the database superuser inside the database container."
