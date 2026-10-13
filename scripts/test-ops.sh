#!/usr/bin/env bash
# Exercise backup status and update failure paths with stub commands.
# Does not start the application stack or touch its volumes.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/repo/scripts" "$tmp/repo/updates" "$tmp/backups"
cp "$root/scripts/ops-common.sh" "$root/scripts/backup.sh" "$root/scripts/monitor.sh" "$root/scripts/update.sh" "$root/scripts/migrate.sh" "$tmp/repo/scripts/"
# Point copied scripts at the temporary repo via a wrapper root.
cat > "$tmp/bin/docker" << 'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "${DOCKER_LOG:?}"
case "$*" in
  *' build'*)
    if [ "${DOCKER_BUILD_FAIL:-0}" = "1" ]; then
      exit 1
    fi
    ;;
  *'ps --status running'*) printf 'backend\n' ;;
  *'ps -aq backend'*)
    if [ "${DOCKER_NO_BACKEND:-0}" = "1" ]; then
      exit 0
    fi
    if [ "${DOCKER_AMBIGUOUS_BACKEND:-0}" = "1" ]; then
      printf 'cid-backend\ncid-backend-extra\n'
      exit 0
    fi
    printf 'cid-backend\n'
    ;;
  *'ps -aq frontend'*)
    if [ "${DOCKER_NO_FRONTEND:-0}" = "1" ]; then
      exit 0
    fi
    printf 'cid-frontend\n'
    ;;
  *'inspect --format {{.Image}} cid-backend'*)
    if [ "${DOCKER_INSPECT_FAIL:-0}" = "1" ]; then
      exit 1
    fi
    printf '%s\n' "${CONTAINER_BACKEND_IMAGE:-sha256:running-backend}"
    ;;
  *'inspect --format {{.Image}} cid-frontend'*)
    if [ "${DOCKER_INSPECT_FAIL:-0}" = "1" ]; then
      exit 1
    fi
    printf '%s\n' "${CONTAINER_FRONTEND_IMAGE:-sha256:running-frontend}"
    ;;
  *'image inspect popmes-backend:latest'*)
    printf '%s\n' "${LATEST_BACKEND_IMAGE:-sha256:latest-backend}"
    ;;
  *'image inspect popmes-frontend:latest'*)
    printf '%s\n' "${LATEST_FRONTEND_IMAGE:-sha256:latest-frontend}"
    ;;
  *' exec '*)
    if [ "${DOCKER_DUMP_FAIL:-0}" = "1" ]; then
      exit 1
    fi
    printf 'dump-bytes\n'
    ;;
  *' run '*)
    if [ "${DOCKER_MEDIA_FAIL:-0}" = "1" ]; then
      exit 1
    fi
    printf 'media-bytes\n'
    ;;
esac
exit 0
EOF
cat > "$tmp/bin/restic" << 'EOF'
#!/bin/sh
if [ "${RESTIC_SHOULD_FAIL:-0}" = "1" ]; then
  echo "restic failed" >&2
  exit 1
fi
exit 0
EOF
cat > "$tmp/bin/git" << 'EOF'
#!/bin/sh
case "$1" in
  status) [ "${GIT_DIRTY:-0}" = "1" ] && printf ' M file\n' ;;
  fetch) exit 0 ;;
  rev-parse)
    if [ "$2" = "HEAD" ]; then printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n'; exit 0; fi
    printf 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
    ;;
  remote) printf 'https://github.com/fkosznik/popmes.git\n' ;;
  checkout) exit 0 ;;
  *) exit 0 ;;
esac
EOF
cat > "$tmp/bin/gh" << 'EOF'
#!/bin/sh
if [ "${CI_SHOULD_FAIL:-0}" = "1" ]; then
  printf 'quality\tfailure\tbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
  printf 'application\tfailure\tbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
  exit 0
fi
printf 'quality\tsuccess\tbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
printf 'application\tsuccess\tbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n'
EOF
cat > "$tmp/bin/curl" << 'EOF'
#!/bin/sh
if [ -n "${CURL_LOG:-}" ]; then
  printf '%s\n' "$*" >> "$CURL_LOG"
fi
if [ "${CURL_SHOULD_FAIL:-0}" = "1" ]; then
  exit 1
