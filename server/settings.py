from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="/etc/license-api.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "prod"
    port: int = 8000

    # IPv4-safe access: PostgREST over HTTPS (anon key works while RLS stays off).
    supabase_url: str
    supabase_anon_key: str

    stripe_secret_key: str
    stripe_price_id: str = ""
    stripe_subscription_price_id: str = ""
    stripe_month_extend_price_id: str = ""
    stripe_webhook_secret: str = ""
    # Optional: a specific Customer portal configuration; blank = the account default.
    stripe_portal_configuration_id: str = ""
    stripe_portal_return_url: str = "https://clashautoloot.duckdns.org/?portal=done"

    def month_extend_price_id(self) -> str:
        """One-time Stripe Price for N× month access; falls back to stripe_subscription_price_id."""
        s = (self.stripe_month_extend_price_id or "").strip()
        return s or (self.stripe_subscription_price_id or "").strip()

    resend_api_key: str
    resend_domain: str = "clashautoloot.com"
    email_from: str
    support_email: str = "clashautoloot@gmail.com"

    duckdns_subdomain: str = "clashautoloot"
    duckdns_token: str = ""


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
