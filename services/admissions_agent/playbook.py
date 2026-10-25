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
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from services.admissions_agent.browser import BrowserSession

PARIS = ZoneInfo("Europe/Paris")
_TEMPLATE = re.compile(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}")


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
        raise PlaybookError(f"libellé non reconnu ({vocabulary}) : « {label} »")


class Playbook:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.name = str(spec.get("name", "playbook"))
        self.timeout = int(spec.get("timeout_ms", 8000))

    @classmethod
    def load(cls, path: str) -> Playbook:
        with open(path, encoding="utf-8") as handle:
            spec = yaml.safe_load(handle)
        if not isinstance(spec, dict):
            raise PlaybookError("playbook invalide")
        return cls(spec)

    def supports(self, task_kind: str) -> bool:
        return task_kind in self.spec

    @property
    def can_verify(self) -> bool:
        return "verify_reply" in self.spec

    # --- steps --------------------------------------------------------------------

    def run_steps(self, session: BrowserSession, steps: list[Any], context: dict[str, Any]) -> None:
        page = session.page
        for step in steps:
            if not isinstance(step, dict) or (len(step) != 1 and "when" not in step):
                raise PlaybookError(f"étape invalide : {step}")
            try:
                if "when" in step:
                    condition = step["when"]
                    payload = context.get("payload", {})
                    if all(str(payload.get(k)) == str(v) for k, v in condition.items()):
                        self.run_steps(session, step.get("steps", []), context)
                    continue
                ((action, arg),) = step.items()
                if action == "goto":
                    session.goto(render(arg, context))
                elif action == "fill":
                    page.fill(arg["selector"], render(arg["value"], context), timeout=self.timeout)
                elif action == "click":
                    page.click(arg, timeout=self.timeout)
                    session._settle()
                elif action == "check":
                    page.check(arg, timeout=self.timeout)
                elif action == "select":
                    label = render(arg["label"], context)
                    options = page.locator(f"{arg['selector']} option").all_inner_texts()
                    chosen = next((o for o in options if fold(o) == fold(label)), None)
                    chosen = chosen or arg.get("fallback")
                    if not chosen:
                        raise PlaybookError(f"option introuvable : {label}")
                    page.select_option(arg["selector"], label=chosen, timeout=self.timeout)
                elif action == "wait_for":
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
                out[name] = transforms.apply(spec.get("transform"), raw)
            except (ValueError, PlaybookError) as exc:
                raise PlaybookError(f"champ {name} illisible : « {raw.strip()} » ({exc})") from exc
        return out

    # --- tasks ----------------------------------------------------------------------

    def login(self, session: BrowserSession, secrets: dict[str, str]) -> None:
        self.run_steps(session, self.spec.get("login", []), {"secrets": secrets})

    def sync_inbox(self, session: BrowserSession, transforms: Transforms) -> list[dict[str, Any]]:
        spec = self.spec["sync_inbox"]
        listing = spec["list"]
        session.goto(listing["goto"])
        refs = [
            r.get_attribute(listing["ref_attribute"]) or ""
            for r in session.page.locator(listing["rows"]).all()
        ]
        requests: list[dict[str, Any]] = []
        for ref in [r for r in refs if r]:
            session.goto(render(listing["detail_path"], {"ref": ref}))
            fields = self.read_fields(session, spec["fields"], transforms)
            fields.update(spec.get("constants", {}))
            fields["patient_ref"] = fields[spec.get("patient_ref_from", "external_ref")]
            requests.append(fields)
        return requests

    def reply(self, session: BrowserSession, payload: dict[str, Any]) -> None:
        self.run_steps(session, self.spec["reply_portal"], {"payload": payload})

    def verify(
        self, session: BrowserSession, payload: dict[str, Any], transforms: Transforms
    ) -> tuple[bool, dict[str, Any]]:
        """Read back the portal and compare with what should have been written."""
        spec = self.spec["verify_reply"]
        context = {"payload": payload}
        session.goto(render(spec["goto"], context))
        observed = self.read_fields(session, spec["fields"], transforms)
        expected = {
            k: render(str(v), context)
            for k, v in spec["expect"].get(str(payload.get("decision")), {}).items()
        }
        ok = bool(expected) and all(str(observed.get(k, "")) == v for k, v in expected.items())
        return ok, {"observed": observed, "expected": expected}
