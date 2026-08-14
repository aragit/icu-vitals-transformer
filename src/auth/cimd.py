"""CIMD / JWT bearer-token parsing stub (auth adapter).

Extracts the principal identity (``requested_by``) and roles from an
``Authorization: Bearer <jwt>`` header. This is a **stub** parser: it decodes
the JWT payload (HS/RS/PS/ECDSA-agnostic) without signature verification, which
is suitable for local dev and unit tests. Production deployments should wrap
this with a verifying decoder (JWKS) before trusting ``roles``.

Pure-adapter concern — not importable from ``src/core`` or ``src/ports``.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

from jwt import PyJWTError
from jwt import decode as _jwt_decode  # noqa: F401  (re-export intent / presence)
from jwt.exceptions import InvalidTokenError  # noqa: F401

logger = logging.getLogger(__name__)

BEARER_SCHEME = "bearer"


class TokenParseError(ValueError):
    """Raised when a bearer token cannot be parsed."""


def _b64url_decode_segment(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _decode_payload_unverified(token: str) -> dict[str, Any]:
    """Decode a JWT payload WITHOUT verifying its signature (dev/test stub)."""
    try:
        from jwt import decode
        return dict(decode(token, options={"verify_signature": False}))
    except Exception:  # noqa: BLE001 - fall back to manual decoding
        parts = token.split(".")
        if len(parts) < 2:
            raise TokenParseError("Malformed JWT (expected 3 segments)")
        try:
            payload = _b64url_decode_segment(parts[1])
        except (binascii.Error, ValueError) as exc:
            raise TokenParseError(f"Unparseable JWT payload: {exc}") from exc
        import json

        return dict(json.loads(payload))


def parse_cimd_token(authorization: str | None) -> dict[str, Any]:
    """Parse a CIMD/JWT bearer header into a principal context.

    Args:
        authorization: The raw ``Authorization`` header value (or ``None``).

    Returns:
        Dict with ``iss``, ``sub``, ``roles`` (list) and ``requested_by``.

    Raises:
        TokenParseError: if the header is absent/malformed and is required.
    """
    if not authorization:
        raise TokenParseError("Authorization header is required")

    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != BEARER_SCHEME:
        raise TokenParseError("Expected 'Bearer <token>' scheme")

    token = parts[1].strip()
    try:
        payload = _decode_payload_unverified(token)
    except PyJWTError as exc:
        raise TokenParseError(f"Invalid JWT: {exc}") from exc

    sub = payload.get("sub")
    if not sub:
        raise TokenParseError("JWT missing 'sub' claim")

    roles = payload.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]

    return {
        "iss": payload.get("iss"),
        "sub": sub,
        "roles": list(roles),
        "requested_by": sub,
    }


def parse_optional_bearer(authorization: str | None) -> dict[str, Any]:
    """Parse a bearer token, returning a default anonymous context when absent."""
    if not authorization:
        return {"iss": None, "sub": None, "roles": [], "requested_by": None}
    try:
        return parse_cimd_token(authorization)
    except TokenParseError:
        logger.warning("CIMD token parse failed; continuing anonymous")
        return {"iss": None, "sub": None, "roles": [], "requested_by": None}


__all__ = [
    "TokenParseError",
    "parse_cimd_token",
    "parse_optional_bearer",
    "BEARER_SCHEME",
]
