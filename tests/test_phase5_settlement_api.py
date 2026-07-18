"""Phase 5 settlement API contract tests."""
from __future__ import annotations

import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from carib_clear.api import app
from carib_clear.auth import _hash_secret
from carib_clear.db import get_db, reset_db
from carib_clear.errors import CARIBClearException

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_auth_state():
    import carib_clear.auth as auth_module
    auth_module._warned_disabled = False
    yield
    auth_module._warned_disabled = False


def _authed_headers(secret="phase5-secret"):
    return {"X-API-Key": secret}


def _init_test_db(db_path=None):
    import tempfile
    from pathlib import Path
    from carib_clear.db import reset_db
    if db_path == ":memory:":
        db_file = ":memory:"
    else:
        db_file = str(Path(db_path or tempfile.gettempdir()) / f"phase5_test_{Path(__file__).stem}.db")
    if db_file != ":memory:" and Path(db_file).exists():
        Path(db_file).unlink()
    reset_db(db_path=db_file)
    return db_file


def test_settlement_post_requires_api_key(monkeypatch):
    _init_test_db()
    monkeypatch.setenv("CARIB_CLEAR_API_KEY", "phase5-secret")
    res = client.post("/settlements", json={"from_currency": "BBD", "to_currency": "JMD", "amount_usd": 1, "amount_from": 1, "amount_to": 1, "rate": 1})
    assert res.status_code == 401


def test_settlement_reads_require_api_key(monkeypatch):
    _init_test_db()
    monkeypatch.setenv("CARIB_CLEAR_API_KEY", "phase5-secret")
    assert client.get("/settlements").status_code == 401
    assert client.get("/settlements/missing/events").status_code == 401


def test_settlement_routes_registered():
    routes = [getattr(route, "path", None) or getattr(getattr(route, "app", None), "path", None) for route in app.router.routes]
    assert "/settlements" in routes
    assert "/settlements/{settlement_id}" in routes
    assert "/settlements/{settlement_id}/events" in routes


