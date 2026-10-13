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
  *' ps '*) printf 'backend\n' ;;
  *' exec '*) printf 'dump-bytes\n' ;;
  *' run '*) printf 'media-bytes\n' ;;
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
echo "ops script checks passed"
