"""Programmatic Alembic entry point (used by the CLI and DB_AUTO_MIGRATE)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from momentum.core.settings import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(settings: Settings) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["momentum_settings"] = settings
    return cfg


def upgrade_head(settings: Settings) -> None:
    command.upgrade(alembic_config(settings), "head")


def downgrade(settings: Settings, revision: str) -> None:
    command.downgrade(alembic_config(settings), revision)
