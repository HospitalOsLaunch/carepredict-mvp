"""Operator commands.

    python -m services.admissions_smr.cli init-group --name "Groupe X" \
        --admin-email admin@groupe-x.fr --admin-name "Nom Prénom"
    python -m services.admissions_smr.cli seed-demo        # development only
    python -m services.admissions_smr.cli seed-demo-mco    # development only (LISCOP demo)
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.clock import Clock
from services.admissions_smr.config import ConfigurationError, ensure_demo_allowed, get_settings
from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.models import AgentConnection, Group, User
from services.admissions_smr.security import hash_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="admissions-smr")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-group", help="Créer un groupe et son premier administrateur")
    init.add_argument("--name", required=True)
    init.add_argument("--admin-email", required=True)
    init.add_argument("--admin-name", required=True)

    sub.add_parser("migrate", help="Mettre le schéma de la base à jour")

    demo = sub.add_parser("seed-demo", help="Charger le groupe de démonstration (synthétique)")
    demo.add_argument("--password", default=os.getenv("ADM_DEMO_PASSWORD", "demo-hospitalos-2026"))
    demo.add_argument(
        "--portal-url", default=os.getenv("ADM_DEMO_PORTAL_URL", "http://portal:8020")
    )

    mco = sub.add_parser("seed-demo-mco", help="Charger l'hôpital MCO de démonstration (LISCOP)")
    mco.add_argument("--password", default=os.getenv("ADM_DEMO_PASSWORD", "demo-hospitalos-2026"))
    mco.add_argument(
        "--bedsoft-url", default=os.getenv("ADM_DEMO_BEDSOFT_URL", "http://bedsoft:8120")
    )

    args = parser.parse_args(argv)
    settings = get_settings()
    if args.command in ("seed-demo", "seed-demo-mco"):
        try:
            ensure_demo_allowed(settings)  # before touching the database (REVIEW S-M3)
        except ConfigurationError as exc:
            print(f"Refusé : {exc}", file=sys.stderr)
            return 1
    engine = make_engine(settings.database_url)
    upgrade(engine)
    if args.command == "migrate":
        print("Schéma à jour.")
        return 0
    session = make_session_factory(engine)()
    clock = Clock(settings.timezone)

    if args.command == "init-group":
        email = args.admin_email.strip().lower()
        if session.scalar(select(User.id).where(User.email == email)):
            print(f"Un compte existe déjà pour {email}", file=sys.stderr)
            return 1
        password = os.getenv("ADM_ADMIN_PASSWORD") or getpass.getpass("Mot de passe (10+ car.) : ")
        group = Group(name=args.name, created_at=clock.now())
        session.add(group)
        session.flush()
        session.add(
            User(
                group_id=group.id,
                email=email,
                full_name=args.admin_name,
                password_hash=hash_password(password, settings.password_iterations),
                role="admin_groupe",
                created_at=clock.now(),
            )
        )
        session.commit()
        print(f"Groupe « {args.name} » créé (id {group.id}), administrateur {email}")
        return 0

    if args.command == "seed-demo":
        from services.admissions_smr.seed import add_demo_portal_connection, seed_demo

        existing = session.scalar(select(Group).where(Group.name == "Groupe Démo Réadaptation"))
        if existing is not None:
            return _repair_demo_connections(
                session,
                existing,
                lambda g: add_demo_portal_connection(
                    session, g, settings.connector_key, args.portal_url
                ),
                "Le groupe de démonstration existe déjà",
            )
        group = seed_demo(
            session,
            clock.today(),
            args.password,
            settings.password_iterations,
            settings.timezone,
            connector_key=settings.connector_key,
            portal_url=args.portal_url,
        )
        print(f"Groupe de démonstration créé (id {group.id}).")
        print("Comptes : admin@, coordination@, tilleuls@, direction@, agent@demo.hospitalos.fr")
        return 0

    if args.command == "seed-demo-mco":
        from services.admissions_smr.seed_mco import (
            EMAIL_DOMAIN,
            GROUP_NAME,
            add_demo_bedsoft_connection,
            seed_demo_mco,
        )

        try:
            existing = session.scalar(select(Group).where(Group.name == GROUP_NAME))
            if existing is not None:
                return _repair_demo_connections(
                    session,
                    existing,
                    lambda g: add_demo_bedsoft_connection(
                        session, g, settings.connector_key, args.bedsoft_url
                    ),
                    "Le groupe de démonstration MCO existe déjà",
                )
            group = seed_demo_mco(
                session,
                clock.now(),
                args.password,
                settings.password_iterations,
                settings.timezone,
                connector_key=settings.connector_key,
                bedsoft_url=args.bedsoft_url,
            )
        finally:  # no transaction left open (it would block a schema change on PostgreSQL)
            session.close()
            engine.dispose()
        print(f"Hôpital MCO de démonstration créé (id {group.id}).")
        print(f"Comptes : bedmanager@, cadre@, direction@, admin@, agent@{EMAIL_DOMAIN}")
        return 0
    return 2


def _repair_demo_connections(
    session: Session, group: Group, add: Callable[[Group], object], exists_message: str
) -> int:
    """A demo database seeded before connections existed gets its demo connection, so that
    `docker compose up` after an update works without wiping the data. Never touches a
    group that already has a connection (one created or archived by an administrator)."""
    if session.scalar(select(AgentConnection.id).where(AgentConnection.group_id == group.id)):
        print(exists_message, file=sys.stderr)
        return 1
    add(group)
    session.commit()
    print(f"{exists_message} : connexion de démonstration ajoutée.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
