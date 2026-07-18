"""Regression tests ensuring CARIB-CLEAR db assembly stays parameterized."""
from __future__ import annotations

import pytest

from carib_clear.db import Database, get_db, reset_db


@pytest.fixture(autouse=True)
def _in_memory_db() -> None:
    reset_db(db_path=":memory:")


def test_insert_rejects_disallowed_table_name() -> None:
    db = get_db()
    assert db.insert("evil_table; DROP TABLE participants; --", {"x": "y"}) is False


def test_special_characters_are_bound_not_interpolated_for_insert() -> None:
    sql_meta = '"; DELETE FROM settlements; --'
    db: Database = get_db()
    assert db.insert("settlements", {
        "settlement_id": sql_meta,
        "scope": "scope",
        "business_key": "bk",
        "rail": "rail",
        "order_id": "ord",
        "status": "pending",
        "amount_usd": 1.0,
        "currency_from": "USD",
        "currency_to": "USD",
        "amount_from": 1.0,
        "amount_to": 1.0,
        "rate": 1.0,
        "fees_usd": 0.0,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    }) is True
    row = db.get_settlement(sql_meta)
    assert row is not None
    assert row["settlement_id"] == sql_meta
    assert db.count("settlements") == 1


def test_list_settlements_special_characters_do_not_break_sql() -> None:
    db = get_db()
    db.insert("settlements", {
        "settlement_id": "s1",
        "scope": "scope",
        "business_key": "bk",
        "rail": "rail",
        "order_id": "ord",
        "status": "pending",
        "amount_usd": 1.0,
        "currency_from": "USD",
        "currency_to": "USD",
        "amount_from": 1.0,
        "amount_to": 1.0,
        "rate": 1.0,
        "fees_usd": 0.0,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
        "participant_id": "P'\"; OR 1=1; --",
    })
    rows = db.list_settlements(participant_id="P'\"; OR 1=1; --")
    assert len(rows) == 1
    assert db.count("settlements") == 1


def test_count_quotes_allowed_table_name() -> None:
    db = get_db()
    db.insert("settlements", {
        "settlement_id": "s2",
        "scope": "scope",
        "business_key": "bk",
        "rail": "rail",
        "order_id": "ord",
        "status": "pending",
        "amount_usd": 1.0,
        "currency_from": "USD",
        "currency_to": "USD",
        "amount_from": 1.0,
        "amount_to": 1.0,
        "rate": 1.0,
        "fees_usd": 0.0,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    })
    assert db.count("settlements", where=["status = ?"], params=("pending",)) == 1


def test_delete_rejects_unallowed_table_and_quotes_allowed_table() -> None:
    db = get_db()
    db.insert("settlements", {
        "settlement_id": "s3",
        "scope": "scope",
        "business_key": "bk",
        "rail": "rail",
        "order_id": "ord",
        "status": "pending",
        "amount_usd": 1.0,
        "currency_from": "USD",
        "currency_to": "USD",
        "amount_from": 1.0,
        "amount_to": 1.0,
        "rate": 1.0,
        "fees_usd": 0.0,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    })
    with pytest.raises(ValueError):
        db.delete("evil_table", where=["1=1"])
    assert db.count("settlements") == 1
    db.delete("settlements", where=["settlement_id = ?"], params=("s3",))
    assert db.count("settlements") == 0


def test_update_settlement_status_quotes_table_name() -> None:
    db = get_db()
    db.insert("settlements", {
        "settlement_id": "s4",
        "scope": "scope",
        "business_key": "bk",
        "rail": "rail",
        "order_id": "ord",
        "status": "pending",
        "amount_usd": 1.0,
        "currency_from": "USD",
        "currency_to": "USD",
        "amount_from": 1.0,
        "amount_to": 1.0,
        "rate": 1.0,
        "fees_usd": 0.0,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00",
    })
    assert db.update_settlement_status("s4", "filled") is True
    assert db.get_settlement("s4")["status"] == "filled"


def test_quote_identifier_rejects_injectionish_table_name() -> None:
    db = Database(":memory:")
    db.init_schema()
    with pytest.raises(ValueError):
        db._quote_identifier("settle'ments")


def test_audit_trail_rejects_delete_and_update() -> None:
    db = Database(":memory:")
    db.init_schema()
    audit_id = "audit-1"
    db.insert_audit_trail(
        audit_id=audit_id,
        event="test",
        actor="api",
        action="test",
        entity="test",
        entity_id=audit_id,
        payload={"ok": True},
        outcome="success",
    )
    with pytest.raises(ValueError):
        db.delete("audit_trail", where=["audit_id = ?"], params=(audit_id,))
    with pytest.raises(ValueError):
        db.execute("UPDATE audit_trail SET actor='evil' WHERE audit_id=?", (audit_id,))
    row = db.query_one("SELECT actor FROM audit_trail WHERE audit_id=?", (audit_id,))
    assert row and row["actor"] == "api"
