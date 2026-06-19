# Contributing to CARIB-CLEAR

> **Guidelines for contributors during and after the Future Caribbean Buildathon**

---

## 🎯 Buildathon Sprint (Jul 17–Aug 7)

### Priority Areas

| Priority | Area | Target |
|----------|------|--------|
| **P0** | Core agents | FlowVisibility, P2PMatching, NetSettlement, Compliance |
| **P0** | Rail adapters | Stellar, ACH (JM/BB), Mobile Money (MonCash) |
| **P0** | Kreyol voice | `kreyol:3b` training → Ollama → JARVIS integration |
| **P1** | MSME credit | DataAggregation, CreditProfile, CashFlowLending |
| **P1** | Governance | HITL approval queue, thresholds config |
| **P2** | Monitoring | Grafana dashboards, Prometheus metrics |
| **P2** | Tests | Unit + integration + E2E |

---

## 🛠️ Development Setup

### Prerequisites
```bash
# Python 3.11+
python3 --version

# NVIDIA H200 (buildathon) or CUDA/MPS
nvidia-smi  # or check torch.backends.mps.is_available()

# Git + GitHub CLI
gh auth status
```

### Local Install
```bash
git clone https://github.com/ralphucious/CARIB-CLEAR
cd CARIB-CLEAR

# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install deps
pip install -r requirements.txt
pip install -e .  # editable install

# Verify
python -c "from carib_clear import *; print('✓ Imports OK')"
```

### H200 (Buildathon)
```bash
# Provided by Highrise — SSH details shared at kickoff
ssh h200.carib-clear.build

# Run training
python scripts/quick_train_kreyol.py --stage both

# Merge to Ollama
python scripts/merge_kreyol_to_ollama.py --output-model kreyol:3b
```

---

## 📋 Contribution Workflow

