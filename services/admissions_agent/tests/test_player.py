"""Agent player, end to end with real Chromium: every frame is masked before capture, the
transcript carries no value read on screen, and the rules fail closed."""

from __future__ import annotations

import io
import json
import threading
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.demo_bedsoft import app as bedsoft_module
from services.admissions_agent.demo_portal import app as portal_module
from services.admissions_agent.playbook import Playbook, PlaybookError
from services.admissions_agent.replay import (
    MASK_COLOR,
    Privacy,
    PrivacyError,
    StepRefused,
    StepUploader,
)
from services.admissions_agent.tests.conftest import db, login
from services.admissions_agent.tests.test_demo_bedsoft import bedsoft_agent
from services.admissions_smr.models import AgentTaskStep

PORTAL_PLAYBOOK = Path(portal_module.__file__).parent.parent / "playbooks" / "demo_portal.yaml"
MASK_RGB = tuple(int(MASK_COLOR[i : i + 2], 16) for i in (1, 3, 5))
PASSWORDS = ("demo-portail", "demo-lits")


def steps_of(api: TestClient, kind: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    admin = login(api, "admin@test.fr")
    task = next(t for t in api.get("/api/agent/tasks", headers=admin).json() if t["kind"] == kind)
    replay = api.get(f"/api/agent/tasks/{task['id']}/replay", headers=admin)
    assert replay.status_code == 200, replay.text
    return task, replay.json()["steps"]


def frame(api: TestClient, step: dict[str, Any]) -> Image.Image:
    r = api.get(f"/api/agent/steps/{step['id']}/frame", headers=login(api, "admin@test.fr"))
    assert r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff"
    image = Image.open(io.BytesIO(r.content)).convert("RGB")
    assert image.width <= 1280
    return image


def covered(image: Image.Image, box: dict[str, float], inset: int = 2) -> bool:
    """Every pixel inside the box (minus a JPEG edge margin) is the mask colour."""
    left, top = int(box["x"]) + inset, int(box["y"]) + inset
    right = min(int(box["x"] + box["w"]) - inset, image.width)
    bottom = min(int(box["y"] + box["h"]) - inset, image.height)
    assert right > left and bottom > top, box
    pixels = image.load()
    assert pixels is not None
    for x in range(left, right):
        for y in range(top, bottom):
            r, g, b = pixels[x, y][:3]  # type: ignore[index]
            # JPEG rings at corners (up to ~60); dark text alone would be over 150.
            if abs(r - MASK_RGB[0]) + abs(g - MASK_RGB[1]) + abs(b - MASK_RGB[2]) > 90:
                return False
    return True


def boxes(url: str, path: str, selectors: list[str], credentials: tuple[str, ...] = ()) -> Any:
    """Where the zones sit on an unscrolled screen, measured independently of the agent."""
    session = BrowserSession(url, ("127.0.0.1",))
    try:
        if credentials:  # (login path, user field, user, password field, password)
            session.goto(credentials[0])
            session.page.fill(credentials[1], credentials[2])
            session.page.fill(credentials[3], credentials[4])
            session.page.click("button[type=submit]")
            session.page.wait_for_load_state("networkidle")
        session.goto(path)
        out: dict[str, list[dict[str, float]]] = {}
        for selector in selectors:
            out[selector] = [
                {"x": b["x"], "y": b["y"], "w": b["width"], "h": b["height"]}
                for b in (el.bounding_box() for el in session.page.locator(selector).all())
                if b
            ]
        return out
    finally:
        session.close()


def no_value_in_steps(api: TestClient, forbidden: list[str]) -> None:
    """Nothing read on screen in the stored steps (labels, targets, masks, transmitted)."""
    session = db(api)
    rows = session.scalars(select(AgentTaskStep)).all()
    text = " ".join(
        f"{s.label} {s.target} {s.masks_json} {s.transmitted_json} {s.pointer_json}" for s in rows
    )
    session.close()
    assert rows
    assert [v for v in forbidden if v in text] == []


def test_portal_frames_are_masked_and_the_transcript_is_clean(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any], portal_url: str
) -> None:
    assert make_agent().cycle() == 1
    task, steps = steps_of(api, "sync_inbox")
    labels = [s["label"] for s in steps]
    assert labels[0] == "Début du passage : relève des demandes"
    assert "Saisit le mot de passe" in labels and "Lit la fiche 3 sur 3" in labels
    assert "Lit 3 demandes" in labels and labels[-1] == "Passage terminé : réussi"
    sent = next(s for s in steps if s["label"].startswith("Transmet 3 demande(s)"))
    assert sent["transmitted"]["count"] == 3 and sent["transmitted"]["applied"] == 3
    assert "external_ref" in sent["transmitted"]["fields"]
    assert [s["seq"] for s in steps] == sorted(s["seq"] for s in steps)
    click = next(s for s in steps if s["label"] == "Valide la connexion")
    assert click["pointer"] and click["box"] and click["has_frame"]

    login_boxes = boxes(portal_url, "/login", ["#identifiant", "#mot-de-passe"])
    detail = boxes(
        portal_url,
        "/dossiers/DOS-2026-0412",
        ["#patient"],
        ("/login", "#identifiant", "demo", "#mot-de-passe", "demo-portail"),
    )
    framed = [s for s in steps if s["has_frame"]]
    assert len(framed) >= 8
    for step in framed:
        image = frame(api, step)
        for mask in step["masks"]:  # every zone the agent declares is really covered
            assert covered(image, mask), (step["label"], mask)
        if step["label"].startswith("Lit la fiche"):
            assert covered(image, detail["#patient"][0]), step["label"]
            assert not covered(image, {"x": 24, "y": 90, "w": 300, "h": 30})  # the title
        if step["label"] == "Saisit le mot de passe":
            assert covered(image, login_boxes["#mot-de-passe"][0])
            assert covered(image, login_boxes["#identifiant"][0])
    names = [d.patient_name for d in portal_module.sample().values()]
    no_value_in_steps(api, [*names, "Jeanne", "Exemple", *PASSWORDS])


