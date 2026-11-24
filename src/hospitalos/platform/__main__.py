"""Operator commands (run inside the platform container: ``docker compose exec platform python -m
hospitalos.platform``).

invite-admin EMAIL [--name NAME]   first administrator (or a new link for a pending one);
                                   prints the link
migrate                            apply pending schema migrations
backup PATH                        consistent online copy of the database
users                              list accounts (no secrets)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from .config import from_env
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hospitalos.platform")
    sub = parser.add_subparsers(dest="command", required=True)
    invite = sub.add_parser("invite-admin")
    invite.add_argument("email")
    invite.add_argument("--name", default="")
    sub.add_parser("migrate")
    backup = sub.add_parser("backup")
    backup.add_argument("path", type=Path)
    sub.add_parser("users")
    args = parser.parse_args(argv)

    settings = from_env()
    store = Store(settings.database_path)
    if args.command == "migrate":
        print(json.dumps({"schema_version": store.migrate()}))
    elif args.command == "backup":
        store.backup(args.path)
        print(json.dumps({"backup": str(args.path)}))
    elif args.command == "users":
        print(json.dumps([u.public() for u in store.users()], indent=1, ensure_ascii=False))
    elif args.command == "invite-admin":
        user = store.user_by_email(args.email)
        if user is None:
            user = store.create_invited(args.email, "admin", args.name, None)
        elif user.status != "invited":
            print(f"Un compte {user.status} existe déjà pour {user.email}.", file=sys.stderr)
            return 1
        token = store.create_token(user.id, "invite", timedelta(days=settings.invitation_days))
        store.audit(None, "admin.bootstrap_invitation", user.id, {})
        print(f"Lien d'invitation (valable {settings.invitation_days} jours, une seule fois) :")
        print(f"{settings.public_base_url}/#/invitation?token={token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
