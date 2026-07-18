"""CARIB-CLEAR background worker package."""
from __future__ import annotations

def main() -> None:
    """Run the worker main loop."""
    from carib_clear.worker.settlement_worker import SettlementWorker

    worker = SettlementWorker()
    print(f"Starting worker {worker.worker_id} ...")
    summary = worker.drain(cycles=999999)
    print(summary)


if __name__ == "__main__":
    main()
