"""Shared FastAPI dependencies.

Phase 1 adds the database session dependency here. Settings are injected via
``Depends(get_settings)`` directly from ``app.core.config``.
"""