def boxes_logged(url: str, path: str, selectors: list[str]) -> Any:
    return boxes(url, path, selectors, ("/connexion", "#utilisateur", "cadre", "#mdp", "demo-lits"))


def test_bedsoft_frames_mask_names_birth_dates_and_clear_identifiers(
    api: TestClient, bedsoft: httpx.Client, mco: None
) -> None:
    url = str(bedsoft.base_url)
    assert bedsoft_agent(api, url).cycle() == 1
    _, steps = steps_of(api, "sync_movements")
    sent = next(s for s in steps if s["label"].startswith("Transmet 8 mouvement(s)"))
    assert sent["transmitted"]["applied"] == 8 and sent["transmitted"]["rejected"] == 0
    assert "Lit 7 mouvements" in [s["label"] for s in steps]

    listing = boxes_logged(url, "/mouvements", ["td.patient"])["td.patient"]
    detail = boxes_logged(url, "/mouvements/BS-0001", ["#patient", "#naissance", "#ipp"])
    assert len(listing) == 7
    framed = [s for s in steps if s["has_frame"]]
    seen_list = seen_detail = 0
    for step in framed:
        image = frame(api, step)
        for mask in step["masks"]:
            assert covered(image, mask), (step["label"], mask)
        if step["label"] in (
            "Ouvre la liste des mouvements du jour",
            "Attend la liste des mouvements",
        ):
            seen_list += 1
            assert all(covered(image, box) for box in listing), step["label"]
        if step["label"].startswith("Lit la fiche"):
            seen_detail += 1
            assert all(covered(image, b[0]) for b in detail.values()), step["label"]
    assert seen_list == 2 and seen_detail == 7
    rows = bedsoft_module.sample().values()
    births = {f"{r.birth:%d/%m/%Y}" for r in rows} | {r.birth.isoformat() for r in rows}
    no_value_in_steps(api, [*{r.name for r in rows}, *births, *PASSWORDS, "4000101", "7000101"])


def without_privacy(tmp_path: Path, **privacy: Any) -> str:
    spec = yaml.safe_load(PORTAL_PLAYBOOK.read_text())
    spec.pop("privacy")
    if privacy:
        spec["privacy"] = privacy
    path = tmp_path / "pb.yaml"
    path.write_text(yaml.safe_dump(spec, allow_unicode=True))
    return str(path)


def test_a_playbook_without_privacy_yields_steps_without_frames(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any], tmp_path: Path
) -> None:
    assert make_agent(playbook_path=without_privacy(tmp_path)).cycle() == 1
    _, steps = steps_of(api, "sync_inbox")
    assert len(steps) > 10 and not any(s["has_frame"] for s in steps)


def test_a_declared_zone_missing_on_its_screen_withholds_the_frame(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any], tmp_path: Path
) -> None:
    privacy = {
        "mask": [{"selector": "#nom-renomme", "reason": "identite", "screen": "/dossiers/*"}]
    }
    assert make_agent(playbook_path=without_privacy(tmp_path, **privacy)).cycle() == 1
    _, steps = steps_of(api, "sync_inbox")
    reads = [s for s in steps if s["label"].startswith("Lit la fiche")]
    assert len(reads) == 3
    for step in reads:
        assert not step["has_frame"]
        assert step["label"].endswith("(capture retenue : zone à protéger introuvable)")
    assert any(s["has_frame"] for s in steps if s["kind"] == "login")  # other screens