fi
exit 0
EOF
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH"
export DOCKER_LOG="$tmp/docker.log"
export BACKUP_DIR="$tmp/backups"
cd "$tmp/repo"
printf 'DJANGO_SECRET_KEY=test\nPOSTGRES_PASSWORD=test\nDEBUG=0\n' > .env

# Previous off-site success, then restic fails. Status must not stay ok.
printf 'ok\n' > "$BACKUP_DIR/OFFSITE_STATUS"
printf '2020-01-01T00:00:00Z\n' > "$BACKUP_DIR/OFFSITE_SUCCESS"
printf '2020-01-01T00:00:00Z\n' > "$BACKUP_DIR/LAST_SUCCESS"
export RESTIC_REPOSITORY=memory:test
export RESTIC_PASSWORD_FILE="$tmp/repo/.env"
export RESTIC_SHOULD_FAIL=1
set +e
bash scripts/backup.sh >"$tmp/backup.out" 2>"$tmp/backup.err"
backup_status=$?
set -e
test "$backup_status" -ne 0
test "$(cat "$BACKUP_DIR/OFFSITE_STATUS")" = "backup_failed"
grep -q '2020-01-01T00:00:00Z' "$BACKUP_DIR/OFFSITE_SUCCESS"
OFFSITE_REQUIRED=1 bash scripts/monitor.sh >"$tmp/monitor.out" 2>"$tmp/monitor.err" && exit 1 || true
grep -q 'offsite: backup_failed' "$tmp/monitor.out"

# Dirty tree blocks the update before any image change.
export GIT_DIRTY=1
unset RESTIC_REPOSITORY
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/dirty.out" 2>"$tmp/dirty.err"
dirty_status=$?
set -e
test "$dirty_status" -ne 0
grep -q 'local changes' "$tmp/dirty.err"

# Failed CI is not treated as verified.
export GIT_DIRTY=0
export CI_SHOULD_FAIL=1
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/ci.out" 2>"$tmp/ci.err"
ci_status=$?
set -e
test "$ci_status" -ne 0
grep -q 'not success' "$tmp/ci.err"

# A second lock cannot start.
mkdir "$tmp/repo/.popmes-ops.lock"
set +e
bash scripts/backup.sh >"$tmp/lock.out" 2>"$tmp/lock.err"
lock_status=$?
set -e
test "$lock_status" -ne 0
rmdir "$tmp/repo/.popmes-ops.lock"

export CI_SHOULD_FAIL=0
export DOCKER_BUILD_FAIL=1
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/build.out" 2>"$tmp/build.err"
build_status=$?
set -e
test "$build_status" -ne 0
grep -q 'Build failed' "$tmp/build.err"
export DOCKER_BUILD_FAIL=0

export CURL_SHOULD_FAIL=1
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/health.out" 2>"$tmp/health.err"
health_status=$?
set -e
test "$health_status" -ne 0
grep -q 'Health endpoint' "$tmp/health.err"
export CURL_SHOULD_FAIL=0

# shellcheck disable=SC1091
source "$tmp/repo/scripts/ops-common.sh"
USE_HTTPS=1 DOMAIN=popmes.example.com
test "$(health_url)" = "https://popmes.example.com/api/health/"
USE_HTTPS=0 APP_PORT=8080
test "$(health_url)" = "http://127.0.0.1:8080/api/health/"

fresh="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\n' "$fresh" > "$BACKUP_DIR/LAST_SUCCESS"
export DOCKER_DUMP_FAIL=1
unset RESTIC_REPOSITORY
set +e
bash scripts/backup.sh >"$tmp/dump.out" 2>"$tmp/dump.err"
dump_status=$?
set -e
test "$dump_status" -ne 0
test "$(cat "$BACKUP_DIR/LAST_SUCCESS")" = "$fresh"
test "$(sed -n '1p' "$BACKUP_DIR/LOCAL_STATUS")" = "dump_failed"
set +e
DISK_ALERT_PERCENT=101 bash scripts/monitor.sh >"$tmp/dump-monitor.out" 2>"$tmp/dump-monitor.err"
dump_monitor=$?
set -e
test "$dump_monitor" -ne 0
grep -q 'backup: last attempt dump_failed' "$tmp/dump-monitor.out"
export DOCKER_DUMP_FAIL=0

