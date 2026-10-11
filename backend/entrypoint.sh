#!/bin/sh
set -eu
python manage.py migrate --noinput
python manage.py bootstrap
if [ "${SEED_CATALOG:-1}" = "1" ]; then python manage.py seed_catalog; fi
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 --access-logfile - --error-logfile -
