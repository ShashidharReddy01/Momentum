"""Momentum: AI-native work management.

Importing this package has no side effects. Use :func:`create_app` for a standalone
application or :func:`mount_momentum` to embed Momentum inside a host FastAPI app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["Settings", "create_app", "mount_momentum"]

if TYPE_CHECKING:
    from momentum.app import create_app, mount_momentum
    from momentum.core.settings import Settings


def __getattr__(name: str) -> Any:
    if name in ("create_app", "mount_momentum"):
        from momentum import app

        return getattr(app, name)
    if name == "Settings":
        from momentum.core.settings import Settings

        return Settings
    raise AttributeError(name)
