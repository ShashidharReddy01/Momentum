"""Phase 7.5 (ADR-0011): file understanding without AI.

Parsers turn an attachment's bytes into a ``DocumentModel`` (``files/model.py``), cached per
attachment (``files/cache.py``); ``files/tables.py`` runs exact table queries over the cached rows;
``files/render.py`` turns a PDF page or an image into a capped JPEG for the vision model;
``files/safety.py`` holds the limits. Nothing here executes file content (macros, formulas,
scripts, embedded objects) and nothing here imports ``momentum.ai`` or ``momentum.domain``:
``domain``, ``reports`` and ``ai`` call in, never the other way round (import-linter).
"""
