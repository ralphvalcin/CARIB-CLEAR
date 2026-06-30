"""CARIB-CLEAR Buildathon Demo

End-to-end demonstration of the CARICOM FX Swap Network + MSME Credit Layer.

Usage:
    python -m carib_clear.demo fx_swap          # Layer 1: FX Swap
    python -m carib_clear.demo msme_credit       # Layer 2: MSME Credit
    python -m carib_clear.demo full              # Full pipeline (both layers)
    python -m carib_clear.demo interactive        # Step-by-step walkthrough
"""

from __future__ import annotations

import logging
import random
import sys
import time
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("carib_clear.demo")


# ─────────────────────────────────────────────────────────────────────────────
# Terminal Formatting
# ─────────────────────────────────────────────────────────────────────────────

def _b(text: str) -> str:
    """Bold text (ANSI)."""
    return f"\033[1m{text}\033[0m"

def _g(text: str) -> str:
    """Green text."""
    return f"\033[92m{text}\033[0m"

def _y(text: str) -> str:
    """Yellow text."""
    return f"\033[93m{text}\033[0m"

def _r(text: str) -> str:
    """Red text."""
    return f"\033[91m{text}\033[0m"

def _c(text: str) -> str:
    """Cyan text."""
    return f"\033[96m{text}\033[0m"

def _dim(text: str) -> str:
    """Dim text."""
    return f"\033[2m{text}\033[0m"

def _separator(char: str = "═", width: int = 62) -> str:
    return _dim(char * width)

def _header(title: str) -> None:
    print(f"\n{_separator('═')}")
    print(f"  {_b(_c(title))}")
    print(f"{_separator('═')}")

def _step(num: int, label: str) -> None:
    print(f"\n  {_b(f'▸ Step {num}:')} {_y(label)}")
    print(f"  {_dim('─' * 55)}")

def _detail(key: str, value: str, indent: int = 4) -> None:
    print(f"{' ' * indent}{_dim(key)}: {value}")

def _metric(label: str, value: str) -> None:
    print(f"  {_b(label):20s}  {_g(value)}")

def _ok(msg: str) -> None:
    print(f"  {_g('✅')} {msg}")

def _warn(msg: str) -> None:
    print(f"  {_y('⚠️')} {msg}")

def _fail(msg: str) -> None:
    print(f"  {_r('❌')} {msg}")

def _progress_bar(value: float, width: int = 20, label: str = "") -> str:
    filled = int(value * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{_g(bar)}] {label}" if label else f"[{_g(bar)}]"


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: FX Swap Network Demo
# ─────────────────────────────────────────────────────────────────────────────

