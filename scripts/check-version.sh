#!/usr/bin/env bash
# VERSION is the only application version. package.json must match it.
# A release tag, when present, must name that same version.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(tr -d '[:space:]' < "$root/VERSION")"
if [ -z "$version" ]; then
  echo "VERSION is empty." >&2
  exit 1
fi
package="$(
  python3 - "$root/frontend/package.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])
PY
)"
if [ "$package" != "$version" ]; then
  echo "frontend/package.json is ${package}, but VERSION is ${version}." >&2
  exit 1
fi
tag="${1:-}"
if [ -z "$tag" ]; then
  case "${GITHUB_REF:-}" in
    refs/tags/*) tag="${GITHUB_REF#refs/tags/}" ;;
  esac
fi
if [ -n "$tag" ]; then
  case "$tag" in
    v*) numbered="${tag#v}" ;;
    *) numbered="$tag" ;;
  esac
  if [ "$numbered" != "$version" ]; then
    echo "Tag ${tag} does not match VERSION ${version}." >&2
    exit 1
  fi
fi
echo "Version ${version} is consistent."
