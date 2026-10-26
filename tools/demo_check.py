"""Check the fictional demo, including a changed form and a human or model handoff.

Run once with v2 and models disabled, then enable a model for this fictional portal
and run with --expect-model. Each run chooses a new dossier; fenced tasks stay fenced.
No routing policy or data permission is changed by this tool.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

T = TypeVar("T")
PASSWORD = "demo-hospitalos-2026"


def wait(what: str, probe: Callable[[], T | None], timeout: float, every: float = 3.0) -> T:
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = probe()
        except httpx.HTTPError:
            value = None
        if value:
            print(f"ok  {what}")
            return value
        if time.monotonic() > deadline:
            raise TimeoutError(f"échec : {what} (après {timeout:.0f} s)")
        time.sleep(every)


def check_outcome(
    task: dict[str, Any],
    observed: dict[str, Any],
    before: dict[str, Any],
    submissions: int,
    variant: str,
    expect_model: bool,
) -> None:
    route = task.get("route", [])
    if variant == "v2":
        if not route or (route[0]["engine"], route[0]["decision"]) != ("playbook", "failure"):
            raise ValueError("v2 : l’échec du script doit apparaître en premier")
        if not expect_model:
            if task["status"] != "needs_human" or observed != before or submissions != 0:
                raise ValueError("v2 sans modèle : reprise humaine sans écriture attendue")
            if task["cost_usd"] != 0:
                raise ValueError("v2 sans modèle : aucun coût de modèle attendu")
            return
    if task["status"] != "done" or submissions != 1:
        raise ValueError("Une seule réponse terminée et relue est attendue")
    if variant == "v2" and (
        task["engine_used"] == "playbook"
        or not any(s["engine"] != "playbook" and s["decision"] == "success" for s in route)
        or task["cost_usd"] <= 0
    ):
        raise ValueError("v2 : succès d’un moteur à modèle et coût enregistré attendus")
    payload = task["payload"]
    if (
        observed["status"] != "Accord donné"
        or observed["proposed"] != payload["proposed_date"]
        or (observed["message"] or "").replace("\r\n", "\n")
        != payload["message"].replace("\r\n", "\n")
    ):
        raise ValueError("Le portail ne montre pas exactement la décision, la date et le message")


def run(api: httpx.Client, portal: httpx.Client, timeout: float, expect_model: bool) -> None:
    def token() -> str | None:
        r = api.post(
            "/auth/login", json={"email": "coordination@demo.hospitalos.fr", "password": PASSWORD}
        )
        return str(r.json()["token"]) if r.status_code == 200 else None

    headers = {"Authorization": f"Bearer {wait('API et compte de démo', token, timeout)}"}
    variant_response = portal.get("/_test/variant")
    variant_response.raise_for_status()
    variant = variant_response.json()["variant"]

    def from_portal() -> list[dict[str, Any]]:
        r = api.get("/requests", params={"scope": "toutes"}, headers=headers)
        r.raise_for_status()
        return [row for row in r.json() if row["source"] == "portail"]

    wait(
        "agent en ligne",
        lambda: api.get("/agent/status", headers=headers).json()["online"],
        timeout,
    )

    # A prior run's ambiguous task is never retried or closed by this checker.
    def new_dossier() -> dict[str, Any] | None:
        return next((row for row in from_portal() if row["status"] == "nouvelle"), None)

    request = wait("nouveau dossier relevé sur le portail", new_dossier, timeout)
    ref = request["external_ref"]
    before = portal.get("/_test/state").json()[ref]
    if portal.get("/_test/submissions").json().get(ref, 0):
        raise ValueError("Choisir un dossier sans réponse préalable sur le portail")
    detail = api.get(f"/requests/{request['id']}", headers=headers).json()
    best = detail["best"]
    if not best or not (best["safe_date"] or best["probable_date"]):
        raise ValueError("Aucune date proposée pour ce dossier ; vérifier les lits de démo")
    day = best["safe_date"] or best["probable_date"]
    r = api.post(
        f"/requests/{request['id']}/accord",
        json={"site_id": best["site_id"], "proposed_date": day},
        headers=headers,
    )
    r.raise_for_status()
    print(f"ok  accord donné sur {ref} pour le {day}")

    def finished() -> dict[str, Any] | None:
        tasks = api.get("/agent/tasks", params={"limit": 500}, headers=headers).json()
        return next(
            (
                t
                for t in tasks
                if t["request_id"] == request["id"]
                and t["status"] in ("done", "needs_human", "failed")
            ),
            None,
        )

    task = wait("traitement terminé", finished, timeout)
    check_outcome(
        task,
        portal.get("/_test/state").json()[ref],
        before,
        portal.get("/_test/submissions").json().get(ref, 0),
        variant,
        expect_model,
    )
    if task["status"] == "needs_human":
        print("ok  v2 : script en échec, reprise humaine, aucune écriture ni coût")
    else:
        print(
            f"ok  {variant} : réponse exacte et relue ; moteur {task['engine_used']}, "
            f"coût {task['cost_usd']:.4f} USD"
        )
    for step in task["route"]:
        print(f"    {step['engine']} : {step['decision']} — {step['reason']}")
    new_ref = portal.post("/_test/arrive").json()["ref"]
    api.post("/agent/sync", headers=headers).raise_for_status()
    wait(
        "nouvelle arrivée relevée",
        lambda: any(x["external_ref"] == new_ref for x in from_portal()),
        timeout,
    )
    print("Démo computer use : parcours vérifié.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", default="http://localhost:8080")
    parser.add_argument("--portal", default="http://localhost:8020")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--expect-model", action="store_true", help="Attendre un relais modèle en v2"
    )
    args = parser.parse_args()
    expect_model = args.expect_model or bool(os.getenv("ANTHROPIC_API_KEY"))
    with (
        httpx.Client(base_url=f"{args.web}/api", timeout=30) as api,
        httpx.Client(base_url=args.portal, timeout=30) as portal,
    ):
        run(api, portal, args.timeout, expect_model)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (TimeoutError, ValueError, httpx.HTTPError) as exc:
        print(f"Échec de la vérification : {exc}", file=sys.stderr)
        sys.exit(1)
