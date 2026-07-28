-- Migration 0010: Client crash reports (fatal bot errors from desktop app).

CREATE TABLE IF NOT EXISTS public.client_error_logs (
    id                   bigserial   PRIMARY KEY,
    machine_fingerprint  text        NOT NULL,
    ip                   inet,
    license_mode         text        NOT NULL CHECK (license_mode IN ('licensed', 'trial')),
    error_type           text,
    error_message        text        NOT NULL,
    bot_version          text,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_client_error_logs_fingerprint_created
    ON public.client_error_logs (machine_fingerprint, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_client_error_logs_created_at
    ON public.client_error_logs (created_at);

ALTER TABLE public.client_error_logs DISABLE ROW LEVEL SECURITY;

-- One accepted report per machine fingerprint every 5 minutes (server-side backstop).
CREATE OR REPLACE FUNCTION public.report_client_error(
  p_machine_fingerprint text,
  p_ip                  text,
  p_license_mode        text,
  p_error_type          text,
  p_error_message       text,
  p_bot_version         text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_fp text;
  v_ip inet;
  v_mode text;
  v_type text;
  v_msg text;
  v_ver text;
BEGIN
  v_fp := lower(trim(COALESCE(p_machine_fingerprint, '')));

  IF NOT (v_fp ~ '^[0-9a-f]{32}$') THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'invalid_fingerprint');
  END IF;

  v_mode := lower(trim(COALESCE(p_license_mode, '')));
  IF v_mode NOT IN ('licensed', 'trial') THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'invalid_license_mode');
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

  v_type := left(trim(COALESCE(p_error_type, '')), 200);
  v_msg := left(trim(COALESCE(p_error_message, '')), 2000);
  v_ver := left(trim(COALESCE(p_bot_version, '')), 64);

  IF v_msg = '' THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'empty_message');
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.client_error_logs
    WHERE machine_fingerprint = v_fp
      AND created_at > now() - interval '5 minutes'
    LIMIT 1
  ) THEN
    RETURN jsonb_build_object('ok', false, 'reason', 'rate_limited');
  END IF;

  INSERT INTO public.client_error_logs (
    machine_fingerprint, ip, license_mode, error_type, error_message, bot_version
  ) VALUES (
    v_fp, v_ip, v_mode, NULLIF(v_type, ''), v_msg, NULLIF(v_ver, '')
  );

  RETURN jsonb_build_object('ok', true);
END;
$$;

REVOKE ALL ON FUNCTION public.report_client_error(text, text, text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.report_client_error(text, text, text, text, text, text) TO anon;
GRANT EXECUTE ON FUNCTION public.report_client_error(text, text, text, text, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.report_client_error(text, text, text, text, text, text) TO service_role;
