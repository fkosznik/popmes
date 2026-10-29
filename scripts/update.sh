#!/usr/bin/env bash
# Update this checkout to a specific commit. Does not restore the database
# and does not upgrade the PostgreSQL major version.
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "$0")/ops-common.sh"
ops_root
if [ "$#" -eq 0 ]; then
  interactive=1
  target=""
elif [ "$#" -eq 2 ] && [ "$2" = "--verified" ]; then
  interactive=0
  target="$1"
else
  echo "Usage: bash scripts/update.sh [tag] --verified" >&2
  echo "Without a tag, the script lists GitHub releases and proposes the newest one." >&2
  exit 1
fi
ops_lock
caddy_saved=""
restore_local_caddy() {
  if [ -z "${caddy_saved:-}" ] || [ ! -f "${caddy_saved}" ]; then
    return 0
  fi
  cp "$caddy_saved" Caddyfile
  rm -f "$caddy_saved"
  caddy_saved=""
  if [ "${USE_HTTPS:-0}" = "1" ] && [ "${COMPOSE_ARGS+x}" = "x" ]; then
    docker compose "${COMPOSE_ARGS[@]}" restart caddy || true
  fi
}
cleanup() {
  restore_local_caddy
  ops_unlock
}
trap cleanup EXIT
if [ ! -f .env ]; then
  echo "Missing .env. Refusing to update." >&2
  exit 1
fi
dirty="$(git status --porcelain)"
if [ -n "$dirty" ]; then
  dirty_count="$(printf '%s\n' "$dirty" | wc -l | tr -d ' ')"
  if [ "$dirty_count" != "1" ] || ! printf '%s\n' "$dirty" | grep -Eq '^[ M][ M] Caddyfile$'; then
    echo "The working tree has local changes. Commit or remove them before updating." >&2
    exit 1
  fi
  caddy_saved="$(mktemp)"
  cp Caddyfile "$caddy_saved"
  git restore Caddyfile 2>/dev/null || git checkout -- Caddyfile
  echo "The local Caddyfile is kept and restored when the update finishes."
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
compose_args
if [ "${DEBUG:-0}" = "1" ]; then
  echo "DEBUG=1. Refusing to update a production checkout with debug enabled." >&2
  exit 1
fi
if [ "${POPMES_ENV:-local}" = "production" ]; then
  if [ -z "${POSTGRES_APP_USER:-}" ] || [ -z "${POSTGRES_APP_PASSWORD:-}" ] || [ -z "${POSTGRES_MIGRATE_USER:-}" ] || [ -z "${POSTGRES_MIGRATE_PASSWORD:-}" ]; then
    echo "Production update requires the restricted application and migration roles." >&2
    exit 1
  fi
