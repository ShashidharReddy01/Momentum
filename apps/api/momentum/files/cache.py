"""Phase 7.5 (spec §4.3): parse a file the first time Mo needs it, then reuse the result.

``get_or_parse`` looks for a ``file_parses`` row at the current ``PARSER_VERSION``; if there is
none it reads the bytes from storage, parses them in a worker thread under
``MOMENTUM_FILE_PARSE_TIMEOUT_S`` and stores the model (database) and the sheet rows (gzipped JSON
in the storage backend). A cache entry is not a change to anyone's data, so it records no
activity. Callers check visibility **before** calling: this module knows nothing about who may
see a file (it can't import ``domain``).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from momentum.core.ids import new_id
from momentum.core.settings import Settings
from momentum.core.storage import StorageBackend
from momentum.core.telemetry import get_logger
from momentum.files import model as file_model
from momentum.files.kinds import kind_of
from momentum.files.model import Cell, DocumentModel, FileHeader, ParseResult
from momentum.files.models import FileParse
from momentum.files.parse import parse_bytes

log = get_logger("files.cache")

# read through this module so a test can bump it; the parsers' own is the source of truth
PARSER_VERSION = file_model.PARSER_VERSION

TIMEOUT_MESSAGE = "That file took too long to read"


@dataclass(frozen=True)
class FileSource:
    """What the cache needs about a file, from an attachment or a conversation file."""

    workspace_id: uuid.UUID
    storage_key: str
    filename: str
    mime: str
    size: int
    attachment_id: uuid.UUID | None = None
    conversation_file_id: uuid.UUID | None = None

    @property
    def file_id(self) -> uuid.UUID:
        fid = self.attachment_id or self.conversation_file_id
        assert fid is not None
        return fid


@dataclass
class CachedParse:
    status: str
    model: DocumentModel
    rows_key: str | None
    storage: StorageBackend
    error: str | None = None
    _rows: dict[str, list[list[Cell]]] | None = field(default=None, repr=False)

    async def rows(self, data_ref: str) -> list[list[Cell]]:
        if self._rows is None:
            if self.rows_key is None:
                self._rows = {}
            else:
                raw = await self.storage.read(self.rows_key)
                self._rows = json.loads(gzip.decompress(raw))
        return self._rows.get(data_ref, [])


def _rows_key(src: FileSource) -> str:
    return f"{src.workspace_id}/parses/{src.file_id}/v{PARSER_VERSION}.json.gz"


async def _one(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _where(src: FileSource):  # type: ignore[no-untyped-def]
    col = FileParse.attachment_id if src.attachment_id else FileParse.conversation_file_id
    return [col == src.file_id, FileParse.parser_version == PARSER_VERSION]


async def cached(
    session: AsyncSession, src: FileSource, storage: StorageBackend
) -> CachedParse | None:
    row = (await session.execute(select(FileParse).where(*_where(src)))).scalar_one_or_none()
    if row is None:
        return None
    return CachedParse(
        status=row.status,
        model=DocumentModel.model_validate(row.model),
        rows_key=row.rows_key,
        storage=storage,
        error=row.error,
    )


async def parse_with_timeout(data: bytes, src: FileSource, settings: Settings) -> ParseResult:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                parse_bytes, data, src.filename, src.mime, max_rows=settings.file_parse_max_rows
            ),
            timeout=settings.file_parse_timeout_s,
        )
    except TimeoutError:
        header = FileHeader(
            filename=src.filename,
            mime=src.mime,
            kind=kind_of(src.mime, src.filename),
            size=src.size,
            warnings=[TIMEOUT_MESSAGE],
        )
        return ParseResult(status="failed", model=DocumentModel(file=header), error="timeout")


async def get_or_parse(
    session: AsyncSession, src: FileSource, *, storage: StorageBackend, settings: Settings
) -> CachedParse:
    hit = await cached(session, src, storage)
    if hit is not None:
        return hit
    data = await storage.read(src.storage_key)
    result = await parse_with_timeout(data, src, settings)
    result.model.file.attachment_id = src.attachment_id or src.conversation_file_id
    rows_key: str | None = None
    if result.rows:
        rows_key = _rows_key(src)
        payload = gzip.compress(json.dumps(result.rows, separators=(",", ":")).encode())
        await storage.save_stream(rows_key, _one(payload))
    stmt = (
        insert(FileParse)
        .values(
            id=new_id(),
            workspace_id=src.workspace_id,
            attachment_id=src.attachment_id,
            conversation_file_id=src.conversation_file_id,
            parser_version=PARSER_VERSION,
            status=result.status,
            model=result.model.model_dump(mode="json"),
            rows_key=rows_key,
            error=result.error,
        )
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)
    log.info(
        "file_parsed",
        file_id=str(src.file_id),
        status=result.status,
        sheets=len(result.model.sheets),
        blocks=len(result.model.blocks),
    )
    return CachedParse(
        status=result.status,
        model=result.model,
        rows_key=rows_key,
        storage=storage,
        error=result.error,
        _rows=result.rows,
    )
