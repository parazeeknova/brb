# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps ./apps
RUN uv run --frozen --no-dev playwright install chromium \
  && uv run --frozen --no-dev playwright install-deps chromium

FROM python:3.14-slim AS runner
WORKDIR /app
ENV PYTHONPATH=/app:/app/apps/ingest \
  PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  PATH="/app/.venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl libstdc++6 \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /ms-playwright /ms-playwright
COPY --from=builder /app/pyproject.toml /app/uv.lock ./
COPY apps ./apps

RUN python -m playwright install-deps chromium

RUN useradd -m -u 1001 brbsvc \
  && chown -R brbsvc:brbsvc /app /ms-playwright /home/brbsvc
USER brbsvc

CMD ["python", "-m", "src.pipeline.run"]
