"""Serve the real hybrid API with a fictional shadow-mode unit, for the cockpit.

    PYTHONPATH=src:. python web/dev/serve_demo_api.py            # frozen clock (stable demo)
    PYTHONPATH=src:. python web/dev/serve_demo_api.py --ageing   # time runs: confirmations go stale

Loopback only. Uses services/api/hybrid_app.create_app unchanged; no execution endpoint.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import timedelta
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_unit import AT, live_batch, live_policy  # noqa: E402

from hospitalos.hybrid.live_store import LiveStore  # noqa: E402
from services.api.hybrid_app import create_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ageing", action="store_true", help="let the clock run from 08:30")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    store = LiveStore(live_policy())
    store.ingest(live_batch(), AT)
    started = time.monotonic()

    def clock():  # type: ignore[no-untyped-def]
        elapsed = time.monotonic() - started if args.ageing else 0
        return AT + timedelta(seconds=30 + elapsed)

    uvicorn.run(create_app(store, clock), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
