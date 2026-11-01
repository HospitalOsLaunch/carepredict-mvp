"""Forecast engine commands.

python -m services.forecast_engine run --group 1 [--as-of 2026-11-02]
python -m services.forecast_engine run --all
python -m services.forecast_engine backtest --group 1 [--out docs/liscop/backtest.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from services.admissions_smr.clock import Clock
from services.admissions_smr.config import get_settings
from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.models import Group
from services.forecast_engine import MODEL_VERSION
from services.forecast_engine.data import load_history
from services.forecast_engine.pipeline import compute
from services.forecast_engine.store import save_backtest, save_failure, save_run, utcnow

log = logging.getLogger("forecast_engine")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forecast-engine")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Calculer et stocker les prévisions d'un groupe")
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--group", type=int)
    target.add_argument("--all", action="store_true", help="Tous les groupes")
    run.add_argument("--as-of", type=date.fromisoformat, help="Jour J+0 (défaut : aujourd'hui)")
    back = sub.add_parser("backtest", help="Backtest pré-enregistré (docs/liscop/BACKTEST.md)")
    back.add_argument("--group", type=int, required=True)
    back.add_argument("--out", type=Path, help="Écrire aussi le rapport JSON complet ici")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    settings = get_settings()
    engine = make_engine(settings.database_url)
    upgrade(engine)
    factory = make_session_factory(engine)
    clock = Clock(settings.timezone)
    try:
        if args.command == "backtest":
            from services.forecast_engine.backtest import render_markdown, run_backtest

            with factory() as session:
                report = run_backtest(session, args.group, clock.today(), settings.timezone)
                report["model_version"] = MODEL_VERSION
                save_backtest(session, args.group, report, utcnow())
            if args.out:
                args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            print(render_markdown(report))
            return 0
        with factory() as session:
            groups = (
                list(session.scalars(select(Group.id).order_by(Group.id)))
                if args.all
                else [args.group]
            )
        failed = 0
        for group_id in groups:
            failed += _run_group(factory, group_id, args.as_of or clock.today(), settings.timezone)
        return 1 if failed else 0
    finally:
        engine.dispose()


def _run_group(factory: sessionmaker[Session], group_id: int, as_of: date, timezone: str) -> int:
    started = time.monotonic()
    with factory() as session:
        if session.get(Group, group_id) is None:
            log.error("Groupe %s introuvable", group_id)
            return 1
        try:
            history = load_history(session, group_id, as_of - timedelta(days=1), timezone)
            result = compute(session, history, as_of, use_current_plans=True)
            run = save_run(session, group_id, result, utcnow())
        except Exception as exc:  # recorded, then reported: the API keeps the last good run
            log.exception("Échec de la prévision du groupe %s", group_id)
            save_failure(session, group_id, as_of, MODEL_VERSION, repr(exc), utcnow())
            return 1
    log.info(
        "Groupe %s : run %s, %s valeurs, %.0f s",
        group_id,
        run.id,
        len(result.values),
        time.monotonic() - started,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