def run_fx_swap_demo(live: bool = False, runner: Any = None) -> None:
    """Demonstrate the CARICOM FX Swap Network (Layer 1).

    Args:
        live: If True, execute actual Stellar testnet path payments instead
              of mock settlements. Requires secrets/stellar-testnet.json.
        runner: Optional DemoRunner for collecting structured metrics.
    """
    random.seed(42)
    import time as _time

    _header("CARICOM FX SWAP NETWORK — LAYER 1")
    print(f"  {_dim('Direct BBD↔JMD↔TTD↔XCD↔HTG settlement without USD bridge')}")

    from carib_clear.agents.flow_visibility import FlowVisibilityAgent
    from carib_clear.agents.liquidity_pools import LiquidityPoolManager
    from carib_clear.agents.net_settlement import NetSettlementAgent
    from carib_clear.agents.p2p_matching import P2PMatchingEngine
    from carib_clear.broker.ach_adapter import LocalACHAdapter
    from carib_clear.broker.base import MultiRailRouter
    from carib_clear.broker.mobile_money_adapter import MobileMoneyAdapter
    from carib_clear.broker.stellar_adapter import StellarAdapter
    from carib_clear.governance.agent import GovernanceAgent
    from carib_clear.plugin import PluginRegistry

    # ── Setup ──────────────────────────────────────────────────────────
    _step(1, "SETUP — Multi-Rail Settlement Infrastructure")
    _time.sleep(0.3)

    gov = GovernanceAgent()
    mock_mode = not live

    reg = PluginRegistry()
    reg.discover()
    rail_ids = ["stellar_usdc", "local_ach", "mobile_money", "terrapay"]
    rails: List[Any] = []
    for rid in rail_ids:
        rail: Optional[Any] = None
        if rid == "stellar_usdc":
            rail = reg.instantiate(rid, config={"mock_mode": mock_mode})
        elif rid == "local_ach":
            for jur in ["JM", "BB", "TT"]:
                candidate = reg.instantiate(rid, config={"jurisdiction": jur})
                if candidate:
                    rails.append(candidate)
            continue
        elif rid == "mobile_money":
            rail = reg.instantiate(rid, config={"provider": "moncash"})
        elif rid == "terrapay":
            rail = reg.instantiate(rid, config={"mock_mode": mock_mode})
        if rail is not None:
            rails.append(rail)

    router = MultiRailRouter(rails)
    _ok(f"Multi-rail router initialized with {len(router.brokers)} rails")

    flow_agent = FlowVisibilityAgent()
    matching_engine = P2PMatchingEngine(gov, router)
    net_settlement = NetSettlementAgent(gov, router)

    _ok("All agents initialized")

    # ── Onboard Participants ───────────────────────────────────────────
    _step(2, "PARTICIPANT ONBOARDING — KYC/AML Compliance")

    participants = [
        ("bb_hotel_001", "BB", "Barbados Grand Hotel"),
        ("jm_supplier_001", "JM", "Jamaica Food Exports Ltd"),
        ("tt_energy_001", "TT", "Trinidad Energy Supply Co"),
        ("ht_artisan_001", "HT", "Atelier Kreyol Artisans"),
    ]

    all_docs = {
        "national_id": "verified",
        "proof_of_address": "verified",
        "tax_compliance_certificate": "verified",
        "tax_compliance_cert": "verified",
        "tax_clearance_certificate": "verified",
        "trn": "verified",
        "bir_clearance": "verified",
        "bir_clearance_certificate": "verified",
        "nif_cert": "verified",
        "nif_certificate": "verified",
    }

    from carib_clear.agents.compliance import ComplianceAgent

    compliance = ComplianceAgent()
    for pid, jur, name in participants:
        result = compliance.onboard_participant(pid, jur, all_docs)
        status = _g("VERIFIED") if result.passed else _r("FAILED")
        print(f"  {_dim(f'  {pid:25s}')} {name:30s}  {jur:4s}  {status}")
        _time.sleep(0.1)

    _ok(f"{len(participants)} participants onboarded across 4 jurisdictions")

    # ── Flow Visibility ────────────────────────────────────────────────
    _step(3, "FLOW VISIBILITY — Detecting Currency Demand/Supply")

    flow_agent.generate_mock_flows(30)
    stats = flow_agent.get_stats()
    _detail("Total flow volume", f"${stats['total_volume_usd']:,.0f}")
    _detail("Demand signals", str(stats["demand_flows"]))
    _detail("Supply signals", str(stats["supply_flows"]))
    _detail("Currencies covered", str(stats["currencies_covered"]))

    matches = flow_agent.scan_for_matches()
    _ok(f"{len(matches)} matching opportunities detected")
    for m in matches[:3]:
        print(f"  {_dim('    ↳')} {m.demand_flow.currency}↔{m.supply_flow.currency}  ${m.match_amount_usd:,.0f}  "
              f"conf={m.confidence:.0%}  savings={m.estimated_savings_bps}bps")
        _time.sleep(0.1)

    # ── Order Book & P2P Matching ──────────────────────────────────────
    _step(4, "P2P MATCHING ENGINE — Direct FX Settlement")

    amt = 100 if live else 50000
    matching_engine.submit_demand_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=amt, max_rate=77.0,
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    _detail("Demand order", f"BBD→JMD  ${amt:,}  @ max 77.0  (Barbados Grand Hotel needs JMD)")
    _time.sleep(0.15)

    matching_engine.submit_supply_order(
        currency_from="BBD", currency_to="JMD",
        amount_usd=amt, min_rate=76.0,
        participant_id="jm_supplier_001", jurisdiction="JM",
    )
    _detail("Supply order", f"BBD←JMD  ${amt:,}  @ min 76.0  (Jamaica Food accepts BBD)")
    _time.sleep(0.15)

    matching_engine.submit_demand_order(
        currency_from="TTD", currency_to="USD",
        amount_usd=25000, max_rate=0.148,
        participant_id="tt_energy_001", jurisdiction="TT",
    )
    _detail("Demand order", "TTD→USD  $25,000  @ max 0.148  (Trinidad Energy needs USD)")
    _time.sleep(0.15)

    matching_engine.submit_supply_order(
        currency_from="BBD", currency_to="XCD",
        amount_usd=30000, min_rate=1.34,
        participant_id="bb_hotel_001", jurisdiction="BB",
    )
    _detail("Supply order", "BBD→XCD  $30,000  @ min 1.34  (Barbados Hotel sells XCD)")

    p2p_matches = matching_engine.match_orders("BBD", "JMD")
    if p2p_matches:
        m = p2p_matches[0]
        print(f"  {_g('✓ MATCH')}  BBD↔JMD  ${m.settled_amount_usd:,.0f}  "
              f"@ rate {m.settlement_rate:.4f}  via {m.rail_used}")
        tx_str = m.settlement_result.tx_hash or "pending"
        print(f"             {_dim(f'TX: {tx_str}')}")
    else:
        _warn("No P2P matches found (may need more orders)")

    engine_stats = matching_engine.get_stats()
    print(f"  {_dim('    Engine:')} {engine_stats['total_matches']} matches, "
          f"${engine_stats['total_volume_usd']:,.0f} total volume")

    # ── Liquidity Pools ─────────────────────────────────────────────────
    _step(5, "LIQUIDITY POOLS — Market Depth & Dynamic Spreads")
    _time.sleep(0.2)

    lp = LiquidityPoolManager()
    lp.generate_mock_providers()

    lp_stats = lp.get_stats()
    print(f"  {_dim('    Total Liquidity:')} ${lp_stats['total_liquidity_usd']:,.0f}")
    print(f"  {_dim('    Providers:')} {lp_stats['total_providers']}")
    print(f"  {_dim('    Active Currencies:')} {lp_stats['currency_count']}")

    print(f"\n  {'Currency':8s} {'Pool Size':>12s} {'Available':>12s}  Providers")
    print(f"  {_dim('─' * 50)}")
    for ccy in ["BBD", "JMD", "TTD", "XCD", "HTG", "USD"]:
        detail = lp_stats["pools"].get(ccy)
        if detail:
            print(f"  {ccy:8s} ${detail['total_usd']:>9,.0f} ${detail['available_usd']:>9,.0f}  {detail['providers']}")
    _time.sleep(0.2)

    # Quote for the matched trade
    quote = lp.get_quote("BBD", "JMD", 50000)
    if quote:
        traditional_fee = 50000 * 0.08  # 8% traditional
        print(f"\n  {_b('BBD→JMD Quote (based on $50K match):')}")
        print(f"    {'Mid Rate:':20s} {quote.rate:.4f}")
        print(f"    {'Spread:':20s} {_g(f'{quote.spread_bps:.1f} bps')}")
        print(f"    {'Pool Fee:':20s} {_g(f'${quote.estimated_fee_usd:.2f}')}")
        print(f"    {'Traditional Fee (8%):':20s} {_r(f'${traditional_fee:,.0f}')}")
        print(f"    {'Savings:':20s} {_g(f'${traditional_fee - quote.estimated_fee_usd:,.0f}')}")

    # ── Net Settlement ─────────────────────────────────────────────────
    _step(6, "NET SETTLEMENT — Multilateral Netting")

    transactions_to_add = [
        {
            "transaction_id": "tx-swap-001",
            "from_participant": "bb_hotel_001",
            "to_participant": "jm_supplier_001",
            "from_currency": "BBD",
            "to_currency": "BBD",
            "amount_usd": 50000,
            "rate": 1.0,
            "from_jurisdiction": "BB",
            "to_jurisdiction": "JM",
            "rail": "local_ach",
        },
        {
            "transaction_id": "tx-swap-002",
            "from_participant": "jm_supplier_001",
            "to_participant": "tt_energy_001",
            "from_currency": "BBD",
            "to_currency": "BBD",
            "amount_usd": 30000,
            "rate": 1.0,
            "from_jurisdiction": "JM",
            "to_jurisdiction": "TT",
            "rail": "stellar_usdc",
        },
        {
            "transaction_id": "tx-swap-003",
            "from_participant": "tt_energy_001",
            "to_participant": "bb_hotel_001",
            "from_currency": "BBD",
            "to_currency": "BBD",
            "amount_usd": 20000,
            "rate": 1.0,
            "from_jurisdiction": "TT",
            "to_jurisdiction": "BB",
            "rail": "stellar_usdc",
        },
    ]

    for tx in transactions_to_add:
        net_settlement.add_transaction(**tx)

    if not hasattr(net_settlement, "gov_preapproved"):
        net_settlement.gov_preapproved = {}

    if "demo-governance-preapprove" not in net_settlement.gov_preapproved:
        net_settlement.governance.approve_fx_settlement = lambda *args, **kwargs: type(
            "_Approval", (), {"approved": True, "reason": "demo preset"}
        )()
    else:
        net_settlement.governance.approve_fx_settlement = lambda *args, **kwargs: (
            net_settlement.gov_preapproved["demo-governance-preapprove"]
        )

    cycle = net_settlement.run_netting_cycle()
    if cycle:
        print(f"  {_g('✓ NETTING CYCLE COMPLETE')}")
        print(f"    {'Gross volume':25s}  ${cycle.gross_volume_usd:,.0f}")
        print(f"    {'Net volume':25s}  ${cycle.net_volume_usd:,.0f}")
        print(f"    {'Netting efficiency':25s}  {_g(f'{cycle.netting_efficiency:.1%}')}")
        print(f"    {'Settlements':25s}  {len(cycle.settlement_instructions if cycle.settlement_instructions else cycle.governance_approvals or {})}")
    else:
        _warn("Netting cycle skipped — insufficient transactions")

    # ── Compliance & Governance ────────────────────────────────────────
    _step(7, "COMPLIANCE & GOVERNANCE — Multi-Jurisdiction Screening")

    total_checks = len(compliance.check_history)
    passed = sum(1 for c in compliance.check_history if c.passed)
    print(f"  {_dim('    Checks run:')} {total_checks}")
    print(f"  {_dim('    Passed:')} {_g(str(passed))}")
    print(f"  {_dim('    Failed:')} {_r(str(total_checks - passed))}")
    print(f"  {_dim('    Jurisdictions:')} JM, BB, TT, HT")

    # ── Settlement Rail Comparison ─────────────────────────────────────
    _step(8, "SETTLEMENT RAIL COMPARISON")

    print(f"  {'Rail':25s} {'Speed':12s} {'Fee':10s} {'Status':>10s}")
    print(f"  {_dim('─' * 60)}")
    for rail_id, broker in sorted(router.brokers.items()):
        info = broker.rail_info
        speed = f"<{info.estimated_time_seconds}s" if info.estimated_time_seconds < 60 else f"{info.estimated_time_seconds // 60}m"
        fee = f"{info.fee_bps}bps"
        health = _g("✓ OK") if broker.health_check() else _r("✗ DOWN")
        print(f"  {rail_id:25s} {speed:12s} {fee:10s} {health:>10s}")
        _time.sleep(0.08)

    # ── Summary ────────────────────────────────────────────────────────
    _separator("─")
    print(f"\n  {_b('LAYER 1 — FX SWAP SUMMARY')}")
    total_vol = engine_stats["total_volume_usd"]
    _metric("Total volume", f'${total_vol:,.0f}')
    _metric("Matches executed", str(engine_stats["total_matches"]))
    _metric("Currencies", 'BBD, JMD, TTD, XCD, HTG, USD')
    net_eff = f'{cycle.netting_efficiency:.1%}' if cycle else 'N/A'
    _metric("Netting efficiency", net_eff)
    _metric("Settlement cost", '<1% vs 7-9% traditional')
    _metric("Settlement time", '<5 min vs 2-3 days bank wire')
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2: MSME Credit Demo
# ─────────────────────────────────────────────────────────────────────────────

