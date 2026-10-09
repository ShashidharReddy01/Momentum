# Momentum production image: one container serving API + SPA + embedded worker (ADR-0001).
# ---- Stage 1: build the SPA ----
FROM node:22-slim AS web
WORKDIR /web
RUN corepack enable
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web/ ./
RUN pnpm build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    MOMENTUM_ENV=production MOMENTUM_LOG_FORMAT=json PORT=8000
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
# Phase 7.6 (ADR-0014): Tesseract for Bernie's OCR of scanned invoices (English, German, French,
# Spanish, Italian, Dutch; add language packs here and to MOMENTUM_OCR_LANGUAGES as needed).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
       tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-spa tesseract-ocr-ita tesseract-ocr-nld \
    && rm -rf /var/lib/apt/lists/*
ENV MOMENTUM_OCR_LANGUAGES=eng+deu+fra+spa+ita+nld
WORKDIR /app
# Phase 7.6 (ADR-0012): packs are a path dependency ("../../packs/<key>" from apps/api/pyproject.toml,
# i.e. /packs/<key> from WORKDIR /app here), so they must exist on disk before the first `uv sync`.
COPY packs/ /packs/
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/momentum ./momentum
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist ./momentum/web/static
RUN useradd --create-home --uid 10001 momentum
USER momentum
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz')"
CMD ["/app/.venv/bin/momentum", "serve"]
