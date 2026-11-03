"""Deterministic portal automation from a YAML playbook (CSS selectors, no model).

A playbook is the cheapest, most auditable engine: same input, same clicks. It is also
what logs in for every engine (credentials never reach a model) and what verifies,
independently, any reply a model engine claims to have written.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.replay import Privacy, PrivacyError

PARIS = ZoneInfo("Europe/Paris")
BUNDLED = Path(__file__).parent / "playbooks"
TASK_ORDER = ("sync_inbox", "reply_portal", "sync_movements")
_TEMPLATE = re.compile(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}")
SECRET_FILL = re.compile(r"\{\{\s*secrets\.(\w+)\s*\}\}")


# What each transform expects, for error messages that never quote the screen.
EXPECTED = {
    "int": "nombre entier",
    "date_fr": "date JJ/MM/AAAA",
    "datetime_fr": "date et heure JJ/MM/AAAA HH:MM",
    "bool_fr": "oui ou non",
    "sex_fr": "sexe",
    "mention_label": "libellé de mention du vocabulaire",
    "needs_labels": "libellés de besoins du vocabulaire",
}


class PlaybookError(RuntimeError):
    """The portal did not look like the playbook expects (layout change, timeout...)."""


def render(value: str, context: dict[str, Any]) -> str:
    def lookup(match: re.Match[str]) -> str:
        current: Any = context
        for part in match.group(1).split("."):
            if not isinstance(current, dict) or part not in current:
                raise PlaybookError(f"variable inconnue : {match.group(1)}")
            current = current[part]
        return "" if current is None else str(current)

    return _TEMPLATE.sub(lookup, value)


def same_text(left: object, right: object) -> bool:
    """HTML may collapse line breaks; keep every word, accent and punctuation exact."""
    return " ".join(str(left).split()) == " ".join(str(right).split())


def fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


@dataclass
class Transforms:
    vocabulary: dict[str, dict[str, str]]

    def apply(self, name: str | None, raw: str) -> Any:
        text = raw.strip()
        if name is None:
            return text
        if name == "int":
            return int(text)
        if name == "date_fr":
            return datetime.strptime(text, "%d/%m/%Y").date().isoformat()
        if name == "datetime_fr":
            local = datetime.strptime(text, "%d/%m/%Y %H:%M").replace(tzinfo=PARIS)
            return local.isoformat()
        if name == "bool_fr":
            return fold(text) in {"oui", "o", "yes", "vrai", "1"}
        if name == "sex_fr":
            key = fold(text)[:1]
            return {"f": "F", "m": "M", "h": "M"}.get(key, "I")
        if name == "mention_label":
            return self._code("mentions", text)
        if name == "needs_labels":
            parts = [p for p in re.split(r"[,;/]", text) if p.strip()]
            return [self._code("special_needs", p) for p in parts]
        raise PlaybookError(f"transformation inconnue : {name}")

    def _code(self, vocabulary: str, label: str) -> str:
        wanted = fold(label)
        for code, text in self.vocabulary.get(vocabulary, {}).items():
            if fold(text) == wanted or fold(code) == wanted:
                return code
        # Accept a label that contains the vocabulary label (portals add details).
        for code, text in self.vocabulary.get(vocabulary, {}).items():
            if fold(text) and fold(text) in wanted:
                return code
        raise PlaybookError(f"libellé non reconnu (vocabulaire {vocabulary})")


class Playbook:
    def __init__(self, spec: dict[str, Any], default_id: str = "playbook") -> None:
        self.spec = spec
        self.name = str(spec.get("name", "playbook"))  # label shown to people
        # Header read by the catalogue: ``id`` (what a connection names) and ``kind``.
        self.id = str(spec.get("id", default_id))
        self.kind = str(spec.get("kind", ""))
        self.timeout = int(spec.get("timeout_ms", 8000))
        try:  # player: zones masked before capture; no section = no frame (fail closed)
            self.privacy = Privacy.from_spec(spec.get("privacy"))
        except PrivacyError as exc:
            raise PlaybookError(str(exc)) from exc

    @classmethod
    def load(cls, path: str) -> Playbook:
        with open(path, encoding="utf-8") as handle:
            spec = yaml.safe_load(handle)
        if not isinstance(spec, dict):
            raise PlaybookError("playbook invalide")
        return cls(spec, Path(path).stem)

    def info(self) -> dict[str, Any]:
        """Catalogue entry reported to HospitalOS: no selector, no secret."""
        return {
            "name": self.id,
            "label": self.name,
            "kind": self.kind,
            "tasks": [k for k in TASK_ORDER if self.supports(k)],
        }

    def supports(self, task_kind: str) -> bool:
        return task_kind in self.spec

    @property
    def can_verify(self) -> bool:
        return "verify_reply" in self.spec

    def verification_ready(self, payload: dict[str, Any]) -> bool:
        spec = self.spec.get("verify_reply", {})
        expected = spec.get("expect", {}).get(payload.get("decision"), {})
        required = {"external_ref", "status", "message"}
        required.add("proposed_date" if payload.get("decision") == "accord" else "refusal_reason")
        return required <= set(expected) and required <= set(spec.get("fields", {}))

    # --- steps --------------------------------------------------------------------

    def run_steps(
        self,
        session: BrowserSession,
        steps: list[Any],
        context: dict[str, Any],
        phase: str | None = None,
    ) -> None:
        """Each step may carry a static ``label`` shown in the player (never templated, so
        no screen or payload value can enter it). ``phase="login"``: login steps."""
        page = session.page
        rec = session.recorder
        for step in steps:
            session.checkpoint()
            body = {k: v for k, v in step.items() if k != "label"} if isinstance(step, dict) else {}
            if not body or (len(body) != 1 and "when" not in body):
                raise PlaybookError(f"étape invalide : {step}")
            label = step.get("label")
            if label is not None and not isinstance(label, str):
                raise PlaybookError(f"libellé invalide : {step}")
            try:
                if "when" in body:
                    condition = body["when"]
                    payload = context.get("payload", {})
                    if all(str(payload.get(k)) == str(v) for k, v in condition.items()):
                        self.run_steps(session, body.get("steps", []), context, phase)
                    continue
                ((action, arg),) = body.items()
                if action == "goto":
                    with rec.step(
                        phase or "navigate", label or "Ouvre une page du logiciel", target=str(arg)
                    ):
                        session.goto(render(arg, context))
                elif action == "fill":
                    selector, template = arg["selector"], str(arg["value"])
                    secret = SECRET_FILL.search(template)
                    if secret:  # always masked in every later frame
                        rec.secret_selectors.add(selector)
                    default = (
                        ("Saisit l'identifiant" if secret.group(1) == "username" else
                         "Saisit le mot de passe")
                        if secret
                        else "Remplit un champ"
                    )  # fmt: skip
                    with rec.step(
                        phase or "fill", label or default, target=selector, selector=selector
                    ):
                        page.fill(selector, render(template, context), timeout=self.timeout)
                elif action in ("click", "check"):
                    default = "Clique sur un bouton" if action == "click" else "Coche une case"
                    with rec.step(
                        phase or "click",
                        label or default,
                        target=arg,
                        selector=arg,
                        capture="before",
                    ):
                        if action == "click":
                            page.click(arg, timeout=self.timeout)
                            session._settle()
                        else:
                            page.check(arg, timeout=self.timeout)
                elif action == "select":
                    with rec.step(
                        phase or "select",
                        label or "Choisit une option dans une liste",
                        target=arg["selector"],
                        selector=arg["selector"],
                    ):
                        wanted = render(arg["label"], context)
                        options = page.locator(f"{arg['selector']} option").all_inner_texts()
                        chosen = next((o for o in options if fold(o) == fold(wanted)), None)
                        chosen = chosen or arg.get("fallback")
                        if not chosen:
                            raise PlaybookError(f"option introuvable : {wanted}")
                        page.select_option(arg["selector"], label=chosen, timeout=self.timeout)
                elif action == "wait_for":
                    with rec.step(
                        phase or "wait", label or "Attend l'affichage de la page", target=arg
                    ):
                        page.wait_for_selector(arg, timeout=self.timeout)
                else:
                    raise PlaybookError(f"action inconnue : {action}")
            except PlaywrightTimeout as exc:
                raise PlaybookError(f"le portail ne répond pas comme prévu ({step})") from exc

    def read_fields(
        self, session: BrowserSession, fields: dict[str, Any], transforms: Transforms
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, spec in fields.items():
            locator = session.page.locator(spec["selector"])
            if locator.count() == 0:
                if spec.get("optional"):
                    continue
                raise PlaybookError(f"champ introuvable : {name} ({spec['selector']})")
            raw = locator.first.inner_text()
            if not raw.strip() and spec.get("optional"):
                continue
            try:
                if "map" in spec:  # screen label -> code, declared in the playbook
                    choices = {fold(str(k)): v for k, v in spec["map"].items()}
                    out[name] = choices[fold(raw)]
                    continue
                out[name] = transforms.apply(spec.get("transform"), raw)
            except (ValueError, KeyError, PlaybookError) as exc:
                # Never the screen value (a name may sit in the wrong field): REVIEW S-M2.
                expected = EXPECTED.get(spec.get("transform") or "", "texte")
                if "map" in spec:
                    expected = "un des libellés prévus par le playbook"
                raise PlaybookError(f"champ {name} illisible (attendu : {expected})") from exc
        return out

    # --- tasks ----------------------------------------------------------------------

    def login(self, session: BrowserSession, secrets: dict[str, str]) -> None:
        self.run_steps(session, self.spec.get("login", []), {"secrets": secrets}, "login")

    def read_listing(
        self, session: BrowserSession, task: str, transforms: Transforms
    ) -> list[dict[str, Any]]:
        """Open each row of a list and read the playbook's fields (and only those).
        ``list.label`` and ``list.items`` (plural noun) word the player's transcript."""
        spec = self.spec[task]
        listing = spec["list"]
        rec = session.recorder
        noun = str(listing.get("items", "fiches"))
        with rec.step(
            "navigate", str(listing.get("label", "Ouvre la liste")), target=listing["goto"]
        ):
            session.goto(listing["goto"])
        refs = [
            r.get_attribute(listing["ref_attribute"]) or ""
            for r in session.page.locator(listing["rows"]).all()
        ]
        refs = [r for r in refs if r]
        items: list[dict[str, Any]] = []
        for n, ref in enumerate(refs, start=1):
            target = str(listing["detail_path"])
            with rec.step(
                "navigate", f"Ouvre la fiche {n} sur {len(refs)}", target=target, capture=None
            ):
                session.goto(render(listing["detail_path"], {"ref": ref}))
            with rec.step("read", f"Lit la fiche {n} sur {len(refs)}") as step:
                fields = self.read_fields(session, spec["fields"], transforms)
                step.transmitted = {"count": 1, "fields": sorted(fields)}
            fields.update(spec.get("constants", {}))
            items.append(fields)
        names = sorted({k for item in items for k in item})
        rec.info(f"Lit {len(items)} {noun}", kind="read", outcome="ok",
                 transmitted={"count": len(items), "fields": names})  # fmt: skip
        return items

    def sync_inbox(self, session: BrowserSession, transforms: Transforms) -> list[dict[str, Any]]:
        requests = self.read_listing(session, "sync_inbox", transforms)
        key = self.spec["sync_inbox"].get("patient_ref_from", "external_ref")
        for fields in requests:
            fields["patient_ref"] = fields[key]
        return requests

    def reply(self, session: BrowserSession, payload: dict[str, Any]) -> None:
        self.run_steps(session, self.spec["reply_portal"], {"payload": payload})

    def verify(
        self, session: BrowserSession, payload: dict[str, Any], transforms: Transforms
    ) -> tuple[bool, dict[str, Any]]:
        """Read back the portal and compare with what should have been written."""
        spec = self.spec["verify_reply"]
        context = {"payload": payload}
        rec = session.recorder
        with rec.step(
            "navigate", "Ouvre le dossier pour le relire", target=spec["goto"], capture=None
        ):
            session.goto(render(spec["goto"], context))
        with rec.step("verify", "Relit le dossier") as step:
            observed = self.read_fields(session, spec["fields"], transforms)
            expected = {
                k: render(str(v), context).strip()
                for k, v in spec["expect"].get(str(payload.get("decision")), {}).items()
            }
            ok = bool(expected) and all(
                same_text(observed.get(k, ""), v) for k, v in expected.items()
            )
            step.label = (
                "Relit le dossier : la réponse attendue y figure"
                if ok
                else "Relit le dossier : la réponse attendue n'y figure pas"
            )
        return ok, {"observed": observed, "expected": expected}


def load_catalogue(directory: str | Path = BUNDLED) -> dict[str, Playbook]:
    """Playbooks bundled with this agent (``*.yaml`` with an ``id`` and a ``kind``): the
    only scripts a connection can name. No script is ever received from the API."""
    catalogue: dict[str, Playbook] = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        playbook = Playbook.load(str(path))
        if playbook.kind in ("portail_orientation", "gestion_lits"):
            catalogue[playbook.id] = playbook
    return catalogue
