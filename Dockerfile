# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.11-slim-bookworm
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    SCANNER_HOST=0.0.0.0 \
    SCANNER_PORT=8091

COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    uv sync --locked --no-default-groups --no-install-project --no-cache --no-build

COPY scanner/ ./scanner/
RUN mkdir -p .runtime/uploads && chown -R 10001:10001 .runtime

USER 10001:10001
EXPOSE 8091
HEALTHCHECK --interval=5s --timeout=3s --retries=6 CMD ["/app/.venv/bin/python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['SCANNER_PORT'] + '/health', timeout=2).close()"]
CMD ["/app/.venv/bin/python", "-m", "scanner"]
