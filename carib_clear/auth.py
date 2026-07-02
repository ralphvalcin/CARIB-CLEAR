"""API-key authentication for CARIB-CLEAR.

Opt-in via the CARIB_CLEAR_API_KEY environment variable: when set, every
route that declares the require_api_key dependency demands a matching
X-API-Key header; when unset, authentication is disabled (demo mode) and a
one-time startup warning is logged.
"""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import Header

from carib_clear.errors import CARIBClearException

logger = logging.getLogger(__name__)

_warned_disabled = False


def require_api_key(x_api_key: str = Header(default="")) -> None:
    """FastAPI dependency guarding state-changing endpoints.

    Reads the expected key from CARIB_CLEAR_API_KEY at request time so tests
    (and operators) can toggle it without restarting the process.
    """
    global _warned_disabled
    expected = os.getenv("CARIB_CLEAR_API_KEY", "")
    if not expected:
        if not _warned_disabled:
            logger.warning(
                "CARIB_CLEAR_API_KEY not set — running with authentication "
                "DISABLED, do not use this configuration in production"
            )
            _warned_disabled = True
        return
    # Compare as bytes: hmac.compare_digest raises TypeError on non-ASCII
    # str input, which would surface as a 500 instead of a clean 401.
    if not hmac.compare_digest(x_api_key.encode("utf-8"), expected.encode("utf-8")):
        raise CARIBClearException(
            code="unauthorized",
            message="Missing or invalid X-API-Key header",
            status_code=401,
        )
