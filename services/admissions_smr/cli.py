"""Operator commands.

    python -m services.admissions_smr.cli init-group --name "Groupe X" \
        --admin-email admin@groupe-x.fr --admin-name "Nom Prénom"
    python -m services.admissions_smr.cli seed-demo        # development only
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from services.admissions_smr.clock import Clock
from services.admissions_smr.config import get_settings
from services.admissions_smr.db import Base, make_engine, make_session_factory
from services.admissions_smr.models import Group, User
from services.admissions_smr.security import hash_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="admissions-smr")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-group", help="Créer un groupe et son premier administrateur")
    init.add_argument("--name", required=True)
    init.add_argument("--admin-email", required=True)
    init.add_argument("--admin-name", required=True)

    demo = sub.add_parser("seed-demo", help="Charger le groupe de démonstration (synthétique)")
    demo.add_argument("--password", default=os.getenv("ADM_DEMO_PASSWORD", "demo-hospitalos-2026"))

    args = parser.parse_args(argv)
    settings = get_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
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
        if settings.is_production:
            print("Refusé : jeu de démonstration interdit en production", file=sys.stderr)
            return 1
        from services.admissions_smr.seed import seed_demo

        if session.scalar(select(Group.id).where(Group.name == "Groupe Démo Réadaptation")):
            print("Le groupe de démonstration existe déjà", file=sys.stderr)
            return 1
        group = seed_demo(
            session, clock.today(), args.password, settings.password_iterations, settings.timezone
        )
        print(f"Groupe de démonstration créé (id {group.id}).")
        print("Comptes : admin@, coordination@, tilleuls@, direction@, agent@demo.hospitalos.fr")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
