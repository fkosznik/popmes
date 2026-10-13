#!/usr/bin/env python3
"""Fail if the production backend container would receive migration or backup secrets.

Prints only variable names, never values.
"""

import json
import os
import subprocess
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = os.environ.copy()
env.update(
    {
        "POPMES_ENV": "production",
        "POSTGRES_APP_USER": "popmes_app",
        "POSTGRES_APP_PASSWORD": "app-secret-not-printed",
        "POSTGRES_MIGRATE_USER": "popmes_migrate",
        "POSTGRES_MIGRATE_PASSWORD": "migrate-secret-not-printed",
        "RESTIC_REPOSITORY": "s3:example",
        "RESTIC_PASSWORD_FILE": "/root/restic",
        "ALERT_WEBHOOK_URL": "https://hooks.example/alert",
        "DJANGO_SECRET_KEY": env.get("DJANGO_SECRET_KEY", "local-test-key"),
        "POSTGRES_PASSWORD": env.get("POSTGRES_PASSWORD", "local-test-db"),
        "ADMIN_PASSWORD": env.get("ADMIN_PASSWORD", "local-test-admin"),
    }
)
raw = subprocess.check_output(
    [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.prod.yaml",
        "config",
        "--format",
        "json",
    ],
    cwd=root,
    env=env,
)
backend = json.loads(raw)["services"]["backend"]["environment"]
forbidden = {
    "POSTGRES_MIGRATE_PASSWORD",
    "POSTGRES_MIGRATE_USER",
    "RESTIC_REPOSITORY",
    "RESTIC_PASSWORD_FILE",
    "ALERT_WEBHOOK_URL",
}
present = sorted(forbidden.intersection(backend))
if present:
    print("Backend environment contains forbidden names:", ", ".join(present))
    sys.exit(1)
if backend.get("POPMES_ENV") != "production":
    print("Production overlay did not set POPMES_ENV=production")
    sys.exit(1)
if backend.get("POSTGRES_USER") != "popmes_app":
    print("Production backend is not using the restricted application role name")
    sys.exit(1)
database = json.loads(raw)["services"]["database"]["environment"]
if "POSTGRES_MIGRATE_PASSWORD" in database or "POSTGRES_APP_PASSWORD" in database:
    print("Database service environment contains a role password")
    sys.exit(1)
print("production backend environment excludes migration and backup secrets")
