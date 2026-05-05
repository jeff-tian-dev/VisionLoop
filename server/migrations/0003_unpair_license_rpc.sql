-- RPC for POST /rpc/unpair_license — removes hardware bind for THIS machine only.

CREATE OR REPLACE FUNCTION public.unpair_license(
  p_license_key text,
  p_machine_fingerprint text,
  p_ip text,
  p_bot_version text DEFAULT 'unknown'
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
  v_key text;
BEGIN
  v_key := upper(trim(COALESCE(p_license_key, '')));

  IF p_ip IS NOT NULL AND btrim(p_ip) <> '' THEN
    BEGIN
      v_ip := p_ip::inet;
    EXCEPTION WHEN invalid_text_representation THEN
      v_ip := NULL;
    END;
  ELSE
    v_ip := NULL;
  END IF;

  SELECT * INTO lic FROM public.licenses WHERE license_key = v_key;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'not_found');
  END IF;

  IF lic.status = 'revoked' THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'revoked');
  END IF;

  SELECT * INTO lm FROM public.license_machines WHERE license_id = lic.id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', true, 'reason', 'not_bound');
  END IF;

  IF lm.machine_fingerprint IS DISTINCT FROM p_machine_fingerprint THEN
    INSERT INTO public.validation_logs (
      license_id, license_key_attempted, machine_fingerprint, ip, result, reason, bot_version
    ) VALUES (
      lic.id, v_key, p_machine_fingerprint, v_ip, 'invalid', 'unpair_mismatch', p_bot_version
    );
    RETURN jsonb_build_object('ok', false, 'reason', 'machine_mismatch');
  END IF;

  DELETE FROM public.license_machines WHERE license_id = lic.id;

  INSERT INTO public.validation_logs (
    license_id, license_key_attempted, machine_fingerprint, ip, result, reason, bot_version
  ) VALUES (
    lic.id, v_key, p_machine_fingerprint, v_ip, 'valid', 'unpaired', p_bot_version
  );

  RETURN jsonb_build_object('ok', true);
END;
$$;

REVOKE ALL ON FUNCTION public.unpair_license(text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.unpair_license(text, text, text, text) TO anon;
GRANT EXECUTE ON FUNCTION public.unpair_license(text, text, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.unpair_license(text, text, text, text) TO service_role;