def test_model_actions_become_steps_with_their_gesture(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any], tmp_path: Path
) -> None:
    from services.admissions_agent.tests.test_agent_e2e import (
        ANTHROPIC,
        ScriptedClaude,
        accord,
        broken_playbook,
        claude_factory,
        enable_claude,
        set_policy,
        track,
        typed,
    )

    make_agent().cycle()
    set_policy(api, enable_claude)
    proposed = accord(api, "DOS-2026-0412")
    sessions: list[BrowserSession] = []
    fake = ScriptedClaude(sessions, typed(proposed))
    agent = make_agent(
        claude_factory(fake), ANTHROPIC, broken_playbook(tmp_path, str(PORTAL_PLAYBOOK))
    )
    track(agent, sessions)
    agent.last_sync = time.monotonic()
    assert agent.cycle() == 1
    task, steps = steps_of(api, "reply_portal")
    assert task["status"] == "done"
    model = [s for s in steps if s["kind"] == "model_action"]
    assert {s["engine"] for s in model} == {"closed_best"}
    clicks = [s for s in model if s["label"] == "Clique à l'endroit choisi par le modèle"]
    assert len(clicks) == 4 and all(s["pointer"] and s["has_frame"] for s in clicks)
    assert "Saisit un texte (10 caractères)" in [s["label"] for s in model]
    assert any(s["label"] == "Fait défiler vers le bas" for s in model)
    failed = [s for s in steps if s["outcome"] == "fail" and s["engine"] == "playbook"]
    assert failed and failed[0]["target"] == "#bouton-renomme"
    verify = [s for s in steps if s["kind"] == "verify"]
    assert verify[-1]["label"] == "Relit le dossier : la réponse attendue y figure"
    message = json.loads(json.dumps(fake.calls[0]["body"]))["messages"][0]["content"][0]["text"]
    no_value_in_steps(api, [message.split("\n---\n")[1][:40], proposed, typed(proposed)])
    assert date.fromisoformat(proposed)  # the date itself is never in a label


# --- units ------------------------------------------------------------------------------


def test_privacy_section_is_validated() -> None:
    assert not Privacy.from_spec(None).enabled
    rules = Privacy.from_spec({"mask": [{"selector": "#p", "screen": ["/a/*", "/b"]}]}).rules
    assert rules and rules[0].reason == "identite" and rules[0].required("/a/1")
    assert not rules[0].required("/c")
    for bad in (
        {"mask": "#p"},
        {"mask": [{"reason": "identite"}]},
        {"mask": [{"selector": "#p", "reason": "nom"}]},
        {"mask": [{"selector": "#p", "screen": "dossiers"}]},
        {"mask": [{"selector": "#p", "on": "/x"}]},
    ):
        with pytest.raises(PrivacyError):
            Privacy.from_spec(bad)
    with pytest.raises(PlaybookError):
        Playbook({"privacy": {"mask": [{"selector": "#p", "reason": "?"}]}})


def test_uploader_drops_frames_not_steps_when_the_api_is_slow() -> None:
    gate = threading.Event()
    sent: list[tuple[int, bool]] = []

    def post(meta: dict[str, Any], frame: bytes | None, timeout: float) -> None:
        gate.wait(5)
        sent.append((meta["seq"], frame is not None))

    uploader = StepUploader(post, max_steps=50, max_frames=2)
    for seq in range(1, 11):
        uploader.submit({"seq": seq}, b"\xff\xd8\xff")
    gate.set()
    uploader.close(5)
    assert [s for s, _ in sent] == list(range(1, 11))  # every step
    assert sum(f for _, f in sent) <= 3 and uploader.dropped_frames >= 7


def test_uploader_stops_when_refused_and_never_blocks() -> None:
    calls: list[int] = []

    def refused(meta: dict[str, Any], frame: bytes | None, timeout: float) -> None:
        calls.append(meta["seq"])
        raise StepRefused("409")

    uploader = StepUploader(refused)
    for seq in range(1, 6):
        uploader.submit({"seq": seq}, None)
    uploader.close(5)
    assert calls == [1]

    def stuck(meta: dict[str, Any], frame: bytes | None, timeout: float) -> None:
        time.sleep(2)

    uploader = StepUploader(stuck, max_steps=3)
    started = time.monotonic()
    for seq in range(1, 20):
        uploader.submit({"seq": seq}, b"x")  # a full queue drops, never waits
    uploader.close(0.2)
    assert time.monotonic() - started < 1 and uploader.dropped_steps > 0
