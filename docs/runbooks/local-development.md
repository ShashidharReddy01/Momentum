# Runbook: Local Development

## Prerequisites
- Docker (Desktop or Engine) · Python 3.12 + **uv** · Node 22 LTS + **pnpm** · make
- Optional: a LiteLLM endpoint you can reach (else `MOMENTUM_LLM_MODE=mock`)

## First run
```bash
cp .env.example .env
make dev        # postgres (5432) + api (8000, reload) + web (5173, proxy)
make migrate    # (auto in local if MOMENTUM_DB_AUTO_MIGRATE=true)
make seed       # synthetic "Acme Demo" workspace
```
Open http://localhost:5173 → dev login → pick a user.

## Auth modes locally
- `MOMENTUM_AUTH_MODE=dev`: simple picker.
- `MOMENTUM_AUTH_MODE=easyauth-sim`: same picker, but requests flow through the real Easy Auth header parser. Use this regularly.

## AI locally
- Mock: `MOMENTUM_LLM_MODE=mock` (default). Deterministic fixtures.
- Real: set `MOMENTUM_LLM_MODE=gateway`, `MOMENTUM_LLM_BASE_URL`, `MOMENTUM_LLM_API_KEY`, and the alias names; run `uv run momentum llm-check`.
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
| Testcontainers fail | Docker not running, or on macOS set `TESTCONTAINERS_RYUK_DISABLED=true` if needed |
