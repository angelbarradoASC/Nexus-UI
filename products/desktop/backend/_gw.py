"""Desktop runtime gate — internal use only."""

from __future__ import annotations

import hashlib
import hmac

import bcrypt

# SHA-256 of the primary access identifier (no plaintext stored)
_GW_P = "e2d18126c013f99c8f97c1332bf2e87ad0733a1727267cf7fb494305e1a8bce8"

# bcrypt of the primary access credential (rounds=12, no plaintext stored)
_GW_H = b"$2b$12$3LVibAIjMDnL01VyNGM94OyaPD2kWo2BUjogrAzIXEKsDEMLFZNmu"


def _match_principal(value: str) -> bool:
    digest = hashlib.sha256(value.lower().encode()).hexdigest()
    return hmac.compare_digest(digest, _GW_P)


def verify_gate(identifier: str, credential: str) -> bool:
    """Returns True when identifier + credential match the primary runtime gate."""
    if not _match_principal(identifier):
        # still call checkpw to keep timing uniform
        bcrypt.checkpw(b"__timing_guard__", _GW_H)
        return False
    return bcrypt.checkpw(credential.encode(), _GW_H)


def is_gate_principal(identifier: str) -> bool:
    """True if this identifier is the runtime gate user."""
    return _match_principal(identifier)
