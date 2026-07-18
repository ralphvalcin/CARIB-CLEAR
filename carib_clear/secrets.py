"""Back-end-agnostic secret loader for CARIB-CLEAR.

Priority:
1. Process environment variables (existing CARIB_CLEAR_* names)
2. Optional HashiCorp Vault when ``CARIB_CLEAR_SECRET_BACKEND=vault``

Non-negotiable: local/dev/test must continue to work without Vault or extra
dependencies installed.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class SecretBackendError(Exception):
    """Raised when the configured secret backend cannot supply a value."""


def _resolved_vault_backend():
    """Lazily import and instantiate a Vault backend when enabled."""
    if os.getenv("CARIB_CLEAR_SECRET_BACKEND", "").lower() != "vault":
        return None

    try:
        import hvac  # type: ignore[import-untyped]
    except Exception as exc:  # pragma: no cover - env dependent
        raise SecretBackendError(
            "CARIB_CLEAR_SECRET_BACKEND=vault selected but 'hvac' is not installed"
        ) from exc

    vault_url = os.getenv("CARIB_CLEAR_VAULT_URL", "")
    vault_token = os.getenv("CARIB_CLEAR_VAULT_TOKEN", "")
    vault_mount = os.getenv("CARIB_CLEAR_VAULT_MOUNT", "secret")
    vault_prefix = os.getenv("CARIB_CLEAR_VAULT_PREFIX", "carib-clear")

    if not vault_url or not vault_token:
        raise SecretBackendError(
            "CARIB_CLEAR_VAULT_URL and CARIB_CLEAR_VAULT_TOKEN are required when "
            "CARIB_CLEAR_SECRET_BACKEND=vault"
        )

    client = hvac.Client(url=vault_url, token=vault_token)
    if not client.is_authenticated():
        raise SecretBackendError("Vault authentication failed for CARIB-CLEAR backend")

    return hvac.Client(url=vault_url, token=vault_token)


def get_secret(key: str, default: Optional[str] = None) -> str:
    """Resolve a secret value by CARIB-CLEAR env var name.

    The ``key`` should be the full environment variable name, for example
    ``CARIB_CLEAR_API_KEY``.

    Resolution order:
    - current process env
    - Vault KV v2 at ``CARIB_CLEAR_VAULT_MOUNT/data/CARIB_CLEAR_VAULT_PREFIX``
      as a field of the same name, if Vault backend is enabled
    - ``default`` if provided
    - empty string if no value is available
    """
    env_value = os.getenv(key)
    if env_value:
        return env_value

    backend = _resolved_vault_backend()
    if backend is not None:
        mount = os.getenv("CARIB_CLEAR_VAULT_MOUNT", "secret")
        prefix = os.getenv("CARIB_CLEAR_VAULT_PREFIX", "carib-clear")
        path = f"{prefix}/data/{key}"
        try:
            response = backend.secrets.kv.v2.read_secret_version(path=path, mount_point=mount)
            data = response.get("data", {}).get("data", {})
            if key in data and data[key] is not None:
                logger.info("[Secrets] loaded %s from Vault", key)
                return str(data[key])
        except Exception as exc:
            logger.debug("[Secrets] Vault read %s failed: %s", path, exc)

    if default is not None:
        return default
    return ""
