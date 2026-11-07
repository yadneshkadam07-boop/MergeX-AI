#!/bin/sh
set -e

export PATH="/opt/venv/bin:$PATH"

echo "==> Running Alembic migrations..."
/opt/venv/bin/python -m alembic upgrade head

echo "==> Starting MergeX Uvicorn server on port ${PORT:-8000}..."
exec /opt/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
