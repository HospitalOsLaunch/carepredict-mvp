"""A server-owned demo clock and an atomic, per-session record of human choices."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from . import engine, plan_search
from .contracts import (
    Entry,
    Objective,
    PlanConfirmation,
    PlanEvaluation,
    PlanMenu,
    PlanPreview,
    PlanRequest,
    Session,
    WardState,
)


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
            version, state = self.lookup(db, identifier)
        if state.phase == "planning" and (
            state.plan_version is None or state.model_version == engine.manifest()["version"]
        ):
            case = engine.cases().get(state.context.id)
            if case and version in (engine.revision(case), engine.revision(case, legacy=True)):
                return self.start(identifier, state.context.id)
        return state

    @staticmethod
    def upgrade_planning(
        db: sqlite3.Connection, state: Session, case: engine.Case, revision: str
    ) -> tuple[str, Session]:
        if (
            state.phase != "planning"
            or (state.plan_version is not None and state.model_version == engine.model_version())
            or revision not in (engine.revision(case, legacy=True), engine.revision(case))
        ):
            return revision, state
        updated = engine.open_session(state.id, case)
        updated.journal = state.journal
        current = engine.revision(case)
        db.execute(
            "UPDATE demo_world_model_sessions SET revision=?, snapshot=? WHERE id=?",
            (current, updated.model_dump_json(), state.id),
        )
        return current, updated

    def start(self, identifier: str, context_id: str) -> Session:
        case = engine.cases().get(context_id)
        if case is None:
            raise Unknown("Ce contexte de simulation est introuvable.")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT context_id, snapshot, revision FROM demo_world_model_sessions WHERE id=?",
                (identifier,),
            ).fetchone()
            if existing:
                if existing[0] != context_id:
                    raise Conflict("Cette session correspond déjà à un autre établissement.")
                _, state = self.upgrade_planning(
                    db, Session.model_validate_json(existing[1]), case, existing[2]
                )
                db.commit()
                return state
            session = engine.open_session(identifier, case)
            db.execute(
                "INSERT INTO demo_world_model_sessions VALUES (?, ?, ?, ?)",
                (identifier, context_id, engine.revision(case), session.model_dump_json()),
            )
            db.commit()
            return session

    def mutate(
        self,
        identifier: str,
        action: Literal["confirm", "advance"],
        value: str | int,
        *,
        objective: Objective | None = None,
    ) -> Session:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            version, state = self.lookup(db, identifier)
            case = engine.cases().get(state.context.id)
            if case is None:
                raise Conflict("Ce contexte a changé. Ouvrez une nouvelle simulation.")
            version, state = self.upgrade_planning(db, state, case, version)
            legacy = state.model_version == engine.manifest()["version"]
            if version != engine.revision(case, legacy=legacy):
                raise Conflict(
                    "Ce parcours utilise un ancien modèle. Ouvrez une nouvelle simulation."
                )
            if action == "confirm":
                choice = next((o for o in state.options if o.id == value), None)
                if choice is None:
                    raise Unknown("Cette affectation n’appartient pas à ce contexte.")
                if not choice.eligible:
                    raise Conflict(choice.constraint or "Cette ressource est indisponible.")
                if state.selected_id == value:
                    return state
                if state.phase != "planning":
                    raise Conflict("Une affectation a déjà été validée pour ce parcours.")
                if not isinstance(value, str):
                    raise ValueError("Identifiant d’affectation invalide.")
                state.selected_id = value
                state.decision_objective = objective
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
                    if state.confirmed_plan is None:
                        engine.publish(state, case, following)
                    else:
                        if state.plan_version != engine.plan_version():
                            raise Conflict("Le modèle qui a produit ce plan a changé.")
                        plan_search.publish(state, case, following)
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

    def _plan_state(self, identifier: str) -> Session:
        state = self.get(identifier)
        if state.confirmed_plan is None and state.phase != "planning":
            raise Conflict("Ce parcours a déjà validé une action individuelle.")
        if state.plan_version != engine.plan_version():
            raise Conflict("Les règles de composition ont changé. Ouvrez un nouveau parcours.")
        return state

    def plan_menu(
        self, identifier: str, objective: Objective, ward_id: str | None = None
    ) -> PlanMenu:
        state = self.get(identifier)
        if state.plan_snapshot is not None:
            if ward_id is not None and ward_id != state.decision_ward_id:
                raise Conflict("Une décision a déjà été validée pour cet établissement.")
            return state.plan_snapshot
        state = self._plan_state(identifier)
        if ward_id is not None:
            return plan_search.unit_menu(state.context.id, ward_id, objective)
        return plan_search.menu(state.context.id, objective)

    def unit_state(self, identifier: str, ward_id: str) -> WardState:
        state = self.get(identifier)
        if (
            state.plan_snapshot
            and state.plan_snapshot.ward_id == ward_id
            and state.plan_snapshot.ward_state
        ):
            return state.plan_snapshot.ward_state
        with self.connection() as db:
            version, state = self.lookup(db, identifier)
        case = engine.cases().get(state.context.id)
        if (
            case is None
            or version != engine.revision(case)
            or state.plan_version != engine.plan_version()
        ):
            raise Conflict("Les données de cette situation ont changé. Ouvrez un nouveau parcours.")
        return plan_search.ward_state(state.context.id, ward_id)

    def plan_preview(self, identifier: str, request: PlanPreview) -> PlanEvaluation:
        state = self._plan_state(identifier)
        if state.phase != "planning":
            raise Conflict("Ce plan a déjà été validé.")
        if request.context_id is not None and state.context.id != request.context_id:
            raise Conflict("Cette décision concerne un autre établissement.")
        return plan_search.preview(state.context.id, request.action_ids, request.ward_id)

    def plan_optimize(self, identifier: str, request: PlanRequest) -> PlanMenu:
        state = self._plan_state(identifier)
        if state.phase != "planning":
            raise Conflict("Ce plan a déjà été validé.")
        return plan_search.menu(state.context.id, request.objective, request.action_ids)

    @staticmethod
    def same_confirmation(state: Session, request: PlanConfirmation) -> bool:
        if state.confirmed_plan is None or state.plan_snapshot is None:
            return False
        scope = (
            request.scope_ids
            if request.scope_ids is not None
            else sorted(a.id for a in state.plan_snapshot.actions)
        )
        return (
            (request.preview_id is None or request.preview_id == state.confirmed_plan.id)
            and state.confirmed_plan.action_ids == request.action_ids
            and state.decision_ward_id == request.ward_id
            and state.decision_objective == request.objective
            and state.plan_snapshot.scope_ids == scope
        )

    def confirm_plan(self, identifier: str, request: PlanConfirmation) -> Session:
        # Evaluate outside the SQLite write transaction. Recheck the snapshot and competing
        # single/composed confirmations under the same lock used by the original state machine.
        if request.ward_id is not None and request.scope_ids is not None:
            raise ValueError("Le périmètre des recommandations est défini par l’unité.")
        if request.scope_ids is not None and not set(request.action_ids) <= set(request.scope_ids):
            raise ValueError("Le plan dépasse le périmètre de comparaison demandé.")
        state = self.get(identifier)
        if request.context_id is not None and state.context.id != request.context_id:
            raise Conflict("Cette décision concerne un autre établissement.")
        if state.phase != "planning":
            if self.same_confirmation(state, request):
                return state
            raise Conflict("Une autre décision est déjà validée pour ce parcours.")
        if state.plan_version != engine.plan_version():
            raise Conflict("Les règles de composition ont changé. Ouvrez un nouveau parcours.")
        if request.ward_id is not None:
            shortlist = plan_search.unit_menu(state.context.id, request.ward_id, request.objective)
            if request.preview_id is not None:
                candidate = plan_search.preview(
                    state.context.id, request.action_ids, request.ward_id
                )
                if request.preview_id != candidate.id:
                    raise Conflict("L’aperçu ne correspond plus à cette composition.")
                if not candidate.feasible or candidate.access_warnings:
                    raise Conflict(" ".join([*candidate.conflicts, *candidate.access_warnings]))
            else:
                try:
                    candidate = next(
                        proposal
                        for proposal in (shortlist.reference, *shortlist.recommendations)
                        if proposal.action_ids == request.action_ids
                    )
                except StopIteration:
                    raise Conflict(
                        "Évaluez votre composition dans cette unité avant de la valider."
                    ) from None
        else:
            candidate = plan_search.preview(state.context.id, request.action_ids)
            if not candidate.feasible:
                raise Conflict(" ".join(candidate.conflicts))
            shortlist = plan_search.menu(state.context.id, request.objective, request.scope_ids)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            version, current = self.lookup(db, identifier)
            case = engine.cases().get(current.context.id)
            if (
                case is None
                or version != engine.revision(case)
                or current.plan_version != engine.plan_version()
            ):
                raise Conflict("Le catalogue ou l’état du parcours a changé.")
            if current.phase != "planning":
                if self.same_confirmation(current, request):
                    return current
                raise Conflict("Une autre décision est déjà validée pour ce parcours.")
            current.confirmed_plan = candidate
            current.plan_snapshot = shortlist
            current.selected_id = candidate.id
            current.decision_objective = request.objective
            current.decision_ward_id = request.ward_id
            current.phase = "confirmed"
            current.journal.append(
                Entry(
                    hour=current.hour,
                    event="confirmed",
                    option_id=candidate.id,
                    ward_id=request.ward_id,
                )
            )
            db.execute(
                "UPDATE demo_world_model_sessions SET snapshot=? WHERE id=?",
                (current.model_dump_json(), identifier),
            )
            db.commit()
            return current
