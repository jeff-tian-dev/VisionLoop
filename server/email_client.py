from __future__ import annotations

import logging

import httpx

from .settings import get_settings

logger = logging.getLogger(__name__)

_RESEND_SEND_URL = "https://api.resend.com/emails"


def _access_paragraph(*, fulfillment_type: str, expires_at_iso: str | None) -> str:
    if fulfillment_type == "lifetime":
        return (
            "<p>This is a <strong>lifetime</strong> license. It does not expire while the product stays supported.</p>"
        )
    exp_line = ""
    if expires_at_iso:
        exp_line = f"<p><strong>Access until:</strong> {expires_at_iso} (UTC)</p>"
    if fulfillment_type == "timed_new":
        return (
            exp_line
            + "<p>Paid access lasts until the date above. Renew with another checkout before expiry to "
            "avoid interruption.</p>"
        )
    if fulfillment_type == "extend":
        return (
            "<p><strong>Your access has been extended.</strong></p>"
            + exp_line
            + "<p>Your existing key below remains valid until that date.</p>"
        )
    if fulfillment_type == "subscription":
        return (
            exp_line
            + "<p>This key is billed as a <strong>Stripe subscription</strong>. Access advances with each paid "
            "billing period until the subscription is cancelled.</p>"
        )
    return ""


def _subject_for(*, fulfillment_type: str, expires_at_iso: str | None) -> str:
    if fulfillment_type == "extend":
        return "Clash Auto Loot — access extended"
    if fulfillment_type in ("timed_new", "subscription") and expires_at_iso:
        return "Your Clash Auto Loot license — access expiry"
    return "Your Clash Auto Loot license key"


def _build_html(
    license_key: str,
    support_email: str,
    *,
    fulfillment_type: str,
    expires_at_iso: str | None,
) -> str:
    extra = _access_paragraph(
        fulfillment_type=fulfillment_type, expires_at_iso=expires_at_iso
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Your Clash Auto Loot license</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:8px;padding:32px;max-width:560px;">
          <tr>
            <td>
              <h1 style="color:#c97a00;font-size:22px;margin:0 0 8px 0;">Thank you for your purchase!</h1>
              <p style="color:#1a1a1a;font-size:14px;line-height:1.6;margin:0 0 8px 0;">
                Your <strong>Clash Auto Loot</strong> license key:
              </p>
              <div style="background-color:#f0f0f0;border:1px solid #cccccc;border-radius:6px;
                          padding:16px;text-align:center;font-size:20px;font-family:monospace;
                          letter-spacing:2px;color:#111111;margin:24px 0;">
                {license_key}
              </div>
              <div style="color:#1a1a1a;font-size:14px;line-height:1.6;">
                {extra}
              </div>
              <p style="color:#1a1a1a;font-size:14px;line-height:1.6;margin:16px 0 4px 0;">
                <strong>How to activate:</strong>
              </p>
              <ol style="color:#1a1a1a;font-size:14px;line-height:1.8;margin:0 0 16px 0;padding-left:20px;">
                <li>Open <strong>Clash Auto Loot</strong>.</li>
                <li>Go to the <em>License</em> tab and paste your key.</li>
                <li>Click <strong>Check Key</strong> — the indicator turns green when valid.</li>
              </ol>
              <p style="color:#1a1a1a;font-size:14px;line-height:1.6;margin:0 0 24px 0;">
                The key is bound to the first machine it is activated on. If you ever need to
                transfer it to a new machine, contact support.
              </p>
              <div style="font-size:12px;color:#666666;border-top:1px solid #e0e0e0;padding-top:16px;">
                Need help? Email us at <a href="mailto:{support_email}" style="color:#c97a00;">{support_email}</a>.<br>
                Please keep this key private — do not share it with others.
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


async def send_license_email(
    to_email: str,
    license_key: str,
    *,
    fulfillment_type: str = "lifetime",
    expires_at_iso: str | None = None,
) -> None:
    settings = get_settings()
    subject = _subject_for(fulfillment_type=fulfillment_type, expires_at_iso=expires_at_iso)
    payload = {
        "from": settings.email_from,
        "to": [to_email],
        "subject": subject,
        "html": _build_html(
            license_key,
            settings.support_email,
            fulfillment_type=fulfillment_type,
            expires_at_iso=expires_at_iso,
        ),
    }
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(_RESEND_SEND_URL, json=payload, headers=headers)

    if resp.status_code == 403:
        body = resp.json()
        if "restricted_api_key" in body.get("name", ""):
            logger.error(
                "Resend: send-only key rejected for recipient %s — "
                "only the Resend account owner email can receive in restricted mode",
                to_email,
            )
        elif "domain_not_verified" in str(body):
            logger.error("Resend: domain not verified. Verify %s in the Resend dashboard.", settings.resend_domain)
        else:
            logger.error("Resend 403: %s", body)
        raise RuntimeError(f"Resend delivery failed (403): {body}")

    if resp.status_code not in (200, 201):
        logger.error("Resend error %d: %s", resp.status_code, resp.text)
        raise RuntimeError(f"Resend delivery failed ({resp.status_code}): {resp.text}")

    logger.info("License key emailed to %s via Resend", to_email)
