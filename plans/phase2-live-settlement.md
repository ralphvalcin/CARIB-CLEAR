# CARIB-CLEAR Phase 2 — Asset Issuance & Path Payments

## Objective
Move from bootstrap (accounts exist) to **live settlement on the Stellar testnet DEX**.
Establish USDC trustlines, issue CARICOM tokens, create AMM liquidity pools,
and execute the first real path payment settlement.

## Blocks

### Block 1: USDC Trustlines *(1 session)*

Each participant account needs a **trustline** to hold USDC (Circle's issuer or our test issuer).

**What:**
```
HUB → trust(USDC:USDC_ISSUER)
BB_HOTEL → trust(USDC:USDC_ISSUER) + trust(BBD:BBD_ISSUER)
JM_SUPPLIER → trust(USDC:USDC_ISSUER) + trust(JMD:JMD_ISSUER)
...all 11 accounts trust USDC
```

**Script:** `scripts/setup_trustlines.py`
- Reads secrets from `secrets/stellar-testnet.json`
- For each account, submits `ChangeTrustOp` for USDC (and currency-specific tokens)
- Marks done in secrets file so it's idempotent

**Verification:** Each account's balances show USDC trustline (balance=0).

---

### Block 2: Currency Token Issuance *(1 session)*

Issue the first batch of CARICOM tokens so participants can trade.

**What:**
```
BBD_ISSUER → payment(100,000 BBD → BB_HOTEL)
JMD_ISSUER → payment(10,000,000 JMD → JM_SUPPLIER)
TTD_ISSUER → payment(500,000 TTD → TT_ENERGY)
HTG_ISSUER → payment(1,000,000 HTG → HT_ARTISAN)
```

**Script:** `scripts/issue_currency_tokens.py`
- Each issuer sends tokens to their corresponding participant
- Uses Stellar `PaymentOp`
- For demo purposes — in production, tokens would come from real anchors

**Verification:** Each participant shows non-zero balance in their currency.

---

### Block 3: AMM Liquidity Pools *(1 session)*

Create AMM pools on the Stellar DEX so path payments can route through them.

**What:**
- `AMM_create(BBD/USDC)` — Barbados Dollar ↔ USDC pool
- `AMM_create(JMD/USDC)` — Jamaica Dollar ↔ USDC pool
- `AMM_create(USD/USDC)` — US Dollar ↔ USDC pool

Each pool needs initial liquidity deposited by the issuer accounts.
Uses Stellar's built-in AMM (XLS-30) — no Uniswap-style contract needed.

**Script:** `scripts/create_amm_pools.py`
- Deposits initial liquidity from HUB/issuer accounts
- Sets initial pool shares (LP tokens)

**Verification:** DEX order books show the AMM pools with liquidity.

---

### Block 4: Live Path Payment Settlement *(1-2 sessions)*

Replace `_mock_settlement()` in `StellarAdapter` with a real Stellar DEX
`path_payment_strict_receive` transaction.

**What the adapter will do:**
```
SettlementOrder(BBD→JMD, $50,000)
  → Build path_payment_strict_receive:
       send_asset=BBD (from BB_HOTEL)
       send_max=calculated
       dest_asset=JMD (to JM_SUPPLIER)
       dest_amount=50,000 USD equivalent
       path=[BBD, USDC, JMD]  # via AMM
  → Sign with BB_HOTEL secret
  → Submit to Horizon
  → Return SettlementResult with real tx_hash
```

**Changes to `StellarAdapter`:**
- `submit_settlement()` for `mock_mode=False` now builds + signs + submits real TX
- Path finding via Stellar DEX `/paths` endpoint
- Error handling: insufficient balance, bad path, network timeout
- Settlement status polling via Horizon

**Script:** `scripts/test_path_payment.py`
- Single end-to-end test: quote → submit → verify

---

### Block 5: Integration Test Suite *(end)*

Add integration tests (gated with `@pytest.mark.integration`) that run against
the live testnet. Only execute when `STELLAR_INTEGRATION_TEST=1` is set.

```python
@pytest.mark.integration
def test_live_trustline():
    # Connect to testnet, check trustline exists

@pytest.mark.integration
def test_live_path_payment():
    # Execute small payment, verify on-chain

@pytest.mark.integration
def test_adapter_live_quote():
    # Get live quote for a known pair
```

---

## Dependencies

| Block | Depends On | Risk |
|-------|-----------|------|
| B1: Trustlines | Phase 1 (accounts funded) | Low — well-documented op |
| B2: Token Issuance | B1 | Low — standard PaymentOp |
| B3: AMM Pools | B1, B2 | **Medium** — AMM creation needs XLS-30 support in SDK |
| B4: Path Payment | B3 | **Medium** — path finding + signing flow |
| B5: Integration Tests | B4 | Low — just wraps existing code |

## Key Decisions

1. **USDC bridge vs self-issued tokens**: Both. Use USDC as the bridge currency
   for FX (BBD→USDC→JMD) AND issue self-issued tokens for the demo.
   The AMM pools bridge the gap.

2. **AMM initial liquidity**: Use the 10,000 XLM each account received from Friendbot.
   Deposit XLM + token pairs into AMM pools (XLM is the native asset,
   lowest friction for testnet AMMs).

3. **Path finding**: Start with hardcoded paths (BBD→USDC→JMD) for simplicity.
   Graduate to Stellar DEX `/paths` endpoint in a follow-up.

## Success Criteria

- `python3 scripts/setup_trustlines.py` exits 0, all accounts have USDC trustlines
- `python3 scripts/issue_currency_tokens.py` — participants receive test tokens
- `python3 scripts/create_amm_pools.py` — pools exist, queryable via Horizon
- `python3 -m carib_clear.demo full` runs with at least one **live settlement**
- `pytest tests/ -q` shows 250+ passing (mock tests still pass without network)
- `STELLAR_INTEGRATION_TEST=1 pytest tests/ -q` adds integration tests