fi
git fetch --tags origin
if [ "$interactive" -eq 1 ]; then
  choose_release() {
    local current releases proposed choice again chosen_ver
    current="$(tr -d '[:space:]' < VERSION 2>/dev/null || true)"
    echo "Zainstalowana wersja: ${current:-nieznana}"
    releases="$(gh api --jq '.[] | select(.draft==false and .prerelease==false) | .tag_name' "repos/${repo_slug}/releases" || true)"
    if [ -z "$releases" ]; then
      echo "Nie udało się odczytać wydań z GitHuba." >&2
      exit 1
    fi
    echo "Dostępne wydania:"
    printf '%s\n' "$releases" | while IFS= read -r tag; do
      if [ "${tag#v}" = "$current" ]; then
        echo "  ${tag}  (ta wersja)"
      else
        echo "  ${tag}"
      fi
    done
    proposed="$(printf '%s\n' "$releases" | python3 -c 'import sys
rows=[line.strip() for line in sys.stdin if line.strip()]
def key(value):
    value=value[1:] if value.startswith("v") else value
    parts=[]
    for part in value.split("."):
        parts.append(int(part) if part.isdigit() else 0)
    return tuple(parts)
print(sorted(rows, key=key)[-1] if rows else "")')"
    if [ -z "$proposed" ]; then
      echo "Brak wydań." >&2
      exit 1
    fi
    if [ "${proposed#v}" = "$current" ]; then
      echo "To już jest najnowsze wydanie. Wpisanie innego tagu zejdzie na starszą wersję."
    else
      echo "Proponowana aktualizacja: ${proposed}"
    fi
    if [ ! -t 0 ]; then
      echo "Brak terminala. Użyj: bash scripts/update.sh ${proposed} --verified" >&2
      exit 1
    fi
    printf 'Enter zatwierdza %s, albo wpisz tag. q kończy: ' "$proposed"
    read -r choice
    if [ "$choice" = "q" ] || [ "$choice" = "Q" ]; then
      echo "Anulowano."
      exit 0
    fi
    if [ -z "$choice" ]; then
      choice="$proposed"
    fi
    case "$choice" in
      v*) ;;
      *) choice="v${choice}" ;;
    esac
    chosen_ver="${choice#v}"
    if [ -n "$current" ] && [ "$chosen_ver" != "$current" ] && [ "$(printf '%s\n%s\n' "$chosen_ver" "$current" | python3 -c 'import sys
rows=[line.strip() for line in sys.stdin if line.strip()]
def key(value):
    parts=[]
    for part in value.split("."):
        parts.append(int(part) if part.isdigit() else 0)
    return tuple(parts)
print(sorted(rows, key=key)[0])')" = "$chosen_ver" ]; then
      echo "To starsza wersja. Baza nie zostanie cofnięta. Wpisz ten sam tag jeszcze raz, żeby potwierdzić:"
      read -r again
      case "$again" in
        v*) ;;
        *) again="v${again}" ;;
      esac
      if [ "$again" != "$choice" ]; then
        echo "Nie potwierdzono. Anulowano." >&2
        exit 1
      fi
    fi
    target="$choice"
  }
  repo_slug="$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"
  choose_release
fi
if ! git rev-parse --verify --quiet "${target}^{commit}" >/dev/null; then
  echo "Cannot resolve ${target}." >&2
  exit 1
fi
current="$(git rev-parse HEAD)"
resolved="$(git rev-parse "${target}^{commit}")"
repo_slug="$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"
if ! command -v gh >/dev/null 2>&1; then
  echo "gh is not available, so CI for ${resolved} cannot be verified." >&2
  exit 1
fi
check_rows() {
  gh api --jq '.check_runs[] | [.name, .conclusion // "", .status // "", .head_sha] | @tsv' "repos/${repo_slug}/commits/${resolved}/check-runs" || true
}
check_matches() {
  local name="$1" checks="$2" kind="$3"
  printf '%s\n' "$checks" | awk -F '\t' -v name="$name" -v sha="$resolved" -v kind="$kind" '
    $1 == name && $4 == sha {
      if (kind == "success" && $2 == "success") found = 1
      if (kind == "failed" && ($2 == "failure" || $2 == "cancelled" || $2 == "timed_out" || $2 == "action_required")) found = 1
      if (kind == "pending" && ($3 == "queued" || $3 == "in_progress" || $3 == "pending" || $3 == "waiting" || $2 == "")) found = 1
    }
    END { exit found ? 0 : 1 }
  '
}
waited=0
pause="${UPDATE_CHECK_INTERVAL:-20}"
limit="${UPDATE_CHECK_TIMEOUT:-900}"
while true; do
  checks="$(check_rows)"
  pending=0
  for required in quality application; do
    if check_matches "$required" "$checks" success; then
      continue
    fi
    if check_matches "$required" "$checks" failed && ! check_matches "$required" "$checks" pending; then
      echo "Required check ${required} for ${resolved} is not success." >&2
      exit 1
    fi
    pending=1
    echo "Waiting for check ${required} on ${resolved}."
  done
  if [ "$pending" -eq 0 ]; then
    break
  fi
  if [ "$waited" -ge "$limit" ]; then
    echo "Timed out waiting for quality and application on ${resolved}." >&2
    exit 1
  fi
  sleep "$pause"
  waited=$((waited + pause))
