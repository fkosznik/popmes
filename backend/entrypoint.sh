#!/bin/sh
set -eu
# Ordinary restarts must not migrate. An empty database still migrates so the
# first boot works. scripts/update.sh runs migrations as its own step.
set +e
python - <<'PY'
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.db import connection

from django.db.migrations.executor import MigrationExecutor

tables = set(connection.introspection.table_names())
if "django_migrations" not in tables or os.environ.get("MIGRATE_ON_START") == "1":
    raise SystemExit(0)
executor = MigrationExecutor(connection)
if executor.migration_plan(executor.loader.graph.leaf_nodes()):
    raise SystemExit(3)
raise SystemExit(2)
PY
status=$?
set -e
if [ "$status" -eq 0 ]; then
  python manage.py migrate --noinput
  python manage.py bootstrap
elif [ "$status" -eq 3 ]; then
  echo "The database is behind this version. Run: bash scripts/migrate.sh" >&2
  exit 1
elif [ "$status" -ne 2 ]; then
  exit "$status"
fi
if [ "${SEED_CATALOG:-1}" = "1" ]; then python manage.py seed_catalog; fi
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 \
  --access-logfile - --error-logfile - --capture-output
