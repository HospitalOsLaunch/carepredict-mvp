"""A fictional orientation portal ("Portail d'orientation, démonstration").

It mimics what such portals show to an SMR: a list of requests, a detail page with
identifiable patient data (a name, on purpose, to test that the agent never copies it),
and a reply form. It imitates no real product: generic look, invented names.

    uvicorn services.admissions_agent.demo_portal.app:app --port 8020
"""

from __future__ import annotations

import html
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

USERNAME = os.getenv("DEMO_PORTAL_USER", "demo")
PASSWORD = os.getenv("DEMO_PORTAL_PASSWORD", "demo-portail")


@dataclass
class Dossier:
    ref: str
    received_at: datetime
    facility: str
    unit: str
    patient_name: str
    age: int
    sex: str
    mention: str
    reason: str
    dependency: int
    isolation: bool
    needs: list[str]
    desired: date
    status: str = "En attente"
    proposed: date | None = None
    refusal_reason: str | None = None
    message: str | None = None


REFUSAL_LABELS = [
    "Pas de lit disponible à la date souhaitée",
    "Mention ou spécialité inadaptée",
    "Charge en soins trop lourde pour l'équipe",
    "Besoin technique non couvert (O2, dialyse…)",
    "Isolement impossible",
    "Projet de rééducation inadapté",
    "Dossier incomplet",
    "Autre motif",
]


def sample(today: date | None = None) -> dict[str, Dossier]:
    d = today or date.today()
    now = datetime.now().replace(second=0, microsecond=0)
    rows = [
        Dossier(
            "DOS-2026-0412",
            now - timedelta(hours=20),
            "CH des Monts d'Or",
            "Médecine polyvalente",
            "Mme Jeanne Exemple",
            86,
            "F",
            "Gériatrie",
            "Chutes à répétition",
            3,
            False,
            ["Oxygénothérapie"],
            d + timedelta(days=2),
        ),
        Dossier(
            "DOS-2026-0413",
            now - timedelta(hours=9),
            "Hôpital Saint-Rambert",
            "Orthopédie",
            "M. Paul Fictif",
            71,
            "M",
            "Locomoteur",
            "Prothèse totale de genou",
            2,
            False,
            [],
            d + timedelta(days=1),
        ),
        Dossier(
            "DOS-2026-0414",
            now - timedelta(hours=3),
            "Hôpital Croix-Pâquet",
            "Neurologie",
            "Mme Lina Imaginaire",
            64,
            "F",
            "Système nerveux",
            "AVC ischémique",
            4,
            True,
            ["Trachéotomie"],
            d + timedelta(days=5),
        ),
    ]
    return {r.ref: r for r in rows}


@dataclass
class Store:
    dossiers: dict[str, Dossier] = field(default_factory=sample)
    sessions: set[str] = field(default_factory=set)


store = Store()
app = FastAPI(title="Portail d'orientation (démonstration)", docs_url=None, redoc_url=None)

