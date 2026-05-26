"""UI constants ported from the legacy theme module."""

ATTACK_STRATEGIES: dict[str, int] = {
    "Sneaky Goblins": 1,
    "Super Minions": 2,
    "Valkyries": 3,
    "Edrags": 4,
}

STRIPE_LIFETIME_URL = "https://clashautoloot.duckdns.org/v1/checkout/lifetime"
MONTH_EXTEND_CHECKOUT_URL = "https://clashautoloot.duckdns.org/v1/checkout/month-extend"

UNPAIR_USER_ERRORS: dict[str, str] = {
    "empty": "No license key was entered.",
    "invalid_format": "That license key is not formatted correctly.",
    "not_found": "That license key was not found.",
    "revoked": "This license key has been revoked.",
    "machine_mismatch": "This PC was not paired with this key, so nothing was changed on the server.",
    "not_bound": "No machine was paired yet; your local saved key will still be removed.",
    "network_unreachable": "Could not reach the license server. Check your internet and try again.",
    "failed": "The server declined the request. Try again or contact support.",
}
