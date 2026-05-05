-- Migration 0004: Trial wallet — tracks free runtime per machine fingerprint.

-- ─── trial_wallets ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.trial_wallets (
    machine_fingerprint text        PRIMARY KEY,
    used_seconds        integer     NOT NULL DEFAULT 0 CHECK (used_seconds >= 0),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    last_ip             inet
);

ALTER TABLE public.trial_wallets DISABLE ROW LEVEL SECURITY;

-- ─── RPC: trial_heartbeat ─────────────────────────────────────────────────────
-- p_elapsed_seconds = 0  →  read-only; returns remaining without mutating row.
-- p_elapsed_seconds > 0  →  add capped seconds (max 120 per call), return new remaining.
-- Budget is 1800 seconds (30 minutes) per machine fingerprint.

CREATE OR REPLACE FUNCTION public.trial_heartbeat(
  p_machine_fingerprint text,
  p_elapsed_seconds     int      DEFAULT 0,
  p_ip                  text     DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  BUDGET constant int := 1800;
  MAX_INCREMENT constant int := 120;
  v_ip     inet;
  v_fp     text;
  v_used   int;
  v_incr   int;
  v_new    int;
BEGIN
  v_fp := lower(trim(COALESCE(p_machine_fingerprint, '')));

  IF NOT (v_fp ~ '^[0-9a-f]{32}$') THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'invalid_fingerprint', 'remaining_seconds', 0);
  END IF;

  IF p_ip IS NOT NULL AND btrim(p_ip) <> '' THEN
    BEGIN
      v_ip := p_ip::inet;
    EXCEPTION WHEN invalid_text_representation THEN
      v_ip := NULL;
    END;
  ELSE
    v_ip := NULL;
  END IF;

  v_incr := least(greatest(COALESCE(p_elapsed_seconds, 0), 0), MAX_INCREMENT);

  -- Upsert row; if p_elapsed_seconds = 0 we still create the row to record first-seen.
  INSERT INTO public.trial_wallets (machine_fingerprint, used_seconds, last_ip)
  VALUES (v_fp, 0, v_ip)
  ON CONFLICT (machine_fingerprint) DO UPDATE
    SET last_ip    = COALESCE(EXCLUDED.last_ip, trial_wallets.last_ip),
        updated_at = now();

  -- Read current used_seconds (locked to this row for this transaction).
  SELECT used_seconds INTO v_used
  FROM public.trial_wallets
  WHERE machine_fingerprint = v_fp
  FOR UPDATE;

  IF v_incr > 0 AND v_used < BUDGET THEN
    v_new := least(BUDGET, v_used + v_incr);
    UPDATE public.trial_wallets
    SET used_seconds = v_new,
        updated_at   = now()
    WHERE machine_fingerprint = v_fp;
  ELSE
    v_new := v_used;
  END IF;

  RETURN jsonb_build_object(
    'ok',                true,
    'remaining_seconds', BUDGET - v_new,
    'used_seconds',      v_new
  );
END;
$$;

REVOKE ALL ON FUNCTION public.trial_heartbeat(text, int, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.trial_heartbeat(text, int, text) TO anon;
GRANT EXECUTE ON FUNCTION public.trial_heartbeat(text, int, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.trial_heartbeat(text, int, text) TO service_role;
