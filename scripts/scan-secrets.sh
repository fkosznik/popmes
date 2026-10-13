#!/usr/bin/env bash
# Fail if tracked files look like private keys or cloud credentials.
# The CI test password in the workflow is a fixture, not a production secret.
set -euo pipefail
cd "$(dirname "$0")/.."
if git grep -n -I -E 'BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY' -- . ':!.github/workflows/ci.yml' >/dev/null; then
  echo "A private key is tracked in git." >&2
  git grep -n -I -E 'BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY' -- . ':!.github/workflows/ci.yml' >&2 || true
  exit 1
fi
if git grep -n -I -E 'AKIA[0-9A-Z]{16}' -- . >/dev/null; then
  echo "An AWS access key id is tracked in git." >&2
  exit 1
fi
echo "No private keys or AWS access key ids in tracked files."
