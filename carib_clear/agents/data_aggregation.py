"""DataAggregation Agent — transforms raw financial documents into unified BusinessProfiles.

Input sources:
  - POS/Sales CSV — daily revenue, transactions, customer data
  - Invoices — accounts receivable/payable, aging, terms
  - Bank statements — cash flow, deposits, withdrawals, balance patterns
  - Tax documents — compliance status, NIF certificate, filing history

Output: Unified BusinessProfile ready for CreditProfileGenerator scoring.

For the buildathon, parsers handle CSV and structured JSON inputs.
Real production deployment would add OCR (PDF invoices) and API integrations
(bank statement APIs, gov tax portals).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class BusinessSpecies:
    """Business sector classification.
    
    Named to avoid confusion with market sector as a trading term.
    """
    sector: str = "retail"  # "retail", "agriculture", "services", "manufacturing", "tech"
    sub_sector: str = ""
    description: str = ""


@dataclass
class MonthlyRevenue:
    """Monthly revenue snapshot from POS/sales data."""
    month: str  # "YYYY-MM"
    total_revenue_usd: float
    transaction_count: int
    avg_ticket_usd: float
    peak_day_revenue_usd: float
    source: str = "pos_csv"


@dataclass
class InvoiceRecord:
    """Individual invoice record."""
    invoice_id: str
    type: str  # "receivable" or "payable"
    counterparty: str
    amount_usd: float
    issued_date: str  # ISO date
    due_date: str
    status: str  # "paid", "pending", "overdue", "cancelled"
    days_outstanding: int = 0
    paid_date: Optional[str] = None


@dataclass
class InvoiceSummary:
    """Aggregated invoice analysis."""
    total_receivables_usd: float
    total_payables_usd: float
    net_receivables_usd: float
    avg_collection_period_days: float
    overdue_ratio: float  # 0.0-1.0
    invoice_count: int
    top_counterparties: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class BankStatementMetrics:
    """Analyzed bank statement metrics."""
    avg_monthly_deposits_usd: float
    avg_monthly_withdrawals_usd: float
    min_balance_3mo_usd: float
    avg_balance_3mo_usd: float
    deposit_volatility: float  # coefficient of variation
    nsf_count: int  # non-sufficient funds / bounced
    cash_flow_pattern: str  # "stable", "seasonal", "erratic"
    statement_months_analyzed: int = 0


@dataclass
class TaxComplianceStatus:
    """Tax compliance evaluation."""
    nif_registered: bool
    tax_filing_status: str  # "compliant", "non_filing", "under_audit"
    last_filing_date: Optional[str]
    years_filed: int
    estimated_tax_liability_usd: float
    has_penalties: bool = False
    jurisdiction: str = ""


@dataclass
class BusinessProfile:
    """Unified business profile — output of DataAggregationAgent.

    This is the input to CreditProfileGenerator for scoring.
    """

    # Identity
    business_id: str
    business_name: str
    jurisdiction: str
    sector: BusinessSpecies = field(default_factory=BusinessSpecies)
    operating_months: int = 0

    # Financial
    monthly_revenues: List[MonthlyRevenue] = field(default_factory=list)
    avg_monthly_revenue_usd: float = 0.0
    revenue_trend: str = "stable"  # "growing", "stable", "declining", "seasonal"
    invoice_summary: Optional[InvoiceSummary] = None
    bank_metrics: Optional[BankStatementMetrics] = None
    tax_status: Optional[TaxComplianceStatus] = None

    # Derived
    estimated_annual_revenue_usd: float = 0.0
    cash_flow_stability_score: float = 0.5  # 0.0-1.0
    data_completeness: float = 0.0  # 0.0-1.0 — how much data was provided
    data_sources: List[str] = field(default_factory=list)

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_files: Dict[str, str] = field(default_factory=dict)


@dataclass
# ─────────────────────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────────────────────


class POSCSVParser:
    """Parse POS/sales CSV data into monthly revenue records.

    Expected CSV columns: date, amount, transaction_id, [customer_id, item, category]
    """

    @staticmethod
    def parse(csv_content: str, source_name: str = "pos_csv") -> List[MonthlyRevenue]:
        """Parse POS CSV content into monthly revenue records."""
        reader = csv.DictReader(io.StringIO(csv_content))
        daily_revenue: Dict[str, float] = {}
        daily_counts: Dict[str, int] = {}
        daily_peak: Dict[str, float] = {}

        for row in reader:
            try:
                date_str = row.get("date", "")
                amount = float(row.get("amount", 0))
                if not date_str or amount <= 0:
                    continue

                # Parse date to get month key
                dt = datetime.fromisoformat(date_str)
                month_key = dt.strftime("%Y-%m")
                day_key = dt.strftime("%Y-%m-%d")

                daily_revenue[month_key] = daily_revenue.get(month_key, 0) + amount
                daily_counts[month_key] = daily_counts.get(month_key, 0) + 1
                daily_peak[day_key] = daily_peak.get(day_key, 0) + amount

            except (ValueError, KeyError):
                continue

        revenues = []
        for month_key in sorted(daily_revenue.keys()):
            total = daily_revenue[month_key]
            count = daily_counts.get(month_key, 0)

            # Find peak day for this month
            month_prefix = month_key + "-"
            peak = max(
                (amt for day, amt in daily_peak.items() if day.startswith(month_prefix)),
                default=0,
            )

            revenues.append(MonthlyRevenue(
                month=month_key,
                total_revenue_usd=round(total, 2),
                transaction_count=count,
                avg_ticket_usd=round(total / count, 2) if count > 0 else 0,
                peak_day_revenue_usd=round(peak, 2),
                source=source_name,
            ))

        logger.info("POS CSV parsed: %d months, %d transactions", len(revenues), sum(r.transaction_count for r in revenues))
        return revenues


class InvoiceParser:
    """Parse invoice data (JSON or CSV) into InvoiceSummary."""

    @staticmethod
    def parse_json(json_data: str) -> Tuple[List[InvoiceRecord], InvoiceSummary]:
        """Parse invoice records from JSON string.

        Expected format:
        {
            "invoices": [
                {
                    "id": "INV-001",
                    "type": "receivable",
                    "counterparty": "Buyer Corp",
                    "amount_usd": 5000,
                    "issued": "2026-01-15",
                    "due": "2026-02-14",
                    "status": "paid",
                    "paid_date": "2026-02-10"
                }
            ]
        }
        """
        data = json.loads(json_data)
        records = []

        for inv in data.get("invoices", []):
            issued = inv.get("issued", "")
            due = inv.get("due", "")
            paid = inv.get("paid_date")

            # Calculate days outstanding
            try:
                due_dt = datetime.fromisoformat(due)
                now = datetime.now(timezone.utc)
                days_out = (now - due_dt.replace(tzinfo=timezone.utc)).days if inv.get("status") != "paid" else 0
                days_out = max(0, days_out)
            except (ValueError, TypeError):
                days_out = 0

            records.append(InvoiceRecord(
                invoice_id=inv.get("id", ""),
                type=inv.get("type", "receivable"),
                counterparty=inv.get("counterparty", ""),
                amount_usd=float(inv.get("amount_usd", 0)),
                issued_date=issued,
                due_date=due,
                status=inv.get("status", "pending"),
                days_outstanding=days_out,
                paid_date=paid,
            ))

        summary = InvoiceParser._summarize(records)
        return records, summary

    @staticmethod
    def _summarize(records: List[InvoiceRecord]) -> InvoiceSummary:
        """Aggregate records into a summary."""
        receivables = [r for r in records if r.type == "receivable"]
        payables = [r for r in records if r.type == "payable"]

        total_rec = sum(r.amount_usd for r in receivables)
        total_pay = sum(r.amount_usd for r in payables)
        overdue = [r for r in receivables if r.status == "overdue"]
        paid_rec = [r for r in receivables if r.status == "paid"]

        # Average collection period from paid invoices
        collection_days = []
        for r in paid_rec:
            if r.paid_date and r.issued_date:
                try:
                    issued = datetime.fromisoformat(r.issued_date)
                    paid_dt = datetime.fromisoformat(r.paid_date)
                    collection_days.append((paid_dt - issued).days)
                except (ValueError, TypeError):
                    pass

        avg_collection = sum(collection_days) / len(collection_days) if collection_days else 45.0
        overdue_ratio = len(overdue) / len(receivables) if receivables else 0

        # Top counterparties by volume
        counterparty_vol: Dict[str, float] = defaultdict(float)
        for r in records:
            counterparty_vol[r.counterparty] += r.amount_usd

        top = sorted(
            [{"name": k, "volume_usd": round(v, 2)} for k, v in counterparty_vol.items()],
            key=lambda x: x["volume_usd"],
            reverse=True,
        )[:5]

        return InvoiceSummary(
            total_receivables_usd=round(total_rec, 2),
            total_payables_usd=round(total_pay, 2),
            net_receivables_usd=round(total_rec - total_pay, 2),
            avg_collection_period_days=round(avg_collection, 1),
            overdue_ratio=round(overdue_ratio, 3),
            invoice_count=len(records),
            top_counterparties=top,
        )

    @staticmethod
    def parse_csv(csv_content: str) -> Tuple[List[InvoiceRecord], InvoiceSummary]:
        """Parse invoice records from CSV.

        Columns: id, type, counterparty, amount_usd, issued, due, status, [paid_date]
        """
        reader = csv.DictReader(io.StringIO(csv_content))
        records = []

        for row in reader:
            try:
                issued = row.get("issued", "")
                due = row.get("due", "")
                paid = row.get("paid_date", "")

                due_dt = datetime.fromisoformat(due)
                now = datetime.now(timezone.utc)
                days_out = max(0, (now - due_dt.replace(tzinfo=timezone.utc)).days) if row.get("status") != "paid" else 0

                records.append(InvoiceRecord(
                    invoice_id=row.get("id", ""),
                    type=row.get("type", "receivable"),
                    counterparty=row.get("counterparty", ""),
                    amount_usd=float(row.get("amount_usd", 0)),
                    issued_date=issued,
                    due_date=due,
                    status=row.get("status", "pending"),
                    days_outstanding=days_out,
                    paid_date=paid or None,
                ))
            except (ValueError, KeyError):
                continue

        summary = InvoiceParser._summarize(records)
        return records, summary


class BankStatementParser:
    """Parse bank statement data (CSV or JSON) into BankStatementMetrics.

    Expected CSV columns: date, description, deposit, withdrawal, balance
    """

    @staticmethod
    def parse_csv(csv_content: str) -> BankStatementMetrics:
        """Parse bank statement CSV into metrics."""
        reader = csv.DictReader(io.StringIO(csv_content))

        monthly_deposits: Dict[str, float] = defaultdict(float)
        monthly_withdrawals: Dict[str, float] = defaultdict(float)
        monthly_balances: Dict[str, List[float]] = defaultdict(list)
        nsf_count = 0

        for row in reader:
            try:
                date_str = row.get("date", "")
                deposit = float(row.get("deposit", 0) or 0)
                withdrawal = float(row.get("withdrawal", 0) or 0)
                balance = float(row.get("balance", 0) or 0)

                dt = datetime.fromisoformat(date_str)
                month_key = dt.strftime("%Y-%m")

                monthly_deposits[month_key] += deposit
                monthly_withdrawals[month_key] += withdrawal
                monthly_balances[month_key].append(balance)

                # Detect NSF (negative balance after withdrawal)
                if withdrawal > 0 and balance < 0:
                    nsf_count += 1

            except (ValueError, KeyError):
                continue

        if not monthly_deposits:
            return BankStatementMetrics(
                avg_monthly_deposits_usd=0,
                avg_monthly_withdrawals_usd=0,
                min_balance_3mo_usd=0,
                avg_balance_3mo_usd=0,
                deposit_volatility=0,
                nsf_count=0,
                cash_flow_pattern="unknown",
                statement_months_analyzed=0,
            )

        deposits_list = list(monthly_deposits.values())
        withdrawals_list = list(monthly_withdrawals.values())
        all_balances = [b for balances in monthly_balances.values() for b in balances]

        avg_deposits = sum(deposits_list) / len(deposits_list)
        avg_withdrawals = sum(withdrawals_list) / len(withdrawals_list)
        min_balance = min(all_balances) if all_balances else 0
        avg_balance = sum(all_balances) / len(all_balances) if all_balances else 0

        # Deposit volatility (coefficient of variation)
        if avg_deposits > 0 and len(deposits_list) > 1:
            std_dev = math.sqrt(sum((d - avg_deposits) ** 2 for d in deposits_list) / len(deposits_list))
            volatility = std_dev / avg_deposits
        else:
            volatility = 0

        # Cash flow pattern classification
        if len(deposits_list) >= 3:
            recent = deposits_list[-3:]
            if max(recent) / max(min(recent), 1) > 3:
                pattern = "seasonal"
            elif volatility > 0.5:
                pattern = "erratic"
            else:
                pattern = "stable"
        else:
            pattern = "stable"

        return BankStatementMetrics(
            avg_monthly_deposits_usd=round(avg_deposits, 2),
            avg_monthly_withdrawals_usd=round(avg_withdrawals, 2),
            min_balance_3mo_usd=round(min_balance, 2),
            avg_balance_3mo_usd=round(avg_balance, 2),
            deposit_volatility=round(volatility, 3),
            nsf_count=nsf_count,
            cash_flow_pattern=pattern,
            statement_months_analyzed=len(monthly_deposits),
        )


class TaxDocumentParser:
    """Parse tax compliance data (minimal for buildathon)."""

    @staticmethod
    def parse_json(json_data: str) -> TaxComplianceStatus:
        """Parse tax compliance data from JSON.

        Expected format:
        {
            "nif": "123-456-789",
            "jurisdiction": "HT",
            "filing_status": "compliant",
            "last_filing": "2026-03-31",
            "years_filed": 3,
            "estimated_liability_usd": 2500,
            "has_penalties": false
        }
        """
        data = json.loads(json_data) if isinstance(json_data, str) else json_data
        return TaxComplianceStatus(
            nif_registered=bool(data.get("nif")),
            tax_filing_status=data.get("filing_status", "non_filing"),
            last_filing_date=data.get("last_filing"),
            years_filed=int(data.get("years_filed", 0)),
            estimated_tax_liability_usd=float(data.get("estimated_liability_usd", 0)),
            has_penalties=bool(data.get("has_penalties", False)),
            jurisdiction=data.get("jurisdiction", ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation Agent
# ─────────────────────────────────────────────────────────────────────────────


class DataAggregationAgent:
    """Data Aggregation Agent — ETL pipeline for MSME business data.

    Ingests raw financial documents and produces a unified BusinessProfile
    ready for credit scoring by CreditProfileGenerator.

    Input methods accept raw file content (strings), so the agent can be
    called from:
      - CLI: file paths
      - API: uploaded files
      - Voice: transcribed descriptions (mock data)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def build_profile(
        self,
        *,
        business_id: str,
        business_name: str,
        jurisdiction: str,
        sector: Optional[Dict[str, str]] = None,
        pos_csv_content: Optional[str] = None,
        invoice_data: Optional[str] = None,
        invoice_format: str = "json",
        bank_statement_csv: Optional[str] = None,
        tax_data: Optional[str] = None,
        tax_format: str = "json",
        operating_months: Optional[int] = None,
    ) -> BusinessProfile:
        """Build a unified BusinessProfile from raw data sources.

        Each input is optional — the profile will note which sources
        were provided (data_completeness score).
        """
        data_sources: List[str] = []
        monthly_revenues: List[MonthlyRevenue] = []
        invoice_summary: Optional[InvoiceSummary] = None
        bank_metrics: Optional[BankStatementMetrics] = None
        tax_status: Optional[TaxComplianceStatus] = None
        source_files: Dict[str, str] = {}

        # 1. Parse POS/sales CSV
        if pos_csv_content:
            try:
                revenues = POSCSVParser.parse(pos_csv_content)
                monthly_revenues.extend(revenues)
                data_sources.append("pos_csv")
                source_files["pos_csv"] = "inline"
                logger.info("[DataAggregation] Parsed %d months of POS data", len(revenues))
            except Exception as exc:
                logger.warning("[DataAggregation] POS CSV parse failed: %s", exc)

        # 2. Parse invoice data
        if invoice_data:
            try:
                if invoice_format == "csv":
                    records, summary = InvoiceParser.parse_csv(invoice_data)
                else:
                    records, summary = InvoiceParser.parse_json(invoice_data)
                invoice_summary = summary
                data_sources.append("invoices")
                source_files["invoices"] = invoice_format
                logger.info("[DataAggregation] Parsed %d invoices", summary.invoice_count)
            except Exception as exc:
                logger.warning("[DataAggregation] Invoice parse failed: %s", exc)

        # 3. Parse bank statement
        if bank_statement_csv:
            try:
                bank_metrics = BankStatementParser.parse_csv(bank_statement_csv)
                data_sources.append("bank_statement")
                source_files["bank_statement"] = "csv"
                logger.info("[DataAggregation] Parsed %d months of bank data", bank_metrics.statement_months_analyzed)
            except Exception as exc:
                logger.warning("[DataAggregation] Bank statement parse failed: %s", exc)

        # 4. Parse tax data
        if tax_data:
            try:
                if tax_format == "json":
                    tax_status = TaxDocumentParser.parse_json(tax_data)
                data_sources.append("tax_document")
                source_files["tax"] = tax_format
                logger.info("[DataAggregation] Parsed tax data: %s", tax_status.tax_filing_status)
            except Exception as exc:
                logger.warning("[DataAggregation] Tax data parse failed: %s", exc)

        # 5. Derive financial metrics

        # Average monthly revenue
        if monthly_revenues:
            avg_rev = sum(r.total_revenue_usd for r in monthly_revenues) / len(monthly_revenues)
            estimated_annual = avg_rev * 12
        else:
            avg_rev = 0.0
            estimated_annual = 0.0

        # Revenue trend
        if len(monthly_revenues) >= 3:
            sorted_revs = sorted(monthly_revenues, key=lambda r: r.month)
            first_half = sum(r.total_revenue_usd for r in sorted_revs[:len(sorted_revs)//2])
            second_half = sum(r.total_revenue_usd for r in sorted_revs[len(sorted_revs)//2:])
            if second_half > first_half * 1.1:
                revenue_trend = "growing"
            elif second_half < first_half * 0.9:
                revenue_trend = "declining"
            else:
                revenue_trend = "stable"
        else:
            revenue_trend = "stable"

        # Cash flow stability score (0.0-1.0)
        stability_factors = []

        # From revenue volatility
        if len(monthly_revenues) >= 3:
            revs = [r.total_revenue_usd for r in monthly_revenues]
            if max(revs) > 0:
                cv = (max(revs) - min(revs)) / max(revs)
                stability_factors.append(max(0, 1.0 - cv))
        else:
            stability_factors.append(0.5)  # Neutral with limited data

        # From bank statement
        if bank_metrics:
            stability_factors.append(max(0, 1.0 - bank_metrics.deposit_volatility))
            stability_factors.append(1.0 if bank_metrics.nsf_count == 0 else max(0, 1.0 - bank_metrics.nsf_count * 0.2))

            if bank_metrics.cash_flow_pattern == "stable":
                stability_factors.append(1.0)
            elif bank_metrics.cash_flow_pattern == "seasonal":
                stability_factors.append(0.6)
            else:
                stability_factors.append(0.3)

        # From invoice aging
        if invoice_summary:
            stability_factors.append(max(0, 1.0 - invoice_summary.overdue_ratio))

        cash_flow_stability = sum(stability_factors) / len(stability_factors) if stability_factors else 0.5

        # Operating months (from revenue data or explicit)
        if operating_months is None:
            operating_months = len(monthly_revenues)
            if operating_months == 0:
                operating_months = 12  # Default assumption

        # Data completeness (0.0-1.0)
        possible_sources = 4  # POS, invoices, bank, tax
        completeness = len(data_sources) / possible_sources

        # Build sector
        sector_obj = BusinessSpecies()
        if sector:
            sector_obj.sector = sector.get("sector", "retail")
            sector_obj.sub_sector = sector.get("sub_sector", "")
            sector_obj.description = sector.get("description", "")

        profile = BusinessProfile(
            business_id=business_id,
            business_name=business_name,
            jurisdiction=jurisdiction,
            sector=sector_obj,
            operating_months=operating_months,
            monthly_revenues=monthly_revenues,
            avg_monthly_revenue_usd=round(avg_rev, 2),
            revenue_trend=revenue_trend,
            invoice_summary=invoice_summary,
            bank_metrics=bank_metrics,
            tax_status=tax_status,
            estimated_annual_revenue_usd=round(estimated_annual, 2),
            cash_flow_stability_score=round(cash_flow_stability, 3),
            data_completeness=round(completeness, 2),
            data_sources=data_sources,
            source_files=source_files,
        )

        logger.info(
            "[DataAggregation] Profile built for %s (%s): "
            "rev=$%.0f/yr, stability=%.2f, completeness=%.0f%%",
            business_name, jurisdiction, estimated_annual, cash_flow_stability, completeness * 100,
        )
        return profile

    # ─────────────────────────────────────────────────────────────────────────
    # Mock Data Generation (Buildathon)
    # ─────────────────────────────────────────────────────────────────────────

    def generate_mock_pos_csv(self, months: int = 12, avg_monthly_revenue: float = 15000) -> str:
        """Generate mock POS CSV data for testing."""
        lines = ["date,amount,transaction_id,customer_id,item,category"]
        now = datetime.now(timezone.utc)

        for m in range(months):
            month_dt = now - timedelta(days=30 * (months - m))
            days_in_month = 30 if month_dt.month != 2 else 28

            # Monthly revenue with some randomness
            monthly_target = avg_monthly_revenue * random.uniform(0.7, 1.3)
            daily_target = monthly_target / days_in_month
            transactions_per_day = random.randint(3, 20)

            for d in range(days_in_month):
                day_dt = month_dt.replace(day=min(d + 1, 28))
                date_str = day_dt.strftime("%Y-%m-%d")

                for t in range(transactions_per_day):
                    amount = daily_target / transactions_per_day * random.uniform(0.5, 2.0)
                    tx_id = f"TX-{date_str}-{t:03d}"
                    cust_id = f"CUST-{random.randint(1, 50):03d}"
                    items = ["produce", "dairy", "beverages", "dry_goods", "household"]
                    item = random.choice(items)
                    lines.append(f"{date_str},{amount:.2f},{tx_id},{cust_id},{item},{item}")

        return "\n".join(lines)

    def generate_mock_invoices(self, count: int = 20) -> str:
        """Generate mock invoice JSON for testing."""
        invoices = []
        now = datetime.now(timezone.utc)

        counterparties = [
            ("HT Distributors", "receivable"),
            ("JM Retail Ltd", "receivable"),
            ("BB Supplies Co", "receivable"),
            ("TT Wholesale", "payable"),
            ("US Imports Inc", "payable"),
        ]

        statuses = ["paid", "paid", "paid", "pending", "overdue"]

        for i in range(count):
            cp, inv_type = random.choice(counterparties)
            amount = random.uniform(500, 15000)
            days_ago_issued = random.randint(15, 180)
            issued = (now - timedelta(days=days_ago_issued)).strftime("%Y-%m-%d")
            due = (now - timedelta(days=days_ago_issued - 30)).strftime("%Y-%m-%d")
            status = random.choice(statuses)

            inv = {
                "id": f"INV-{i+1:04d}",
                "type": inv_type,
                "counterparty": cp,
                "amount_usd": round(amount, 2),
                "issued": issued,
                "due": due,
                "status": status,
            }

            if status == "paid":
                paid = (now - timedelta(days=random.randint(1, days_ago_issued - 10))).strftime("%Y-%m-%d")
                inv["paid_date"] = paid

            invoices.append(inv)

        return json.dumps({"invoices": invoices}, indent=2)

    def generate_mock_bank_statement(self, months: int = 6, avg_deposit: float = 20000) -> str:
        """Generate mock bank statement CSV for testing."""
        lines = ["date,description,deposit,withdrawal,balance"]
        now = datetime.now(timezone.utc)
        balance = random.uniform(5000, 15000)

        for m in range(months):
            month_dt = now - timedelta(days=30 * (months - m))
            days_in_month = 30

            # 3-8 transactions per month
            for _ in range(random.randint(3, 8)):
                day = random.randint(1, days_in_month)
                day_dt = month_dt.replace(day=min(day, 28))
                date_str = day_dt.strftime("%Y-%m-%d")

                if random.random() < 0.6:  # Deposit
                    amount = random.uniform(avg_deposit * 0.3, avg_deposit * 1.5)
                    desc = random.choice(["Sales deposit", "Wire transfer", "Check deposit", "Card settlement"])
                    balance += amount
                    lines.append(f"{date_str},{desc},{amount:.2f},,{balance:.2f}")
                else:  # Withdrawal
                    amount = random.uniform(100, avg_deposit * 0.5)
                    desc = random.choice(["Supplier payment", "Payroll", "Rent", "Utilities", "Inventory"])
                    balance -= amount
                    if balance < 0:
                        balance = 0  # Simulate NSF floor
                    lines.append(f"{date_str},{desc},,{amount:.2f},{balance:.2f}")

        return "\n".join(lines)

    def generate_mock_tax_data(self, jurisdiction: str = "HT") -> str:
        """Generate mock tax compliance JSON."""
        data = {
            "nif": f"{random.randint(100, 999)}-{random.randint(100, 999)}-{random.randint(100, 999)}",
            "jurisdiction": jurisdiction,
            "filing_status": random.choice(["compliant", "compliant", "compliant", "non_filing"]),
            "last_filing": (datetime.now(timezone.utc) - timedelta(days=random.randint(30, 365))).strftime("%Y-%m-%d"),
            "years_filed": random.randint(1, 5),
            "estimated_liability_usd": round(random.uniform(500, 5000), 2),
            "has_penalties": random.random() < 0.1,
        }
        return json.dumps(data, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# Quick test / demo
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = DataAggregationAgent()

    # Generate mock data
    pos_csv = agent.generate_mock_pos_csv(months=6, avg_monthly_revenue=12000)
    invoices = agent.generate_mock_invoices(count=15)
    bank_stmt = agent.generate_mock_bank_statement(months=6, avg_deposit=15000)
    tax_data = agent.generate_mock_tax_data("HT")

    # Build profile
    profile = agent.build_profile(
        business_id="ht_artisan_001",
        business_name="Atelier Kreyol Artisans",
        jurisdiction="HT",
        sector={"sector": "retail", "sub_sector": "handicrafts", "description": "Haitian artisan collective"},
        pos_csv_content=pos_csv,
        invoice_data=invoices,
        bank_statement_csv=bank_stmt,
        tax_data=tax_data,
    )

    print(f"\n{'='*60}")
    print(f"Business Profile: {profile.business_name}")
    print(f"{'='*60}")
    print(f"  ID: {profile.business_id}")
    print(f"  Jurisdiction: {profile.jurisdiction}")
    print(f"  Sector: {profile.sector.sector}/{profile.sector.sub_sector}")
    print(f"  Operating: {profile.operating_months} months")
    print(f"  Avg Monthly Revenue: ${profile.avg_monthly_revenue_usd:,.2f}")
    print(f"  Estimated Annual: ${profile.estimated_annual_revenue_usd:,.2f}")
    print(f"  Revenue Trend: {profile.revenue_trend}")
    print(f"  Cash Flow Stability: {profile.cash_flow_stability_score:.2f}")
    print(f"  Data Completeness: {profile.data_completeness:.0%}")
    print(f"  Data Sources: {profile.data_sources}")

    if profile.invoice_summary:
        inv = profile.invoice_summary
        print(f"\n  Invoices: {inv.invoice_count} total")
        print(f"    Receivables: ${inv.total_receivables_usd:,.2f}")
        print(f"    Payables: ${inv.total_payables_usd:,.2f}")
        print(f"    Overdue Ratio: {inv.overdue_ratio:.1%}")
        print(f"    Avg Collection: {inv.avg_collection_period_days:.0f} days")

    if profile.bank_metrics:
        bm = profile.bank_metrics
        print(f"\n  Bank Statement ({bm.statement_months_analyzed} months):")
        print(f"    Avg Deposits: ${bm.avg_monthly_deposits_usd:,.2f}/mo")
        print(f"    Min Balance: ${bm.min_balance_3mo_usd:,.2f}")
        print(f"    Pattern: {bm.cash_flow_pattern}")
        print(f"    NSF Count: {bm.nsf_count}")

    if profile.tax_status:
        tx = profile.tax_status
        print(f"\n  Tax Status: {tx.tax_filing_status}")
        print(f"    NIF Registered: {tx.nif_registered}")
        print(f"    Years Filed: {tx.years_filed}")
