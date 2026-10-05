#!/usr/bin/env bash
# Momentum backup (S7.5.5): the Momentum schema (pg_dump custom format: every table, the job
# queue, sequences) plus the attachment files, into one folder. Production also has Azure's
# point-in-time restore; this is the portable copy and what the rehearsal restores.
#
#   tools/ops/backup.sh <out dir>
# Reads MOMENTUM_DATABASE_URL (the app's URL, +psycopg is fine), MOMENTUM_DB_SCHEMA (default
# momentum) and MOMENTUM_STORAGE_LOCAL_DIR (default ./.data/files). PG_EXEC runs the Postgres
# client tools somewhere else, e.g. PG_EXEC="docker exec -i compose-postgres-1" locally.
set -euo pipefail
OUT="${1:?usage: backup.sh <out dir>}"
URL="${MOMENTUM_DATABASE_URL:?set MOMENTUM_DATABASE_URL}"
URL="${URL/+psycopg/}"
SCHEMA="${MOMENTUM_DB_SCHEMA:-momentum}"
FILES="${MOMENTUM_STORAGE_LOCAL_DIR:-./.data/files}"
PG_EXEC="${PG_EXEC:-}"
mkdir -p "$OUT"
$PG_EXEC pg_dump --format=custom --no-owner --no-privileges --schema="$SCHEMA" "$URL" > "$OUT/db.dump"
if [ -d "$FILES" ]; then tar -czf "$OUT/files.tar.gz" -C "$FILES" .; fi
EXTENSIONS=$($PG_EXEC psql "$URL" -Atc "select string_agg(extname, ',') from pg_extension where extname <> 'plpgsql'")
{
  echo "schema=$SCHEMA"
  echo "extensions=$EXTENSIONS"
  echo "taken_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "db_bytes=$(wc -c < "$OUT/db.dump")"
  [ -f "$OUT/files.tar.gz" ] && echo "files_bytes=$(wc -c < "$OUT/files.tar.gz")"
} > "$OUT/backup.txt"
echo "backup written to $OUT"
