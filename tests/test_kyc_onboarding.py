"""Regression tests for KYC status-gated onboarding."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from carib_clear.api import app
from carib_clear.auth import _hash_secret
from carib_clear.db import get_db, reset_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def _use_shared_file_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "kyc_test.db")
    monkeypatch.delenv("CARIB_CLEAR_API_KEY", raising=False)
    monkeypatch.setenv("CARIB_CLEAR_ENV", "demo")
    monkeypatch.setenv("CARIB_CLEAR_DATABASE_URL", f"sqlite:///{db_path}")
    reset_db(db_path=db_path)
    yield
    monkeypatch.delenv("CARIB_CLEAR_DATABASE_URL", raising=False)


def test_settlement_blocked_until_verified():
    db = get_db()
    db.create_participant("p_block", "Blocked", "HT", participant_type="msme")
    secret = "blocked-secret-xxxxxxxxxxxxxxxxxxxx"
    db.create_api_key(
        key_id="key-blocked",
        participant_id="p_block",
        prefix=secret[:12],
        secret_hash=_hash_secret(secret),
        name="Blocked Key",
    )

    response = client.post("/settlements", json={
        "from_currency": "HTG",
        "to_currency": "USD",
        "amount_usd": 100,
        "amount_from": 100,
        "amount_to": 100,
        "rate": 1,
        "rail": "stellar",
        "order_id": "order-blocked",
        "business_key": "fx",
    }, headers={"X-API-Key": secret})

    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "kyc_required"


def test_settlement_allowed_after_onboard_and_verify():
    from carib_clear.agents.compliance import ComplianceAgent

    db = get_db()
    db.create_participant("p_ok", "OK", "BB", participant_type="msme")
    agent = ComplianceAgent()
    agent.onboard_participant(
        participant_id="p_ok",
        jurisdiction="BB",
        kyc_documents={
            "tax_clearance_certificate": "TCC",
            "national_id": "NAT",
            "proof_of_address": "POA",
        },
    )

    db = get_db()
    db.update_participant_status(participant_id="p_ok", status="verified")

    secret = "p_ok-secret-xxxxxxxxxxxxxxxxxxxx"
    db.create_api_key(
        key_id="key-ok",
        participant_id="p_ok",
        prefix=secret[:12],
        secret_hash=_hash_secret(secret),
        name="OK Key",
    )

    response = client.post("/settlements", json={
        "from_currency": "BBD",
        "to_currency": "JMD",
        "amount_usd": 100,
        "amount_from": 100,
        "amount_to": 100,
        "rate": 1,
        "rail": "stellar",
        "order_id": "order-ok",
        "business_key": "fx",
        "to_participant": "jmd-supplier",
        "from_jurisdiction": "BB",
        "to_jurisdiction": "JM",
    }, headers={"X-API-Key": secret})

    assert response.status_code == 200
    body = response.json()
    assert "settlement_id" in body


def test_onboarding_changes_pending_to_verified():
    db = get_db()
    db.create_participant("p_status", "StatusTest", "JM", participant_type="msme")
    participant = db.get_participant("p_status")
    assert participant is not None
    assert participant["status"] == "pending"

    response = client.post("/compliance/onboard", json={
        "participant_id": "p_status",
        "jurisdiction": "JM",
        "documents": {
            "tax_compliance_certificate": "TCC",
            "national_id": "NAT",
            "proof_of_address": "POA",
            "trn": "TRN",
        },
    })
    assert response.status_code == 200
    participant = db.get_participant("p_status")
    assert participant is not None
    assert participant["status"] == "verified"
