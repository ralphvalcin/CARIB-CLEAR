"""Tests for DataAggregationAgent and related data models."""

from __future__ import annotations

from carib_clear.agents.data_aggregation import (
    BankStatementMetrics,
    BankStatementParser,
    BusinessProfile,
    BusinessSpecies,
    DataAggregationAgent,
    InvoiceParser,
    InvoiceRecord,
    InvoiceSummary,
    MonthlyRevenue,
    POSCSVParser,
    TaxComplianceStatus,
    TaxDocumentParser,
)


def test_business_species_defaults() -> None:
    """Verify BusinessSpecies default values."""
    species = BusinessSpecies()
    assert species.sector == "retail"
    assert species.sub_sector == ""
    assert species.description == ""


def test_business_species_custom() -> None:
    """Verify BusinessSpecies accepts custom values."""
    species = BusinessSpecies(sector="agriculture", sub_sector="coffee", description="Coffee farmer collective")
    assert species.sector == "agriculture"
    assert species.sub_sector == "coffee"
    assert species.description == "Coffee farmer collective"


def test_monthly_revenue_basic() -> None:
    """Verify MonthlyRevenue dataclass."""
    rev = MonthlyRevenue(
        month="2026-01",
        total_revenue_usd=15000.50,
        transaction_count=120,
        avg_ticket_usd=125.00,
        peak_day_revenue_usd=2500.00,
    )
    assert rev.month == "2026-01"
    assert rev.total_revenue_usd == 15000.50
    assert rev.transaction_count == 120


def test_invoice_record_basic() -> None:
    """Verify InvoiceRecord dataclass."""
    inv = InvoiceRecord(
        invoice_id="INV-001",
        type="receivable",
        counterparty="HT Distributors",
        amount_usd=5000.00,
        issued_date="2026-01-15",
        due_date="2026-02-14",
        status="pending",
        days_outstanding=10,
    )
    assert inv.invoice_id == "INV-001"
    assert inv.type == "receivable"
    assert inv.amount_usd == 5000.00


def test_bank_statement_metrics_basic() -> None:
    """Verify BankStatementMetrics dataclass."""
    bm = BankStatementMetrics(
        avg_monthly_deposits_usd=25000.00,
        avg_monthly_withdrawals_usd=20000.00,
        min_balance_3mo_usd=5000.00,
        avg_balance_3mo_usd=15000.00,
        deposit_volatility=0.15,
        nsf_count=0,
        cash_flow_pattern="stable",
        statement_months_analyzed=6,
    )
    assert bm.avg_monthly_deposits_usd == 25000.00
    assert bm.cash_flow_pattern == "stable"
    assert bm.nsf_count == 0


def test_tax_compliance_status_basic() -> None:
    """Verify TaxComplianceStatus dataclass."""
    tax = TaxComplianceStatus(
        nif_registered=True,
        tax_filing_status="compliant",
        last_filing_date="2026-03-31",
        years_filed=3,
        estimated_tax_liability_usd=2500.00,
        jurisdiction="HT",
    )
    assert tax.nif_registered is True
    assert tax.tax_filing_status == "compliant"
    assert tax.years_filed == 3


def test_business_profile_defaults() -> None:
    """Verify BusinessProfile default values."""
    profile = BusinessProfile(
        business_id="test_001",
        business_name="Test Business",
        jurisdiction="HT",
    )
    assert profile.business_id == "test_001"
    assert profile.business_name == "Test Business"
    assert profile.jurisdiction == "HT"
    assert profile.sector.sector == "retail"
    assert profile.avg_monthly_revenue_usd == 0.0
    assert profile.data_completeness == 0.0
    assert profile.data_sources == []


def test_pos_csv_parser_basic() -> None:
    """Verify POS CSV parsing."""
    csv_content = """date,amount,transaction_id,customer_id,item,category
2026-01-05,150.00,TX-001,CUST-001,produce,produce
2026-01-05,200.00,TX-002,CUST-002,dairy,dairy
2026-01-10,300.00,TX-003,CUST-001,beverages,beverages
2026-02-01,500.00,TX-004,CUST-003,dry_goods,dry_goods"""
    revenues = POSCSVParser.parse(csv_content)
    assert len(revenues) == 2  # Two months: January and February
    assert revenues[0].month == "2026-01"
    assert revenues[0].total_revenue_usd == 650.00  # 150 + 200 + 300
    assert revenues[0].transaction_count == 3
    assert revenues[1].month == "2026-02"
    assert revenues[1].total_revenue_usd == 500.00


def test_pos_csv_parser_empty() -> None:
    """Verify POS CSV parsing with empty content."""
    revenues = POSCSVParser.parse("date,amount,transaction_id")
    assert revenues == []


