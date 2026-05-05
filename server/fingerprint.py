from __future__ import annotations

import re

# A machine fingerprint sent by the bot client is a 32-char lowercase hex string.
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{32}$")


def is_valid_fingerprint(value: str) -> bool:
    return bool(_FINGERPRINT_RE.match(value))
