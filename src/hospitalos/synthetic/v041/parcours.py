"""
Couche séjour (v0.3) : trajectoire opérationnelle de chaque séjour, telle que connue à chaque heure.

Principe : chaque valeur provient d'une livraison déjà disponible (h_disponible <= h), dédupliquée,
et la plus récente au sens de l'horloge du fait. Aucune valeur ne lit la vérité. Les cibles par
séjour ne lisent que la vérité, et ne servent que d'étiquettes.

Un séjour apparaît dès qu'un mouvement (admission, transfert interne) ou une évaluation est disponible.
Il disparaît quand sa sortie est disponible, quand un autre patient est enregistré dans son lit, ou
après 96 h sans aucune information (séjour fantôme dont la sortie n'a jamais été saisie).
"""
from __future__ import annotations

import datetime as dt

from . import observation as ob

INACTIVITE_MAX_H = 96
HORIZONS_SEJOUR = [24, 48, 72]

# Colonnes autorisées dans apprentissage/sejours_asof (liste fermée : toute autre colonne est une fuite potentielle)
COLONNES_SEJOURS_ASOF = [
    "sample_id", "h", "ts", "sejour_id", "split",
    "unite_actuelle", "unite_appartenance", "heberge", "mode_entree", "tranche_age", "isolement", "oxygene",
    "duree_ecoulee_h", "mouvements_internes",
    "dependance_obs", "mobilite_obs", "charge_soins_24h_obs", "age_evaluation_h",
    "dsp_jours_restants", "dsp_revisions", "dsp_absente",
    "sortant_medical_saisi", "h_depuis_sortant_saisi",
    "destination_demandee", "destination_revisions",
    "imagerie_en_attente", "avis_en_attente", "transport_en_attente",
    "demande_aval_en_attente", "anciennete_demande_aval_h", "place_aval_confirmee",
    "aide_domicile_requise", "aide_domicile_organisee",
    "age_derniere_information_h", "derniere_disponibilite", "dsp_event_id",
]
COLONNES_CIBLES_SEJOURS = (["sample_id", "split", "cible_present_vrai"]
                           + [f"cible_sortie_{H}h" for H in HORIZONS_SEJOUR]
                           + ["cible_duree_restante_h", "cible_sortant_medical_24h"])

TYPES_SEJOUR = {
    "DEMANDE_ADMISSION", "ADMISSION", "TRANSFERT_INTERNE", "SORTIE", "SORTANT_MEDICAL", "EVALUATION_CHARGE",
    "DATE_SORTIE_PREVISIONNELLE", "DESTINATION_DEMANDEE", "DEMANDE_AVAL", "DEMANDE_AVAL_ANNULEE",
    "PLACE_AVAL_CONFIRMEE", "AIDE_DOMICILE_DEMANDE", "AIDE_DOMICILE_ORGANISEE",
    "IMAGERIE_DEMANDE", "IMAGERIE_FIN", "AVIS_DEMANDE", "AVIS_FIN", "TRANSPORT_DEMANDE", "TRANSPORT_FIN",
}


def _nouveau():
    return dict(home=None, mode=None, tranche=None, iso=None, oxy=None,
                adm_t=None, unite=None, unite_t=-1e18, lit=None, lit_t=-1e18, n_mvt=0,
                sortie=False, deduit=False,
                dep=None, mob=None, charge=None, eval_t=None, eval_unite=None,
                dsp=None, dsp_t=-1e18, dsp_n=0, dsp_eid=None,
                sortant_t=None, dest=None, dest_t=-1e18, dest_n=0,
                img_dem=False, img_fin=False, avis_dem=False, avis_fin=False, tr_dem=False, tr_fin=False,
                aval_t=None, aval_ann_t=-1e18, aval_conf=False, aide_req=False, aide_org=False,
                last_t=-1e18, dispo_max=-1e18)


