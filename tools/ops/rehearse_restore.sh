#!/usr/bin/env bash
# Restore rehearsal (S7.5.5): back up a database, restore it into a brand-new one, and prove they
# hold the same data: `momentum export` of both must give identical table checksums.
#
#   tools/ops/rehearse_restore.sh <source database url> <new database name>
# Example (local Docker Postgres):
#   PG_EXEC="docker exec -i compose-postgres-1" tools/ops/rehearse_restore.sh \
#     postgresql+psycopg://momentum:momentum@localhost:5432/momentum momentum_restore_rehearsal
set -euo pipefail
SRC="${1:?source database url}"
NEW="${2:?name for the new database}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PG_EXEC="${PG_EXEC:-}"
# inside a container the database is at localhost:5432 whatever the host port is
inner() { echo "${1/+psycopg/}" | sed -E 's#@[^/]+/#@localhost:5432/#'; }
ADMIN_URL="$(inner "$SRC" | sed -E 's#/[^/]+$#/postgres#')"
NEW_URL="${SRC%/*}/$NEW"

echo "1/4 backup of $(basename "$SRC")"
MOMENTUM_DATABASE_URL="$(inner "$SRC")" MOMENTUM_STORAGE_LOCAL_DIR="$WORK/none" \
  "$ROOT/tools/ops/backup.sh" "$WORK/backup" >/dev/null
echo "2/4 a fresh database $NEW"
$PG_EXEC psql "$ADMIN_URL" -qc "drop database if exists $NEW" -c "create database $NEW"
echo "3/4 restore"
MOMENTUM_DATABASE_URL="$(inner "$NEW_URL")" MOMENTUM_STORAGE_LOCAL_DIR="$WORK/files" \
  "$ROOT/tools/ops/restore.sh" "$WORK/backup" >/dev/null
echo "4/4 compare (momentum export of both)"
cd "$ROOT/apps/api"
MOMENTUM_DATABASE_URL="$SRC" uv run momentum export --out "$WORK/a" >/dev/null
MOMENTUM_DATABASE_URL="$NEW_URL" uv run momentum export --out "$WORK/b" >/dev/null
python - "$WORK/a/manifest.json" "$WORK/b/manifest.json" <<'PY'
import json, sys
a, b = (json.load(open(p))["tables"] for p in sys.argv[1:3])
diff = [t for t in sorted(set(a) | set(b)) if a.get(t) != b.get(t)]
rows = sum(t["rows"] for t in a.values())
if diff:
    sys.exit(f"MISMATCH in {len(diff)} tables: {', '.join(diff)}")
print(f"restore rehearsal OK: {len(a)} tables, {rows} rows, identical checksums")
PY
