-- Migration 0001: License key validation tables
-- RLS is intentionally disabled on all three tables.
-- Access is via the postgres superuser service-role connection only (FastAPI + admin CLI).

-- ─── licenses ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS licenses (
    id                          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    license_key                 text        NOT NULL UNIQUE,
    status                      text        NOT NULL DEFAULT 'active'
                                            CHECK (status IN ('active', 'revoked')),
    email                       text,
    stripe_customer_id          text,
    stripe_payment_intent_id    text,
    stripe_checkout_session_id  text        UNIQUE,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    revoked_at                  timestamptz,
    notes                       text
);

CREATE INDEX IF NOT EXISTS idx_licenses_email
    ON licenses (email);

CREATE INDEX IF NOT EXISTS idx_licenses_stripe_session
    ON licenses (stripe_checkout_session_id);

ALTER TABLE licenses DISABLE ROW LEVEL SECURITY;

-- ─── license_machines ────────────────────────────────────────────────────────
-- One row per license; inserted on the first successful validation (hardware bind).
CREATE TABLE IF NOT EXISTS license_machines (
    license_id          uuid        PRIMARY KEY REFERENCES licenses(id) ON DELETE CASCADE,
    machine_fingerprint text        NOT NULL,
    bound_at            timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now(),
    last_ip             inet,
    bot_version         text
);

ALTER TABLE license_machines DISABLE ROW LEVEL SECURITY;

-- ─── validation_logs ─────────────────────────────────────────────────────────
-- High-write audit log; bigserial pk avoids UUID gen overhead per row.
CREATE TABLE IF NOT EXISTS validation_logs (
    id                   bigserial   PRIMARY KEY,
    license_id           uuid        REFERENCES licenses(id) ON DELETE SET NULL,
    license_key_attempted text,
    machine_fingerprint  text,
    ip                   inet,
    result               text        NOT NULL CHECK (result IN ('valid', 'invalid')),
    reason               text,       -- not_found | revoked | machine_mismatch | bound | ok
    bot_version          text,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_validation_logs_license_id
    ON validation_logs (license_id);

CREATE INDEX IF NOT EXISTS idx_validation_logs_created_at
    ON validation_logs (created_at);

ALTER TABLE validation_logs DISABLE ROW LEVEL SECURITY;
