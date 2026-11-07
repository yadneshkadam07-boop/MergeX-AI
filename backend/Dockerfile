# syntax=docker/dockerfile:1
# MergeX AI backend. Two targets:
#   dev  -> editable install + dev dependencies, used by docker-compose
#   prod -> lean runtime image, used by Render
ARG PYTHON_VERSION=3.11-slim

# -----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

# `git` is required: repository import uses a shallow clone into the sandbox.
# `curl` backs the container healthcheck.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv \
    && pip install --upgrade pip setuptools wheel

WORKDIR /app

# -----------------------------------------------------------------------------
# Dependency layer. Only the manifest is copied, with a stub package so the
# editable install resolves, so dependency layers cache across code edits.
FROM base AS deps
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py

# -----------------------------------------------------------------------------
FROM deps AS dev
RUN pip install -e ".[dev]"
RUN mkdir -p /workspace
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# -----------------------------------------------------------------------------
FROM deps AS builder
COPY app ./app
RUN pip install "."

# -----------------------------------------------------------------------------
FROM base AS prod
ENV APP_ENV=production \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    WORKSPACE_DIR=/workspace
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Symlink all venv binaries to /usr/local/bin so any bare command (alembic, uvicorn, python) resolves globally
RUN ln -sf /opt/venv/bin/* /usr/local/bin/

COPY start.sh /start.sh
RUN chmod +x /start.sh

# Never run the API as root: it handles untrusted repository content.
RUN useradd --create-home --uid 10001 mergex \
    && mkdir -p /workspace \
    && chown -R mergex:mergex /app /workspace /opt/venv /start.sh
USER mergex

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1
# Render injects $PORT; default to 8000 for plain `docker run`.
CMD ["/start.sh"]
