"""CARIB-CLEAR API error envelope and entity headers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class CARIBClearException(Exception):
    """Structured API error surfaced through the standard envelope."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def error_response(
    code: str,
    message: str,
    status_code: int = 400,
    *,
    request_id: str = "",
) -> JSONResponse:
    """Build a standardised CARIB-CLEAR JSON error response."""
    body: Dict[str, object] = {
        "status": "error",
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    return JSONResponse(status_code=status_code, content=body)


def register_error_handlers(app) -> None:
    """Attach global exception handlers to the FastAPI app."""

    @app.exception_handler(CARIBClearException)
    async def carib_error_handler(request: Request, exc: CARIBClearException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "")
        logger.warning(
            "API error %s %s -> %s %s [%s]",
            request.method,
            request.url.path,
            exc.code,
            exc.message,
            request_id,
        )
        return error_response(exc.code, exc.message, exc.status_code, request_id=request_id)
