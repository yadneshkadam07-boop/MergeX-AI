#!/bin/sh
set -e

echo "==> Running Alembic migrations..."
python -m alembic upgrade head

echo "==> Starting MergeX Uvicorn server on port ${PORT:-8000}..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
