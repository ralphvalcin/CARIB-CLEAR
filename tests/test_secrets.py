"""Regression tests for carib_clear.secrets."""

from __future__ import annotations

import os
import pytest

from carib_clear.secrets import get_secret, SecretBackendError


def test_get_secret_env_wins():
    os.environ["CARIB_CLEAR_TEST_SECRET_A"] = "from-env"
    os.environ.pop("CARIB_CLEAR_SECRET_BACKEND", None)
    assert get_secret("CARIB_CLEAR_TEST_SECRET_A") == "from-env"


def test_get_secret_default_when_missing():
    os.environ.pop("CARIB_CLEAR_TEST_SECRET_B", None)
    os.environ.pop("CARIB_CLEAR_SECRET_BACKEND", None)
    assert get_secret("CARIB_CLEAR_TEST_SECRET_B", "fallback") == "fallback"
    assert get_secret("CARIB_CLEAR_TEST_SECRET_B") == ""


def test_vault_missing_install_raises(monkeypatch):
    monkeypatch.delenv("CARIB_CLEAR_TEST_SECRET_C", raising=False)
    monkeypatch.setenv("CARIB_CLEAR_SECRET_BACKEND", "vault")
    with pytest.raises(SecretBackendError):
        get_secret("CARIB_CLEAR_TEST_SECRET_C", "local")


def test_vault_paths_ignored_when_backend_unset():
    assert get_secret("CARIB_CLEAR_TEST_SECRET_C", "local") == "local"
