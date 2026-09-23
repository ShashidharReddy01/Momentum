# Momentum

**Keep work moving.** Momentum is an AI-native work management app with an Asana-style layout: teams, projects, sections, tasks, and list/board/timeline views. It adds **Mo**, an assistant built into every screen, and **agents** that work as teammates.

- Backend: Python 3.12 · FastAPI · SQLAlchemy 2 (async) · PostgreSQL 16 + pgvector · Procrastinate (Postgres job queue)
- Frontend: React 19 · TypeScript · Vite · React Router 7 · TanStack Query · Tailwind v4 + Radix/shadcn primitives · Momentum design system
- AI: OpenAI-compatible gateway (LiteLLM) → Claude models on AWS Bedrock; Cohere Embed v3 for semantic search
- Target runtime (final phase): Azure App Service + Easy Auth (Entra ID) + Azure Database for PostgreSQL + Blob Storage
- Designed to be **lifted and shifted** to another environment and **embedded** into another project

## Quickstart (local)

```bash
cp .env.example .env          # defaults work for local dev (AUTH_MODE=dev, LLM_MODE=mock)
make install                  # backend (uv) + frontend (pnpm) deps
make db-up                    # Postgres 16 + pgvector in Docker (or native: see the runbook)
make migrate && make seed     # schema + synthetic "Acme Demo" workspace
make dev                      # api http://localhost:8000 + web http://localhost:5173
make check                    # the quality gate
make e2e                      # E2E journeys (Playwright, throwaway *_e2e database)
```

**Windows (PowerShell, no `make` needed):** install [uv](https://docs.astral.sh/uv/), Node.js 20+ with `npm install -g pnpm`, and Docker Desktop (running). Then:

```powershell
powershell -ExecutionPolicy Bypass -File tools\dev.ps1 setup   # install, Postgres in Docker, migrate, seed
powershell -ExecutionPolicy Bypass -File tools\dev.ps1 dev     # API :8000 (new window) + web http://localhost:5173
```

`tools\dev.ps1` also has `seed-perf` (adds the 2,000-task project), `db-down` and `check`.

Open http://localhost:5173 and pick a seeded user on the dev login screen.

## Documentation

Start at [`docs/README.md`](docs/README.md). AI contributors start at [`CLAUDE.md`](CLAUDE.md). Plugging Momentum into another project: [`INTEGRATION_GUIDE.md`](INTEGRATION_GUIDE.md).
