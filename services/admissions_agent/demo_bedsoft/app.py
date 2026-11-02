"""A fictional bed-management software ("Gestion des lits, démonstration").

What such software shows a bed manager: the movements of the day (entries, emergency
arrivals and hospitalisations, transfers, leaves, discharges), each with the patient's
name and birth date on screen, on purpose, to test that the agent never copies them. It
imitates no real product: generic look, invented names and numbers, the units of the
``seed-demo-mco`` hospital.

    uvicorn services.admissions_agent.demo_bedsoft.app:app --port 8120

``POST /_test/arrive`` adds an entry, ``POST /_test/cancel/{id}`` cancels a movement,
``POST /_test/reset`` restores the sample: demonstration helpers no real software has.
"""

from __future__ import annotations

import html
import os
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

USERNAME = os.getenv("DEMO_BEDSOFT_USER", "cadre")
PASSWORD = os.getenv("DEMO_BEDSOFT_PASSWORD", "demo-lits")
PARIS = ZoneInfo("Europe/Paris")

TYPES = {
    "A01": "Entrée",
    "A02": "Mutation",
    "A03": "Sortie",
    "A04": "Arrivée aux urgences",
    "A06": "Hospitalisation depuis les urgences",
    "A21": "Absence provisoire",
    "A22": "Retour d'absence",
}
UNITS = {
    "1001": "Urgences",
    "2101": "Médecine polyvalente",
    "2301": "Cardiologie",
    "5201": "SMR gériatrie",
}


@dataclass
class Row:
    id: str
    type: str  # A01...
    minutes: int  # minutes after midnight, today
    venue: str
    ipp: str
    name: str
    birth: date
    sex: str
    uf: str
    room: str = ""
    bed: str = ""
    cancelled: bool = False

    def at(self, day: date) -> datetime:
        return datetime.combine(day, time(0), tzinfo=PARIS) + timedelta(minutes=self.minutes)


def sample() -> dict[str, Row]:
    rows = [
        Row("BS-0001", "A04", 7 * 60 + 12, "7000101", "4000101", "Mme Rosalie Exemplaire",
            date(1941, 3, 12), "F", "1001"),
        Row("BS-0002", "A06", 9 * 60 + 40, "7000101", "4000101", "Mme Rosalie Exemplaire",
            date(1941, 3, 12), "F", "2101", "2103", "2103"),
        Row("BS-0003", "A01", 8 * 60 + 5, "7000102", "4000102", "M. Gaston Fictif",
            date(1958, 11, 2), "M", "2301", "2302", "2302"),
        Row("BS-0004", "A02", 11 * 60 + 30, "7000102", "4000102", "M. Gaston Fictif",
            date(1958, 11, 2), "M", "2101", "2116", "2116A"),
        Row("BS-0005", "A01", 6 * 60 + 50, "7000103", "4000103", "Mme Odile Imaginaire",
            date(1936, 7, 21), "F", "5201", "5203", "5203"),
        Row("BS-0006", "A03", 10 * 60 + 15, "7000103", "4000103", "Mme Odile Imaginaire",
            date(1936, 7, 21), "F", "5201", "5203", "5203"),
        Row("BS-0007", "A01", 10 * 60, "7000104", "4000104", "M. Hector Modèle",
            date(1970, 1, 30), "M", "2101", "2104", "2104", cancelled=True),
    ]  # fmt: skip
    return {r.id: r for r in rows}


def wall_clock() -> datetime:
    return datetime.now(PARIS)


@dataclass
class Store:
    rows: dict[str, Row] = field(default_factory=sample)
    sessions: set[str] = field(default_factory=set)
    added: int = 0
    clock: Callable[[], datetime] = wall_clock  # tests freeze it (REVIEW T-18)


store = Store()
app = FastAPI(title="Gestion des lits (démonstration)", docs_url=None, redoc_url=None)

