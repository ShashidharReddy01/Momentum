"""S7.5.1: export a Momentum database to a versioned bundle, and import one into an empty one
(``docs/architecture/embedding-and-portability.md``).

A bundle is a directory (or the same as a ``.zip``):

- ``manifest.json``: the format version, the migration revision it was taken at, when, and per
  table its row count and the SHA-256 of its rows;
- ``tables/<table>.jsonl``: every row, one canonical JSON object per line, in primary-key order,
  every column but the computed ones (search vectors are rebuilt by the database);
- ``files/<storage key>`` (with ``--files``): every attachment's stored bytes.

Ids are kept, so links, mentions and external references keep working. Import is into an empty
schema at the same migration revision: tables load parent-first, the few foreign keys that point
forward or at their own table (a subtask's parent, a goal's parent, an agent's user) are filled in
a second pass, sequences are moved past the imported ids, and every table's checksum is verified
against the manifest before the transaction commits. The same JSON lines come out of an export of
the imported database, which is the round-trip test.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Table, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.db import Base
from momentum.core.storage import StorageBackend

FORMAT = 1
BATCH = 1000
SKIP = {"idempotency_keys"}  # short-lived request dedupe keys: nothing to carry over


class PortabilityError(Exception):
    """The bundle can't be imported here (wrong version, not empty, a checksum mismatch...)."""


@dataclass
class TableInfo:
    rows: int = 0
    sha256: str = ""


@dataclass
class Manifest:
    format: int
    revision: str
    exported_at: str
    tables: dict[str, TableInfo] = field(default_factory=dict)
    files: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "revision": self.revision,
            "exported_at": self.exported_at,
            "tables": {k: {"rows": v.rows, "sha256": v.sha256} for k, v in self.tables.items()},
            "files": self.files,
        }

    @classmethod
    def of(cls, data: dict[str, Any]) -> Manifest:
        return cls(
            format=int(data["format"]),
            revision=str(data["revision"]),
            exported_at=str(data["exported_at"]),
            tables={
                k: TableInfo(int(v["rows"]), str(v["sha256"])) for k, v in data["tables"].items()
            },
            files=int(data.get("files", 0)),
        )


def tables() -> list[Table]:
    import momentum.models  # noqa: F401  (registers every table on Base.metadata)

    return [t for t in Base.metadata.sorted_tables if t.name not in SKIP]


def _columns(table: Table) -> list[Any]:
    return [c for c in table.columns if c.computed is None]


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode()
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_encode(v) for v in value]
    if hasattr(value, "tolist"):  # a pgvector embedding (numpy array)
        return [float(x) for x in value.tolist()]
    raise TypeError(f"can't export a {type(value).__name__}")


def _decode(column: Any, value: Any) -> Any:
    if value is None:
        return None
    kind = type(column.type).__name__
    if kind == "Uuid":
        return uuid.UUID(value)
    if kind == "DateTime":
        return datetime.fromisoformat(value)
    if kind == "Date":
        return date.fromisoformat(value)
    if kind == "Numeric":
        return Decimal(value)
    if kind == "LargeBinary":
        return base64.b64decode(value)
    return value


