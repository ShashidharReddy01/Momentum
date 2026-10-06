"""Phase 7.5 (ADR-0011, D2/D7): reports built from Momentum's own work data.

``ReportSpec`` (``spec.py``) → a builder per kind (``builders/``, domain queries **as the
requester**) → a neutral ``ReportDocument`` (``document.py``) → renderers (``render/``: docx, xlsx,
pdf, md, csv). The optional AI narrative is a callable handed in by ``momentum.ai``; this package
never imports ``ai`` (import-linter).
"""
