#!/usr/bin/env bash
# Starts a throwaway Momentum for the E2E journeys: fresh database (name must end in _e2e),
# migrations, synthetic seed, dev login, built SPA. Used by apps/web/playwright.config.ts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export MOMENTUM_DATABASE_URL="${MOMENTUM_E2E_DATABASE_URL:-postgresql+psycopg://momentum:momentum@localhost:5432/momentum_e2e}"
export MOMENTUM_AUTH_MODE=dev
export MOMENTUM_ENV=local
export MOMENTUM_SPA_DIR="$ROOT/apps/web/dist"
cd "$ROOT/apps/api"
uv run python "$ROOT/tools/e2e/reset_db.py"
uv run momentum migrate
uv run momentum seed
exec uv run momentum serve --port "${E2E_PORT:-8123}"