printf '%s\n' "$fresh" > "$BACKUP_DIR/LAST_SUCCESS"
export DOCKER_MEDIA_FAIL=1
set +e
bash scripts/backup.sh >"$tmp/media.out" 2>"$tmp/media.err"
media_status=$?
set -e
test "$media_status" -ne 0
test "$(cat "$BACKUP_DIR/LAST_SUCCESS")" = "$fresh"
test "$(sed -n '1p' "$BACKUP_DIR/LOCAL_STATUS")" = "media_failed"
set +e
DISK_ALERT_PERCENT=101 bash scripts/monitor.sh >"$tmp/media-monitor.out" 2>"$tmp/media-monitor.err"
media_monitor=$?
set -e
test "$media_monitor" -ne 0
grep -q 'backup: last attempt media_failed' "$tmp/media-monitor.out"
export DOCKER_MEDIA_FAIL=0

mkdir -p "$tmp/bin-sha"
cat > "$tmp/bin-sha/sha256sum" << 'EOF'
#!/bin/sh
exit 1
EOF
chmod +x "$tmp/bin-sha/sha256sum"
printf '%s\n' "$fresh" > "$BACKUP_DIR/LAST_SUCCESS"
saved_path="$PATH"
PATH="$tmp/bin-sha:$PATH"
set +e
bash scripts/backup.sh >"$tmp/sum.out" 2>"$tmp/sum.err"
sum_status=$?
set -e
PATH="$saved_path"
test "$sum_status" -ne 0
test "$(cat "$BACKUP_DIR/LAST_SUCCESS")" = "$fresh"
test "$(sed -n '1p' "$BACKUP_DIR/LOCAL_STATUS")" = "checksum_failed"

bash scripts/backup.sh >"$tmp/again.out" 2>"$tmp/again.err"
test "$(sed -n '1p' "$BACKUP_DIR/LOCAL_STATUS")" = "ok"
DISK_ALERT_PERCENT=101 bash scripts/monitor.sh >"$tmp/clear.out" 2>"$tmp/clear.err"
grep -q 'backup: last success' "$tmp/clear.out"
if grep -q 'backup: last attempt' "$tmp/clear.out"; then
  echo "successful backup left the previous failure alarm" >&2
  exit 1
fi

printf 'not_configured\n' > "$BACKUP_DIR/OFFSITE_STATUS"
printf 'running\n%s\n' "$fresh" > "$BACKUP_DIR/LOCAL_STATUS"
DISK_ALERT_PERCENT=101 BACKUP_RUNNING_MAX_MINUTES=30 bash scripts/monitor.sh >"$tmp/run.out" 2>"$tmp/run.err"
grep -q 'backup: attempt running for' "$tmp/run.out"
if grep -q 'backup: attempt has been running' "$tmp/run.out"; then
  echo "a fresh running backup raised an alarm" >&2
  exit 1
fi
printf 'running\n2020-01-01T00:00:00Z\n' > "$BACKUP_DIR/LOCAL_STATUS"
set +e
DISK_ALERT_PERCENT=101 BACKUP_RUNNING_MAX_MINUTES=30 bash scripts/monitor.sh >"$tmp/stuck.out" 2>"$tmp/stuck.err"
stuck_status=$?
set -e
test "$stuck_status" -ne 0
grep -q 'backup: attempt has been running' "$tmp/stuck.out"

printf 'ok\n%s\n' "$fresh" > "$BACKUP_DIR/LOCAL_STATUS"
printf '%s\n' "$fresh" > "$BACKUP_DIR/LAST_SUCCESS"
export CURL_LOG="$tmp/curl.log"
: > "$CURL_LOG"
USE_HTTPS=0 APP_PORT=9090 MONITOR_URL= HEALTHCHECK_URL= DISK_ALERT_PERCENT=101 bash scripts/monitor.sh >/dev/null
grep -q 'http://127.0.0.1:9090/api/health/' "$CURL_LOG"
: > "$CURL_LOG"
USE_HTTPS=1 DOMAIN=popmes.example.com APP_PORT=8080 MONITOR_URL= HEALTHCHECK_URL= DISK_ALERT_PERCENT=101 bash scripts/monitor.sh >/dev/null
grep -q 'https://popmes.example.com/api/health/' "$CURL_LOG"
: > "$CURL_LOG"
HEALTHCHECK_URL=https://proxy.example/api/health/ USE_HTTPS=1 DOMAIN=popmes.example.com MONITOR_URL= DISK_ALERT_PERCENT=101 bash scripts/monitor.sh >/dev/null
grep -q 'https://proxy.example/api/health/' "$CURL_LOG"
: > "$CURL_LOG"
MONITOR_URL=http://override.example/api/health/ USE_HTTPS=1 DOMAIN=popmes.example.com HEALTHCHECK_URL=https://proxy.example/api/health/ DISK_ALERT_PERCENT=101 bash scripts/monitor.sh >/dev/null
grep -q 'http://override.example/api/health/' "$CURL_LOG"
if grep -q 'https://popmes.example.com/api/health/' "$CURL_LOG"; then
  echo "MONITOR_URL did not take precedence" >&2
  exit 1
