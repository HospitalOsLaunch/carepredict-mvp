"""A server-owned demo clock and an atomic, per-session record of human choices."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from . import engine
from .contracts import Entry, Session


class Unknown(LookupError):
    pass


class Conflict(ValueError):
    pass


class SessionStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS demo_world_model_sessions (
                id TEXT PRIMARY KEY, context_id TEXT NOT NULL,
                revision TEXT NOT NULL, snapshot TEXT NOT NULL
            )""")
            yield db
        finally:
            db.close()

    @staticmethod
    def lookup(db: sqlite3.Connection, identifier: str) -> tuple[str, Session]:
        row = db.execute(
            "SELECT revision, snapshot FROM demo_world_model_sessions WHERE id=?", (identifier,)
        ).fetchone()
        if row is None:
            raise Unknown("Cette session de simulation est introuvable.")
        return row[0], Session.model_validate_json(row[1])

    def get(self, identifier: str) -> Session:
        with self.connection() as db:
            return self.lookup(db, identifier)[1]

    def start(self, identifier: str, context_id: str) -> Session:
        case = engine.cases().get(context_id)
        if case is None:
            raise Unknown("Ce contexte de simulation est introuvable.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT context_id, snapshot FROM demo_world_model_sessions WHERE id=?",
                (identifier,),
            ).fetchone()
            if existing:
                if existing[0] != context_id:
                    raise Conflict("Cette session correspond déjà à un autre établissement.")
                return Session.model_validate_json(existing[1])
            session = engine.open_session(identifier, case)
            db.execute(
                "INSERT INTO demo_world_model_sessions VALUES (?, ?, ?, ?)",
                (identifier, context_id, engine.revision(case), session.model_dump_json()),
            )
            db.commit()
            return session

    def mutate(
        self, identifier: str, action: Literal["confirm", "advance"], value: str | int
    ) -> Session:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            version, state = self.lookup(db, identifier)
            case = engine.cases().get(state.context.id)
            if case is None or version != engine.revision(case):
                raise Conflict(
                    "Ce parcours utilise un ancien modèle. Ouvrez une nouvelle simulation."
                )
            if action == "confirm":
                if not any(option.id == value for option in state.options):
                    raise Unknown("Cette affectation n’appartient pas à ce contexte.")
                if state.selected_id == value:
                    return state
                if state.phase != "planning":
                    raise Conflict("Une affectation a déjà été validée pour ce parcours.")
                if not isinstance(value, str):
                    raise ValueError("Identifiant d’affectation invalide.")
                state.selected_id = value
                state.phase = "confirmed"
                event = Entry(hour=state.hour, event="confirmed", option_id=value)
            else:
                if value not in (12, 16):
                    raise ValueError("L’étape de départ doit être midi ou 16 h.")
                if not isinstance(value, int):
                    raise ValueError("Heure de départ invalide.")
                if state.hour > value:
                    return state  # Same command replayed after a lost response.
                if state.hour != value or state.phase not in ("confirmed", "awaiting_report"):
                    raise Conflict(
                        "Validez l’affectation et utilisez l’étape affichée avant d’avancer."
                    )
                following = 16 if value == 12 else state.publication_hour
                if following < state.publication_hour:
                    state.phase = "awaiting_report"
                    event = Entry(
                        hour=following, event="awaiting_report", option_id=state.selected_id
                    )
                else:
                    engine.publish(state, case, following)
                    state.phase = "review"
                    event = Entry(
                        hour=following, event="report_received", option_id=state.selected_id
                    )
                state.hour = following
            state.journal.append(event)
            db.execute(
                "UPDATE demo_world_model_sessions SET snapshot=? WHERE id=?",
                (state.model_dump_json(), identifier),
            )
            db.commit()
            return state
