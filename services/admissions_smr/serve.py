"""Start the API with several processes (règle 28 de l'audit de performance).

    python -m services.admissions_smr.serve

One Python process answers one computation at a time: a forecast that takes 100 ms makes
the next bed manager wait behind it. Several processes answer side by side, and one that
dies is restarted by uvicorn while the others keep answering. ``ADM_API_WORKERS`` sets
how many (default: the machine's cores, between 2 and 4, so that each keeps its pool of
database connections within PostgreSQL's limit). With SQLite (development only) there is
one process: it accepts a single writer.

Behind nginx, several containers can share the load too (``docker compose up --scale
api=3``): nginx spreads the calls over every address of ``api`` it found at start.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import uvicorn

from services.admissions_smr.config import get_settings

MAX_DEFAULT_WORKERS = 4


def workers(database_url: str, env: Mapping[str, str], cores: int | None) -> int:
    if database_url.startswith("sqlite"):
        return 1
    wanted = env.get("ADM_API_WORKERS", "").strip()
    if wanted:
        return max(1, int(wanted))
    return min(MAX_DEFAULT_WORKERS, max(2, cores or 2))


def main() -> None:
    count = workers(get_settings().database_url, os.environ, os.cpu_count())
    uvicorn.run(
        "services.admissions_smr.main:app",
        host=os.environ.get("ADM_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("ADM_API_PORT", "8010")),
        proxy_headers=True,
        workers=count,
    )


if __name__ == "__main__":
    main()