STYLE = """
body{font-family:Arial,Helvetica,sans-serif;margin:0;background:#f4f5f7;color:#222}
header{background:#3b4a5a;color:#fff;padding:12px 24px;font-size:18px}
main{padding:24px;max-width:980px}
table{border-collapse:collapse;width:100%;background:#fff}
td,th{border:1px solid #ccd;padding:8px;text-align:left}
dl{display:grid;grid-template-columns:220px 1fr;background:#fff;padding:16px}
dt{font-weight:bold}
form.reply{background:#fff;padding:16px;margin-top:16px}
label{display:block;margin:8px 0 4px}
.banner{background:#dff0d8;padding:10px;margin-bottom:12px}
"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>{title}</title>"
        f"<style>{STYLE}</style></head><body><header>Portail d'orientation "
        f"(démonstration)</header><main>{body}</main></body></html>"
    )


def logged_in(request: Request) -> bool:
    return request.cookies.get("session") in store.sessions


def esc(value: object) -> str:
    return html.escape(str(value))


@app.get("/login")
def login_form() -> HTMLResponse:
    return page(
        "Connexion",
        """
      <h1>Connexion</h1>
      <form method="post" action="/login">
        <label for="identifiant">Identifiant</label><input id="identifiant" name="identifiant">
        <label for="mot-de-passe">Mot de passe</label>
        <input id="mot-de-passe" name="mot_de_passe" type="password">
        <p><button type="submit">Se connecter</button></p>
      </form>""",
    )


@app.post("/login", response_model=None)
def login(
    identifiant: str = Form(...), mot_de_passe: str = Form(...)
) -> HTMLResponse | RedirectResponse:
    if identifiant != USERNAME or not secrets.compare_digest(mot_de_passe, PASSWORD):
        return page("Connexion", "<p id='erreur'>Identifiants incorrects</p>")
    token = secrets.token_hex(16)
    store.sessions.add(token)
    response = RedirectResponse("/dossiers", status_code=303)
    response.set_cookie("session", token, httponly=True)
    return response


@app.get("/dossiers", response_model=None)
def list_dossiers(request: Request, statut: str | None = None) -> HTMLResponse | RedirectResponse:
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    rows = [
        d for d in store.dossiers.values() if statut != "en_attente" or d.status == "En attente"
    ]
    body = "".join(
        f"<tr data-ref='{esc(d.ref)}'><td>{esc(d.ref)}</td><td>{esc(d.facility)}</td>"
        f"<td>{esc(d.mention)}</td><td>{d.received_at:%d/%m/%Y %H:%M}</td><td>{esc(d.status)}</td>"
        f"<td><a class='ouvrir' href='/dossiers/{esc(d.ref)}'>Ouvrir</a></td></tr>"
        for d in sorted(rows, key=lambda d: d.received_at)
    )
    return page(
        "Demandes reçues",
        f"""
      <nav><a href="/dossiers">Toutes</a> |
        <a href="/dossiers?statut=en_attente">En attente</a></nav>
      <h1>Demandes reçues</h1>
      <table data-testid="liste-dossiers"><thead><tr><th>Dossier</th><th>Demandeur</th>
      <th>Mention</th>
      <th>Reçue le</th><th>Statut</th><th></th></tr></thead><tbody>{body}</tbody></table>""",
    )


@app.get("/dossiers/{ref}", response_model=None)
def detail(ref: str, request: Request, ok: int = 0) -> HTMLResponse | RedirectResponse:
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    d = store.dossiers.get(ref)
    if d is None:
        return page("Introuvable", "<p>Dossier introuvable</p>")
    options = "".join(f"<option>{esc(r)}</option>" for r in REFUSAL_LABELS)
    banner = "<p class='banner' id='confirmation'>Réponse enregistrée.</p>" if ok else ""
    proposed = f"{d.proposed:%d/%m/%Y}" if d.proposed else ""
    return page(
        d.ref,
        f"""
      {banner}<h1>Dossier <span id="ref">{esc(d.ref)}</span></h1>
      <dl>
        <dt>Patient</dt><dd id="patient">{esc(d.patient_name)}</dd>
        <dt>Reçue le</dt><dd id="recu-le">{d.received_at:%d/%m/%Y %H:%M}</dd>
        <dt>Établissement demandeur</dt><dd id="etablissement">{esc(d.facility)}</dd>
        <dt>Service</dt><dd id="service">{esc(d.unit)}</dd>
        <dt>Âge</dt><dd id="age">{d.age}</dd>
        <dt>Sexe</dt><dd id="sexe">{esc(d.sex)}</dd>
        <dt>Mention demandée</dt><dd id="mention">{esc(d.mention)}</dd>
        <dt>Motif</dt><dd id="motif">{esc(d.reason)}</dd>
        <dt>Dépendance (1 à 4)</dt><dd id="dependance">{d.dependency}</dd>
        <dt>Isolement</dt><dd id="isolement">{"Oui" if d.isolation else "Non"}</dd>
        <dt>Besoins</dt><dd id="besoins">{esc(", ".join(d.needs))}</dd>
        <dt>Entrée souhaitée</dt><dd id="date-souhaitee">{d.desired:%d/%m/%Y}</dd>
        <dt>Statut</dt><dd id="statut">{esc(d.status)}</dd>
        <dt>Date proposée</dt><dd id="date-proposee">{proposed}</dd>
      </dl>
      <form class="reply" method="post" action="/dossiers/{esc(d.ref)}/reponse">
        <h2>Répondre</h2>
        <label><input type="radio" id="decision-accord" name="decision" value="accord">
          Accord</label>
        <label><input type="radio" id="decision-refus" name="decision" value="refus"> Refus</label>
        <label for="date-entree">Date d'entrée proposée (JJ/MM/AAAA)</label>
        <input type="text" id="date-entree" name="date_entree" placeholder="JJ/MM/AAAA" size="12">
        <label for="motif-refus">Motif de refus</label>
        <select id="motif-refus" name="motif_refus"><option value=""></option>{options}</select>
        <label for="message">Message au demandeur</label>
        <textarea id="message" name="message" rows="5" cols="60"></textarea>
        <p><button id="envoyer" type="submit">Envoyer la réponse</button></p>
      </form>""",
    )


@app.post("/dossiers/{ref}/reponse", response_model=None)
def reply(
    ref: str,
    request: Request,
    decision: str = Form(""),
    date_entree: str = Form(""),
    motif_refus: str = Form(""),
    message: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    if not logged_in(request):
        return RedirectResponse("/login", status_code=303)
    d = store.dossiers.get(ref)
    if d is None:
        return page("Introuvable", "<p>Dossier introuvable</p>")
    if decision == "accord":
        try:
            proposed = datetime.strptime(date_entree.strip(), "%d/%m/%Y").date()
        except ValueError:
            return page("Erreur", "<p id='erreur'>Date d'entrée invalide (JJ/MM/AAAA).</p>")
        d.status, d.proposed, d.refusal_reason = "Accord donné", proposed, None
    elif decision == "refus":
        if not motif_refus:
            return page("Erreur", "<p id='erreur'>Le motif de refus est obligatoire.</p>")
        d.status, d.proposed, d.refusal_reason = "Refusé", None, motif_refus
    else:
        return page("Erreur", "<p id='erreur'>Choisissez accord ou refus.</p>")
    d.message = message
    return RedirectResponse(f"/dossiers/{ref}?ok=1", status_code=303)


# --- test helpers (not part of a real portal) ---------------------------------


@app.post("/_test/reset")
def reset() -> JSONResponse:
    store.dossiers = sample()
    store.sessions = set()
    return JSONResponse({"ok": True})


@app.get("/_test/state")
def state() -> JSONResponse:
    return JSONResponse(
        {
            ref: {
                k: (v.isoformat() if isinstance(v, date | datetime) else v)
                for k, v in asdict(d).items()
            }
            for ref, d in store.dossiers.items()
        }
    )
