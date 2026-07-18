"""Legacy-compliance compatibility regression tests."""

from __future__ import annotations

from carib_clear.agents.compliance import ComplianceAgent
from carib_clear.compliance.screening import ComplianceScreeningEngine


def test_legacy_compliance_agent_matches_engine_jurisdiction_rules():
    engine = ComplianceScreeningEngine()
    engine.initialize()
    agent = ComplianceAgent()

    for jurisdiction in ["JM", "BB", "TT", "HT", "ECCB"]:
        engine_rules = engine.get_jurisdiction_rules(jurisdiction)
        legacy_rules = agent.get_jurisdiction_rules(jurisdiction)
        assert engine_rules == legacy_rules


def test_legacy_compliance_agent_onboard_matches_engine_kyc_outcome():
    engine = ComplianceScreeningEngine()
    engine.initialize()
    agent = ComplianceAgent()

    documents = {
        "JM": {"tax_compliance_certificate": "filed", "national_id": "verified", "proof_of_address": "verified", "trn": "verified"},
        "BB": {"tax_clearance_certificate": "f", "national_id": "f", "proof_of_address": "f"},
        "HT": {"national_id": "f", "proof_of_address": "f", "nif_certificate": "f"},
    }
    for jurisdiction, docs in documents.items():
        participant_id = f"compat_{jurisdiction.lower()}"
        engine_result = engine.onboard_participant(participant_id=participant_id, jurisdiction=jurisdiction, kyc_documents=docs)
        legacy_result = agent.onboard_participant(participant_id=participant_id, jurisdiction=jurisdiction, kyc_documents=docs)
        assert engine_result.passed == legacy_result.passed
        assert engine_result.check_type == legacy_result.check_type
