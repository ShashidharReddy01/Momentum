#!/usr/bin/env bash
# Momentum restore (S7.5.5): a backup.sh folder into a database whose Momentum schema doesn't
# exist yet (a fresh environment), then the files. Run migrations afterwards only when the app
# version is newer than the backup's.
#
#   tools/ops/restore.sh <backup dir>
# Reads the same variables as backup.sh (MOMENTUM_DATABASE_URL points at the *target*).
set -euo pipefail
IN="${1:?usage: restore.sh <backup dir>}"
URL="${MOMENTUM_DATABASE_URL:?set MOMENTUM_DATABASE_URL}"
URL="${URL/+psycopg/}"
SCHEMA="${MOMENTUM_DB_SCHEMA:-momentum}"
FILES="${MOMENTUM_STORAGE_LOCAL_DIR:-./.data/files}"
PG_EXEC="${PG_EXEC:-}"
exists=$($PG_EXEC psql "$URL" -Atc "select 1 from information_schema.schemata where schema_name = '$SCHEMA'")
if [ "$exists" = "1" ]; then
  echo "schema $SCHEMA already exists in the target: restore into a fresh database" >&2
  exit 1
fi
# extensions live outside the schema (vector, citext, pg_trgm...): the target needs the same ones
EXTENSIONS=$(sed -n 's/^extensions=//p' "$IN/backup.txt")
for ext in ${EXTENSIONS//,/ }; do
  $PG_EXEC psql "$URL" -v ON_ERROR_STOP=1 -qc "create extension if not exists \"$ext\""
done
$PG_EXEC pg_restore --no-owner --no-privileges --exit-on-error --dbname="$URL" < "$IN/db.dump"
if [ -f "$IN/files.tar.gz" ]; then mkdir -p "$FILES" && tar -xzf "$IN/files.tar.gz" -C "$FILES"; fi
echo "restored $IN into schema $SCHEMA"
