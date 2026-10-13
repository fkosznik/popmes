#!/usr/bin/env bash
# Shared Compose selection, lock and health URL for backup and updates.
ops_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
}

compose_args() {
  COMPOSE_ARGS=(-f compose.yaml)
  if [ "${POPMES_ENV:-local}" = "production" ]; then
    COMPOSE_ARGS+=(-f compose.prod.yaml)
  fi
  if [ "${USE_HTTPS:-0}" = "1" ]; then
    COMPOSE_ARGS+=(-f compose.https.yaml)
  fi
}

health_url() {
  if [ -n "${HEALTHCHECK_URL:-}" ]; then
    printf '%s\n' "$HEALTHCHECK_URL"
    return
  fi
  if [ "${USE_HTTPS:-0}" = "1" ]; then
    printf 'https://%s/api/health/\n' "${DOMAIN:?Set DOMAIN or HEALTHCHECK_URL}"
    return
  fi
  printf 'http://127.0.0.1:%s/api/health/\n' "${APP_PORT:-8080}"
}

# Replace a status file in one step so a reader never sees a partial write.
write_atomic() {
  local dest="$1" value="$2" dir tmp
  dir="$(dirname "$dest")"
  mkdir -p "$dir"
  tmp="$(mktemp "${dir}/.status.XXXXXX")"
  printf '%s\n' "$value" > "$tmp"
  mv -f "$tmp" "$dest"
}

epoch_of() {
  local value="$1" parsed
  parsed="$(date -u -d "$value" +%s 2>/dev/null || true)"
  if [ -n "$parsed" ]; then
    printf '%s\n' "$parsed"
    return
  fi
  date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$value" +%s
}

ops_lock() {
  OPS_LOCK="${PWD}/.popmes-ops.lock"
  if [ "${POPMES_LOCK_HELD:-0}" = "1" ]; then
    return
  fi
  if ! mkdir "$OPS_LOCK" 2>/dev/null; then
    echo "Another backup or update holds ${OPS_LOCK}." >&2
    exit 1
  fi
  OPS_LOCK_OWNED=1
}

ops_unlock() {
  if [ "${OPS_LOCK_OWNED:-0}" = "1" ]; then
    rmdir "${OPS_LOCK:-}" 2>/dev/null || true
    OPS_LOCK_OWNED=0
  fi
}

require_positive_int() {
  case "$2" in
    ''|*[!0-9]*)
      echo "$1 must be a positive integer." >&2
      exit 1
      ;;
  esac
  if [ "$2" -lt 1 ]; then
    echo "$1 must be at least 1." >&2
    exit 1
  fi
}
