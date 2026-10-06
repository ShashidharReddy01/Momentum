"""Archives: a .zip's entry list only. Nothing inside is extracted or read (no recursion): Mo
says to attach the file inside on its own to read it."""

from __future__ import annotations

import io
import zipfile

from momentum.files.model import ArchiveEntry, ArchiveInfo, ParseResult
from momentum.files.parsers.base import Builder

MAX_ENTRIES = 500


def parse_zip(data: bytes, filename: str, mime: str) -> ParseResult:
    b = Builder(data, filename, mime, "archive")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
    b.model.archive = ArchiveInfo(
        entries=[ArchiveEntry(path=i.filename, size=i.file_size) for i in infos[:MAX_ENTRIES]],
        skipped_reason="Files inside an archive aren't opened: attach the one you need on its own",
    )
    if len(infos) > MAX_ENTRIES:
        b.header.truncated = True
        b.warn(f"The archive lists {len(infos):,} files: only the first {MAX_ENTRIES} are shown")
    return b.done()