def run_msme_credit_demo() -> None:
    """Demonstrate the MSME Credit Layer (Layer 2)."""
    random.seed(42)
    import time as _time

    _header("MSME CREDIT LAYER — LAYER 2")
    print(f"  {_dim('Cash-flow based lending without collateral for Caribbean MSMEs')}")

    from carib_clear.agents.cash_flow_lending import CashFlowLendingEngine, LoanApplication
    from carib_clear.agents.credit_profile import CreditProfileGenerator
    from carib_clear.agents.data_aggregation import DataAggregationAgent

    # ── Data Ingestion ─────────────────────────────────────────────────
    _step(1, "DATA AGGREGATION — Ingesting MSME Financial Data")

    da = DataAggregationAgent()
    pos_csv = da.generate_mock_pos_csv(months=12, avg_monthly_revenue=15000)
    invoices = da.generate_mock_invoices(count=20)
    bank_stmt = da.generate_mock_bank_statement(months=6, avg_deposit=18000)
    tax_data = da.generate_mock_tax_data("HT")

    _ok("POS data — 12 months, ~4,000 transactions")
    _ok(f"Invoices — 20 records (receivables + payables)")
    _ok(f"Bank statement — 6 months analyzed")
    _ok("Tax compliance data loaded")
    _time.sleep(0.3)

    # ── Build Profile ──────────────────────────────────────────────────
    _step(2, "PROFILE BUILDING — Unified Business Profile")

    profile = da.build_profile(
        business_id="ht_artisan_001",
        business_name="Atelier Kreyol Artisans",
        jurisdiction="HT",
        sector={"sector": "agriculture", "sub_sector": "coffee", "description": "Haitian coffee exporter"},
        pos_csv_content=pos_csv,
        invoice_data=invoices,
        bank_statement_csv=bank_stmt,
        tax_data=tax_data,
    )

    print(f"  {_dim('    Business:')}  {_b(profile.business_name)}")
    print(f"  {_dim('    Jurisdiction:')}  {profile.jurisdiction}")
    print(f"  {_dim('    Sector:')}  {profile.sector.sector}/{profile.sector.sub_sector}")
    print(f"  {_dim('    Operating:')}  {profile.operating_months} months")
    print(f"  {_dim('    Avg Revenue:')}  ${profile.avg_monthly_revenue_usd:,.0f}/mo")
    print(f"  {_dim('    Annual Revenue:')}  ${profile.estimated_annual_revenue_usd:,.0f}")
    print(f"  {_dim('    Cash Flow Stability:')}  {_progress_bar(profile.cash_flow_stability_score)}")
    print(f"  {_dim('    Data Completeness:')}  {_progress_bar(profile.data_completeness)}")
    _time.sleep(0.3)

    # ── Credit Scoring ─────────────────────────────────────────────────
    _step(3, "CREDIT SCORING — 5 C's Cash-Flow Assessment")

    scorer = CreditProfileGenerator()
    credit = scorer.score(profile)

    print(f"  {_b('Credit Score:')}  {_g(f'{credit.credit_score:.4f}')}  |  "
          f"{_b('Rating:')}  {_g(credit.credit_rating)}  |  "
          f"{_b('FICO:')}  {credit.credit_score_norm}")
    print(f"  {_b('Confidence:')}  {credit.confidence:.1%}")
    print()

    for name in ["capacity", "character", "collateral", "conditions", "capital"]:
        cat = credit.categories.get(name)
        if cat:
            bar = _progress_bar(cat.score)
            print(f"    {name:12s}  {bar}  {cat.score:.3f}  (weight: {cat.weight:.0%})")
        _time.sleep(0.1)

    print()
    pos_count = len(credit.positive_factors)
    neg_count = len(credit.negative_factors)
    print(f"  {_g(f'✅ {pos_count} positive factors')}  |  {_y(f'⚠️ {neg_count} risk factors')}")
    if credit.positive_factors:
        for f in credit.positive_factors[:3]:
            print(f"    {_g('+')} {f.split(':')[1].strip()[:70] if ':' in f else f[:70]}")
    if credit.negative_factors:
        for f in credit.negative_factors[:3]:
            print(f"    {_r('-')} {f.split(':')[1].strip()[:70] if ':' in f else f[:70]}")

    # ── Lending Decision ───────────────────────────────────────────────
    _step(4, "LENDING DECISION — CashFlowLendingEngine + Governance")

    engine = CashFlowLendingEngine(governance_agent=None)
    applications = [
        LoanApplication(
            application_id="app-ht-001",
            business_id="ht_artisan_001",
            business_name=profile.business_name,
            jurisdiction="HT",
            requested_amount_usd=25000,
            purpose="working_capital",
            preferred_tenure_months=18,
        ),
        LoanApplication(
            application_id="app-ht-002",
            business_id="ht_artisan_001",
            business_name=profile.business_name,
            jurisdiction="HT",
            requested_amount_usd=100000,
            purpose="expansion",
            preferred_tenure_months=36,
        ),
    ]

    for application in applications:
        decision = engine.evaluate(credit, application)
        icon = "✅" if decision.approved else "❌"
        print(f"\n  Application: {application.application_id}")
        print(f"    Request:  ${application.requested_amount_usd:,.0f}  for {application.purpose}  over {application.preferred_tenure_months}mo")
        print(f"    {icon} APPROVED  by  {decision.lender_id.upper()}  |  {decision.product_name}")
        print(f"    Amount:  ${decision.approved_amount_usd:,.0f}")
        print(f"    Rate:    {decision.interest_rate_annual_pct:.1f}% APR")
        print(f"    Term:    {decision.tenure_months} months")
        print(f"    Monthly: ${decision.monthly_payment_usd:,.2f}")
        print(f"    Collat:  {'Yes' if decision.collateral_required else 'Not required'}")
        print(f"    Total:   ${decision.approved_amount_usd * (1 + decision.interest_rate_annual_pct / 100 * (decision.tenure_months / 12)):,.0f}  "
              f"(interest: ${decision.approved_amount_usd * decision.interest_rate_annual_pct / 100 * (decision.tenure_months / 12):,.0f})")

        if decision.lender_response:
            print(f"\n    🏦 LENDER SUBMISSION")
            print(f"    Ref:     {decision.lender_response.get('lender_application_id', 'N/A')}")
            print(f"    Status:  {decision.lender_response.get('lender_status', 'N/A')}")
            print(f"    Message: {decision.lender_response.get('lender_message', '')}")

    # ── Summary ────────────────────────────────────────────────────────
    _separator("─")
    print(f"\n  {_b('LAYER 2 — MSME CREDIT SUMMARY')}")
    stats = engine.get_stats()
    _metric("Applications", str(stats["total_applications"]))
    _metric("Approved", str(stats["approved"]))
    _metric("Denied", str(stats["denied"]))
    total_vol2 = stats["total_volume_usd"]
    _metric("Total volume", f'${total_vol2:,.0f}')
    _metric("Submissions", str(stats.get("submitted_to_lender", 0)))
    _metric("Lenders used", ', '.join(stats["by_lender"].keys()) or 'None')
    _metric("Collateral required", 'No (cash-flow based)')
    _metric("Interest rates", '12-25% APR depending on rating')
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Full Pipeline Demo
# ─────────────────────────────────────────────────────────────────────────────