### 1. Pick an Issue
- Check [GitHub Issues](https://github.com/ralphucious/CARIB-CLEAR/issues)
- Look for `buildathon-p0`, `buildathon-p1`, `good-first-issue` labels
- Comment to claim: "Taking this for Buildathon Week 1"

### 2. Branch & Develop
```bash
git checkout main
git pull origin main
git checkout -b feat/p2p-matching-orderbook

# Make changes
# Write tests
# Run linting
```

### 3. Test Locally
```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# Lint
ruff check .
mypy carib_clear/
```

### 4. Submit PR
```bash
git add .
git commit -m "feat(p2p): add price-time priority order book

- Implement OrderBookEntry with price-time priority
- Add submit_demand_order / submit_supply_order
- Integrate with GovernanceAgent for approval
- Add match_orders() with price-time priority

Closes #42"
git push origin feat/p2p-matching-orderbook

# Create PR via GitHub
gh pr create --title "feat(p2p): price-time priority order book" --body "..."

# Request review from @ralphucious
```

### 5. Review & Merge
- CI must pass (tests, lint, type-check)
- At least 1 approval from core team
- Squash & merge to main

---

## 📝 Code Standards

### Python Style
```python
# Type hints required for public APIs
def submit_demand_order(
    self,
    *,
    currency_from: str,
    currency_to: str,
    amount_usd: float,
    max_rate: float,
    participant_id: str,
    jurisdiction: str
) -> OrderBookEntry:
    ...

# Docstrings for public classes/functions
class P2PMatchingEngine:
    """
    P2P Matching Engine - The "heart" of the CARICOM FX Swap Network.
    
    Features:
    - Direct currency matching (no USD bridge required)
    - Price-time priority order book
    - Multi-currency support (BBD, JMD, TTD, XCD, HTG, USD)
    """
```

### Naming Conventions
| Element | Convention | Example |
|---------|------------|---------|
| Classes | PascalCase | `P2PMatchingEngine` |
| Functions/Methods | snake_case | `submit_demand_order` |
| Constants | UPPER_SNAKE | `DEFAULT_SLIPPAGE_BPS` |
| Private | _snake_case | `_calculate_implied_rate` |
| Type variables | PascalCase | `T = TypeVar("T")` |

### Async Patterns
```python
# Use async for I/O-bound operations
async def submit_settlement(self, order: SettlementOrder) -> SettlementResult:
    async with self._semaphore:
        result = await self._rail.submit(order)
    return result

# Use sync for CPU-bound (ML inference, matching engine)
def match_orders(self, ccy_from: str, ccy_to: str) -> List[MatchResult]:
    ...
```

---

## 🧪 Testing Standards

### Test Structure
```
tests/
├── unit/
│   ├── agents/
│   │   ├── test_flow_visibility.py
│   │   ├── test_p2p_matching.py
│   │   └── test_compliance.py
│   ├── broker/
│   │   ├── test_stellar_adapter.py
│   │   └── test_ach_adapter.py
│   └── governance/
│       └── test_approval_queue.py
├── integration/
│   ├── test_fx_swap_flow.py
│   └── test_msme_credit_flow.py
└── e2e/
    └── test_voice_pipeline.py
```

### Fixtures
```python
# tests/conftest.py
import pytest
from carib_clear.agents import FlowVisibilityAgent
from carib_clear.broker import StellarAdapter

@pytest.fixture
def flow_agent():
    return FlowVisibilityAgent()

@pytest.fixture
def stellar_adapter():
    adapter = StellarAdapter({"mock_mode": True})
    adapter.initialize()
    yield adapter

# Usage
def test_flow_visibility_generates_matches(flow_agent):
    flow_agent.generate_mock_flows(10)
    matches = flow_agent.scan_for_matches()
    assert len(matches) > 0
```

### Mocking External Services
```python
# Use unittest.mock for external APIs
from unittest.mock import AsyncMock, patch

@patch("carib_clear.broker.stellar_adapter.Server")
async def test_stellar_submit_settlement(mock_server, stellar_adapter):
    mock_server.return_value.submit_transaction.return_value = {
        "successful": True,
        "hash": "0xabc123"
    }
    result = await stellar_adapter.submit_settlement(order)
    assert result.success
    assert result.tx_hash == "0xabc123"
```

---

## 📦 Release Process (Post-Buildathon)

### Versioning
- **SemVer**: `MAJOR.MINOR.PATCH`
- **Buildathon**: `0.1.0-buildathon`
- **Post-buildathon**: `0.2.0` → `1.0.0` (production)

### Changelog
```markdown
## [0.2.0] - 2026-09-01
### Added
- NetSettlementAgent multilateral netting
- MonCash mobile money adapter
- Kreyol-AI voice integration

### Changed
- P2PMatchingEngine: price-time priority order book
- ComplianceAgent: jurisdiction rules engine

### Fixed
- NetSettlementAgent: config.get() NoneType bug
```

---

## 🤝 Community

### Communication
- **Discord:** `#carib-clear-dev` (Buildathon team)
- **GitHub Discussions:** Design proposals, RFCs
- **Weekly Sync:** Tuesdays 10:00 AST (Buildathon)

### Code of Conduct
- Follow [Future Caribbean Code of Conduct](https://futurecaribbean.com/code-of-conduct)
- Be respectful, inclusive, constructive
- No harassment, discrimination, or spam

### Getting Help
- **Technical questions:** GitHub Discussions or Discord
- **Blockers:** Tag @ralphucious in PR or Discord
- **Urgent:** DM on Discord or email ralph@carib-clear.build

---

## 🏆 Recognition

### Buildathon Contributors
All merged PR authors during Buildathon (Jul 17–Aug 7) listed in:
- `CONTRIBUTORS.md`
- Buildathon submission credits
- Future Caribbean showcase page

### Ongoing Contributors
- Top 5 contributors/month → swag + governance tokens (post-launch)
- Maintainer track for sustained contributors

---

## 📄 License

By contributing, you agree that your contributions will be licensed under the **MIT License** (same as project).

---

*Built for the Future Caribbean Global AI Buildathon — Track 3: Finance, Payments & MSME Capital*