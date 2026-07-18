"""Worker health-check entrypoint for Kubernetes probes."""

from __future__ import annotations

import sys


def check() -> int:
    """Exit 0 if the worker module imports cleanly, otherwise 1."""
    try:
        from carib_clear.worker.settlement_worker import SettlementWorker  # noqa: F401
        return 0
    except Exception:  # noqa: BLE001
        return 1


if __name__ == "__main__":
    sys.exit(check())
