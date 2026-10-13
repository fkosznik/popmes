#!/usr/bin/env bash
# Copy VERSION into frontend/package.json. Run this when preparing a release.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(tr -d '[:space:]' < "$root/VERSION")"
python3 - "$root/frontend/package.json" "$version" <<'PY'
import json, sys
path, version = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
data["version"] = version
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY
bash "$root/scripts/check-version.sh"
