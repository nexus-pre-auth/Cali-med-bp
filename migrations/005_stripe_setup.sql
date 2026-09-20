-- migrations/005_stripe_setup.sql
--
-- Add Stripe price IDs to products table and a checkout_sessions audit log.
-- Run after 004_supabase_platform.sql.

-- ---------------------------------------------------------------------------
-- Add stripe_price_* columns to products
-- ---------------------------------------------------------------------------

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS stripe_price_onetime     TEXT,   -- price_... one-time review
    ADD COLUMN IF NOT EXISTS stripe_price_monthly     TEXT;   -- price_... monthly subscription

-- Seed price placeholders (replace with real price IDs from Stripe dashboard)
UPDATE products SET
    stripe_price_onetime = 'price_REPLACE_REVIEW_299',
    stripe_price_monthly = 'price_REPLACE_MONTHLY_499'
WHERE slug = 'medblueprints';

-- ---------------------------------------------------------------------------
-- checkout_sessions  (audit log)
-- ---------------------------------------------------------------------------
-- Records every Stripe Checkout session created, for reconciliation.

CREATE TABLE IF NOT EXISTS checkout_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID REFERENCES firms(id) ON DELETE SET NULL,
    stripe_session_id   TEXT UNIQUE NOT NULL,
    mode                TEXT NOT NULL CHECK (mode IN ('payment', 'subscription')),
    amount_total        INTEGER,          -- cents
    currency            TEXT DEFAULT 'usd',
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','complete','expired')),
    stripe_customer_id  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_cs_firm    ON checkout_sessions (firm_id);
CREATE INDEX IF NOT EXISTS idx_cs_status  ON checkout_sessions (status);
CREATE INDEX IF NOT EXISTS idx_cs_stripe  ON checkout_sessions (stripe_session_id);

-- RLS: firms can view their own checkout history
ALTER TABLE checkout_sessions ENABLE ROW LEVEL SECURITY;

CREATE POLICY checkout_own_data ON checkout_sessions
    USING (firm_id IN (SELECT id FROM firms WHERE user_id = auth.uid()));

-- ---------------------------------------------------------------------------
-- Add stripe_invoice_id to reviews (for receipt linking)
-- ---------------------------------------------------------------------------

ALTER TABLE reviews
    ADD COLUMN IF NOT EXISTS stripe_session_id TEXT;
