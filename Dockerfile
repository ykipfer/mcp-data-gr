FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY main.py .env README.md ./
RUN uv sync --frozen --no-dev

# The container is meant to serve HTTP; override with -e MCP_TRANSPORT=stdio if needed.
ENV MCP_TRANSPORT=streamable-http

EXPOSE 8000

ENTRYPOINT ["uv", "run", "main.py"]
