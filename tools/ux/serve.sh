#!/usr/bin/env bash
# Starts a throwaway Momentum with the showcase workspace for UI audits (tools/ux/audit.mjs):
# fresh synthetic database (name must end in _e2e), migrations, `seed --showcase` (every screen and
# state), dev login, mock AI, the built SPA. Build the SPA first (`pnpm build` in apps/web).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export MOMENTUM_DATABASE_URL="${MOMENTUM_UX_DATABASE_URL:-postgresql+psycopg://momentum:momentum@localhost:5432/momentum_ux_e2e}"
export MOMENTUM_AUTH_MODE=dev
export MOMENTUM_ENV=local
export MOMENTUM_LLM_MODE=mock
export MOMENTUM_SPA_DIR="$ROOT/apps/web/dist"
cd "$ROOT/apps/api"
uv run python "$ROOT/tools/e2e/reset_db.py"
uv run momentum migrate
uv run momentum seed --showcase
uv run momentum serve --port "${UX_PORT:-8140}"
