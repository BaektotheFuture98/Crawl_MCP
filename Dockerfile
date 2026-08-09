FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN groupadd --system crawling && useradd --system --gid crawling --create-home crawling

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
RUN uv sync --frozen --no-dev --no-editable

COPY config ./config
COPY .env.example ./
RUN mkdir -p data/auth data/results data/failures data/screenshots \
    && chown -R crawling:crawling /app

USER crawling

ENTRYPOINT ["/app/.venv/bin/python", "-m", "crawling_mcp"]
