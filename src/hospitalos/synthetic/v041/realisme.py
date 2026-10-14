"""
Contrôle de réalisme et de cohérence causale d'un jeu généré.

Usage : python realisme.py <dossier_donnees> [--figures]
Écrit rapport_realisme.json (et realisme.png avec --figures) dans le dossier.
"""
import json
import sys

import numpy as np
import pandas as pd


def stats(dossier):
    s = pd.read_csv(f"{dossier}/verite/sejours.csv.gz")
    for c in ("ts_decision", "ts_entree", "ts_sortie"):
        s[c] = pd.to_datetime(s[c].str[:19])
    e = pd.read_csv(f"{dossier}/verite/etats_horaires.csv.gz")
    e["ts"] = pd.to_datetime(e.ts.str[:19])
    e = e[e.niveau == "unite"].rename(columns={"entite": "unite"})
    e["lits_installes"] = e.lits_physiques - e.lits_supplementaires_actifs
    e["lits_utilisables_libres"] = e.lits_propres_libres
    eff = pd.read_csv(f"{dossier}/verite/effectifs_postes.csv.gz")
    dec = pd.read_csv(f"{dossier}/causal/decisions.csv.gz")
    va = pd.read_csv(f"{dossier}/apprentissage/variables_asof.csv.gz")
    r = {"par_unite": {}}
    for unite, g in s.groupby("unite_cible"):
        so = g[g.issue == "sortie"]
        urg = g[g.mode_entree == "urgences"]
        a = urg.attente_avant_lit_h.dropna()
        eu = e[e.unite == unite]
        r["par_unite"][unite] = dict(
            sejours=int(len(g)),
            sorties=int(len(so)),
            dms_moyenne_j=round(so.dms_jours.mean(), 2),
            dms_mediane_j=round(so.dms_jours.median(), 2),
            part_sejours_moins_48h=round((so.dms_jours < 2).mean(), 3),
            modes_entree=g.mode_entree.value_counts(normalize=True).round(3).to_dict(),
            destinations=so.destination.value_counts(normalize=True).round(3).to_dict(),
            occupation_lits_ouverts=round((eu.lits_occupes / eu.lits_ouverts).mean(), 3),
            occupation_lits_installes=round((eu.lits_occupes / eu.lits_installes).mean(), 3),
            heures_sans_lit_utilisable=round((eu.lits_utilisables_libres == 0).mean(), 3),
            attente_urg_mediane_h=round(a.median(), 2),
            attente_urg_p90_h=round(a.quantile(0.9), 2),
            attente_urg_part_sup_4h=round((a > 4).mean(), 3),
            attente_urg_part_sup_12h=round((a > 12).mean(), 3),
            part_heberges=round(g.heberge.mean(), 3),
            part_hors_perimetre=round((g.issue == "hors_perimetre").mean(), 3),
            deprogrammations=int((g.issue == "deprogramme").sum()),
            ratio_charge_moyen=round(eu.ratio_charge.mean(), 3),
            part_heures_ratio_sup_115=round((eu.ratio_charge > 1.15).mean(), 3),
            sorties_sous_pression=int(g.sortie_sous_pression.sum()),
            sorties_retardees_par_charge=int((g.retard_sortie_charge_h > 0).sum()),
            readmission_30j=round(so.readmission_30j.dropna().astype(str).eq("True").mean(), 3),
            ei_observes=int(eu.ei_observes_h.sum()),
            part_heberges_rapatries=round((g[g.heberge].rapatriements > 0).mean(), 3) if g.heberge.any() else None,
            attente_transport_moy=round(eu.en_attente_transport.mean(), 2),
            attente_imagerie_moy=round(eu.en_attente_imagerie.mean(), 2),
            lits_sales_moy=round(eu.lits_sales_ou_nettoyage.mean(), 2),
            heure_sortie_domicile=so[so.destination == "domicile"].ts_sortie.dt.hour.value_counts(
                normalize=True).sort_index().round(3).to_dict(),
            jour_sortie=so.ts_sortie.dt.dayofweek.value_counts(normalize=True).sort_index().round(3).to_dict(),
            occupation_mensuelle=(eu.groupby(eu.ts.dt.month).apply(
                lambda x: (x.lits_occupes / x.lits_ouverts).mean(), include_groups=False)).round(3).to_dict(),
            absenteisme=round((eff[eff.unite == unite].absences.sum() / eff[eff.unite == unite].soignants_prevus.sum()), 3),
        )
    vu = va[va.niveau == "unite"].merge(e[["h", "unite", "lits_occupes"]], left_on=["h", "entite"], right_on=["h", "unite"])
    ec = vu.obs_lits_occupes - vu.lits_occupes
    r["ecart_observe_vs_vrai_lits"] = dict(moyen=round(ec.mean(), 3), abs_moyen=round(ec.abs().mean(), 3),
                                           part_non_nul=round((ec != 0).mean(), 3),
                                           age_observation_median_h=round(vu.age_observation_h.median(), 2),
                                           part_manquante=round(vu.observation_manquante.mean(), 4))
    r["politique"] = {c[2:]: dict(taux_action=round(dec[c].mean(), 3),
                                  q_reco_min=round(dec["q_reco_" + c[2:]].min(), 3),
                                  q_reco_max=round(dec["q_reco_" + c[2:]].max(), 3),
                                  part_q_strictement_entre_0_et_1=round(dec["q_reco_" + c[2:]].between(0.001, 0.999).mean(), 3))
                      for c in dec.columns if c.startswith("a_")}
    r["chaine_decision"] = {lev: dict(
        recommande=round(dec["r_" + lev].mean(), 3),
        valide_si_recommande_et_vu=round(dec.loc[(dec["r_" + lev] == 1) & (dec.exposition == 1), "a_" + lev].mean(), 3),
        initiative_sans_recommandation_vue=round(dec.loc[~((dec["r_" + lev] == 1) & (dec.exposition == 1)), "a_" + lev].mean(), 3),
        execute=round(dec["x_" + lev].mean(), 3),
        echec_si_engage=round(1 - dec.loc[dec["a_" + lev] == 1, "x_" + lev].mean(), 3))
        for lev in [c[2:] for c in dec.columns if c.startswith("x_")]}
    r["chaine_decision"]["exposition"] = round(dec.exposition.mean(), 3)
    r["mecanismes_v03"] = {u: dict(
        part_avis=round(g.avis_requis.mean(), 3), part_aide_domicile=round(g.aide_domicile_requise.mean(), 3),
        mobilite=g.mobilite.value_counts(normalize=True).round(3).to_dict())
        for u, g in s.groupby("unite_cible")}
    r["sejours_asof"] = qualite_sejours(dossier, s)
    r["notes"] = stats_notes(dossier)
    try:
        cf = pd.read_csv(f"{dossier}/causal/contrefactuels.csv.gz")
        r["effets_causaux_verite"] = effets(cf)
        r["biais_comparaison_naive"] = biais_naif(cf, dec)
    except FileNotFoundError:
        pass
    return r


