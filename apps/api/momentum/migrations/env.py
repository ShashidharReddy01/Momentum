"""Alembic environment. Everything (including alembic_version) lives in MOMENTUM_DB_SCHEMA."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, text

from momentum.core.settings import Settings
from momentum.models import metadata

config = context.config
settings: Settings = config.attributes.get("momentum_settings") or Settings()
schema = settings.db_schema


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    # Ignore tables we don't model in SQLAlchemy (alembic's own, Procrastinate's).
    return not (
        type_ == "table"
        and name is not None
        and (name == "alembic_version" or name.startswith("procrastinate"))
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=metadata,
        literal_binds=True,
        version_table_schema=schema,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.execute(text(f"SET search_path TO {settings.search_path}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=metadata,
            version_table_schema=schema,
            include_schemas=False,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