STYLE = """
body{font-family:Verdana,Geneva,sans-serif;margin:0;background:#eef1ee;color:#1d2a1d}
header{background:#2f5d50;color:#fff;padding:10px 20px;font-size:17px}
main{padding:20px;max-width:1100px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px}
td,th{border:1px solid #c5d0c5;padding:6px;text-align:left}
dl{display:grid;grid-template-columns:200px 1fr;background:#fff;padding:14px}
dt{font-weight:bold}
.annule{color:#999;text-decoration:line-through}
"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>{title}</title>"
        f"<style>{STYLE}</style></head><body><header>Gestion des lits "
        f"(démonstration)</header><main>{body}</main></body></html>"
    )


def esc(value: object) -> str:
    return html.escape(str(value))


def logged_in(request: Request) -> bool:
    return request.cookies.get("session") in store.sessions


def age(birth: date, day: date) -> int:
    return day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))


@app.get("/connexion")
def login_form() -> HTMLResponse:
    return page(
        "Connexion",
        """
      <h1>Connexion</h1>
      <form method="post" action="/connexion">
        <label for="utilisateur">Utilisateur</label> <input id="utilisateur" name="utilisateur">
        <label for="mdp">Mot de passe</label> <input id="mdp" name="mdp" type="password">
        <button type="submit">Entrer</button>
      </form>""",
    )


@app.post("/connexion", response_model=None)
def login(utilisateur: str = Form(...), mdp: str = Form(...)) -> HTMLResponse | RedirectResponse:
    if utilisateur != USERNAME or not secrets.compare_digest(mdp, PASSWORD):
        return page("Connexion", "<p id='erreur'>Utilisateur ou mot de passe incorrect</p>")
    token = secrets.token_hex(16)
    store.sessions.add(token)
    response = RedirectResponse("/mouvements", status_code=303)
    response.set_cookie("session", token, httponly=True, samesite="lax")
    return response


@app.get("/mouvements", response_model=None)
def movements(request: Request) -> HTMLResponse | RedirectResponse:
    if not logged_in(request):
        return RedirectResponse("/connexion", status_code=303)
    today = store.clock().date()
    body = "".join(
        f"<tr data-id='{esc(r.id)}' class='{'annule' if r.cancelled else ''}'>"
        f"<td>{r.at(today):%H:%M}</td><td>{esc(TYPES[r.type])}</td><td>{esc(r.name)}</td>"
        f"<td>{esc(UNITS[r.uf])}</td><td>{esc(r.room)}</td><td>{esc(r.bed)}</td>"
        f"<td>{'Annulé' if r.cancelled else 'Validé'}</td>"
        f"<td><a href='/mouvements/{esc(r.id)}'>Détail</a></td></tr>"
        for r in sorted(store.rows.values(), key=lambda r: r.minutes)
    )
    return page(
        "Mouvements du jour",
        f"""<h1>Mouvements du jour — {today:%d/%m/%Y}</h1>
      <table data-testid="mouvements"><thead><tr><th>Heure</th><th>Type</th><th>Patient</th>
      <th>Unité</th><th>Chambre</th><th>Lit</th><th>Statut</th><th></th></tr></thead>
      <tbody>{body}</tbody></table>""",
    )


@app.get("/mouvements/{row_id}", response_model=None)
def detail(row_id: str, request: Request) -> HTMLResponse | RedirectResponse:
    if not logged_in(request):
        return RedirectResponse("/connexion", status_code=303)
    r = store.rows.get(row_id)
    if r is None:
        return page("Introuvable", "<p>Mouvement introuvable</p>")
    today = store.clock().date()
    return page(
        r.id,
        f"""<h1>Mouvement <span id="id-mouvement">{esc(r.id)}</span></h1>
      <dl>
        <dt>Type</dt><dd id="type">{esc(TYPES[r.type])}</dd>
        <dt>Statut</dt><dd id="statut">{"Annulé" if r.cancelled else "Validé"}</dd>
        <dt>Date et heure</dt><dd id="date-heure">{r.at(today):%d/%m/%Y %H:%M}</dd>
        <dt>Patient</dt><dd id="patient">{esc(r.name)}</dd>
        <dt>Né(e) le</dt><dd id="naissance">{r.birth:%d/%m/%Y}</dd>
        <dt>Âge</dt><dd id="age">{age(r.birth, today)}</dd>
        <dt>Sexe</dt><dd id="sexe">{esc(r.sex)}</dd>
        <dt>IPP</dt><dd id="ipp">{esc(r.ipp)}</dd>
        <dt>N° de venue</dt><dd id="venue">{esc(r.venue)}</dd>
        <dt>UF</dt><dd id="uf">{esc(r.uf)}</dd>
        <dt>Unité</dt><dd id="unite">{esc(UNITS[r.uf])}</dd>
        <dt>Chambre</dt><dd id="chambre">{esc(r.room)}</dd>
        <dt>Lit</dt><dd id="lit">{esc(r.bed)}</dd>
      </dl>""",
    )


# --- test helpers (not part of a real software) ---------------------------------


@app.post("/_test/reset")
def reset() -> JSONResponse:
    store.rows, store.sessions, store.added = sample(), set(), 0
    return JSONResponse({"ok": True})


@app.post("/_test/arrive")
def arrive() -> JSONResponse:
    store.added += 1
    n = store.added
    now = store.clock()
    row = Row(
        f"BS-{100 + n:04d}",
        "A01",
        now.hour * 60 + now.minute,
        f"71{n:05d}",
        f"41{n:05d}",
        f"Mme Démo Inventée {n}",
        date(1950, 1, 1),
        "F",
        "2101",
        f"21{n:02d}",
        f"21{n:02d}",
    )
    store.rows[row.id] = row
    return JSONResponse({"id": row.id})


@app.post("/_test/cancel/{row_id}")
def cancel(row_id: str) -> JSONResponse:
    store.rows[row_id].cancelled = True
    return JSONResponse({"ok": True})


@app.get("/_test/state")
def state() -> JSONResponse:
    return JSONResponse(
        {k: {**asdict(v), "birth": v.birth.isoformat()} for k, v in store.rows.items()}
    )
