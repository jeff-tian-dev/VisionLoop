-- Migration 0005: Subscription licenses — expiry + Stripe subscription id

ALTER TABLE public.licenses
  ADD COLUMN IF NOT EXISTS expires_at timestamptz,
  ADD COLUMN IF NOT EXISTS stripe_subscription_id text;

-- One subscription maps to one license row (renewals PATCH this row).
CREATE UNIQUE INDEX IF NOT EXISTS idx_licenses_stripe_subscription_id
  ON public.licenses (stripe_subscription_id)
  WHERE stripe_subscription_id IS NOT NULL;

-- ─── validate_license: reject expired subscriptions (after revoked check) ───
CREATE OR REPLACE FUNCTION public.validate_license(
  p_license_key text,
  p_machine_fingerprint text,
  p_bot_version text,
  p_ip text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  lic public.licenses%ROWTYPE;
  lm public.license_machines%ROWTYPE;
  v_ip inet;
BEGIN
  IF p_ip IS NOT NULL AND btrim(p_ip) <> '' THEN
    BEGIN
      v_ip := p_ip::inet;
    EXCEPTION WHEN invalid_text_representation THEN
      v_ip := NULL;
    END;
  ELSE
    v_ip := NULL;
  END IF;

  SELECT * INTO lic FROM public.licenses WHERE license_key = p_license_key;
  IF NOT FOUND THEN
    INSERT INTO public.validation_logs (
      license_id, license_key_attempted, machine_fingerprint, ip, result, reason, bot_version
    ) VALUES (
      NULL, p_license_key, p_machine_fingerprint, v_ip, 'invalid', 'not_found', p_bot_version
    );
    RETURN jsonb_build_object('valid', false, 'reason', 'not_found');
  END IF;

  IF lic.status = 'revoked' THEN
    INSERT INTO public.validation_logs (
      license_id, license_key_attempted, machine_fingerprint, ip, result, reason, bot_version
    ) VALUES (
      lic.id, p_license_key, p_machine_fingerprint, v_ip, 'invalid', 'revoked', p_bot_version
    );
    RETURN jsonb_build_object('valid', false, 'reason', 'revoked');
  END IF;

  IF lic.expires_at IS NOT NULL AND lic.expires_at <= now() THEN
    INSERT INTO public.validation_logs (
      license_id, license_key_attempted, machine_fingerprint, ip, result, reason, bot_version
    ) VALUES (
      lic.id, p_license_key, p_machine_fingerprint, v_ip, 'invalid', 'expired', p_bot_version
    );
    RETURN jsonb_build_object('valid', false, 'reason', 'expired');
  END IF;

  SELECT * INTO lm FROM public.license_machines WHERE license_id = lic.id;
  IF NOT FOUND THEN
    INSERT INTO public.license_machines (license_id, machine_fingerprint, last_ip, bot_version)
    VALUES (lic.id, p_machine_fingerprint, v_ip, p_bot_version);
    INSERT INTO public.validation_logs (
      license_id, license_key_attempted, machine_fingerprint, ip, result, reason, bot_version
    ) VALUES (
      lic.id, p_license_key, p_machine_fingerprint, v_ip, 'valid', 'bound', p_bot_version
    );
    RETURN jsonb_build_object('valid', true);
  END IF;

  IF lm.machine_fingerprint IS DISTINCT FROM p_machine_fingerprint THEN
    INSERT INTO public.validation_logs (
      license_id, license_key_attempted, machine_fingerprint, ip, result, reason, bot_version
    ) VALUES (
      lic.id, p_license_key, p_machine_fingerprint, v_ip, 'invalid', 'machine_mismatch', p_bot_version
    );
    RETURN jsonb_build_object('valid', false, 'reason', 'machine_mismatch');
  END IF;

  UPDATE public.license_machines
  SET last_seen_at = now(),
      last_ip = COALESCE(v_ip, last_ip),
      bot_version = p_bot_version
  WHERE license_id = lic.id;

  INSERT INTO public.validation_logs (
    license_id, license_key_attempted, machine_fingerprint, ip, result, reason, bot_version
  ) VALUES (
    lic.id, p_license_key, p_machine_fingerprint, v_ip, 'valid', 'ok', p_bot_version
  );
  RETURN jsonb_build_object('valid', true);
END;
$$;

REVOKE ALL ON FUNCTION public.validate_license(text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.validate_license(text, text, text, text) TO anon;
GRANT EXECUTE ON FUNCTION public.validate_license(text, text, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.validate_license(text, text, text, text) TO service_role;
