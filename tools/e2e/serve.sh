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

# J6's recorded-fixture Asana API (see asana_fixture_server.py's own docstring). Runs alongside
# the app for the lifetime of this script; killed on exit since it's a throwaway per-run process.
ASANA_FIXTURE_PORT="${MOMENTUM_ASANA_FIXTURE_PORT:-8129}"
uv run uvicorn --app-dir "$ROOT/tools/e2e" asana_fixture_server:app \
  --port "$ASANA_FIXTURE_PORT" --log-level warning &
ASANA_FIXTURE_PID=$!
trap 'kill "$ASANA_FIXTURE_PID" 2>/dev/null || true' EXIT
export MOMENTUM_ASANA_BASE_URL="http://localhost:${ASANA_FIXTURE_PORT}"

uv run momentum serve --port "${E2E_PORT:-8123}"
