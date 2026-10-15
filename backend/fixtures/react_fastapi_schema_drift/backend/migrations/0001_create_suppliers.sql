-- Migration 0001: suppliers
CREATE TABLE suppliers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    contact_email   VARCHAR(255)
);

CREATE INDEX idx_suppliers_name ON suppliers (name);