def stats_notes(dossier):
    """Volumes, délais de disponibilité, taux de documentation et erreurs des notes synthétiques."""
    import gzip
    try:
        nts = [json.loads(l) for l in gzip.open(f"{dossier}/observe/notes.jsonl.gz", "rt")]
        anns = [json.loads(l) for l in gzip.open(f"{dossier}/verite/notes_annotations.jsonl.gz", "rt")]
    except FileNotFoundError:
        return None
    d = pd.DataFrame(nts)
    for c in ("ts_creation", "ts_modification", "ts_disponible"):
        d[c] = pd.to_datetime(d[c].str[:19])
    d["delai_dispo_h"] = (d.ts_disponible - d.ts_creation) / pd.Timedelta(hours=1)
    d["longueur"] = d.texte.str.len()
    der = d.sort_values("version").groupby("note_id").tail(1)
    out = dict(notes=int(d.note_id.nunique()), versions=int(len(d)),
               par_type={t: dict(notes=int(g.note_id.nunique()), versions_par_note=round(len(g) / g.note_id.nunique(), 2),
                                 longueur_mediane=int(der[der.type_note == t].longueur.median()),
                                 delai_creation_disponibilite_median_h=round(g.delai_dispo_h.median(), 2),
                                 part_disponible_plus_de_2h_apres_creation=round((g.delai_dispo_h > 2).mean(), 3))
                         for t, g in d.groupby("type_note")})
    faits = pd.DataFrame([dict(type_note=n["type_note"], version=n["version"], **f) for n, a in zip(nts, anns)
                          for f in a["faits"]])
    tf = faits.groupby("type_note")
    nv = d.groupby("type_note").size()
    out["faits_par_version"] = {t: round(len(g) / max(int(nv[t]), 1), 1) for t, g in tf}
    out["statuts"] = faits.statut.value_counts(normalize=True).round(3).to_dict()
    out["exactitude"] = faits.correct.value_counts(normalize=True).round(3).to_dict()
    return out


