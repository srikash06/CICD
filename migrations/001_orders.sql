-- Baseline, additive, repeatable initialization. No destructive migration on startup.
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_paise INTEGER NOT NULL CHECK (unit_price_paise > 0),
    status TEXT NOT NULL CHECK (status IN ('pending', 'cancelled')),
    idempotency_key TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS orders_created ON orders(created_at, id);