def _appliquer(S, lits, o, jour0):
    """Intègre une livraison dans l'état observé des séjours. Renvoie l'identifiant du séjour touché."""
    sid = o["sejour_id"]
    s = S.get(sid)
    if s is None:
        s = S[sid] = _nouveau()
    t, typ, pl = o["t_evenement"], o["type"], o["payload"]
    s["last_t"] = max(s["last_t"], t)
    s["dispo_max"] = max(s["dispo_max"], o["t_disponible"])
    if typ == "DEMANDE_ADMISSION":
        s["home"], s["mode"], s["tranche"] = o["unite"], pl.get("mode_entree"), pl.get("tranche_age")
        s["iso"], s["oxy"] = pl.get("isolement"), pl.get("oxygene")
    elif typ in ("ADMISSION", "TRANSFERT_INTERNE"):
        if typ == "ADMISSION":
            s["adm_t"] = t
            if s["home"] is None:
                s["home"] = pl.get("unite_cible")
        else:
            s["n_mvt"] += 1
        if t > s["unite_t"]:
            s["unite"], s["unite_t"] = o["unite"], t
        lit = f'{o["unite"]}#{pl.get("lit")}'
        if t > s["lit_t"]:
            s["lit"], s["lit_t"] = lit, t
        prec = lits.get(lit)
        if prec is not None and prec[0] != sid and t > prec[1]:
            sp = S.get(prec[0])
            if sp is not None and sp["lit"] == lit:
                sp["deduit"] = True  # un autre patient occupe ce lit : la sortie non saisie est déduite
        if prec is None or t > prec[1]:
            lits[lit] = (sid, t)
    elif typ == "SORTIE":
        s["sortie"] = True
    elif typ == "SORTANT_MEDICAL":
        s["sortant_t"] = t
    elif typ == "EVALUATION_CHARGE":
        if s["eval_t"] is None or t > s["eval_t"]:
            s["eval_t"], s["eval_unite"] = t, o["unite"]
            s["dep"], s["mob"], s["charge"] = pl.get("dependance"), pl.get("mobilite"), pl.get("minutes_soins_24h")
    elif typ == "DATE_SORTIE_PREVISIONNELLE":
        s["dsp_n"] += 1
        if t > s["dsp_t"]:
            s["dsp_t"], s["dsp_eid"] = t, o["event_id"]
            s["dsp"] = (dt.date.fromisoformat(pl["date_prevue"]) - jour0).days
    elif typ == "DESTINATION_DEMANDEE":
        s["dest_n"] += 1
        if t > s["dest_t"]:
            s["dest"], s["dest_t"] = pl["destination_demandee"], t
    elif typ == "DEMANDE_AVAL":
        if s["aval_t"] is None or t < s["aval_t"]:
            s["aval_t"] = t
    elif typ == "DEMANDE_AVAL_ANNULEE":
        s["aval_ann_t"] = max(s["aval_ann_t"], t)
    elif typ == "PLACE_AVAL_CONFIRMEE":
        s["aval_conf"] = True
    elif typ == "AIDE_DOMICILE_DEMANDE":
        s["aide_req"] = True
    elif typ == "AIDE_DOMICILE_ORGANISEE":
        s["aide_req"] = s["aide_org"] = True
    elif typ == "IMAGERIE_DEMANDE":
        s["img_dem"] = True
    elif typ == "IMAGERIE_FIN":
        s["img_fin"] = True
    elif typ == "AVIS_DEMANDE":
        s["avis_dem"] = True
    elif typ == "AVIS_FIN":
        s["avis_fin"] = True
    elif typ == "TRANSPORT_DEMANDE":
        s["tr_dem"] = True
    elif typ == "TRANSPORT_FIN":
        s["tr_fin"] = True
    return sid


def _present(s, h):
    connu = s["adm_t"] is not None or s["unite"] is not None or s["eval_t"] is not None
    return connu and not s["sortie"] and not s["deduit"] and h - s["last_t"] <= INACTIVITE_MAX_H