fi
unset MONITOR_URL HEALTHCHECK_URL USE_HTTPS

: > "$DOCKER_LOG"
export CONTAINER_BACKEND_IMAGE=sha256:image-a-backend
export CONTAINER_FRONTEND_IMAGE=sha256:image-a-frontend
export LATEST_BACKEND_IMAGE=sha256:image-b-backend
export LATEST_FRONTEND_IMAGE=sha256:image-b-frontend
export DOCKER_BUILD_FAIL=1
export CURL_SHOULD_FAIL=0
find "$tmp/repo/updates" -mindepth 1 -maxdepth 1 -type d | sort > "$tmp/updates-before"
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/image.out" 2>"$tmp/image.err"
image_status=$?
set -e
test "$image_status" -ne 0
attempt_dir="$(find "$tmp/repo/updates" -mindepth 1 -maxdepth 1 -type d | sort | comm -13 "$tmp/updates-before" -)"
test "$(cat "$attempt_dir/backend.image")" = "sha256:image-a-backend"
test "$(cat "$attempt_dir/frontend.image")" = "sha256:image-a-frontend"
test "$(cat "$attempt_dir/checkout")" != "sha256:image-a-backend"
grep -q 'tag sha256:image-a-backend popmes-backend:latest' "$DOCKER_LOG"
if grep -q 'tag sha256:image-b-backend popmes-backend:latest' "$DOCKER_LOG"; then
  echo "build failure rolled back to the latest tag instead of the running image" >&2
  exit 1
fi
saved_backend="$(cat "$attempt_dir/backend.image")"
before_count="$(find "$tmp/repo/updates" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/image2.out" 2>"$tmp/image2.err"
image_status=$?
set -e
test "$image_status" -ne 0
after_count="$(find "$tmp/repo/updates" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
test "$after_count" = "$((before_count + 1))"
test "$(cat "$attempt_dir/backend.image")" = "$saved_backend"
export DOCKER_BUILD_FAIL=0

: > "$DOCKER_LOG"
export DOCKER_NO_BACKEND=1
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/missing.out" 2>"$tmp/missing.err"
missing_status=$?
set -e
test "$missing_status" -ne 0
if grep -q 'stop backend' "$DOCKER_LOG"; then
  echo "missing container still stopped services" >&2
  exit 1
fi
export DOCKER_NO_BACKEND=0

: > "$DOCKER_LOG"
export DOCKER_AMBIGUOUS_BACKEND=1
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/ambiguous.out" 2>"$tmp/ambiguous.err"
ambiguous_status=$?
set -e
test "$ambiguous_status" -ne 0
grep -q 'before services were stopped' "$tmp/ambiguous.err"
if grep -q 'stop backend' "$DOCKER_LOG"; then
  echo "ambiguous containers still stopped services" >&2
  exit 1
fi
export DOCKER_AMBIGUOUS_BACKEND=0

: > "$DOCKER_LOG"
export DOCKER_INSPECT_FAIL=1
set +e
bash scripts/update.sh bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --verified >"$tmp/inspect.out" 2>"$tmp/inspect.err"
inspect_status=$?
set -e
test "$inspect_status" -ne 0
grep -q 'before services were stopped' "$tmp/inspect.err"
if grep -q 'stop backend' "$DOCKER_LOG"; then
  echo "unreadable image still stopped services" >&2
  exit 1
fi
export DOCKER_INSPECT_FAIL=0

echo "ops script checks passed"
