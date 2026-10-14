"""
Couche d'observation et vues d'apprentissage (portées du corpus v0.1 du laboratoire, adaptées au moteur).

Principe : la physique ne dépend jamais de l'observation. Les livraisons sont tirées avec un
générateur aléatoire indépendant ; les variables d'apprentissage ne lisent que ce qui est
disponible à l'instant de décision ; les cibles ne lisent que la vérité.

Les horloges sont exprimées en heures depuis le début de la simulation (float), puis converties
en ISO 8601 au fuseau fixe +01:00 (le changement d'heure n'est pas modélisé).
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

SOURCES = {"ETAT_UNITE": "GESTION_LITS", "EVALUATION_CHARGE": "DOSSIER_SOIN", "PRISE_DE_POSTE": "PLANNING",
           "DECISION": "CELLULE_ORDONNANCEMENT", "RECOMMANDATION": "HOSPITALOS",
           "DATE_SORTIE_PREVISIONNELLE": "DPI_STAFF", "DESTINATION_DEMANDEE": "SERVICE_SOCIAL",
           "DEMANDE_AVAL": "VIATRAJECTOIRE", "DEMANDE_AVAL_ANNULEE": "VIATRAJECTOIRE",
           "PLACE_AVAL_CONFIRMEE": "VIATRAJECTOIRE", "AIDE_DOMICILE_DEMANDE": "SERVICE_SOCIAL",
           "AIDE_DOMICILE_ORGANISEE": "SERVICE_SOCIAL", "IMAGERIE_DEMANDE": "PRESCRIPTIONS",
           "IMAGERIE_DEBUT": "IMAGERIE", "IMAGERIE_FIN": "IMAGERIE", "AVIS_DEMANDE": "PRESCRIPTIONS",
           "AVIS_DEBUT": "PRESCRIPTIONS", "AVIS_FIN": "PRESCRIPTIONS", "TRANSPORT_DEMANDE": "REGULATION_TRANSPORTS",
           "TRANSPORT_DEBUT": "REGULATION_TRANSPORTS", "TRANSPORT_FIN": "REGULATION_TRANSPORTS",
           "NETTOYAGE_DEMANDE": "BIONETTOYAGE", "NETTOYAGE_DEBUT": "BIONETTOYAGE", "NETTOYAGE_FIN": "BIONETTOYAGE"}
CHAMPS_ETAT_OBSERVES = [
    "lits_physiques", "lits_fermes", "lits_ouverts", "lits_occupes", "lits_sales_ou_nettoyage",
    "lits_propres_libres", "lits_supplementaires_actifs", "patients_heberges_presents", "attente_urgences_nb",
    "attente_urgences_4h_plus", "programmes_en_attente", "entrees_h", "sorties_h", "sortants_medicaux_presents",
    "en_attente_aval", "en_attente_transport", "en_attente_imagerie", "en_attente_avis", "en_attente_aide_domicile",
    "charge_soins_min_h", "soignants_prevus", "soignants_presents", "ide_presents", "as_presents"]
CHAMPS_VARIABLES = [
    "lits_ouverts", "lits_occupes", "lits_propres_libres", "lits_sales_ou_nettoyage", "patients_heberges_presents",
    "attente_urgences_nb", "attente_urgences_4h_plus", "sortants_medicaux_presents", "en_attente_aval",
    "en_attente_transport", "en_attente_imagerie", "en_attente_avis", "en_attente_aide_domicile",
    "charge_soins_min_h", "soignants_presents", "ide_presents", "as_presents"]
CIBLES = ["lits_occupes", "attente_urgences_nb", "lits_propres_libres", "charge_soins_min_h",
          "minutes_non_couvertes_h", "sortants_medicaux_presents", "en_attente_aval", "patients_heberges_presents",
          "ratio_charge"]
HORIZONS = [12, 24, 48, 72, 168]

OBS = dict(
    p_absence=0.015, p_absence_sortant_medical=0.45, p_doublon=0.008, p_revision=0.02,
    delai_etat_min=12, delai_autre_min=25, delai_sigma=0.9, facteur_tension=1.6,
    p_sortie_fin_journee=0.12, p_sortie_lendemain=0.03, delai_sortie_min=45, delai_sortant_h=6,
    part_sortants_documentes=0.6, part_aval_documente=0.8, bruit_charge_sigma=0.10,
    panne_si_heure_debut=9, panne_si_heure_fin=17,
    # v0.3 : couche séjour
    p_absence_par_type={"DATE_SORTIE_PREVISIONNELLE": 0.10, "DESTINATION_DEMANDEE": 0.10, "DEMANDE_AVAL": 0.05,
                        "DEMANDE_AVAL_ANNULEE": 0.10, "PLACE_AVAL_CONFIRMEE": 0.10, "AIDE_DOMICILE_DEMANDE": 0.15,
                        "AIDE_DOMICILE_ORGANISEE": 0.15, "EVALUATION_CHARGE": 0.08, "AVIS_DEMANDE": 0.05,
                        "AVIS_FIN": 0.05},
    delai_staff_min=40, p_erreur_dependance=0.10, p_erreur_mobilite=0.10,
)

def tranche_age(age):
    """Minimisation : l'âge exact ne sort pas de la vérité."""
    t = "<65"
    for borne, lib in ((65, "65-74"), (75, "75-84"), (85, "85+")):
        if age >= borne:
            t = lib
    return t


