#!/usr/bin/env bash
# Bidirectional cross-language index cache interop over one Redis.
# One language points a RAM mount's index at a Redis key prefix through
# the workspace-level index config and records a listing, an empty
# listing and the entries under them; the other attaches to the same
# prefix and must read them back as the same facts (entry fields, listing
# order, "listed but empty" versus "never listed"), then invalidate and
# clear them for both. This is the one place the two stores' wire format
# is compared against each other rather than against a literal.
#
# Usage: index_store.sh
#   Requires REDIS_URL (defaults to redis://localhost:6379/0), the python
#   venv at python/.venv, and built TypeScript dists (pnpm -r build).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${PY:-$ROOT/python/.venv/bin/python}"
RUN_ID="$RANDOM$RANDOM"
fail=0

run_direction() {
  local writer_name="$1" reader_name="$2"
  local prefix="mirage-integ-xindex-${RUN_ID}-${writer_name}:"
  echo
  echo "===== $writer_name index write -> $reader_name index read ====="
  if [ "$writer_name" == "py" ]; then
    "$PY" "$HERE/index_store.py" write "$prefix" || fail=1
    (cd "$ROOT/typescript" && pnpm --filter @struktoai/mirage-integ exec tsx index_store.ts read "$prefix") || fail=1
  else
    (cd "$ROOT/typescript" && pnpm --filter @struktoai/mirage-integ exec tsx index_store.ts write "$prefix") || fail=1
    "$PY" "$HERE/index_store.py" read "$prefix" || fail=1
  fi
}

run_direction "py" "ts"
run_direction "ts" "py"

if [ "$fail" != "0" ]; then
  echo
  echo "Cross-language index store interop FAILED."
  exit 1
fi
echo
echo "Cross-language index store interop OK (both directions)."