def test_settlement_submit_with_api_key_returns_body(monkeypatch):
    _init_test_db()
    monkeypatch.setenv("CARIB_CLEAR_API_KEY", "phase5-secret")
    db = get_db()
    db.create_participant("p-body", "Body", "BB", participant_type="msme")
    db.create_api_key(
        key_id="key-body",
        participant_id="p-body",
        prefix="phase5-secre",
        secret_hash=_hash_secret("phase5-secret"),
        name="Body Key",
    )
    client.post(
        "/compliance/onboard",
        json={
            "participant_id": "p-body",
            "jurisdiction": "BB",
            "documents": {
                "tax_clearance_certificate": "TCC",
                "national_id": "NAT",
                "proof_of_address": "POA",
            },
        },
        headers={"X-API-Key": "phase5-secret"},
    )
    headers = _authed_headers()
    res = client.post("/settlements", json={
        "from_currency": "BBD",
        "to_currency": "JMD",
        "amount_usd": 500,
        "amount_from": 250,
        "amount_to": 385,
        "rate": 1.54,
        "fees_usd": 0.05,
        "business_key": "fx",
        "priority": "cost",
        "to_participant": "jmd-supplier",
        "from_jurisdiction": "BB",
        "to_jurisdiction": "JM",
    }, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["settlement_id"].startswith("stellar_usdc:")
    assert body["tx_hash"].endswith("stellar")

    events = client.get(f"/settlements/{body['settlement_id']}/events", headers=headers)
    assert events.status_code == 200
    assert len(events.json()["events"]) >= 1


def test_list_settlements_is_scoped_by_participant_id(monkeypatch):
    _init_test_db()
    monkeypatch.delenv("CARIB_CLEAR_API_KEY", raising=False)
    monkeypatch.setenv("CARIB_CLEAR_ENV", "demo")

    db = get_db()
    db.create_participant("p1", "P1", "BB", participant_type="msme")
    db.create_participant("p2", "P2", "JM", participant_type="msme")
    db.create_settlement("stellar_usdc:order-p1-1", scope="fx", business_key="fx", data={
        "rail": "stellar",
        "order_id": "order-p1-1",
        "status": "pending",
        "amount_usd": 100,
        "currency_from": "BBD",
        "currency_to": "JMD",
        "amount_from": 100,
        "amount_to": 100,
        "rate": 1,
        "raw_response": {},
    }, participant_id="p1")
    db.create_settlement("stellar_usdc:order-p1-2", scope="fx", business_key="fx", data={
        "rail": "stellar",
        "order_id": "order-p1-2",
        "status": "pending",
        "amount_usd": 200,
        "currency_from": "BBD",
        "currency_to": "JMD",
        "amount_from": 200,
        "amount_to": 200,
        "rate": 1,
        "raw_response": {},
    }, participant_id="p1")
    db.create_settlement("stellar_usdc:order-p2-1", scope="fx", business_key="fx", data={
        "rail": "stellar",
        "order_id": "order-p2-1",
        "status": "pending",
        "amount_usd": 300,
        "currency_from": "BBD",
        "currency_to": "JMD",
        "amount_from": 300,
        "amount_to": 300,
        "rate": 1,
        "raw_response": {},
    }, participant_id="p2")

    p1_rows = db.list_settlements(participant_id="p1")
    p2_rows = db.list_settlements(participant_id="p2")

    assert {row["settlement_id"] for row in p1_rows} == {"stellar_usdc:order-p1-1", "stellar_usdc:order-p1-2"}
    assert {row["settlement_id"] for row in p2_rows} == {"stellar_usdc:order-p2-1"}


def test_settlement_list_scoped_via_api(monkeypatch):
    _init_test_db()
    monkeypatch.delenv("CARIB_CLEAR_API_KEY", raising=False)
    monkeypatch.setenv("CARIB_CLEAR_ENV", "demo")

    db = get_db()
    db.create_participant("p1", "P1", "BB", participant_type="msme")
    db.create_participant("p2", "P2", "JM", participant_type="msme")
    k1_secret = "p1-secret-xxxxxxxxxxxxxxxxxxxx"
    k1_prefix = k1_secret[:12]
    k2_secret = "p2-secret-xxxxxxxxxxxxxxxxxxxx"
    k2_prefix = k2_secret[:12]
    db.create_api_key(
        key_id="key-p1",
        participant_id="p1",
        prefix=k1_prefix,
        secret_hash=_hash_secret(k1_secret),
        name="P1 Key",
    )
    db.create_api_key(
        key_id="key-p2",
        participant_id="p2",
        prefix=k2_prefix,
        secret_hash=_hash_secret(k2_secret),
        name="P2 Key",
    )

    client.post("/compliance/onboard", json={
        "participant_id": "p1",
        "jurisdiction": "BB",
        "documents": {
            "tax_clearance_certificate": "TCC-P1",
            "national_id": "NAT-P1",
            "proof_of_address": "POA-P1",
        },
    }, headers={"X-API-Key": k1_secret})
    client.post("/compliance/onboard", json={
        "participant_id": "p2",
        "jurisdiction": "JM",
        "documents": {
            "tax_compliance_certificate": "TCC-P2",
            "national_id": "NAT-P2",
            "proof_of_address": "POA-P2",
            "trn": "TRN-P2",
        },
    }, headers={"X-API-Key": k2_secret})

    def submit(participant_id: str, order_suffix: str):
        return client.post("/settlements", json={
            "from_currency": "BBD",
            "to_currency": "JMD",
            "amount_usd": 100,
            "amount_from": 100,
            "amount_to": 100,
            "rate": 1,
            "rail": "stellar",
            "order_id": f"order-{order_suffix}",
            "business_key": "fx",
            "to_participant": f"party-{participant_id}",
            "from_jurisdiction": "BB",
            "to_jurisdiction": "JM",
        }, headers={"X-API-Key": k1_secret if participant_id == "p1" else k2_secret}).json()

    p1_1 = submit("p1", "p1-1")
    p1_2 = submit("p1", "p1-2")
    p2_1 = submit("p2", "p2-1")

    p1_list = client.get("/settlements", headers={"X-API-Key": k1_secret}).json()["settlements"]
    p2_list = client.get("/settlements", headers={"X-API-Key": k2_secret}).json()["settlements"]

    assert {row["settlement_id"] for row in p1_list} == {p1_1["settlement_id"], p1_2["settlement_id"]}
    assert {row["settlement_id"] for row in p2_list} == {p2_1["settlement_id"]}
