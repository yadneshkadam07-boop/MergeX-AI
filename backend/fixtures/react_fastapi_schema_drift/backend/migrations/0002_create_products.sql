-- Migration 0002: products
--
-- Drifted from app/models.py in four ways. Each is deliberate:
--   * warehouse_code is absent entirely            (MX-DB-001)
--   * unit_price is INTEGER, the model says NUMERIC (MX-DB-002)
--   * supplier_id has no REFERENCES and no index    (MX-DB-004)
--   * last_counted_at, used by queries.py, is absent (MX-DB-003)
CREATE TABLE products (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(64) NOT NULL UNIQUE,
    name            VARCHAR(200) NOT NULL,
    unit_price      INTEGER NOT NULL,
    reorder_level   INTEGER NOT NULL DEFAULT 0,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    supplier_id     INTEGER
);
