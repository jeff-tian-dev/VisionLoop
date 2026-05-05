-- Idempotency for Stripe Checkout webhooks (especially month-extend PATCH without new license row).

CREATE TABLE IF NOT EXISTS public.stripe_checkout_fulfillments (
    stripe_checkout_session_id text PRIMARY KEY,
    variant                      text NOT NULL
        CHECK (variant IN ('lifetime_new', 'month_bundle_new', 'month_extend')),
    created_at                   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.stripe_checkout_fulfillments DISABLE ROW LEVEL SECURITY;

CREATE INDEX IF NOT EXISTS idx_stripe_checkout_fulfillments_created_at
    ON public.stripe_checkout_fulfillments (created_at);

GRANT SELECT, INSERT ON public.stripe_checkout_fulfillments TO anon;
GRANT SELECT, INSERT ON public.stripe_checkout_fulfillments TO authenticated;
GRANT ALL ON public.stripe_checkout_fulfillments TO service_role;
