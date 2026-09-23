"""Recreate the (synthetic-data-only) E2E database from scratch.

Refuses to touch any database whose name doesn't end in "_e2e", so it can never be pointed
at a real one by mistake.
"""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg import sql

url = os.environ["MOMENTUM_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
info = psycopg.conninfo.conninfo_to_dict(url)
name = str(info.get("dbname", ""))
if not name.endswith("_e2e"):
    sys.exit(f"refusing to reset {name!r}: E2E database names must end in _e2e")
admin = psycopg.conninfo.make_conninfo(url, dbname="postgres")
with psycopg.connect(admin, autocommit=True) as conn:
    conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
print(f"reset {name}")
