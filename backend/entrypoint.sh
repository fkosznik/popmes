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

tables = set(connection.introspection.table_names())
need = os.environ.get("MIGRATE_ON_START") == "1" or "django_migrations" not in tables
raise SystemExit(0 if need else 2)
PY
status=$?
set -e
if [ "$status" -eq 0 ]; then
  python manage.py migrate --noinput
  python manage.py bootstrap
elif [ "$status" -ne 2 ]; then
  exit "$status"
fi
if [ "${SEED_CATALOG:-1}" = "1" ]; then python manage.py seed_catalog; fi
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 \
  --access-logfile - --error-logfile - --capture-output