def split_de(h, h_val, h_test, h1, embargo=168):
    """Découpage temporel commun à toutes les vues : train / validation / test, embargo avant chaque frontière."""
    borne = h_val if h < h_val else (h_test if h < h_test else h1)
    if h + embargo >= borne:
        return "embargo_ou_censure"
    return "train" if h < h_val else ("validation" if h < h_test else "test")


def iso(base, t_h):
    """Heures depuis le début de simulation -> ISO 8601 au fuseau fixe +01:00, à la seconde."""
    s = int(round(t_h * 3600))
    return (base + np.timedelta64(s, "s")).astype("datetime64[s]").astype(str) + "+01:00"


def observer(evenements, x, seed, debut_np):
    """Transforme les événements vrais en livraisons du système d'information.

    evenements : liste de dict(event_id, h, type, unite, sejour, payload)
    Retourne la liste des livraisons (dicts), triée par disponibilité.
    """
    ro = np.random.default_rng(np.random.SeedSequence([seed, 7]))  # flux indépendant de la physique
    ouvres = [d for d in range(x.ndays) if x.ouvre[d] and 270 <= x.doy[d] <= 300]
    jour_panne = int(ouvres[int(ro.integers(0, len(ouvres)))]) if ouvres else -1
    p0, p1 = jour_panne * 24 + OBS["panne_si_heure_debut"], jour_panne * 24 + OBS["panne_si_heure_fin"]
    out = []
    for e in evenements:
        typ = e["type"]
        payload = dict(e["payload"])
        tension = payload.get("minutes_non_couvertes_h", 0) > 0
        if typ == "SORTANT_MEDICAL":
            pm = OBS["p_absence_sortant_medical"]
        else:
            pm = OBS["p_absence_par_type"].get(typ, OBS["p_absence"]) * (2 if tension else 1)
        u_miss = ro.random()
        if u_miss < pm:
            continue
        if typ == "ETAT_UNITE":
            dmin = ro.lognormal(math.log(OBS["delai_etat_min"]), OBS["delai_sigma"])
            payload = {k: payload[k] for k in CHAMPS_ETAT_OBSERVES}
            payload["sortants_medicaux_presents"] = int(ro.binomial(payload["sortants_medicaux_presents"], OBS["part_sortants_documentes"]))
            payload["en_attente_aval"] = int(ro.binomial(payload["en_attente_aval"], OBS["part_aval_documente"]))
            payload["charge_soins_min_h"] = round(payload["charge_soins_min_h"] * float(ro.lognormal(0, OBS["bruit_charge_sigma"])), 2)
        elif typ == "SORTIE":
            r = ro.random()
            dmin = ro.lognormal(math.log(OBS["delai_sortie_min"]), 0.8)
            jour = math.floor(e["h"] / 24) * 24
            if r < OBS["p_sortie_fin_journee"]:
                dmin = max(dmin, (jour + 19 + 4 * ro.random() - e["h"]) * 60)
            elif r < OBS["p_sortie_fin_journee"] + OBS["p_sortie_lendemain"]:
                dmin = (jour + 24 + 9 - e["h"]) * 60 + ro.uniform(0, 60)
        elif typ == "SORTANT_MEDICAL":
            dmin = ro.lognormal(math.log(OBS["delai_sortant_h"] * 60), OBS["delai_sigma"])
        elif typ in ("DATE_SORTIE_PREVISIONNELLE", "DESTINATION_DEMANDEE", "DEMANDE_AVAL", "DEMANDE_AVAL_ANNULEE"):
            dmin = ro.lognormal(math.log(OBS["delai_staff_min"]), OBS["delai_sigma"])
        else:
            dmin = ro.lognormal(math.log(OBS["delai_autre_min"]), OBS["delai_sigma"])
        if typ == "DEMANDE_ADMISSION":
            payload["tranche_age"] = tranche_age(payload.pop("age"))
        elif typ == "EVALUATION_CHARGE":
            payload["minutes_soins_24h"] = round(payload["minutes_soins_24h"] * float(ro.lognormal(0, OBS["bruit_charge_sigma"])), 1)
            if ro.random() < OBS["p_erreur_dependance"]:
                payload["dependance"] = int(min(4, max(1, payload["dependance"] + (1 if ro.random() < 0.5 else -1))))
            if ro.random() < OBS["p_erreur_mobilite"]:
                autres = [m for m in ("autonome", "aide", "brancard") if m != payload["mobilite"]]
                payload["mobilite"] = autres[int(ro.integers(0, 2))]
        if tension:
            dmin *= OBS["facteur_tension"]
        saisie = e["h"] + dmin / 60
        ingestion = saisie + ro.uniform(1, 15) / 60
        if p0 <= ingestion < p1:  # panne du système d'information : livraison différée à la reprise
            ingestion = p1 + ro.uniform(1, 30) / 60
        dispo = ingestion + 30 / 3600
        revise = typ == "ETAT_UNITE" and ro.random() < OBS["p_revision"]
        if revise:
            vrai = payload["lits_occupes"]
            payload["lits_occupes"] = max(0, vrai + int(ro.choice([-1, 1])))
        base = dict(event_id=e["event_id"], event_version=1, type=typ, unite=e["unite"], sejour_id=e["sejour"],
                    source=SOURCES.get(typ, "DPI_MOUVEMENTS"), t_evenement=e["h"], t_saisie=saisie,
                    t_ingestion=ingestion, t_disponible=dispo, remplace_version=None, qualite=[],
                    payload=payload, synthetique=True)
        out.append(base)
        if revise:
            rt = ingestion + ro.uniform(6, 48)
            corr = dict(payload)
            corr["lits_occupes"] = vrai
            out.append({**base, "event_version": 2, "payload": corr, "t_saisie": rt, "t_ingestion": rt + 1 / 60,
                        "t_disponible": rt + 2 / 60, "remplace_version": 1, "qualite": ["CORRECTION_SOURCE"]})
        if ro.random() < OBS["p_doublon"]:
            out.append({**base, "t_ingestion": ingestion + 2 / 60, "t_disponible": ingestion + 3 / 60})
    out.sort(key=lambda o: (o["t_disponible"], o["event_id"], o["event_version"]))
    for i, o in enumerate(out):
        o["delivery_id"] = f"L{i + 1:08d}"
        canon = {k: v for k, v in o.items() if k not in ("delivery_id", "t_ingestion", "t_disponible")}
        o["empreinte"] = hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()
    return out, jour_panne


