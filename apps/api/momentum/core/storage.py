"""S2.6.1: file storage abstraction (`docs/architecture/overview.md`'s `StorageBackend`).

Only `local` (the filesystem) is implemented — Azure Blob is Phase 9 per
`docs/architecture/configuration.md`. `key` is always a server-generated, UUID-based path
(never derived from user-supplied input like a filename), so there is no path-traversal
surface to defend against here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from momentum.core.settings import Settings


class StorageBackend(ABC):
    @abstractmethod
    async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> None: ...

    @abstractmethod
    async def read(self, key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...


class LocalStorageBackend(StorageBackend):
    def __init__(self, root_dir: str) -> None:
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._root / key

    async def save_stream(self, key: str, chunks: AsyncIterator[bytes]) -> None:
        path = self._path(key)
        await anyio.Path(path.parent).mkdir(parents=True, exist_ok=True)
        async with await anyio.open_file(path, "wb") as f:
            async for chunk in chunks:
                await f.write(chunk)

    async def read(self, key: str) -> bytes:
        return await anyio.Path(self._path(key)).read_bytes()

    async def delete(self, key: str) -> None:
        p = anyio.Path(self._path(key))
        if await p.exists():
            await p.unlink()


def build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.storage_local_dir)
    raise NotImplementedError(
        f"Storage backend {settings.storage_backend!r} isn't implemented yet "
        "(Azure Blob is Phase 9)"
    )
