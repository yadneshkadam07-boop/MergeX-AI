#!/bin/sh
set -e

export PATH="/opt/venv/bin:$PATH"
cd /app

echo "==> Running Alembic migrations..."
if /opt/venv/bin/python -m alembic -c /app/alembic.ini upgrade head; then
    echo "==> Alembic migrations applied successfully."
else
    echo "==> WARNING: Alembic upgrade failed or database connection delayed. Proceeding with application startup..."
fi

echo "==> Starting MergeX Uvicorn server on port ${PORT:-8000}..."
exec /opt/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
