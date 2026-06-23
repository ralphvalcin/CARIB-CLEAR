"""Tests for the CARIB-CLEAR FastAPI server."""

from __future__ import annotations

from fastapi.testclient import TestClient

from carib_clear.api import app

client = TestClient(app)


def test_health() -> None:
    """Verify health endpoint returns healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0-buildathon"


def test_health_root() -> None:
    """Verify root endpoint also returns health."""
    response = client.get("/")
    assert response.status_code == 200


def test_liquidity_state() -> None:
    """Verify liquidity pool state endpoint."""
    response = client.get("/liquidity/state")
    assert response.status_code == 200
    data = response.json()
    assert "total_liquidity_usd" in data
    assert data["total_liquidity_usd"] > 0


def test_compliance_jurisdictions() -> None:
    """Verify compliance jurisdictions are returned."""
    response = client.get("/compliance/jurisdictions")
    assert response.status_code == 200
    data = response.json()
    assert "JM" in data
    assert "BB" in data
    assert "HT" in data
    assert data["JM"]["regulator"] == "Bank of Jamaica"


def test_loan_apply_approved() -> None:
    """Verify loan application is processed."""
    response = client.post("/loan/apply", json={
        "business_name": "Test Business",
        "jurisdiction": "BB",
        "amount_usd": 25000,
        "sector": "retail",
        "purpose": "working_capital",
        "months": 18,
    })
    assert response.status_code == 200
    data = response.json()
    assert "application_id" in data
    assert "credit_score" in data
    assert "credit_rating" in data


def test_loan_apply_validation() -> None:
    """Verify loan application validation rejects invalid data."""
    response = client.post("/loan/apply", json={
        "business_name": "",
        "jurisdiction": "",
        "amount_usd": -100,
    })
    assert response.status_code == 422  # Validation error


def test_list_applications() -> None:
    """Verify listing applications returns data."""
    # Submit one first
    client.post("/loan/apply", json={
        "business_name": "List Test",
        "jurisdiction": "JM",
        "amount_usd": 10000,
        "sector": "agriculture",
        "purpose": "expansion",
        "months": 12,
    })
    response = client.get("/loan/applications?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "applications" in data
    assert len(data["applications"]) >= 1


def test_compliance_profile_not_found() -> None:
    """Verify unknown compliance profile returns 404."""
    response = client.get("/compliance/profile/nonexistent")
    assert response.status_code == 404


def test_compliance_onboard() -> None:
    """Verify onboarding a new participant."""
    response = client.post("/compliance/onboard", json={
        "participant_id": "api_test_user",
        "jurisdiction": "HT",
        "documents": {
            "national_id": "verified",
            "proof_of_address": "verified",
            "nif_certificate": "verified",
        },
    })
    assert response.status_code == 200
    data = response.json()
    assert data["participant_id"] == "api_test_user"
    assert data["passed"] is True


def test_compliance_screen() -> None:
    """Verify transaction screening endpoint."""
    response = client.post("/compliance/screen", json={
        "from_participant": "sender_test",
        "to_participant": "receiver_test",
        "amount_usd": 5000,
        "currency": "BBD",
        "purpose": "trade",
    })
    assert response.status_code == 200
    data = response.json()
    assert "passed" in data
    assert "score" in data


def test_market_state() -> None:
    """Verify market state endpoint."""
    response = client.get("/market/state")
    assert response.status_code == 200
    data = response.json()
    assert "flows" in data
    assert "liquidity" in data


def test_dashboard_returns_html() -> None:
    """Verify dashboard endpoint returns HTML."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "CARIB-CLEAR" in response.text
    assert "<html" in response.text.lower()


def test_trade_finance_demo() -> None:
    """Verify trade finance demo endpoint."""
    response = client.get("/demo/trade_finance")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "stats" in data
    assert data["stats"]["funded"] >= 0