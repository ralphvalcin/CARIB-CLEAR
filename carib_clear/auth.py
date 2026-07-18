"""API-key authentication for CARIB-CLEAR.

Opt-in via the CARIB_CLEAR_API_KEY environment variable: when set, every
route that declares the require_api_key dependency demands a matching
X-API-Key header; when unset, authentication is disabled (demo mode) and a
one-time startup warning is logged.

Productization bridge: when a participant-scoped key is presented and
lookup succeeds, the dependency also resolves the owning participant_id
so downstream handlers can scope data access.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Header
from pydantic import BaseModel

from carib_clear.errors import CARIBClearException
from carib_clear.secrets import get_secret

logger = logging.getLogger(__name__)

_warned_disabled = False


@dataclass
class AuthenticatedIdentity:
    participant_id: Optional[str]
    key_id: Optional[str]
    source: str
    kyc_status: Optional[str] = None


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _legacy_auth(x_api_key: str) -> Optional[AuthenticatedIdentity]:
    expected = get_secret("CARIB_CLEAR_API_KEY", "")
    if expected and hmac.compare_digest(x_api_key.encode("utf-8"), expected.encode("utf-8")):
        return AuthenticatedIdentity(participant_id=None, key_id=None, source="legacy_env")
    return None


def require_api_key(x_api_key: str = Header(default="")) -> AuthenticatedIdentity:
    """FastAPI dependency guarding state-changing endpoints."""
    global _warned_disabled
    expected = get_secret("CARIB_CLEAR_API_KEY", "")
    env_mode = os.getenv("CARIB_CLEAR_ENV", "").lower()

    is_demo_mode = env_mode in {"local", "demo"}

    if not x_api_key:
        if not expected:
            if is_demo_mode:
                if not _warned_disabled:
                    logger.warning(
                        "CARIB_CLEAR_API_KEY not set — running with authentication "
                        "DISABLED in demo mode; do not use this configuration in production"
                    )
                    _warned_disabled = True
                return AuthenticatedIdentity(participant_id=None, key_id=None, source="disabled")
            raise CARIBClearException(
                code="unauthorized",
                message="Missing or invalid X-API-Key header",
                status_code=401,
            )
        raise CARIBClearException(
            code="unauthorized",
            message="Missing or invalid X-API-Key header",
            status_code=401,
        )

    legacy = _legacy_auth(x_api_key)
    if legacy:
        return legacy

    try:
        from carib_clear.db import get_db
        prefix = x_api_key[:12]
        row = get_db().get_active_api_key_by_prefix(prefix)

        if row and hmac.compare_digest(
            _hash_secret(x_api_key).encode("utf-8"),
            row["secret_hash"].encode("utf-8"),
        ):
            return AuthenticatedIdentity(
                participant_id=row["participant_id"],
                key_id=row["key_id"],
                source="participant_key",
            )
    except Exception as exc:
        logger.debug("Participant key lookup failed: %s", exc)

    raise CARIBClearException(
        code="unauthorized",
        message="Missing or invalid X-API-Key header",
        status_code=401,
    )


def _get_participant_status_db(participant_id: str) -> Optional[str]:
    from carib_clear.db import get_db
    row = get_db().query_one(
        "SELECT status FROM participants WHERE participant_id = ?",
        (participant_id,),
    )
    if not row:
        return None
    return row.get("status", "")


def _require_participant_status(identity: AuthenticatedIdentity) -> AuthenticatedIdentity:
    participant_id = identity.participant_id
    if not participant_id:
        identity.kyc_status = "disabled"
        return identity

    status = _get_participant_status_db(participant_id)
    if status is None:
        raise CARIBClearException(
            code="not_found",
            message="Participant not found for KYC status check",
            status_code=404,
        )
    normalized = (status or "").lower()
    if normalized not in {"verified", "active"}:
        raise CARIBClearException(
            code="kyc_required",
            message=f"Participant KYC status is '{status}'. Verify identity via /compliance/onboard before submitting settlements.",
            status_code=400,
        )
    identity.kyc_status = normalized
    return identity


def require_verified_participant(identity: AuthenticatedIdentity = Depends(require_api_key)) -> AuthenticatedIdentity:
    """Gate settlement calls behind participant KYC status.

    Blocks participants with status != verified/active with a 400 and
    the standard JSON error envelope.
    """
    return _require_participant_status(identity)


def _require_admin_token(x_admin_token: str = Header(..., alias="X-Admin-Token")) -> AuthenticatedIdentity:
    """Require a matching operator/admin token for sensitive read APIs.

    Fail-closed:
    - unset env => request denied
    - missing header => 403
    - mismatch => 403
    """
    expected = get_secret("CARIB_CLEAR_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=403, detail="admin token not configured")
    if not hmac.compare_digest(expected.encode("utf-8"), x_admin_token.encode("utf-8")):
        raise HTTPException(status_code=403, detail="invalid admin token")
    return AuthenticatedIdentity(participant_id=None, key_id=None, source="admin_token", kyc_status="admin")


def require_admin(identity: AuthenticatedIdentity = Depends(_require_admin_token)) -> AuthenticatedIdentity:
    return identity


class ParticipantAuthResult(BaseModel):
    participant_id: str
    key_id: str