done
mkdir -p updates
printf '%s current=%s target=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current" "$resolved" >> updates/history.log
one_container() {
  local service="$1" ids count
  if ! ids="$(docker compose "${COMPOSE_ARGS[@]}" ps -aq "$service")"; then
    echo "Cannot list the ${service} container. Update stopped before services were stopped." >&2
    exit 1
  fi
  count="$(printf '%s\n' "$ids" | grep -c . || true)"
  if [ "$count" -ne 1 ]; then
    echo "Need exactly one ${service} container, found ${count}. Update stopped before services were stopped." >&2
    exit 1
  fi
  printf '%s\n' "$ids" | head -n 1
}
backend_cid="$(one_container backend)"
frontend_cid="$(one_container frontend)"
if ! backend_image="$(docker inspect --format '{{.Image}}' "$backend_cid")" || [ -z "$backend_image" ]; then
  echo "Cannot read the image of the running backend container. Update stopped before services were stopped." >&2
  exit 1
fi
if ! frontend_image="$(docker inspect --format '{{.Image}}' "$frontend_cid")" || [ -z "$frontend_image" ]; then
  echo "Cannot read the image of the running frontend container. Update stopped before services were stopped." >&2
  exit 1
fi
attempt_dir="updates/$(date -u +%Y%m%dT%H%M%SZ)-$$-${RANDOM}"
mkdir "$attempt_dir"
write_atomic "$attempt_dir/backend.image" "$backend_image"
write_atomic "$attempt_dir/frontend.image" "$frontend_image"
write_atomic "$attempt_dir/checkout" "$current"
restore_hint() {
  echo "Rollback uses the images recorded in ${attempt_dir}. It does not restore the database and does not undo migrations." >&2
  echo "  git checkout --detach ${current}" >&2
  echo "  docker tag ${backend_image} popmes-backend:latest" >&2
  echo "  docker tag ${frontend_image} popmes-frontend:latest" >&2
  echo "  docker compose ${COMPOSE_ARGS[*]} up -d --no-build" >&2
}
rollback_code() {
  git checkout --detach "$current" >/dev/null
  docker tag "$backend_image" popmes-backend:latest
  docker tag "$frontend_image" popmes-frontend:latest
  POPMES_LOCK_HELD=1 docker compose "${COMPOSE_ARGS[@]}" up -d --no-build
}
echo "Building images for ${resolved} before stopping the application."
echo "Running containers stay on ${backend_image} and ${frontend_image} until this update replaces them."
git checkout --detach "$resolved"
if ! docker compose "${COMPOSE_ARGS[@]}" build; then
  echo "Build failed. The running images were not replaced." >&2
  rollback_code || true
  echo "Backend was left on the image recorded before the build. Database was not restored." >&2
  restore_hint
  exit 1
fi
echo "Stopping the backend so backup and migrations see a quiet database."
docker compose "${COMPOSE_ARGS[@]}" stop backend
if ! POPMES_KEEP_BACKEND_STOPPED=1 POPMES_LOCK_HELD=1 bash scripts/backup.sh; then
  echo "Backup failed. The backend is still stopped. No migration was started." >&2
  restore_hint
  exit 1
fi
if ! POPMES_LOCK_HELD=1 bash scripts/migrate.sh; then
  echo "Migration failed. The backend is stopped. The database was not restored." >&2
  echo "Code rollback does not undo migrations." >&2
  restore_hint
  exit 1
fi
if ! docker compose "${COMPOSE_ARGS[@]}" up -d --no-build --wait --wait-timeout 180; then
  echo "Containers did not become healthy. Backend may be running and failing its check." >&2
  restore_hint
  echo "Do not restore the database unless you accept losing writes made after the backup." >&2
  exit 1
fi
url="$(health_url)"
if ! curl -fsS --max-time 10 "$url" >/dev/null; then
  echo "Health endpoint did not answer at ${url}." >&2
  echo "Containers were started. Rollback uses the recorded images and does not restore the database." >&2
  restore_hint
  exit 1
fi
echo "Update finished. Running ${resolved}. Previous checkout ${current}."
echo "Previous images are recorded in ${attempt_dir}."
echo "PostgreSQL major version was not changed."