def qualite_sejours(dossier, sej):
    """Qualité de la couche séjour : couverture, absences, précision de la date de sortie prévisionnelle."""
    v = pd.read_csv(f"{dossier}/apprentissage/sejours_asof.csv.gz", low_memory=False,
                    usecols=["sample_id", "h", "sejour_id", "dsp_jours_restants", "dsp_absente", "destination_demandee",
                             "dependance_obs", "demande_aval_en_attente", "aide_domicile_requise"])
    c = pd.read_csv(f"{dossier}/apprentissage/cibles_sejours.csv.gz", low_memory=False,
                    usecols=["sample_id", "cible_present_vrai", "cible_duree_restante_h"])
    d = v.merge(c, on="sample_id")
    pv = d.cible_present_vrai.astype(str).eq("True")
    x = d[pv & d.cible_duree_restante_h.notna() & d.dsp_jours_restants.notna() & (d.h % 24 == 12)]
    reel = np.floor((x.h + x.cible_duree_restante_h) / 24) - np.floor(x.h / 24)
    err = x.dsp_jours_restants - reel
    return dict(lignes=int(len(d)), sejours_par_heure_moyen=round(d.groupby("h").size().mean(), 1),
                part_fantomes=round(1 - pv.mean(), 4),
                part_sans_date_previsionnelle=round(d.dsp_absente.astype(str).eq("True").mean(), 3),
                part_sans_destination_demandee=round(d.destination_demandee.isna().mean(), 3),
                part_sans_evaluation=round(d.dependance_obs.isna().mean(), 3),
                date_previsionnelle=dict(echantillon_midi=int(len(x)), jour_exact=round((err == 0).mean(), 3),
                                         a_un_jour_pres=round((err.abs() <= 1).mean(), 3),
                                         erreur_moyenne_j=round(err.mean(), 2), erreur_absolue_moyenne_j=round(err.abs().mean(), 2)))


def effets(cf):
    """Effets vrais par famille de contrefactuels (différences appariées, mêmes aléas)."""
    key = ["ts", "unite_cible"]
    cols = [c for c in cf.columns if c.endswith("_72h") and not c.startswith("pole_")]
    cols += [c for c in cf.columns if c.startswith("pole_") and c.endswith("_72h")]
    out = {}
    for fam, ref in (("A_levier_seul_puis_rien", "aucun"), ("B_action_imposee_puis_politique", "aucun"),
                     ("C_recommandation_imposee_puis_politique", "aucune")):
        g0 = cf[cf.famille == fam]
        base = g0[g0.scenario == ref].set_index(key)
        out[fam] = {}
        for lev, g in g0[~g0.scenario.isin([ref, "factuel"])].groupby("scenario"):
            g = g.set_index(key)
            d = g[cols] - base.loc[g.index, cols]
            if fam.startswith("C"):
                actif = pd.Series(True, index=g.index)
            else:
                actif = g.n_concernes > 0
            r = dict(part_jours=round(actif.mean(), 3),
                     effet_moyen={c: round(d.loc[actif, c].mean(), 3) for c in cols})
            if fam.startswith("C"):
                r["part_validee"] = round(g.levier_valide.mean(), 3)
                r["part_executee"] = round((g.levier_valide.astype(bool) & (g.n_concernes > 0)).mean(), 3)
            out[fam][lev] = r
    return out


def biais_naif(cf, dec):
    """Comparaison naïve des jours avec et sans action exécutée, face à l'effet vrai (famille B)."""
    key = ["ts", "unite_cible"]
    B = cf[cf.famille == "B_action_imposee_puis_politique"]
    fact = B[B.scenario == "factuel"].set_index(key)
    base = B[B.scenario == "aucun"].set_index(key)
    d = dec.rename(columns={"unite": "unite_cible"}).set_index(key)
    y = "attente_urg_patient_h_72h"
    out = {}
    for lev in [c[2:] for c in dec.columns if c.startswith("x_")]:
        x = d.loc[fact.index, "x_" + lev]
        naif = fact.loc[x == 1, y].mean() - fact.loc[x == 0, y].mean()
        g = B[B.scenario == lev].set_index(key)
        vrai = (g[y] - base.loc[g.index, y])[g.n_concernes > 0].mean()
        out[lev] = dict(jours_executes=int(x.sum()), difference_naive=round(naif, 2), effet_vrai_si_applicable=round(vrai, 2))
    return out


