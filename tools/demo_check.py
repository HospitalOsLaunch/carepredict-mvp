"""End-to-end check of a running demo (docker-compose.demo.yml).

    python tools/demo_check.py --web http://localhost:8080 --portal http://localhost:8020
    python tools/demo_check.py --web http://localhost:8510 --liscop-only   # API alone

Computer use (skipped with --liscop-only):

1. the agent is online and has read the portal: requests from the portal exist;
2. a coordinator gives an accord in HospitalOS;
3. the agent writes that reply on the portal and it is verified ("done");
4. the portal shows the reply;
5. the admin pauses the portal connection: a new request arriving on the portal does not
   reach HospitalOS and no task of that connection is claimed while paused; the admin
   resumes it and the request arrives;
6. the MCO worker has read the fictional bed software (its connection has a last run).

LISCOP (fictional MCO hospital, seed-demo-mco):

7. an HL7 ADT^A04 message (from the test fixture, with fresh identifiers) posted with the
   ingestion account is acknowledged MSA|AA;
8. a forecast run is stored (the forecast job ran): /api/forecast/liscop has a run;
9. the ROR export has a unit forecast as "disponibles attendus";
10. /api/ed/census and /api/beds/availability answer 200.

Exit code 0 when every step passed, 1 otherwise. Used by the CI and by hand.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

import httpx

T = TypeVar("T")
PASSWORD = "demo-hospitalos-2026"
MCO_DOMAIN = "ch-demo.hospitalos.fr"  # seed_mco.EMAIL_DOMAIN
HL7_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "services/admissions_smr/tests/fixtures/hl7/a04_ed_arrival.hl7"
)


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


def login(api: httpx.Client, email: str) -> dict[str, str] | None:
    r = api.post("/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {r.json()['token']}"} if r.status_code == 200 else None


def fresh_hl7(now: datetime) -> bytes:
    """The A04 fixture with new message, movement, visit and patient identifiers, dated now
    (local time, as a hospital information system sends it)."""
    tag = uuid.uuid4().hex[:8].upper()
    stamp = now.strftime("%Y%m%d%H%M%S")
    text = HL7_FIXTURE.read_text(encoding="utf-8")
    for old, new in (
        ("MSG-A04", f"DEMO{tag}"),
        ("MVT-10", f"MVT{tag}"),
        ("900002", f"9{int(tag, 16) % 10**8:08d}"),
        ("IPP5151", f"IPP{int(tag, 16) % 10**8:08d}"),
        ("20261025021500", stamp),
        ("20261025021000", stamp),
    ):
        text = text.replace(old, new)
    return "\r".join(line for line in text.splitlines() if line).encode("utf-8")


def check_liscop(api: httpx.Client, timeout: float) -> None:
    agent = wait("compte d'ingestion MCO", lambda: login(api, f"agent@{MCO_DOMAIN}"), timeout)
    r = api.post(
        "/ingest/hl7",
        content=fresh_hl7(datetime.now(ZoneInfo("Europe/Paris"))),
        headers={**agent, "Content-Type": "x-application/hl7-v2+er7"},
    )
    if "MSA|AA" not in r.text:
        raise SystemExit(f"échec : message HL7 non accepté ({r.status_code}) : {r.text[:300]}")
    print("ok  message HL7 ADT^A04 accusé MSA|AA")
    admin = login(api, f"admin@{MCO_DOMAIN}")
    if admin is None:
        raise SystemExit("échec : connexion au compte admin de l'hôpital MCO de démonstration")

    def run() -> dict[str, Any] | None:
        body = api.get("/forecast/liscop", headers=admin).json()
        return body["run"] if body.get("run") else None

    stored = wait("prévision LISCOP calculée et stockée", run, timeout)
    print(f"    run {stored['id']} du {stored['as_of']}, modèle {stored['model_version']}")
    units = api.get("/ror/export", headers=admin).raise_for_status().json()["unites"]
    expected = [u for u in units if u["previsionnel_nature"]["nature"] == "disponibles_attendus"]
    if not expected:
        raise SystemExit("échec : aucune unité de l'export ROR en « disponibles attendus »")
    print(f"ok  export ROR : {len(expected)} unités en « disponibles attendus »")
    for path in ("/ed/census", "/beds/availability"):
        r = api.get(path, headers=admin)
        if r.status_code != 200:
            raise SystemExit(f"échec : {path} répond {r.status_code}")
        print(f"ok  {path} répond 200")


def check_pause_resume(api: httpx.Client, portal: httpx.Client, seconds: float) -> str:
    """Pause the SMR portal connection, check that nothing runs for it, then resume it.
    Returns the reference of the request that arrived on the portal during the pause."""
    admin = login(api, "admin@demo.hospitalos.fr")
    if admin is None:
        raise SystemExit("échec : connexion au compte admin de démonstration")
    connections = api.get("/agent/connections", headers=admin).raise_for_status().json()
    conn = next(c for c in connections if c["kind"] == "portail_orientation")
    paused = api.post(f"/agent/connections/{conn['id']}/pause", headers=admin)
    paused.raise_for_status()
    if paused.json()["status"] != "en_pause":
        raise SystemExit("échec : la connexion du portail n'est pas en pause")
    print(f"ok  connexion « {conn['name']} » mise en pause")
    refused = api.post(f"/agent/connections/{conn['id']}/sync", headers=admin).status_code
    if refused != 409:
        raise SystemExit(f"échec : relève acceptée sur une connexion en pause ({refused})")
    runs_url = f"/agent/connections/{conn['id']}/runs"
    before = {r["id"]: r["status"] for r in api.get(runs_url, headers=admin).json()}
    new_ref = str(portal.post("/_test/arrive").json()["ref"])
    time.sleep(seconds)
    after = {r["id"]: r["status"] for r in api.get(runs_url, headers=admin).json()}
    moved = [i for i, s in after.items() if s in ("running", "done") and before.get(i) != s]
    rows = api.get("/requests", params={"scope": "toutes"}, headers=admin).json()
    if moved or any(r["external_ref"] == new_ref for r in rows):
        raise SystemExit("échec : l'agent a travaillé pour une connexion en pause")
    print(f"ok  rien de relevé ni réservé pendant {seconds:.0f} s de pause")
    resumed = api.post(f"/agent/connections/{conn['id']}/resume", headers=admin)
    resumed.raise_for_status()
    print("ok  connexion reprise")
    return new_ref


def check_bed_connection(api: httpx.Client, timeout: float) -> None:
    admin = wait("compte admin MCO", lambda: login(api, f"admin@{MCO_DOMAIN}"), timeout)

    def ran() -> dict[str, Any] | None:
        rows = api.get("/agent/connections", headers=admin).json()
        beds = next((c for c in rows if c["kind"] == "gestion_lits"), None)
        return beds if beds and beds["last_run_at"] else None

    beds = wait("logiciel de gestion des lits relevé par le poste MCO", ran, timeout)
    print(f"    dernier passage : {beds['last_outcome']} {beds['last_error'] or ''}".rstrip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", default="http://localhost:8080")
    parser.add_argument("--portal", default="http://localhost:8020")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=50,
        help="Durée d'observation d'une connexion en pause (plus de deux cycles d'agent)",
    )
    parser.add_argument(
        "--liscop-only", action="store_true", help="Contrôles LISCOP seulement (sans agent)"
    )
    args = parser.parse_args()
    api = httpx.Client(base_url=f"{args.web}/api", timeout=30)
    if args.liscop_only:
        check_liscop(api, args.timeout)
        print("Démo LISCOP : tout fonctionne.")
        return 0
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
    new_ref = check_pause_resume(api, portal, args.pause_seconds)
    wait(
        f"nouvelle demande {new_ref} arrivée dans HospitalOS après la reprise",
        lambda: any(x["external_ref"] == new_ref for x in from_portal()),
        args.timeout,
    )
    check_bed_connection(api, args.timeout)
    print("Démo computer use : tout fonctionne.")
    check_liscop(api, args.timeout)
    print("Démo LISCOP : tout fonctionne.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TimeoutError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
