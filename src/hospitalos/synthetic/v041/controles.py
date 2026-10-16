"""
Contrôles structurels, temporels et causaux d'un jeu généré (v0.3).

Usage : python controles.py <dossier_donnees>
Écrit rapport_controles.json et manifest.json. Réussir ces contrôles ne prouve aucun réalisme empirique.
"""
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import parcours as pc
from . import notes as nt

COMPTES = ["lits_physiques", "lits_fermes", "lits_ouverts", "lits_occupes", "lits_sales_ou_nettoyage",
           "lits_propres_libres", "attente_urgences_nb", "entrees_h", "sorties_h", "transferts_internes_entrants_h",
           "transferts_internes_sortants_h", "charge_soins_min_h", "soignants_presents"]
PRIVILEGIES = {"ready_h", "dis_h", "los_med_h", "destination", "ts_sortie", "dms_jours", "readmission_30j",
               "ts_sortant_medical", "ts_aide_organisee", "confusion_z", "aide_h", "exit_h", "admit_h"}
FAMILLES_ATTENDUES = {"A_levier_seul_puis_rien": 6, "B_action_imposee_puis_politique": 7,
                      "C_recommandation_imposee_puis_politique": 5}


def split_de(h, hv, hT, h1, embargo=168):
    borne = hv if h < hv else (hT if h < hT else h1)
    if h + embargo >= borne:
        return "embargo_ou_censure"
    return "train" if h < hv else ("validation" if h < hT else "test")


def jsonl(path):
    with gzip.open(path, "rt") as f:
        return [json.loads(l) for l in f]


def _aligner(nts, anns):
    idx = {(a["note_id"], a["version"]): a for a in anns}
    paires = [(n, idx[(n["note_id"], n["version"])]) for n in nts if (n["note_id"], n["version"]) in idx]
    return [p[0] for p in paires], [p[1] for p in paires]


def controler_fusion(etat, notes):
    """Audite les snapshots contre les ajouts observés, sans lire la vérité clinique."""
    from . import extraction as ex
    idx = {(n["note_id"], int(n["version"])): n for n in notes}
    mentions, historiques = {}, {}
    erreurs_provenance = 0
    for n in sorted(notes, key=lambda n: (n["h_disponible"], n["note_id"], n["version"])):
        cle = (n["note_id"], int(n["version"]))
        try:
            mentions[cle] = ex.mentions_nouvelles(n, historiques.get(n["note_id"]))
        except ValueError:
            mentions[cle] = {}
            erreurs_provenance += 1
        historiques[n["note_id"]] = n
    colonnes = {v + s for v in ex.VARIABLES for s in ("", "_statut", *ex.PROVENANCE)}
    if not colonnes.issubset(etat.columns):
        return 1, erreurs_provenance + 1

    def egal(a, b):
        if pd.isna(a) or pd.isna(b):
            return bool(pd.isna(a) and pd.isna(b))
        return a == b

    erreurs_copies, precedents, vus = 0, {}, set()
    for r in etat.sort_values(["h_disponible", "note_id", "version"]).to_dict("records"):
        cle = (r["note_id"], int(r["version"]))
        n = idx.get(cle)
        if n is None or cle in vus:
            erreurs_provenance += 1
            continue
        vus.add(cle)
        if (n["sejour_id"] != r["sejour_id"] or n["type_note"] != r["type_note"]
                or abs(n["h_disponible"] - r["h_disponible"]) > 1e-6):
            erreurs_provenance += 1
        precedent = precedents.get(r["sejour_id"], {})
        for v in ex.VARIABLES:
            if v not in mentions[cle]:
                erreurs_copies += not all(egal(r[v + s], precedent.get(v + s))
                                          for s in ("", "_statut", *ex.PROVENANCE))
            if pd.isna(r[v]):
                continue
            version = r[v + "_version_source"]
            if pd.isna(version) or version != int(version):
                erreurs_provenance += 1
                continue
            source = (r[v + "_note_id_source"], int(version))
            ns = idx.get(source)
            fait = mentions.get(source, {}).get(v)
            if ns is None or fait is None:
                erreurs_provenance += 1
                continue
            attendu = {v: fait["valeur"], v + "_statut": fait["statut"],
                       v + "_source": ns["type_note"], v + "_h_source": round(ns["h_disponible"], 6),
                       v + "_ts_redaction_source": ns["ts_modification"], v + "_extrait_source": fait["extrait"]}
            ok = (ns["sejour_id"] == r["sejour_id"] and ns["h_disponible"] <= r["h_disponible"] + 1e-6
                  and all(egal(r[k], x) for k, x in attendu.items()))
            # Une nouvelle mention doit prendre la priorité dès qu'elle devient disponible.
            if v in mentions[cle]:
                ok &= source == cle
            erreurs_provenance += not ok
        precedents[r["sejour_id"]] = r
    erreurs_provenance += len(set(idx) - vus)
    return int(erreurs_copies), int(erreurs_provenance)


