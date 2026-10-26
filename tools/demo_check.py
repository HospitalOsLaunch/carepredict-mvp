"""End-to-end check of a running computer-use demo (docker-compose.demo.yml).

    python tools/demo_check.py --web http://localhost:8080 --portal http://localhost:8020

1. the agent is online and has read the portal: requests from the portal exist;
2. a coordinator gives an accord in HospitalOS;
3. the agent writes that reply on the portal and it is verified ("done");
4. the portal shows the reply;
5. a new request arriving on the portal reaches HospitalOS.

Exit code 0 when every step passed, 1 otherwise. Used by the CI and by hand.
"""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", default="http://localhost:8080")
    parser.add_argument("--portal", default="http://localhost:8020")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    api = httpx.Client(base_url=f"{args.web}/api", timeout=30)
    portal = httpx.Client(base_url=args.portal, timeout=30)

    def token() -> str | None:
        r = api.post(
            "/auth/login", json={"email": "coordination@demo.hospitalos.fr", "password": PASSWORD}
        )
        return str(r.json()["token"]) if r.status_code == 200 else None

    headers = {
        "Authorization": f"Bearer {wait('API joignable, compte de démo', token, args.timeout)}"
    }

    def from_portal() -> list[dict[str, Any]]:
        rows = api.get("/requests", params={"scope": "toutes"}, headers=headers).json()
        return [r for r in rows if r["source"] == "portail"]

    def online() -> bool:
        return bool(api.get("/agent/status", headers=headers).json()["online"])

    wait("agent en ligne", online, args.timeout)
    rows = wait("demandes relevées sur le portail", from_portal, args.timeout)
    request = next(r for r in rows if r["status"] == "nouvelle")
    detail = api.get(f"/requests/{request['id']}", headers=headers).json()
    best = detail["best"]
    day = best["safe_date"] or best["probable_date"]
    r = api.post(
        f"/requests/{request['id']}/accord",
        json={"site_id": best["site_id"], "proposed_date": day},
        headers=headers,
    )
    r.raise_for_status()
    print(f"ok  accord donné sur {request['external_ref']} pour le {day}")

    def replied() -> str | None:
        reply = api.get(f"/requests/{request['id']}", headers=headers).json()["portal_reply"]
        if reply and reply["status"] in ("needs_human", "failed"):
            raise SystemExit(f"échec : report sur le portail en état {reply['status']}")
        return str(reply["engine_used"]) if reply and reply["status"] == "done" else None

    engine = wait("réponse reportée et relue sur le portail", replied, args.timeout)
    print(f"    moteur : {engine}")

    def shown() -> bool:
        state = portal.get("/_test/state").json()[request["external_ref"]]
        return bool(state["status"] == "Accord donné" and state["proposed"] == day)

    wait("le portail affiche l'accord à la bonne date", shown, 30)
    new_ref = portal.post("/_test/arrive").json()["ref"]
    r = api.post("/agent/sync", headers=headers)
    r.raise_for_status()
    wait(
        f"nouvelle demande {new_ref} arrivée dans HospitalOS",
        lambda: any(x["external_ref"] == new_ref for x in from_portal()),
        args.timeout,
    )
    print("Démo computer use : tout fonctionne.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TimeoutError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
