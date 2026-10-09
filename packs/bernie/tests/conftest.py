"""Bernie's pure tests run in the API gate (pytest's testpaths include ../../packs); they use only
this pack and the synthetic generator. The tests that need a database live in
apps/api/tests/test_bernie_pipeline.py (they reuse the API's fixtures)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # `synth`