def _ligne(sid, s, h, split):
    jour = h // 24
    unite = s["unite"] if s["unite"] is not None else s["eval_unite"]
    if s["eval_unite"] is not None and s["eval_t"] is not None and s["eval_t"] > s["unite_t"]:
        unite = s["eval_unite"]
    aval_en_cours = s["aval_t"] is not None and s["aval_ann_t"] < s["aval_t"] and not s["aval_conf"]
    return (
        f"{sid}@{h}", h, None, sid, split,
        unite, s["home"], (None if s["home"] is None or unite is None else unite != s["home"]),
        s["mode"], s["tranche"], s["iso"], s["oxy"],
        (round(h - s["adm_t"], 3) if s["adm_t"] is not None else None), s["n_mvt"],
        s["dep"], s["mob"], s["charge"], (round(h - s["eval_t"], 3) if s["eval_t"] is not None else None),
        (s["dsp"] - jour if s["dsp"] is not None else None), s["dsp_n"], s["dsp"] is None,
        s["sortant_t"] is not None, (round(h - s["sortant_t"], 3) if s["sortant_t"] is not None else None),
        s["dest"], s["dest_n"],
        s["img_dem"] and not s["img_fin"], s["avis_dem"] and not s["avis_fin"], s["tr_dem"] and not s["tr_fin"],
        aval_en_cours, (round(h - s["aval_t"], 3) if aval_en_cours else None), s["aval_conf"],
        s["aide_req"], s["aide_org"],
        round(h - s["last_t"], 3), round(s["dispo_max"], 6), s["dsp_eid"],
    )


def _cibles(sid, h, split, verite, h1):
    """verite : sejour_id -> (admit_h, exit_h ou None si censuré au 31/12, ready_h ou None)."""
    adm, sortie, pret = verite.get(sid, (None, None, None))
    present = adm is not None and adm < h and (sortie is None or sortie >= h)
    row = [f"{sid}@{h}", split, present]
    for H in HORIZONS_SEJOUR:
        if sortie is not None:
            row.append(h <= sortie < h + H)
        else:
            row.append(False if h + H <= h1 else None)
    row.append(sortie - h if sortie is not None else None)
    if pret is None:
        row.append(False if (adm is not None and h + 24 <= h1) else None)
    elif pret < h:
        row.append(None)
    else:
        row.append(pret < h + 24)
    return tuple(row)


def iter_vues_sejours(livraisons, verite, jour0, h0, h1, frontieres, embargo=168, bloc_h=24 * 31):
    """Produit, par blocs de `bloc_h` heures, les lignes (variables, cibles) de la couche séjour.

    livraisons : livraisons triées par disponibilité (sortie de observation.observer) ;
    verite : sejour_id -> (admit_h, exit_h, ready_h) ; jour0 : date du jour 0 de la simulation.
    """
    flux = [o for o in livraisons if o.get("sejour_id") and o["type"] in TYPES_SEJOUR]
    h_val, h_test = frontieres
    S, lits, vus = {}, {}, set()
    j = 0
    var, cib = [], []
    for h in range(h0 - 24 * 30, h1):
        while j < len(flux) and flux[j]["t_disponible"] <= h:
            o = flux[j]
            j += 1
            k = (o["event_id"], o["event_version"])
            if k in vus:
                continue
            vus.add(k)
            _appliquer(S, lits, o, jour0)
        if h < h0:
            continue
        split = ob.split_de(h, h_val, h_test, h1, embargo)
        for sid in sorted(S):
            s = S[sid]
            if _present(s, h):
                var.append(_ligne(sid, s, h, split))
                cib.append(_cibles(sid, h, split, verite, h1))
        if (h + 1 - h0) % bloc_h == 0 or h == h1 - 1:
            yield var, cib
            var, cib = [], []
        # purge des séjours terminés depuis longtemps (mémoire)
        if h % 168 == 0:
            for sid in [k for k, s in S.items() if (s["sortie"] or s["deduit"]) and h - s["last_t"] > 24 * 15]:
                del S[sid]
