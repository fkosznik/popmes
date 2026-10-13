#!/bin/sh
# Runs only when the PostgreSQL data directory is created for the first time.
# Existing volumes are unchanged; use scripts/postgres-roles.sh for those.
set -eu
if [ -z "${POSTGRES_APP_PASSWORD:-}" ] || [ -z "${POSTGRES_MIGRATE_PASSWORD:-}" ]; then
  echo "popmes: app and migrate roles were not created (passwords not set)."
  exit 0
fi
case "${POSTGRES_APP_USER:-popmes_app}${POSTGRES_MIGRATE_USER:-popmes_migrate}" in
  *[!a-z0-9_]*)
    echo "popmes: role names may contain only lowercase letters, digits and underscores." >&2
    exit 1
    ;;
esac
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${POSTGRES_DB:-popmes}" \
  -v app_user="${POSTGRES_APP_USER:-popmes_app}" \
  -v migrate_user="${POSTGRES_MIGRATE_USER:-popmes_migrate}" \
  -v app_db="${POSTGRES_DB:-popmes}" \
  -v app_password="$POSTGRES_APP_PASSWORD" \
  -v migrate_password="$POSTGRES_MIGRATE_PASSWORD" \
  -f /usr/local/share/popmes/roles.sql
echo "popmes: application and migration roles are ready."
