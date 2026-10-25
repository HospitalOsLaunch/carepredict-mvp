"""Choose an engine for each task, escalate when it fails, and never write blindly.

For each task the policy gives an ordered chain (cheapest first). An engine is skipped,
with the reason logged, when it is disabled, not configured on this machine, not allowed
to see identifiable patient screens, not calibrated, or when the task or daily budget
is spent. Every engine run is reported to the API with its cost.

Writes to the portal (``reply_portal``) follow three safety rules:
1. credentials never reach a model: the deterministic playbook logs in for every engine;
2. a reply is only "done" once the playbook has read the portal back and found exactly
   the expected answer, whichever engine wrote it;
3. before escalating after a failed attempt, the portal is read back: if something was
   written but not what was expected, the task stops for a human instead of letting a
   second engine write again.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from services.admissions_agent.api_client import ApiError, HospitalOSClient
from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.config import AgentSettings
from services.admissions_agent.engines.base import (
    BudgetExceeded,
    EngineResult,
    VisionEngine,
    reply_goal,
    sync_goal,
)
from services.admissions_agent.playbook import PARIS, Playbook, PlaybookError, Transforms, render

EngineFactory = Callable[[str, dict[str, Any]], VisionEngine | None]
SessionFactory = Callable[[], BrowserSession]

REQUEST_FIELDS = {
    "source",
    "external_ref",
    "received_at",
    "referrer_facility",
    "referrer_unit",
    "patient_ref",
    "patient_age",
    "patient_sex",
    "mention_requested",
    "clinical_category",
    "care_level",
    "isolation_required",
    "special_needs",
    "desired_date",
}


@dataclass
class TaskOutcome:
    status: str  # done | failed | needs_human
    engine: str | None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Router:
    def __init__(
        self,
        settings: AgentSettings,
        api: HospitalOSClient,
        playbook: Playbook,
        transforms: Transforms,
        engine_factory: EngineFactory,
        session_factory: SessionFactory,
    ) -> None:
        self.settings = settings
        self.api = api
        self.playbook = playbook
        self.transforms = transforms
        self.engine_factory = engine_factory
        self.session_factory = session_factory

    # --- eligibility ---------------------------------------------------------------

    def configured(self, name: str, engine: dict[str, Any]) -> bool:
        if engine["kind"] == "playbook":
            return True
        endpoint = self.settings.engines.get(name)
        if endpoint is None:
            return False
        if engine["kind"] == "anthropic":
            return bool(endpoint.api_key)
        return bool(endpoint.base_url)

    def skip_reason(
        self,
        name: str,
        engine: dict[str, Any],
        kind: str,
        budget_left: float,
        calibrations: dict[str, float],
    ) -> str | None:
        if not engine.get("enabled"):
            return "désactivé dans la politique"
        if engine["kind"] == "playbook" and not self.playbook.supports(kind):
            return "pas de script pour cette tâche"
        if not self.configured(name, engine):
            return "non configuré sur cette machine"
        if engine["kind"] != "playbook" and not engine.get("identifiable_data_allowed"):
            return "non autorisé à voir des données patient identifiantes"
        minimum = engine.get("min_calibration")
        if minimum is not None and calibrations.get(name, 0.0) < minimum:
            score = calibrations.get(name, 0.0)
            return f"calibration de pointage insuffisante ({score:.0%} < {minimum:.0%})"
        if engine["kind"] != "playbook" and budget_left <= 0:
            return "budget épuisé"
        return None

    # --- task handling -------------------------------------------------------------

    def handle(self, task: dict[str, Any], heartbeat: dict[str, Any]) -> TaskOutcome:
        policy = heartbeat["policy"]
        kind = task["kind"]
        chain: list[str] = policy["routes"].get(kind, [])
        daily_left = float(policy["daily_budget_usd"]) - float(
            heartbeat.get("spent_today_usd", 0.0)
        )
        task_left = float(policy.get("task_budget_usd", {}).get(kind, 1.0))
        calibrations: dict[str, float] = heartbeat.get("calibrations", {})
        route: list[dict[str, Any]] = []
        session = self.session_factory()
        try:
            try:
                self.playbook.login(
                    session,
                    {
                        "username": self.settings.portal_username,
                        "password": self.settings.portal_password,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - portal down or login changed
                return TaskOutcome(
                    "failed", None, {"route": route}, f"connexion au portail : {exc}"
                )

            before: dict[str, Any] | None = None
            if kind == "reply_portal":
                before = self._read_back(session, task["payload"])

            for name in chain:
                engine = policy["engines"].get(name)
                if engine is None:
                    continue
                budget_left = min(task_left, daily_left)
                reason = self.skip_reason(name, engine, kind, budget_left, calibrations)
                if reason:
                    route.append({"engine": name, "decision": "ignoré", "reason": reason})
                    continue
                result = self._run(name, engine, kind, task, session, budget_left)
                task_left -= result.cost_usd
                daily_left -= result.cost_usd
                self._report(task["id"], name, result)
                route.append(
                    {
                        "engine": name,
                        "decision": result.outcome,
                        "cost_usd": round(result.cost_usd, 4),
                        "steps": result.steps,
                        "error": result.error,
                    }
                )
                if result.outcome != "success":
                    if kind == "reply_portal":
                        after = self._read_back(session, task["payload"])
                        verdict = self._compare(before, after, task["payload"])
                        if verdict == "done":
                            return TaskOutcome(
                                "done", name, {"route": route, "verification": after}
                            )
                        if verdict == "changed":
                            return TaskOutcome(
                                "needs_human",
                                name,
                                {"route": route, "verification": after},
                                "le portail a été modifié sans correspondre à la réponse attendue",
                            )
                    continue
                if kind == "sync_inbox":
                    return self._finish_sync(name, result.data, route)
                return self._finish_reply(name, session, task["payload"], route)
            return TaskOutcome(
                "needs_human",
                None,
                {"route": route},
                "aucun moteur n'a pu traiter la tâche : à faire à la main",
            )
        finally:
            session.close()

    def _run(
        self,
        name: str,
        engine: dict[str, Any],
        kind: str,
        task: dict[str, Any],
        session: BrowserSession,
        budget_left: float,
    ) -> EngineResult:
        started = time.monotonic()
        if engine["kind"] == "playbook":
            try:
                if kind == "sync_inbox":
                    data = self.playbook.sync_inbox(session, self.transforms)
                    return EngineResult("success", data, 0.0, 1, time.monotonic() - started)
                self.playbook.reply(session, task["payload"])
                return EngineResult("success", None, 0.0, 1, time.monotonic() - started)
            except Exception as exc:  # noqa: BLE001 - layout change, timeout, missing field
                return EngineResult("failure", None, 0.0, 1, time.monotonic() - started, str(exc))
        vision = self.engine_factory(name, engine)
        if vision is None:
            return EngineResult("refused", None, 0.0, 0, 0.0, "moteur indisponible")
        goal = sync_goal() if kind == "sync_inbox" else reply_goal(task["payload"])
        if kind == "sync_inbox":
            session.goto(self.playbook.spec["sync_inbox"]["list"]["goto"])
        try:
            return vision.run(session, goal, self.settings.max_steps, budget_left)
        except BudgetExceeded as exc:
            return EngineResult(
                "failure", None, budget_left, 0, time.monotonic() - started, str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - network, model, browser
            return EngineResult(
                "failure", None, 0.0, 0, time.monotonic() - started, f"{type(exc).__name__}: {exc}"
            )

    def _report(self, task_id: int, engine: str, result: EngineResult) -> None:
        self.api.attempt(
            task_id,
            engine=engine,
            outcome=result.outcome,
            cost_usd=round(result.cost_usd, 6),
            steps=result.steps,
            duration_s=round(result.duration_s, 2),
            error=result.error,
        )

    # --- reply verification ------------------------------------------------------------

    def _read_back(self, session: BrowserSession, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.playbook.can_verify:
            return None
        try:
            _, info = self.playbook.verify(session, payload, self.transforms)
            observed: dict[str, Any] = info["observed"]
            return observed
        except Exception:  # noqa: BLE001
            return None

    def _compare(
        self, before: dict[str, Any] | None, after: dict[str, Any] | None, payload: dict[str, Any]
    ) -> str:
        if after is None:
            return "unknown"
        expected = self.playbook.spec["verify_reply"]["expect"].get(
            str(payload.get("decision")), {}
        )
        wanted = {k: render(str(v), {"payload": payload}) for k, v in expected.items()}
        if wanted and all(str(after.get(k, "")) == v for k, v in wanted.items()):
            return "done"
        return "unchanged" if after == before else "changed"

    def _finish_reply(
        self,
        engine: str,
        session: BrowserSession,
        payload: dict[str, Any],
        route: list[dict[str, Any]],
    ) -> TaskOutcome:
        if not self.playbook.can_verify:
            return TaskOutcome(
                "needs_human",
                engine,
                {"route": route},
                "réponse saisie mais non vérifiable automatiquement : contrôlez-la dans le portail",
            )
        ok, info = self.playbook.verify(session, payload, self.transforms)
        if ok:
            return TaskOutcome("done", engine, {"route": route, "verification": info})
        return TaskOutcome(
            "needs_human",
            engine,
            {"route": route, "verification": info},
            "la relecture du portail ne montre pas la réponse attendue",
        )

    # --- inbox ----------------------------------------------------------------------------

    def normalise(self, item: dict[str, Any]) -> dict[str, Any]:
        """Keep allowed fields only; model labels become codes; the patient is the dossier."""
        clean = {k: v for k, v in item.items() if k in REQUEST_FIELDS and v not in (None, "")}
        clean.setdefault(
            "source",
            self.playbook.spec.get("sync_inbox", {}).get("constants", {}).get("source", "portail"),
        )
        clean["patient_ref"] = str(clean.get("external_ref", ""))
        mention = str(clean.get("mention_requested", ""))
        if mention and mention not in self.transforms.vocabulary.get("mentions", {}):
            clean["mention_requested"] = self.transforms.apply("mention_label", mention)
        needs = clean.get("special_needs") or []
        if isinstance(needs, str):
            needs = [needs]
        codes = self.transforms.vocabulary.get("special_needs", {})
        clean["special_needs"] = [
            n if n in codes else self.transforms.apply("needs_labels", str(n))[0] for n in needs
        ]
        received = clean.get("received_at")
        if isinstance(received, str):
            stamp = datetime.fromisoformat(received)
            if stamp.tzinfo is None:  # the portal shows local time
                stamp = stamp.replace(tzinfo=PARIS)
            clean["received_at"] = stamp.isoformat()
        return clean

    def _finish_sync(self, engine: str, items: Any, route: list[dict[str, Any]]) -> TaskOutcome:
        created = existing = 0
        rejected: list[str] = []
        for item in items or []:
            try:
                answer = self.api.ingest(self.normalise(item))
                if answer.get("created"):
                    created += 1
                else:
                    existing += 1
            except (ApiError, PlaybookError, KeyError, ValueError) as exc:
                rejected.append(f"{item.get('external_ref', '?')}: {exc}")
        result = {
            "route": route,
            "created": created,
            "already_known": existing,
            "rejected": rejected,
        }
        if rejected:
            return TaskOutcome(
                "needs_human", engine, result, f"{len(rejected)} demande(s) rejetée(s)"
            )
        return TaskOutcome("done", engine, result)