def figures(dossier):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = pd.read_csv(f"{dossier}/verite/sejours.csv.gz")
    s["ts_sortie"] = pd.to_datetime(s.ts_sortie.str[:19])
    e = pd.read_csv(f"{dossier}/verite/etats_horaires.csv.gz")
    e["ts"] = pd.to_datetime(e.ts.str[:19])
    e = e[e.niveau == "unite"].rename(columns={"entite": "unite"})
    e["lits_installes"] = e.lits_physiques - e.lits_supplementaires_actifs
    units = list(e.unite.unique())
    fig, ax = plt.subplots(2, 3, figsize=(16, 8.5))
    for u in units:
        eu = e[e.unite == u].set_index("ts")
        occ = (eu.lits_occupes / eu.lits_installes).resample("W").mean()
        ax[0, 0].plot(occ.index, occ.values, label=u)
        ax[0, 1].plot(eu.ratio_charge.resample("W").mean().index, eu.ratio_charge.resample("W").mean().values, label=u)
        att = eu.attente_urgences_nb.resample("W").mean()
        ax[0, 2].plot(att.index, att.values, label=u)
    ax[0, 0].set_title("Occupation des lits installés (moyenne hebdomadaire)")
    ax[0, 1].set_title("Ratio charge en soins / effectif présent")
    ax[0, 2].set_title("Patients en attente d'un lit aux urgences")
    so = s[s.issue == "sortie"]
    for u in units:
        ax[1, 0].hist(so[so.unite_cible == u].dms_jours.clip(upper=30), bins=60, histtype="step", label=u, density=True)
    ax[1, 0].set_title("Durée de séjour (jours, tronquée à 30)")
    a = s[s.mode_entree == "urgences"].attente_avant_lit_h.dropna().clip(upper=36)
    ax[1, 1].hist(a, bins=72, color="#5b7bd5")
    ax[1, 1].set_title("Attente entre décision et lit (h), patients des urgences")
    sem = e.copy()
    sem["heure"] = sem.ts.dt.hour
    prof = sem.groupby("heure")[["entrees_h", "sorties_h"]].mean()
    ax[1, 2].plot(prof.index, prof.entrees_h, label="entrées")
    ax[1, 2].plot(prof.index, prof.sorties_h, label="sorties")
    ax[1, 2].set_title("Entrées et sorties moyennes par heure")
    for a_ in ax.flat:
        a_.legend(fontsize=8)
        a_.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(f"{dossier}/realisme.png", dpi=110)


if __name__ == "__main__":
    d = sys.argv[1]
    r = stats(d)
    with open(f"{d}/rapport_realisme.json", "w") as f:
        json.dump(r, f, ensure_ascii=False, indent=1, default=str)
    if "--figures" in sys.argv:
        figures(d)
    pu = r["par_unite"]
    for u, v in pu.items():
        print(u, {k: v[k] for k in ["dms_moyenne_j", "dms_mediane_j", "occupation_lits_ouverts", "attente_urg_mediane_h",
                                    "attente_urg_p90_h", "attente_urg_part_sup_4h", "attente_urg_part_sup_12h",
                                    "part_heberges", "part_hors_perimetre", "ratio_charge_moyen",
                                    "part_heures_ratio_sup_115", "sorties_sous_pression", "readmission_30j",
                                    "sorties_retardees_par_charge", "absenteisme", "deprogrammations", "part_heberges_rapatries",
                                    "attente_transport_moy", "attente_imagerie_moy", "lits_sales_moy"]})
        print("  heure sortie dom", v["heure_sortie_domicile"])
        print("  jour sortie", v["jour_sortie"])
        print("  occ mensuelle", v["occupation_mensuelle"])
    print("observe vs vrai", r["ecart_observe_vs_vrai_lits"])
    print("politique", r["politique"])
    print("chaine", json.dumps(r["chaine_decision"], ensure_ascii=False))
    print("mecanismes", json.dumps(r["mecanismes_v03"], ensure_ascii=False))
    print("sejours", json.dumps(r["sejours_asof"], ensure_ascii=False))
    print("notes", json.dumps(r["notes"], ensure_ascii=False))
    if "effets_causaux_verite" in r:
        for fam, levs in r["effets_causaux_verite"].items():
            print(fam)
            for lev, v in levs.items():
                print("  ", lev, {k: x for k, x in v.items() if k != "effet_moyen"},
                      {k: x for k, x in v["effet_moyen"].items()
                       if any(t in k for t in ["attente", "hebergements", "minutes_non", "heures_ratio"])})
        print("biais", json.dumps(r["biais_comparaison_naive"], ensure_ascii=False))