def vues_apprentissage(livraisons, verite, unites, h0, h1, frontieres, embargo=168):
    """Variables telles que connues à chaque heure (unité et pôle) et cibles vraies multi-horizons.

    livraisons : livraisons triées par disponibilité ; verite : dict (entité, h) -> ligne d'état vrai
    frontieres : (h_validation, h_test)
    """
    etats = [o for o in livraisons if o["type"] == "ETAT_UNITE"]
    j = 0
    dernier, versions = {}, {}
    variables, cibles = [], []
    h_val, h_test = frontieres
    for h in range(h0, h1):
        while j < len(etats) and etats[j]["t_disponible"] <= h:
            e = etats[j]
            k = e["event_id"]
            old = versions.get(k)
            if old is None or e["event_version"] > old["event_version"]:
                versions[k] = e
                prev = dernier.get(e["unite"])
                if prev is None or (e["t_evenement"], e["event_id"], e["event_version"]) > \
                        (prev["t_evenement"], prev["event_id"], prev["event_version"]):
                    dernier[e["unite"]] = e
            j += 1
        split = split_de(h, h_val, h_test, h1, embargo)
        lignes = []
        for u in unites:
            e = dernier.get(u)
            r = dict(sample_id=f"{u}@{h}", h=h, entite=u, niveau="unite", split=split,
                     entree_event_id=e["event_id"] if e else None, entree_version=e["event_version"] if e else None,
                     entree_disponible=round(e["t_disponible"], 6) if e else None,
                     age_observation_h=round(h - e["t_evenement"], 3) if e else None,
                     observation_manquante=e is None)
            for f in CHAMPS_VARIABLES:
                r["obs_" + f] = e["payload"][f] if e else None
            lignes.append(r)
        pole = dict(sample_id=f"POLE@{h}", h=h, entite="POLE", niveau="pole", split=split,
                    entree_event_id=None, entree_version=None,
                    entree_disponible=max((r["entree_disponible"] for r in lignes if r["entree_disponible"] is not None), default=None),
                    age_observation_h=max((r["age_observation_h"] for r in lignes if r["age_observation_h"] is not None), default=None),
                    observation_manquante=any(r["observation_manquante"] for r in lignes))
        for f in CHAMPS_VARIABLES:
            vals = [r["obs_" + f] for r in lignes]
            pole["obs_" + f] = (round(sum(vals), 3) if all(v is not None for v in vals) else None)
        if len(unites) > 1:
            lignes.append(pole)
        for r in lignes:
            variables.append(r)
            for H in HORIZONS:
                t = verite.get((r["entite"], h + H))
                if t is None or h + H >= h1:
                    continue
                c = dict(sample_id=r["sample_id"], horizon_h=H, h_cible=h + H, split=split)
                for k in CIBLES:
                    c["cible_" + k] = t[k]
                cibles.append(c)
    return variables, cibles
