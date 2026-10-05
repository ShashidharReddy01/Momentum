# Backup and restore

Production's first line is Azure Database for PostgreSQL's automatic backups and point-in-time
restore (enabled at go-live, phase-8.md checklist). This runbook is the portable copy: a backup
you can keep anywhere and restore into any fresh Postgres, rehearsed (S7.5.5).

## Back up

```bash
MOMENTUM_DATABASE_URL=postgresql://... MOMENTUM_DB_SCHEMA=momentum \
MOMENTUM_STORAGE_LOCAL_DIR=/path/to/files tools/ops/backup.sh backups/2026-10-06
```

The folder holds `db.dump` (`pg_dump` custom format of the Momentum schema: every table, the job
queue, sequences), `files.tar.gz` (attachments) and `backup.txt` (schema, time, sizes, and the
Postgres extensions the database uses). Locally, prefix `PG_EXEC="docker exec -i compose-postgres-1"`
to use the container's client tools.

## Restore

Into a database where the Momentum schema doesn't exist yet (a fresh environment):

```bash
MOMENTUM_DATABASE_URL=postgresql://.../momentum_new tools/ops/restore.sh backups/2026-10-06
```

It creates the extensions the backup lists (vector, citext, pg_trgm...), restores the schema and
unpacks the files. If the app is newer than the backup, run `momentum migrate` afterwards. Point
the app at the new database and check `/healthz` and `momentum smoke`.

## Rehearse

```bash
PG_EXEC="docker exec -i compose-postgres-1" tools/ops/rehearse_restore.sh \
  postgresql+psycopg://momentum:momentum@localhost:5432/momentum momentum_restore_rehearsal
```

Backs up the source, restores into a brand-new database, then exports both with `momentum
export` and requires identical per-table checksums.

**Rehearsed 2026-10-06** (local Docker Postgres 16): the dev database (55 tables, 377 rows) and
the 50,000-task load-test database (55 tables, 280,957 rows, 116 s end to end) restored with
identical checksums. Found and fixed while rehearsing: the restore needs every extension the
source uses (`pg_trgm` for name search, not only `vector` and `citext`), so the backup now
records them.

## Other ways to move data

`momentum export --out bundle.zip --with-files` / `momentum import bundle.zip` (S7.5.1) is the
database-independent route (another host, an embedding application): versioned JSON with
checksums; see `docs/architecture/embedding-and-portability.md` §3.
