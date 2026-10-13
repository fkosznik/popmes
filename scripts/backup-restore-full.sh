#!/usr/bin/env bash
# Full restore drill for the restricted roles.
# Creates two throwaway Compose projects and two throwaway volumes.
# Never selects the running "popmes" project and never deletes its volumes.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
source_project="${ROLE_PROJECT:-popmesrolefull}"
dest_project="${ROLE_PROJECT_DEST:-popmesrolefullb}"
for project in "$source_project" "$dest_project"; do
  if [ "$project" = "popmes" ]; then
    echo "Refusing to use the main Compose project." >&2
    exit 1
  fi
done
if ! docker image inspect popmes-backend >/dev/null 2>&1; then
  echo "Build the backend image first: docker compose build backend" >&2
  exit 1
fi
tmp="$(mktemp -d)"
media_a="popmesrolefull-media"
media_b="popmesrolefull-media-b"
# Fixed fixture passwords for this disposable database. They are not production secrets.
app_password="role-test-app-password"
migrate_password="role-test-migrate-password"
super_password="role-test-super-password"
admin_password="Role-test-admin-932!"
cleanup() {
  docker compose -p "$source_project" -f "$tmp/compose.yaml" down -v >/dev/null 2>&1 || true
  docker compose -p "$dest_project" -f "$tmp/compose.yaml" down -v >/dev/null 2>&1 || true
  docker volume rm "$media_a" "$media_b" >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT
cat > "$tmp/compose.yaml" <<EOF
services:
  database:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: popmes
      POSTGRES_USER: popmes
      POSTGRES_PASSWORD: ${super_password}
    volumes:
      - ${root}/docker/postgres/roles.sql:/usr/local/share/popmes/roles.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U popmes -d popmes"]
      interval: 2s
      timeout: 5s
      retries: 40
EOF
apply_roles() {
  docker compose -p "$1" -f "$tmp/compose.yaml" exec -T \
    -e APP_PASSWORD="$app_password" \
    -e MIGRATE_PASSWORD="$migrate_password" \
    database sh -c 'psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v app_user=popmes_app -v migrate_user=popmes_migrate -v app_db=popmes -v app_password="$APP_PASSWORD" -v migrate_password="$MIGRATE_PASSWORD" -f /usr/local/share/popmes/roles.sql' >/dev/null
}
run_manage() {
  local project="$1"
  local db_user="$2"
  local db_password="$3"
  shift 3
  docker run --rm \
    --network "${project}_default" \
    -v "$root/backend:/app" \
    -e POSTGRES_HOST=database \
    -e POSTGRES_DB=popmes \
    -e POSTGRES_USER="$db_user" \
    -e POSTGRES_PASSWORD="$db_password" \
    -e DJANGO_SECRET_KEY=role-test-django-secret \
    -e DEBUG=0 \
    -e POPMES_ENV=local \
    -e ALLOWED_HOSTS=testserver,localhost,127.0.0.1 \
    -e ADMIN_USERNAME=admin \
    -e ADMIN_PASSWORD="$admin_password" \
    -e MEDIA_ROOT=/app/media \
    -e PYTHONPATH=/app \
    -w /app \
    --entrypoint python \
    popmes-backend manage.py "$@"
}
run_exercise() {
  local project="$1"
  local mode="$2"
  local media="$3"
  docker run --rm \
    --network "${project}_default" \
    -v "$root/backend:/app" \
    -v "$media:/app/media" \
    -v "$root/scripts/role_restore_exercise.py:/exercise.py:ro" \
    -e POSTGRES_HOST=database \
    -e POSTGRES_DB=popmes \
    -e POSTGRES_USER=popmes_app \
    -e POSTGRES_PASSWORD="$app_password" \
    -e DJANGO_SECRET_KEY=role-test-django-secret \
    -e DEBUG=0 \
    -e POPMES_ENV=local \
    -e ALLOWED_HOSTS=testserver,localhost,127.0.0.1 \
    -e ADMIN_USERNAME=admin \
    -e ADMIN_PASSWORD="$admin_password" \
    -e MEDIA_ROOT=/app/media \
    -e PYTHONPATH=/app \
    -w /app \
    --entrypoint python \
    popmes-backend /exercise.py "$mode"
}
prepare_media() {
  docker run --rm --user root --entrypoint sh \
    -v "$1:/app/media" \
    popmes-backend -c 'mkdir -p /app/media && chown -R app:app /app/media'
}
deny_sql() {
  local project="$1"
  local sql="$2"
  if docker compose -p "$project" -f "$tmp/compose.yaml" exec -T \
    -e PGPASSWORD="$app_password" \
    database psql -U popmes_app -d popmes -v ON_ERROR_STOP=1 -c "$sql" >/dev/null 2>&1; then
    echo "Application role was allowed to run a privileged statement." >&2
    exit 1
  fi
}
echo "Starting an isolated database for the restricted-role drill."
docker compose -p "$source_project" -f "$tmp/compose.yaml" up -d --wait
apply_roles "$source_project"
echo "Migrating as popmes_migrate."
run_manage "$source_project" popmes_migrate "$migrate_password" migrate --noinput
prepare_media "$media_a"
run_exercise "$source_project" seed "$media_a"
deny_sql "$source_project" "CREATE TABLE popmes_should_fail (id integer)"
deny_sql "$source_project" "CREATE ROLE popmes_should_fail"
deny_sql "$source_project" "CREATE DATABASE popmes_should_fail"
docker compose -p "$source_project" -f "$tmp/compose.yaml" exec -T database \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$tmp/database.dump"
docker run --rm --user root --entrypoint tar \
  -v "$media_a:/app/media:ro" \
  popmes-backend -C /app/media -czf - . > "$tmp/media.tar.gz"
echo "Restoring into a second isolated database with the same roles."
docker compose -p "$dest_project" -f "$tmp/compose.yaml" up -d --wait
apply_roles "$dest_project"
docker compose -p "$dest_project" -f "$tmp/compose.yaml" exec -T database \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error' \
  < "$tmp/database.dump"
prepare_media "$media_b"
docker run --rm -i --user root --entrypoint sh \
  -v "$media_b:/app/media" \
  popmes-backend -c 'tar -xzf - -C /app/media && chown -R app:app /app/media' \
  < "$tmp/media.tar.gz"
run_exercise "$dest_project" verify "$media_b"
deny_sql "$dest_project" "CREATE TABLE popmes_should_fail (id integer)"
deny_sql "$dest_project" "CREATE ROLE popmes_should_fail"
deny_sql "$dest_project" "CREATE DATABASE popmes_should_fail"
echo "Full role restore passed. The main popmes volumes were not used."
