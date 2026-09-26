# Runbook: Local Development

## Prerequisites
- Python 3.12 + **uv** · Node 22 LTS + **pnpm** · make
- PostgreSQL 16 with **pgvector**: either Docker (`make db-up`) or a native install (below)
- Optional: a LiteLLM endpoint you can reach (else `MOMENTUM_LLM_MODE=mock`)

## First run
```bash
cp .env.example .env
make install    # uv sync + pnpm install
make db-up      # Docker Postgres+pgvector on :5432 (skip if native)
make migrate    # creates everything in the `momentum` schema
make seed       # synthetic "Acme Demo" workspace (12 users)
make dev        # api :8000 (reload) + web :5173 (proxies /api)
```
Open http://localhost:5173 → dev login → pick a user. The component gallery is at http://localhost:5173/dev/ui.

**Single-process run (like production):** `make build && cd apps/api && uv run momentum serve` → http://localhost:8000.

## Native Postgres (no Docker)
```bash
# Ubuntu/Debian: sudo apt install postgresql-16 postgresql-16-pgvector
# macOS (Homebrew): brew install postgresql@16 pgvector
createuser -s momentum && psql -c "alter user momentum password 'momentum'"
createdb -O momentum momentum && createdb -O momentum momentum_test
for db in momentum momentum_test; do psql -d $db -c "create extension if not exists vector; create extension if not exists pg_trgm; create extension if not exists citext;"; done
```

## Tests
`make check` runs everything. Backend tests use `MOMENTUM_TEST_DATABASE_URL` (default `postgresql+psycopg://momentum:momentum@localhost:5432/momentum_test`) and migrate a throwaway schema `momentum_test`.

## Auth modes locally
- `MOMENTUM_AUTH_MODE=dev`: simple picker.
- `MOMENTUM_AUTH_MODE=easyauth-sim`: same picker, but every request is converted into realistic `X-MS-CLIENT-PRINCIPAL` claims and parsed by the real Easy Auth provider. Use this regularly so the production path stays exercised.

## AI locally

- **Evals (S3.5.1):** `make evals` (mock: the cases with handwritten fixtures, ~5 s) or `EVALS_LIVE=1 make evals` (every case against your gateway, plus LLM-as-judge; a few minutes and some tokens). Each run drops and rebuilds a throwaway `<your db>_evals` database (migrate → seed → the eval workspace in `ai/evals/fixtures/workspaces/launch_v1.yaml` → search index), so your own data is never touched; the role needs `CREATEDB`. Output: a pass/fail table per feature, every failed case with the failing checks, and a JSON report in `reports/evals/`. `--feature chat` / `--case pricing` narrow a run (`cd apps/api && uv run momentum evals --live --feature chat`). `uv run momentum evals --all` runs every case in mock mode (a plumbing check: expect many content failures, but no errors).
- Mock: `MOMENTUM_LLM_MODE=mock` (default). Deterministic fixtures from `momentum/ai/evals/fixtures/mock_responses/` (format in `momentum/ai/mock.py`'s docstring); anything unmatched answers with a visible "(mock)" text.
- Real: set `MOMENTUM_LLM_MODE=gateway`, `MOMENTUM_LLM_BASE_URL`, `MOMENTUM_LLM_API_KEY`, and the alias names; run `uv run momentum llm-check`. It prints a pass/fail table (basic chat per alias, tool calling, the full tool catalog's schemas in one request with the arguments validated by the registry's own model, streaming, streaming with tool calls, both embedding input types, latency) and exits 1 if anything fails.
- Portkey instead of LiteLLM (example; use your own provider-config slug and model ids):
  ```bash
  MOMENTUM_LLM_MODE=gateway
  MOMENTUM_LLM_BASE_URL=https://api.portkey.ai/v1
  MOMENTUM_LLM_API_KEY=<your Portkey key>
  MOMENTUM_LLM_API_KEY_HEADER=x-portkey-api-key
  MOMENTUM_LLM_MODEL_DEFAULT=@<your-provider-config>/<bedrock claude sonnet model id>
  MOMENTUM_LLM_MODEL_FAST=@<your-provider-config>/<a cheaper model id>
  MOMENTUM_LLM_MODEL_SMART=@<your-provider-config>/<the strongest model id>
  MOMENTUM_LLM_EMBED_MODEL=@<your-provider-config>/cohere.embed-english-v3
  ```
- Search index (S3.1.4): the worker keeps embeddings current (`index_embeddings`, every minute). After loading data by hand, or switching `MOMENTUM_LLM_EMBED_MODEL`, run `uv run momentum reindex` (all) or `--entity task --since 2026-09-01`; unchanged content is skipped.
- Record: `MOMENTUM_LLM_MODE=record` calls the real gateway and saves each chat response as a mock fixture (keyed by `request_key`, system prompt excluded). Review recorded files before committing: synthetic data only.
- Local LiteLLM: `docker compose --profile ai up litellm` with `infra/litellm/config.yaml` (copy from the example, add your own provider keys; never commit it).

## Useful commands
See `CLAUDE.md` §4.

## Troubleshooting
| Symptom | Fix |
|---|---|
| `extension "vector" does not exist` | Use the `pgvector/pgvector:pg16` image; re-run the init script |
| Tables created in `public` | Check `MOMENTUM_DB_SCHEMA` and that migrations use the configured schema; run the portability test |
| 403 on every POST | Missing `X-Requested-With: momentum` header (use the API client) |
| WS keeps reconnecting | The API isn't running, or the Vite proxy `ws: true` is missing |
| Stale frontend types | `make types` |
| Backend tests can't connect | Start Postgres (`make db-up`) and create `momentum_test` with the extensions (see above) |
| `pkill`/port 8000 busy | Another `momentum serve` is running; stop it or use `--port` |
