#!/usr/bin/env bash
# Phase 7 load test (E7.1): a throwaway Momentum at the planned size. Fresh synthetic database
# (name must end in _e2e), migrations, `seed --scale` (~150 people, 60 projects, 50k tasks), dev
# login, mock AI, realtime on, the built SPA. Then run tools/load/locustfile.py against it.
#   SKIP_RESET=1 reuses an already-seeded database (seeding takes a few minutes).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export MOMENTUM_DATABASE_URL="${MOMENTUM_LOAD_DATABASE_URL:-postgresql+psycopg://momentum:momentum@localhost:5432/momentum_load_e2e}"
export MOMENTUM_AUTH_MODE=dev
export MOMENTUM_ENV=local
export MOMENTUM_LLM_MODE=mock
export MOMENTUM_SPA_DIR="$ROOT/apps/web/dist"
export MOMENTUM_WEB_WORKERS="${WEB_WORKERS:-4}"  # ~150 active people need 3-4 web processes
cd "$ROOT/apps/api"
if [ "${SKIP_RESET:-0}" != "1" ]; then
  uv run python "$ROOT/tools/e2e/reset_db.py"
  uv run momentum migrate
  time uv run momentum seed --scale
fi
uv run momentum serve --port "${LOAD_PORT:-8150}"