def main(root):
    root = Path(root)
    rep = json.loads((root / "rapport_generation.json").read_text())
    cfg = json.loads((root / "config/parametres.json").read_text())
    checks, details = {}, {}

    def check(nom, ok, detail=None):
        checks[nom] = bool(ok)
        if detail is not None and not ok:
            details[nom] = detail

    # --- physique
    viol = rep["violations_invariants"]
    check("invariants_lits_toutes_heures", all(v == 0 for v in viol.values()) and rep["heures_controlees"] > 0, viol)
    check("rejeu_exact_depuis_captures", rep["test_rejeu_ecarts"] == 0, rep["test_rejeu_ecarts"])
    et = pd.read_csv(root / "verite/etats_horaires.csv.gz")
    n_h = (cfg["h_fin_periode"] - cfg["h_debut_periode"])
    n_ent = et.entite.nunique()
    check("une_ligne_par_heure_et_entite", len(et) == n_h * n_ent and et.groupby("entite").size().eq(n_h).all())
    check("cles_etats_uniques", not et.duplicated(["entite", "h"]).any())
    check("partition_des_lits", ((et.lits_physiques == et.lits_fermes + et.lits_ouverts) &
                                 (et.lits_ouverts == et.lits_occupes + et.lits_sales_ou_nettoyage + et.lits_propres_libres)).all())
    check("occupes_inferieurs_aux_ouverts", (et.lits_occupes <= et.lits_ouverts).all())
    un = et[et.niveau == "unite"]
    if n_ent > 1:
        po = et[et.niveau == "pole"].set_index("h")
        sm = un.groupby("h")[COMPTES].sum()
        check("pole_egal_somme_des_unites", np.allclose(sm[COMPTES].values, po.loc[sm.index, COMPTES].values, atol=0.05))
        check("transferts_internes_s_annulent_au_pole",
              (po.transferts_internes_entrants_h == po.transferts_internes_sortants_h).all())
    ok = True
    for _, g in un.sort_values("h").groupby("entite"):
        prev = g.lits_occupes.shift(1)
        attendu = prev + g.entrees_h + g.transferts_internes_entrants_h - g.sorties_h - g.transferts_internes_sortants_h
        ok &= bool((attendu.iloc[1:] == g.lits_occupes.iloc[1:]).all())
    check("conservation_stock_flux_horaire", ok)
    eff = pd.read_csv(root / "verite/effectifs_postes.csv.gz")
    check("comptabilite_effectifs", (eff.soignants_presents == eff.soignants_prevus - eff.absences
                                     + eff.remplacements + eff.renforts).all() and
          (eff.ide_presents + eff.as_presents == eff.soignants_presents).all())

    # --- séjours et services
    sej = pd.read_csv(root / "verite/sejours.csv.gz")
    t = {c: pd.to_datetime(sej[c].str[:19]) for c in ("ts_decision", "ts_entree", "ts_sortant_medical", "ts_sortie")}
    check("identifiants_sejours_uniques", sej.sejour_id.is_unique)
    adm = t["ts_entree"].notna()
    check("ordre_decision_entree_sortie", ((t["ts_decision"] <= t["ts_entree"]) | ~adm).all() and
          ((t["ts_entree"] <= t["ts_sortie"]) | t["ts_sortie"].isna()).all() and
          ((t["ts_entree"] <= t["ts_sortant_medical"]) | t["ts_sortant_medical"].isna()).all() and
          (t["ts_sortant_medical"].isna() | adm).all())
    avant = t["ts_sortie"] < t["ts_sortant_medical"]
    check("sortie_avant_sortant_medical_seulement_vers_domicile", (~avant | (sej.destination == "domicile")).all())
    check("censure_preservee", sej.loc[sej.issue == "censure", "ts_sortie"].isna().all() and
          sej.loc[sej.issue == "censure", "destination"].isna().all() and
          sej.loc[sej.issue == "sortie", "ts_sortie"].notna().all())
    debut_sim = pd.Timestamp(cfg["debut_simulation"])
    fin_periode = debut_sim + pd.Timedelta(hours=cfg["h_fin_periode"])
    cols_ts = [c for c in sej.columns if c.startswith("ts_")]
    futurs = {c: int((pd.to_datetime(sej[c].str[:19]) >= fin_periode).sum()) for c in cols_ts}
    check("sejours_figes_au_31_12_sans_date_posterieure", sum(futurs.values()) == 0, futurs)
    check("non_admis_sans_lit", sej.loc[sej.issue.isin(["hors_perimetre", "deprogramme", "transfert_refuse"]),
                                        "ts_entree"].isna().all())
    tk = pd.read_csv(root / "verite/taches_services.csv.gz")
    tt = {c: pd.to_datetime(tk[c].str[:19]) for c in ("ts_demande", "ts_debut", "ts_fin")}
    check("ordre_horloges_taches", ((tt["ts_demande"] <= tt["ts_debut"]) | tt["ts_debut"].isna()).all() and
          ((tt["ts_debut"] <= tt["ts_fin"]) | tt["ts_fin"].isna()).all() and
          (tk.statut.eq("TERMINEE") == tt["ts_fin"].notna()).all())
    ready = dict(zip(sej.sejour_id, t["ts_sortant_medical"]))
    dest = dict(zip(sej.sejour_id, sej.destination))
    tr = tk[tk.type == "TRANSPORT"]
    check("transport_avant_sortant_medical_seulement_vers_domicile", all(
        pd.isna(ready.get(s)) or d >= ready[s] or dest.get(s) == "domicile"
        for s, d in zip(tr.sejour_id, pd.to_datetime(tr.ts_demande.str[:19]))))
    im = tk[tk.type.isin(["IMAGERIE", "AVIS"]) & tk.ts_fin.notna()]
    check("imagerie_et_avis_avant_sortant_medical", all(
        pd.isna(ready.get(s)) or dest.get(s) == "deces" or f < ready[s]
        for s, f in zip(im.sejour_id, pd.to_datetime(im.ts_fin.str[:19]))))

    # --- observation et apprentissage
    livr = jsonl(root / "observe/livraisons.jsonl.gz")
    ts = lambda s: pd.Timestamp(s[:19])  # noqa: E731
    check("ordre_horloges_observation", all(ts(o["ts_evenement"]) <= ts(o["ts_saisie"]) <= ts(o["ts_ingestion"])
                                            <= ts(o["ts_disponible"]) for o in livr))
    versions = {(o["event_id"], o["event_version"]) for o in livr}
    check("revisions_avec_predecesseur", all((o["event_id"], o["remplace_version"]) in versions
                                             for o in livr if o["remplace_version"]))
    premier, stable = {}, True
    for o in livr:
        k = (o["event_id"], o["event_version"])
        if k in premier and premier[k]["empreinte"] != o["empreinte"]:
            stable = False
        if k not in premier or o["h_disponible"] < premier[k]["h_disponible"]:
            premier[k] = o
    check("doublons_contenu_identique", stable)
    va = pd.read_csv(root / "apprentissage/variables_asof.csv.gz")
    ci = pd.read_csv(root / "apprentissage/cibles.csv.gz")
    check("variables_disponibles_avant_l_instant", (va.entree_disponible.isna() | (va.entree_disponible <= va.h)).all())
    lin = va[va.entree_event_id.notna()]
    check("lignage_variables_conforme", all(
        premier[(e, int(v))]["payload"]["lits_occupes"] == o and abs(premier[(e, int(v))]["h_disponible"] - d) < 1e-6
        for e, v, o, d in zip(lin.entree_event_id, lin.entree_version, lin.obs_lits_occupes, lin.entree_disponible)))
    check("aucune_variable_privilegiee_ou_cible", not any(c.startswith("cible_") or c in PRIVILEGIES for c in va.columns))
    vt = et.set_index(["entite", "h"])
    j = ci.merge(va[["sample_id", "entite", "h"]], on="sample_id")
    check("cibles_conformes_verite_et_horizon",
          (j.h_cible == j.h + j.horizon_h).all() and
          np.array_equal(j.cible_lits_occupes.values, vt.loc[list(zip(j.entite, j.h_cible)), "lits_occupes"].values))
    hv, hT = cfg["h_validation"], cfg["h_test"]
    act = j[j.split.isin(["train", "validation", "test"])]
    check("decoupage_sans_chevauchement",
          act[act.split == "train"].h_cible.max() < hv and act[act.split == "validation"].h_cible.max() < hT and
          act[act.split == "validation"].h.min() >= hv and act[act.split == "test"].h.min() >= hT)

    # --- couche causale
    hv, hT, h1 = cfg["h_validation"], cfg["h_test"], cfg["h_fin_periode"]
    dec = pd.read_csv(root / "causal/decisions.csv.gz")
    ok = dec.exposition.isin([0, 1]).all()
    for lev in cfg["leviers"]:
        q, r, a, n, x = (dec[c + lev] for c in ("q_reco_", "r_", "a_", "n_concernes_", "x_"))
        ok &= bool(q.between(0, 1).all() and r.isin([0, 1]).all() and a.isin([0, 1]).all()
                   and ((q > 0) | (r == 0)).all() and ((n == 0) | (a == 1)).all()
                   and (x == ((a == 1) & (n > 0)).astype(int)).all())
    check("chaine_recommandation_execution_coherente", ok)
    check("decisions_sans_probabilite_du_cadre", not any(c.startswith("p_action_") or c == "confusion_z" for c in dec.columns))
    check("decoupage_decisions", (dec.split == [split_de(int(h), hv, hT, h1) for h in dec.h]).all())
    cf_path = root / "causal/contrefactuels.csv.gz"
    if cf_path.exists():
        cf = pd.read_csv(cf_path)
        cle = ["ts", "unite_cible"]
        n_fam = cf.groupby(cle + ["famille"]).scenario.nunique().unstack()
        check("contrefactuels_complets", set(n_fam.columns) == set(FAMILLES_ATTENDUES) and
              all((n_fam[f] == k).all() for f, k in FAMILLES_ATTENDUES.items()) and
              not cf.duplicated(cle + ["famille", "scenario"]).any())
        hz = int(json.loads((root / "causal/estimands.json").read_text())["horizon_h"])
        actifs = cf[cf.split != "embargo_ou_censure"]
        borne = np.where(actifs.h < hv, hv, np.where(actifs.h < hT, hT, h1))
        check("decoupage_contrefactuels_sans_franchissement",
              (cf.split == [split_de(int(h), hv, hT, h1) for h in cf.h]).all() and (actifs.h + hz <= borne).all())
        mets = [c for c in cf.columns if c.endswith(("_24h", f"_{hz}h"))]

        def egal(famille, ref, masque):
            g = cf[cf.famille == famille]
            base = g[g.scenario == ref].set_index(cle)[mets]
            nul = g[(g.scenario != ref) & masque(g)].set_index(cle)
            return len(nul), bool(np.allclose(nul[mets].values, base.loc[nul.index].values))
        fa, fb, fc = list(FAMILLES_ATTENDUES)
        na, oka = egal(fa, "aucun", lambda g: g.n_concernes == 0)
        nb, okb = egal(fb, "aucun", lambda g: (g.n_concernes == 0) & (g.scenario != "factuel"))
        nc, okc = egal(fc, "aucune", lambda g: g.expose == 0)
        check("nombres_aleatoires_communs_scenarios_sans_effet", oka and okb and okc,
              f"{na} + {nb} + {nc} lignes testées")
        B = cf[cf.famille == fb]
        fact = B[B.scenario == "factuel"]
        simples = fact[~fact.actions_h0.str.contains("+", regex=False)]
        imp = B.set_index(cle + ["scenario"])[mets]
        idx = list(zip(simples.ts, simples.unite_cible, simples.actions_h0))
        pv = cf[cf.scenario == "renfort_soignant_pourvu"]
        check("renfort_pourvu_toujours_present", len(pv) > 0 and (pv.n_concernes > 0).all(), int((pv.n_concernes == 0).sum()))
        check("factuel_egal_action_imposee_identique", np.allclose(simples[mets].values, imp.loc[idx].values),
              f"{len(simples)} lignes")
        dans = fact[fact.h + hz <= h1]
        ok = True
        for col_cf, col_et in (("attente_urg_patient_h", "attente_urgences_nb"), ("sorties", "sorties_h"),
                               ("entrees", "entrees_h")):
            cum = {e: (g.h.values[0], np.concatenate([[0], np.cumsum(g[col_et].values)]))
                   for e, g in un.sort_values("h").groupby("entite")}
            s_et = np.array([cum[u][1][h - cum[u][0] + hz] - cum[u][1][h - cum[u][0]]
                             for u, h in zip(dans.unite_cible, dans.h)])
            ok &= bool(np.allclose(s_et, dans[f"{col_cf}_{hz}h"].values))
        check("factuel_egal_verite", ok, f"{len(dans)} lignes")
    # --- couche séjour
    sv = pd.read_csv(root / "apprentissage/sejours_asof.csv.gz", low_memory=False)
    sc = pd.read_csv(root / "apprentissage/cibles_sejours.csv.gz", low_memory=False)
    check("sejours_colonnes_liste_fermee", list(sv.columns) == pc.COLONNES_SEJOURS_ASOF and
          list(sc.columns) == pc.COLONNES_CIBLES_SEJOURS, sorted(set(sv.columns) ^ set(pc.COLONNES_SEJOURS_ASOF)))
    check("sejours_cles_alignees", sv.sample_id.is_unique and (sv.sample_id.values == sc.sample_id.values).all()
          and (sv.sample_id == sv.sejour_id + "@" + sv.h.astype(str)).all())
    check("sejours_informations_disponibles_avant_l_instant", (sv.derniere_disponibilite <= sv.h).all())
    adm_h = dict(zip(sej.sejour_id, (t["ts_entree"] - debut_sim) / pd.Timedelta(hours=1)))
    ah = sv.sejour_id.map(adm_h)
    # un séjour absent de verite/sejours est sorti avant la période (fantôme hérité de la montée en charge)
    sorti_avant = ~sv.sejour_id.isin(sej.sejour_id)
    check("sejours_jamais_avant_l_admission_vraie", ((ah.notna() & (sv.h > ah)) | sorti_avant).all(),
          int((~((ah.notna() & (sv.h > ah)) | sorti_avant)).sum()))
    dsp = {}
    for (e, v), o in premier.items():
        if o["type"] == "DATE_SORTIE_PREVISIONNELLE":
            dsp[e] = ((pd.Timestamp(o["payload"]["date_prevue"]) - debut_sim).days, o["h_disponible"])
    ld = sv[sv.dsp_event_id.notna()]
    jour_dsp = ld.dsp_event_id.map(lambda e: dsp.get(e, (None, None))[0])
    dispo_dsp = ld.dsp_event_id.map(lambda e: dsp.get(e, (None, 1e18))[1])
    check("sejours_lignage_date_previsionnelle", jour_dsp.notna().all() and (dispo_dsp <= ld.h).all() and
          ((jour_dsp - ld.h // 24) == ld.dsp_jours_restants).all())
    check("sejours_decoupage", (sv.split == [split_de(int(h), hv, hT, h1) for h in sv.h]).all() and
          (sv.split == sc.split).all())
    sortie_h = dict(zip(sej.sejour_id, (t["ts_sortie"] - debut_sim) / pd.Timedelta(hours=1)))
    sh = sv.sejour_id.map(sortie_h)
    att = np.where(sh.notna(), ((sh >= sv.h) & (sh < sv.h + 24)).astype(float),
                   np.where(sv.h + 24 <= h1, 0.0, -1.0))
    obs = sc.cible_sortie_24h.map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0}).fillna(-1.0).values
    present = ((sv.h > ah) & (sh.isna() | (sh >= sv.h))).values
    pv = sc.cible_present_vrai.astype(str).eq("True").values
    check("sejours_cibles_conformes_verite", bool((obs == att).all() and (pv == present).all()),
          dict(sortie_24h=int((obs != att).sum()), present=int((pv != present).sum())))
    check("aucune_variable_privilegiee_ou_cible_sejours", not any(c.startswith("cible_") or c in PRIVILEGIES for c in sv.columns))

    # --- notes cliniques
    if (root / "observe/notes.jsonl.gz").exists():
        nts = jsonl(root / "observe/notes.jsonl.gz")
        anns = jsonl(root / "verite/notes_annotations.jsonl.gz")
        tsn = lambda s: pd.Timestamp(s[:19])  # noqa: E731
        par_note = {}
        for n in nts:
            par_note.setdefault(n["note_id"], []).append(n)
        ok = all(tsn(n["ts_creation"]) <= tsn(n["ts_modification"]) <= tsn(n["ts_disponible"]) for n in nts)
        ok &= all(abs((tsn(n["ts_disponible"]) - debut_sim) / pd.Timedelta(hours=1) - n["h_disponible"]) < 1 / 60 for n in nts)
        for vs in par_note.values():
            vs = sorted(vs, key=lambda n: n["version"])
            ok &= [n["version"] for n in vs] == list(range(1, len(vs) + 1))
            for a, b in zip(vs, vs[1:]):
                ok &= (b["remplace_version"] == a["version"] and b["texte"].startswith(a["texte"])
                       and b["h_disponible"] > a["h_disponible"] and b["ts_creation"] == a["ts_creation"])
        check("notes_horloges_et_versions_en_ajout_seul", ok)
        motif_date = re.compile(r"(\d{2})/(\d{2})/(\d{4})(?:\s*(?:à\s*)?(\d{2})h(\d{2}))?")
        futurs = 0
        for n in nts:
            lim = tsn(n["ts_modification"])
            for m in motif_date.finditer(n["texte"]):
                d = pd.Timestamp(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                if m.group(4):
                    d += pd.Timedelta(hours=int(m.group(4)), minutes=int(m.group(5)))
                    futurs += d > lim.floor("min")
                else:
                    futurs += d.normalize() > lim.normalize()
        check("notes_sans_date_posterieure_a_leur_redaction", futurs == 0, futurs)
        interdit = re.compile(r"sortie (?:prévue|programmée|le \d)|date de sortie|\bDMS\b|durée de séjour", re.I)
        check("notes_sans_mention_de_sortie_future", not any(interdit.search(n["texte"]) for n in nts))
        texte = {(n["note_id"], n["version"]): n["texte"] for n in nts}
        ok = set(texte) == {(a["note_id"], a["version"]) for a in anns}
        for a in anns:
            t = texte.get((a["note_id"], a["version"]), "")
            for f in a["faits"]:
                ok &= (t[f["debut"]:f["fin"]] == f["extrait"] and f["variable"] in nt.VARIABLES_NOTES
                       and f["variable"] not in nt.VARIABLES_INTERDITES
                       and f["statut"] in ("documente", "negation", "hypothese")
                       and f["correct"] in ("vrai", "faux", "perime", "prevision"))
        check("notes_annotations_conformes_au_texte", ok)
        check("notes_dans_la_periode", all(n["h_disponible"] < h1 for n in nts))
        # complétude : toute phrase portant un marqueur explicite d'une variable doit être annotée pour cette variable
        manques = {}
        for n, a in zip(*_aligner(nts, anns)):
            t = n["texte"]
            spans = [(f["debut"], f["fin"], f["variable"]) for f in a["faits"]]
            for m in re.finditer(r"[^.\n]+", t):
                ph = m.group(0)
                for var, motif in nt.MARQUEURS.items():
                    if re.search(motif, ph, re.I) and not any(d < m.end() and f > m.start() and v in nt.COUVRE[var]
                                                              for d, f, v in spans):
                        manques[var] = manques.get(var, 0) + 1
        check("notes_annotations_completes_sur_marqueurs", not manques, manques)
        # conformité : un fait « vrai » égale la situation vraie ; un fait « faux » ou « périmé » en diffère
        cl = pd.read_csv(root / "verite/sejours_cliniques.csv.gz").set_index("sejour_id")
        sj = sej.set_index("sejour_id")
        iso_type = {txt: typ for typ, txt in nt.T.CAUSES_ISOLEMENT}
        ecarts = {}
        for a in anns:
            sid = a["sejour_id"]
            if sid not in cl.index:
                continue
            c, s_ = cl.loc[sid], sj.loc[sid]
            vrai = dict(motif=c.motif, vit_seul=bool(c.vit_seul), aidant_present=bool(c.aidant_present),
                        aides_existantes=bool(c.aides_existantes), troubles_cognitifs=bool(c.troubles_cognitifs),
                        perte_autonomie_recente=bool(c.perte_autonomie_recente),
                        evaluation_sociale_demandee=bool(c.evaluation_sociale_demandee), autonomie=int(s_.dependance),
                        mobilite=s_.mobilite, oxygene=bool(s_.oxygene), imagerie_prevue=bool(s_.imagerie_requise),
                        avis_prevu=bool(s_.avis_requis),
                        isolement=iso_type.get(c.cause_isolement) if isinstance(c.cause_isolement, str) else None)
            for f in a["faits"]:
                v = f["variable"]
                if v not in vrai:
                    continue
                if (f["correct"] == "vrai") != (f["valeur"] == vrai[v]):
                    ecarts[v] = ecarts.get(v, 0) + 1
        check("notes_faits_conformes_a_la_verite", not ecarts, ecarts)
        # cohérence : aucune contradiction entre les faits « vrais » d'un même séjour, toutes notes confondues
        par_sejour = {}
        for a in anns:
            par_sejour.setdefault(a["sejour_id"], []).extend(f["extrait"].lower() for f in a["faits"] if f["correct"] == "vrai")
        contradictions = {}
        for nom, (g, d) in nt.INCOMPATIBLES.items():
            k = sum(1 for ex_ in par_sejour.values() if any(re.search(g, x) for x in ex_) and any(re.search(d, x) for x in ex_))
            if k:
                contradictions[nom] = k
        check("notes_sans_contradiction_hors_erreurs_volontaires", not contradictions, contradictions)

        et_n = pd.read_csv(root / "apprentissage/etat_notes_asof.csv.gz", low_memory=False)
        from . import extraction as ex_
        ok = (et_n.h_utilisable >= et_n.h_disponible).all()
        for v in ex_.VARIABLES:
            hs_ = et_n[v + "_h_source"]
            ok &= bool((hs_.isna() | (hs_ <= et_n.h_disponible + 1e-9)).all())
        connu = et_n[[v for v in ex_.VARIABLES]].notna()
        deja = connu.groupby(et_n.sejour_id).cummax()
        check("etat_notes_sans_effacement_ni_futur", ok and bool((connu | ~deja).all().all()),
              int((~connu & deja).sum().sum()))
        copies, provenance = controler_fusion(et_n, nts)
        check("etat_notes_copies_sans_rafraichissement", copies == 0, copies)
        check("etat_notes_provenance_verifiable", provenance == 0, provenance)
        xn = pd.read_csv(root / "apprentissage/extraction_notes.csv.gz", low_memory=False)
        cle_n = {(n["note_id"], n["version"]): n["h_disponible"] for n in nts}
        check("extraction_alignee_sur_les_notes", len(xn) == len(nts) and all(
            abs(cle_n.get((i, int(v)), -1e9) - h) < 1e-6 for i, v, h in zip(xn.note_id, xn.version, xn.h_disponible))
            and (xn.h_utilisable >= xn.h_disponible).all())

    check("etiquette_synthetique", all(o["synthetique"] for o in livr) and rep["statut"].startswith("SYNTHETIQUE"))

    res = dict(statut="PASS" if all(checks.values()) else "FAIL", controles=checks, details_echecs=details,
               reussis=sum(checks.values()), total=len(checks),
               portee="COHERENCE_INTERNE_UNIQUEMENT_PAS_DE_VALIDATION_EMPIRIQUE_NI_CLINIQUE")
    (root / "rapport_controles.json").write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n")
    manif = [dict(chemin=str(p.relative_to(root)), octets=p.stat().st_size,
                  sha256=hashlib.sha256(p.read_bytes()).hexdigest())
             for p in sorted(root.rglob("*")) if p.is_file() and p.name not in ("manifest.json",)]
    (root / "manifest.json").write_text(json.dumps(manif, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


if __name__ == "__main__":
    r = main(sys.argv[1])
    sys.exit(0 if r["statut"] == "PASS" else 1)
