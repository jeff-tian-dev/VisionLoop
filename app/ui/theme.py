"""Single source of truth for visual design tokens. Change here -> whole UI follows."""

# Surfaces (CTk often uses light / dark tuple for fg_color)
COLOR_APP_BG = ("#151a22", "#0e1116")
COLOR_SURFACE = "#181d28"
COLOR_SURFACE_HI = "#222837"
COLOR_BORDER = "#2a3142"
CARD_FG = (COLOR_SURFACE_HI, COLOR_SURFACE)
BORDER = (COLOR_BORDER, "#1a2030")

# Text
COLOR_TEXT = "#e6edf3"
COLOR_TEXT_MUTED = "#8b97a8"

# Brand / semantic
COLOR_PRIMARY = "#0ea5e9"
COLOR_PRIMARY_HOV = "#0284c7"
COLOR_SUCCESS = "#22c55e"
COLOR_SUCCESS_HOV = "#16a34a"
COLOR_DANGER = "#ef4444"
COLOR_DANGER_HOV = "#dc2626"
COLOR_WARNING = "#f59e0b"
COLOR_WARNING_TEXT = "#fbbf24"
COLOR_NEUTRAL = ("#4a5568", "#3d4556")
COLOR_NEUTRAL_HOV = ("#5c6578", "#4d5566")
COLOR_NEUTRAL_DARK = ("#3a4256", "#2d3444")
COLOR_NEUTRAL_DARK_HOV = ("#4a5265", "#3d4455")

# Spacing
SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG = 4, 8, 12, 16
PAD_OUTER = SPACE_LG
CARD_PAD = SPACE_LG
CARD_GAP = SPACE_MD
RADIUS = 12

# Typography (CTkFont size)
FONT_TITLE = 22
FONT_SECTION = 13
FONT_BODY = 13
FONT_BUTTON = 13
FONT_BUTTON_LG = 14
FONT_MONO = "Courier New"

# Segmented / switches
ATTACK_SEGMENTED_HEIGHT = 40
ATTACK_SECTION_FONT = 14

# Heights
H_SM, H_MD, H_LG = 28, 34, 42

# License popup
LICENSE_POPUP_W = 480
LICENSE_POPUP_H = 520
LICENSE_STATUS_BODY_W = 400
LICENSE_STATUS_BODY_H = 120

UNPAIR_DIALOG_W = 440
UNPAIR_DIALOG_H = 420

# External URLs
STRIPE_LIFETIME_URL = "https://clashautoloot.duckdns.org/v1/checkout/lifetime"
MONTH_EXTEND_CHECKOUT_URL = "https://clashautoloot.duckdns.org/v1/checkout/month-extend"

# Strategy display label -> bot method id
ATTACK_STRATEGIES: dict[str, int] = {
    "Sneaky Goblins": 1,
    "Super Minions": 2,
    "Valkyries": 3,
}

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

# Ranked attack switch styling (danger emphasis)
RANKED_SWITCH_COLORS: dict[str, object] = {
    "text_color": COLOR_DANGER,
    "fg_color": ("#3f3f46", "#27272a"),
    "progress_color": COLOR_DANGER,
    "button_color": ("#f87171", "#ef4444"),
    "button_hover_color": COLOR_DANGER_HOV,
}
