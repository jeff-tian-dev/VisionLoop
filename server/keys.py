from __future__ import annotations

import secrets

# Crockford base32 alphabet — no I, L, O, U to avoid visual confusion.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_crockford(data: bytes) -> str:
    """Encode bytes to Crockford base32 string (uppercase, no padding)."""
    value = int.from_bytes(data, "big")
    chars: list[str] = []
    while value > 0:
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def generate_license_key() -> str:
    """Return a key in the format CLASH-XXXX-XXXX-XXXX-XXXX.

    Uses 10 random bytes = 80 bits of entropy encoded as Crockford base32,
    then split into 4 groups of 4 characters.
    """
    raw = secrets.token_bytes(10)
    encoded = _encode_crockford(raw).zfill(16)
    # Ensure exactly 16 chars; trim if longer (token_bytes(10) -> ~16 base32 chars)
    chars = encoded[-16:]
    groups = [chars[i : i + 4] for i in range(0, 16, 4)]
    return "CLASH-" + "-".join(groups)


# Regex for validating a license key on inbound requests.
LICENSE_KEY_RE = r"^CLASH(-[0-9A-HJ-NP-TV-Z]{4}){4}$"
