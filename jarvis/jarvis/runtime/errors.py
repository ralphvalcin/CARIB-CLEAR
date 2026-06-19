from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Centralised error codes for JARVIS runtime responses."""

    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    APPROVAL_ALREADY_DENIED = "APPROVAL_ALREADY_DENIED"
    APPROVAL_CLAIM_CONFLICT = "APPROVAL_CLAIM_CONFLICT"
    APPROVAL_EXECUTION_FAILED = "APPROVAL_EXECUTION_FAILED"