def test_invoice_parser_json_basic() -> None:
    """Verify invoice JSON parsing."""
    json_data = """{
        "invoices": [
            {
                "id": "INV-001",
                "type": "receivable",
                "counterparty": "Buyer Corp",
                "amount_usd": 5000.00,
                "issued": "2026-01-15",
                "due": "2026-02-14",
                "status": "paid",
                "paid_date": "2026-02-10"
            },
            {
                "id": "INV-002",
                "type": "payable",
                "counterparty": "Supplier Inc",
                "amount_usd": 2000.00,
                "issued": "2026-01-20",
                "due": "2026-02-19",
                "status": "pending"
            }
        ]
    }"""
    records, summary = InvoiceParser.parse_json(json_data)
    assert len(records) == 2
    assert summary.invoice_count == 2
    assert summary.total_receivables_usd == 5000.00
    assert summary.total_payables_usd == 2000.00
    assert summary.net_receivables_usd == 3000.00


def test_invoice_parser_csv() -> None:
    """Verify invoice CSV parsing."""
    csv_content = """id,type,counterparty,amount_usd,issued,due,status
INV-001,receivable,Buyer Corp,5000.00,2026-01-15,2026-02-14,paid
INV-002,payable,Supplier Inc,2000.00,2026-01-20,2026-02-19,pending"""
    records, summary = InvoiceParser.parse_csv(csv_content)
    assert len(records) == 2
    assert summary.invoice_count == 2


def test_bank_statement_parser() -> None:
    """Verify bank statement CSV parsing."""
    csv_content = """date,description,deposit,withdrawal,balance
2026-01-05,Sales deposit,5000.00,,15000.00
2026-01-10,Rent,,2000.00,13000.00
2026-02-01,Sales deposit,6000.00,,19000.00
2026-02-15,Payroll,,4000.00,15000.00
2026-03-01,Sales deposit,7000.00,,22000.00"""
    metrics = BankStatementParser.parse_csv(csv_content)
    assert metrics.statement_months_analyzed == 3
    assert metrics.avg_monthly_deposits_usd > 0
    assert metrics.avg_monthly_withdrawals_usd > 0
    assert metrics.min_balance_3mo_usd >= 0
    assert metrics.nsf_count == 0


def test_tax_parser() -> None:
    """Verify tax document JSON parsing."""
    json_data = """{
        "nif": "123-456-789",
        "jurisdiction": "HT",
        "filing_status": "compliant",
        "last_filing": "2026-03-31",
        "years_filed": 3,
        "estimated_liability_usd": 2500.00,
        "has_penalties": false
    }"""
    status = TaxDocumentParser.parse_json(json_data)
    assert status.nif_registered is True
    assert status.tax_filing_status == "compliant"
    assert status.years_filed == 3
    assert status.jurisdiction == "HT"
    assert status.has_penalties is False


def test_data_aggregation_agent_build_profile() -> None:
    """Verify DataAggregationAgent builds a complete profile."""
    agent = DataAggregationAgent()

    pos_csv = agent.generate_mock_pos_csv(months=3, avg_monthly_revenue=10000)
    invoices = agent.generate_mock_invoices(count=5)
    bank_stmt = agent.generate_mock_bank_statement(months=3, avg_deposit=12000)
    tax_data = agent.generate_mock_tax_data("JM")

    profile = agent.build_profile(
        business_id="test_001",
        business_name="Test Business",
        jurisdiction="JM",
        sector={"sector": "retail", "sub_sector": "general"},
        pos_csv_content=pos_csv,
        invoice_data=invoices,
        bank_statement_csv=bank_stmt,
        tax_data=tax_data,
    )

    assert profile.business_id == "test_001"
    assert profile.jurisdiction == "JM"
    assert profile.sector.sector == "retail"
    assert len(profile.data_sources) == 4  # All sources provided
    assert profile.data_completeness == 1.0
    assert profile.estimated_annual_revenue_usd > 0
    assert profile.cash_flow_stability_score > 0


def test_data_aggregation_minimal_data() -> None:
    """Verify profile builds with minimal data (only POS)."""
    agent = DataAggregationAgent()
    pos_csv = agent.generate_mock_pos_csv(months=2, avg_monthly_revenue=5000)

    profile = agent.build_profile(
        business_id="minimal_001",
        business_name="Minimal Business",
        jurisdiction="BB",
        pos_csv_content=pos_csv,
    )

    assert profile.business_id == "minimal_001"
    assert profile.data_sources == ["pos_csv"]
    assert profile.data_completeness == 0.25  # 1 of 4 sources
    assert profile.invoice_summary is None
    assert profile.bank_metrics is None
    assert profile.tax_status is None
    assert profile.avg_monthly_revenue_usd > 0


def test_data_aggregation_mock_generators() -> None:
    """Verify mock data generators produce valid output."""
    agent = DataAggregationAgent()

    pos_csv = agent.generate_mock_pos_csv(months=6, avg_monthly_revenue=15000)
    assert "date,amount" in pos_csv
    assert pos_csv.count("\n") > 10

    invoices = agent.generate_mock_invoices(count=10)
    assert '"invoices"' in invoices
    invoices_parsed, summary = InvoiceParser.parse_json(invoices)
    assert len(invoices_parsed) == 10

    bank_stmt = agent.generate_mock_bank_statement(months=6, avg_deposit=20000)
    assert "date,description,deposit,withdrawal,balance" in bank_stmt

    tax_data = agent.generate_mock_tax_data("HT")
    assert '"jurisdiction": "HT"' in tax_data