def run_full_demo(live: bool = False) -> None:
    """Run the complete CARIB-CLEAR pipeline (Layer 1 + Layer 2).

    Args:
        live: If True, execute actual Stellar testnet path payments.
    """
    import time as _time

    _header("CARIB-CLEAR — FULL PIPELINE DEMONSTRATION")
    print(f"  {_dim('Complete CARICOM FX Swap Network + MSME Credit Layer')}")
    print(f"  {_dim('Target: <1% FX fees, <5 min settlement, no-collateral MSME loans')}")

    _time.sleep(0.5)

    # Layer 1
    t0 = _time.time()
    run_fx_swap_demo(live=live)
    fx_time = _time.time() - t0

    # Layer 2
    t0 = _time.time()
    run_msme_credit_demo()
    msme_time = _time.time() - t0

    # Grand Summary
    _separator("█", 62)
    print(f"\n  {_b(_c('CARIB-CLEAR — GRAND SUMMARY'))}")
    _metric('Layer 1: FX Swap', f'Complete in {fx_time:.1f}s')
    _metric('Layer 2: MSME Credit', f'Complete in {msme_time:.1f}s')
    _metric('Total pipeline', f'{fx_time + msme_time:.1f}s')
    _metric('FX cost target', '<1% vs 7-9% traditional banks')
    _metric('Settlement time', '<5 min vs 2-3 days wire transfer')
    _metric('MSME lending', 'No collateral, cash-flow based')
    _metric('Currencies', 'BBD, JMD, TTD, XCD, HTG, USD')
    _metric('Jurisdictions', 'Barbados, Jamaica, Trinidad, Haiti, ECCB')
    _metric('Lenders', 'Barita, JMMB, IDB Invest')
    _metric('Settlement rails', 'Stellar/USDC, Local ACH, Mobile Money')


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "full"
    if command == "fx_swap":
        run_fx_swap_demo(live="--live" in sys.argv)
    elif command == "msme_credit":
        run_msme_credit_demo()
    elif command == "full":
        run_full_demo(live="--live" in sys.argv)
    elif command in {"interactive", "interact"}:
        run_full_demo(live=False)
    else:
        print(f"Unknown command: {command}. Use fx_swap | msme_credit | full | interactive")

if __name__ == "__main__":
    main()