def _line(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


async def _rows(session: AsyncSession, table: Table) -> AsyncIterator[dict[str, Any]]:
    cols = _columns(table)
    pk = list(table.primary_key.columns) or cols
    result = await session.stream(select(*cols).order_by(*pk).execution_options(yield_per=BATCH))
    async for row in result:
        yield {c.name: _encode(v) for c, v in zip(cols, row, strict=True)}


async def revision(session: AsyncSession) -> str:
    value = (await session.execute(text("select version_num from alembic_version"))).scalar_one()
    return str(value)


async def export_to(
    session: AsyncSession,
    out: Path,
    *,
    storage: StorageBackend | None = None,
    with_files: bool = False,
) -> Manifest:
    """Write a bundle directory at ``out`` (created; must not exist or be empty). File writes
    are plain blocking I/O: an export is an operator's offline task, not a request path."""
    _prepare(out)
    manifest = Manifest(FORMAT, await revision(session), datetime.now(UTC).isoformat())
    for table in tables():
        digest = hashlib.sha256()
        count = 0
        with (out / "tables" / f"{table.name}.jsonl").open(
            "w", encoding="utf-8", newline="\n"
        ) as f:
            async for row in _rows(session, table):
                line = _line(row)
                f.write(line + "\n")
                digest.update(line.encode() + b"\n")
                count += 1
        manifest.tables[table.name] = TableInfo(count, digest.hexdigest())
    if with_files:
        if storage is None:
            raise PortabilityError("--files needs the file storage")
        keys = (await session.execute(text("select storage_key from attachments"))).scalars()
        for key in keys:
            target = out / "files" / key
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_bytes(await storage.read(key))
                manifest.files += 1
            except FileNotFoundError:
                continue  # a file already gone from storage: the row still says what it was
    (out / "manifest.json").write_text(json.dumps(manifest.to_json(), indent=2), encoding="utf-8")
    return manifest


def _prepare(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise PortabilityError(f"{out} isn't empty")
    (out / "tables").mkdir()


def zip_bundle(directory: Path, target: Path) -> Path:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(directory).as_posix())
    return target


def _open(bundle: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if bundle.is_dir():
        return bundle, None
    tmp = tempfile.TemporaryDirectory(prefix="momentum-import-")
    with zipfile.ZipFile(bundle) as z:
        for name in z.namelist():  # never write outside the temporary directory
            if name.startswith("/") or ".." in Path(name).parts:
                raise PortabilityError(f"unsafe path in the bundle: {name}")
        z.extractall(tmp.name)
    return Path(tmp.name), tmp


def _lines(path: Path) -> Iterator[str]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield line.rstrip("\n")


async def import_from(
    session: AsyncSession, bundle: Path, *, storage: StorageBackend | None = None
) -> Manifest:
    """Load a bundle (directory or .zip) into this empty database, in the caller's transaction."""
    root, tmp = _open(bundle)
    try:
        manifest = Manifest.of(json.loads((root / "manifest.json").read_text(encoding="utf-8")))
        if manifest.format != FORMAT:
            raise PortabilityError(f"bundle format {manifest.format}; this version reads {FORMAT}")
        here = await revision(session)
        if manifest.revision != here:
            raise PortabilityError(
                f"the bundle was exported at migration {manifest.revision}; this database is at "
                f"{here} (migrate one of them first)"
            )
        order = tables()
        for table in order:
            if (await session.execute(select(func.count()).select_from(table))).scalar_one():
                raise PortabilityError(f"the database isn't empty ({table.name} has rows)")

        loaded = {t.name for t in order}
        deferred: list[tuple[Table, dict[str, Any], dict[str, Any]]] = []
        seen: set[str] = set()
        for table in order:
            cols = {c.name: c for c in _columns(table)}
            # foreign keys to a table not loaded yet (or to this one) wait for the second pass
            later = {
                fk.parent.name
                for fk in table.foreign_keys
                if fk.column.table.name not in seen and fk.column.table.name in loaded
            }
            batch: list[dict[str, Any]] = []
            for line in _lines(root / "tables" / f"{table.name}.jsonl"):
                raw = json.loads(line)
                row = {k: _decode(cols[k], v) for k, v in raw.items() if k in cols}
                held = {k: row[k] for k in later if row.get(k) is not None}
                if held:
                    pk = {c.name: row[c.name] for c in table.primary_key.columns}
                    # the second pass must not touch on-update columns (updated_at)
                    keep = {c.name: row[c.name] for c in cols.values() if c.onupdate is not None}
                    deferred.append((table, pk, {**keep, **held}))
                    row.update({k: None for k in held})
                batch.append(row)
                if len(batch) >= BATCH:
                    await session.execute(table.insert(), batch)
                    batch = []
            if batch:
                await session.execute(table.insert(), batch)
            seen.add(table.name)
        for table, pk, held in deferred:
            await session.execute(
                update(table).where(*[table.c[k] == v for k, v in pk.items()]).values(**held)
            )
        await _reset_sequences(session, order)

        # verify: what's in the database now is exactly what the bundle holds
        for table in order:
            digest = hashlib.sha256()
            count = 0
            async for row in _rows(session, table):
                digest.update(_line(row).encode() + b"\n")
                count += 1
            want = manifest.tables.get(table.name, TableInfo())
            if (count, digest.hexdigest()) != (want.rows, want.sha256 or digest.hexdigest()):
                raise PortabilityError(
                    f"{table.name}: {count} rows don't match the bundle's {want.rows} "
                    "(or their contents differ)"
                )
        if storage is not None and (root / "files").exists():
            for path in (root / "files").rglob("*"):
                if path.is_file():
                    key = path.relative_to(root / "files").as_posix()

                    async def chunk(data: bytes = path.read_bytes()) -> AsyncIterator[bytes]:
                        yield data

                    await storage.save_stream(key, chunk())
        return manifest
    finally:
        if tmp is not None:
            tmp.cleanup()


async def _reset_sequences(session: AsyncSession, order: list[Table]) -> None:
    """Serial columns continue after the imported ids (e.g. the events outbox)."""
    for table in order:
        for col in table.primary_key.columns:
            if type(col.type).__name__ not in ("Integer", "BigInteger"):
                continue
            seq = (
                await session.execute(
                    text("select pg_get_serial_sequence(:t, :c)"),
                    {
                        "t": f"{table.schema + '.' if table.schema else ''}{table.name}",
                        "c": col.name,
                    },
                )
            ).scalar_one_or_none()
            if seq:
                top = (await session.execute(select(func.coalesce(func.max(col), 0)))).scalar_one()
                await session.execute(
                    text("select setval(:s, :v, false)"), {"s": seq, "v": int(top) + 1}
                )


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
