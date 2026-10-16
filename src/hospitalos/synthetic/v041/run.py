"""
Génère un an de données synthétiques HospitalOS (v0.2) : un pôle, ses unités, et la projection d'une unité focale.

Usage :
    python run.py --sortie ../data
Options : --echelle (pole | unite), --unite-focale, --seed, --annee, --sans-contrefactuels, --processus
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import multiprocessing as mp
import os
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import hospsim as hs
from . import observation as ob
from . import parcours as pc
from . import notes as nt
from . import extraction as ex

VERSION = "0.4.1"
ECHELLES = {"unite": ["MED_POLY"], "pole": ["MED_POLY", "CSG", "PNEUMO", "CARDIO"]}
WARMUP_J = 61
APRES_J = 9


# --------------------------------------------------------------------------
# Journal de la simulation factuelle
# --------------------------------------------------------------------------

class Journal:
    def __init__(self, sim):
        self.sim = sim
        self.etats, self.actions, self.sejours, self.events, self.cadre = [], [], [], [], []
        self.taches = {}

    def _rec(self, h):
        return self.sim.h0_rec <= h < self.sim.h1_rec

    def event(self, h, typ, u, pid, **payload):
        self.events.append(dict(h=h, type=typ, u=u, pid=pid, payload=payload))

    def etat(self, h, u, row):
        row = dict(row, h=h, u=u)
        self.etats.append(row)
        self.event(h, "ETAT_UNITE", u, None, **{k: v for k, v in row.items() if k not in ("h", "u")})

    def action(self, h, u, f, q, reco, expo, pa, z, acts, nconc):
        if self._rec(h):
            row = dict(h=h, u=u, **f)
            for k, nom in enumerate(hs.LEVIERS):
                row[f"q_reco_{nom}"] = round(q[k], 4)
                row[f"r_{nom}"] = int(reco[k])
            row["exposition"] = int(expo)
            for k, nom in enumerate(hs.LEVIERS):
                row[f"a_{nom}"] = int(acts[k])
                row[f"n_concernes_{nom}"] = int(nconc[k])
                row[f"x_{nom}"] = int(acts[k] and nconc[k] > 0)
            self.actions.append(row)
            self.cadre.append(dict(h=h, u=u, confusion_z=round(z, 4),
                                   **{f"p_action_{nom}": round(pa[k], 4) for k, nom in enumerate(hs.LEVIERS)}))

    def tache(self, kind, tid, u, pid, lit, h):
        self.taches[tid] = dict(tache_id=tid, type=kind, u=u, pid=pid, lit=lit, h_demande=h, h_debut=None, h_fin=None)
        self.event(h, kind + "_DEMANDE", u, pid, tache_id=tid, lit=lit)

    def tache_debut(self, tid, h):
        t = self.taches[tid]
        t["h_debut"] = h
        self.event(h, t["type"] + "_DEBUT", t["u"], t["pid"], tache_id=tid)

    def tache_fin(self, tid, h):
        t = self.taches[tid]
        t["h_fin"] = h
        self.event(h, t["type"] + "_FIN", t["u"], t["pid"], tache_id=tid)

    def sejour(self, sim, p, h, issue):
        self.sejours.append(dict(
            pid=p.pid, home=p.home, unit=p.unit, lit=p.bed, issue=issue, dec_h=p.dec_h, admit_h=p.admit_h,
            ready_h=p.ready_h, exit_h=h, hosted=p.hosted, press=p.press, retard=int(p.delayed), accel=p.accel,
            antic=p.antic, rapat=p.rapat, aide_h=p.aide_h))


# --------------------------------------------------------------------------
# Simulation factuelle et calibrage
# --------------------------------------------------------------------------

def construire(units, seed, annee, echelles):
    debut = dt.date(annee, 1, 1) - dt.timedelta(WARMUP_J)
    fin = dt.date(annee + 1, 1, 1) + dt.timedelta(APRES_J)
    exo = hs.Exo(units, debut, fin, seed, echelles)
    h0 = WARMUP_J * 24
    h1 = h0 + (dt.date(annee + 1, 1, 1) - dt.date(annee, 1, 1)).days * 24
    return exo, h0, h1


def verifier(sim, st, h, viol):
    """Invariants lit par lit, contrôlés à chaque heure de la simulation factuelle."""
    x = sim.x
    vus = set()
    for u in range(sim.U):
        n_occ = 0
        for b, pid in enumerate(st.bed_pid[u]):
            if pid == -1:
                continue
            n_occ += 1
            p = st.occ[u].get(pid)
            viol["lit_double_affectation"] += pid in vus
            vus.add(pid)
            viol["lien_patient_lit"] += p is None or p.bed != b or p.unit != u
            viol["compatibilite_lit"] += bool((sim.p_iso[pid] and not x.lit_iso[u][b]) or (sim.p_oxy[pid] and not x.lit_oxy[u][b]))
            viol["lit_occupe_et_sale"] += st.bed_sale[u][b] != 0
        viol["occupation_vs_lits"] += n_occ != len(st.occ[u])
        phys, ferm, ouv, occ, sale, libre = sim.compte_lits(st, u, h)
        viol["partition_lits"] += (ouv != occ + sale + libre) or (phys != ferm + ouv)
    viol["registre_patients"] += len(vus) != len(st.patients)
    viol["heures_controlees"] += 1


def simuler(sim, journal=None, snap=None, jusqu_a=None, viol=None, capture=None):
    """Simulation factuelle. capture : dict rempli avec un clone de l'état au début de l'heure h1
    (fin de la période enregistrée), pour construire les séjours censurés sans information postérieure."""
    st = hs.State(sim.x)
    occ_sum = np.zeros(sim.U)
    n = 0
    for h in range(jusqu_a or sim.x.H):
        if capture is not None and h == sim.h1_rec:
            capture["etat"] = st.clone()
        m = sim.step(st, h, politique=True, log=journal, snap=snap)
        if viol is not None:
            verifier(sim, st, h, viol)
        if sim.h0_rec <= h < sim.h1_rec:
            occ_sum += m["occ"]
            n += 1
    return st, occ_sum / max(n, 1)


def evenements(journal, units, h1):
    """Événements vrais numérotés, dans l'ordre de production."""
    return [dict(event_id=f"E{i + 1:08d}", h=e["h"], type=e["type"], unite=units[e["u"]],
                 sejour=(f"S{int(e['pid']):06d}" if e["pid"] is not None else None), payload=e["payload"])
            for i, e in enumerate(journal.events) if e["h"] < h1]


def calibrer(units, echelle, seed, annee, iterations=8, tolerance=0.01, log=print):
    """Ajuste le volume d'arrivées de chaque unité pour atteindre l'occupation visée.

    Retient l'itération mesurée la plus proche de la cible (jamais une correction non vérifiée).
    """
    ech = {u: 1.0 for u in units}
    meilleur, err_min = dict(ech), 9.0
    cible = hs.P["occupation_cible"]
    for it in range(iterations):
        exo, h0, h1 = construire(units, seed, annee, ech)
        sim = hs.Sim(exo, echelle, h0, h1)
        _, occ = simuler(sim, jusqu_a=h1)
        err = float(np.max(np.abs(occ - cible)))
        log(f"  calibrage {it + 1}/{iterations} : occupation " + ", ".join(f"{u}={o:.3f}" for u, o in zip(units, occ))
            + f" (écart max {err:.3f})")
        if err < err_min:
            meilleur, err_min = dict(ech), err
        if err < tolerance:
            break
        for u, o in zip(units, occ):
            ech[u] *= float(np.clip((cible / o) ** 1.2, 0.8, 1.25))
    log(f"  échelles retenues (écart max {err_min:.3f})")
    return meilleur


# --------------------------------------------------------------------------
# Contrefactuels (nombres aléatoires communs)
# --------------------------------------------------------------------------

_SIM = None
_SNAPS = None


FAMILLES = {
    "A_levier_seul_puis_rien": "Levier engagé seul à 9 h à l'unité ciblée, avec son éventuel échec d'exécution ; aucune "
                               "décision ensuite, nulle part. Scénario « renfort_soignant_pourvu » : renfort présent.",
    "B_action_imposee_puis_politique": "Actions de l'unité ciblée engagées à 9 h (aucune, ou un levier seul), avec "
                                       "leurs échecs d'exécution (renfort non pourvu) ; les autres unités et les jours "
                                       "suivants suivent la politique en vigueur (recommandeur + cadre). Scénario "
                                       "« renfort_soignant_pourvu » : renfort effectivement présent. Scénario « factuel » : "
                                       "rien n'est imposé.",
    "C_recommandation_imposee_puis_politique": "Recommandations de l'unité ciblée imposées à 9 h (aucune, ou un "
                                               "levier seul) ; exposition, validation et exécution suivent leurs "
                                               "mécanismes ; ensuite la politique en vigueur. Effet en intention "
                                               "de traiter, non-adoption comprise.",
}


def metriques(sim, st, h0, horizon, politique=False, force=None):
    """Déroule `horizon` heures ; métriques cumulées à 24 h et à l'horizon, et décision de 9 h au départ."""
    U = sim.U
    acc = {k: np.zeros(U) for k in ("attente", "heberg", "hors", "annul_prog", "pression", "ei", "occ",
                                    "ratio_max", "h_ratio_sup", "non_couvert", "entrees", "sorties")}
    out = {}
    decision0 = None
    for i in range(horizon):
        m = sim.step(st, h0 + i, politique=politique, force=force)
        if i == 0:
            decision0 = dict(st.derniere)
        acc["attente"] += m["attente"]
        acc["heberg"] += m["heberg_sortants"] + m["hors_perimetre"]
        acc["hors"] += m["hors_perimetre"]
        acc["annul_prog"] += m["annul_prog"]
        acc["pression"] += m["pression"]
        acc["ei"] += m["ei_att"]
        acc["occ"] += m["occ"]
        acc["ratio_max"] = np.maximum(acc["ratio_max"], m["ratio"])
        acc["h_ratio_sup"] += m["ratio"] > 1.15
        acc["non_couvert"] += m["non_couvert"]
        acc["entrees"] += m["entrees"]
        acc["sorties"] += m["sorties"]
        if i + 1 in (24, horizon):
            s = {k: v.copy() for k, v in acc.items()}
            s["occ"] = s["occ"] / (i + 1)
            out[i + 1] = s
    return out, decision0


def _worker(idx):
    sim, (h0, st0) = _SIM, _SNAPS[idx]
    H = hs.P["horizon_cf_h"]
    L = len(hs.LEVIERS)
    fa, fb, fc = list(FAMILLES)
    rows = []
    # A : levier seul puis rien (référence commune à toutes les unités)
    base, _ = metriques(sim, st0.clone(), h0, H)
    for u in range(sim.U):
        rows.append(_ligne(sim, h0, u, fa, "aucun", 0, base))
    for u in range(sim.U):
        for k, nom in enumerate(hs.LEVIERS):
            st = st0.clone()
            n = sim.appliquer(st, u, k, h0)
            rows.append(_ligne(sim, h0, u, fa, nom, n, metriques(sim, st, h0, H)[0]))
        st = st0.clone()
        n = sim.appliquer(st, u, 2, h0, garanti=True)
        rows.append(_ligne(sim, h0, u, fa, "renfort_soignant_pourvu", n, metriques(sim, st, h0, H)[0]))
    # B : factuel (rien d'imposé), puis actions imposées
    fact, dec = metriques(sim, st0.clone(), h0, H, politique=True)
    for u in range(sim.U):
        reco, expo, acts, nconc = dec[u]
        combo = "+".join(hs.LEVIERS[k] for k in range(L) if acts[k]) or "aucun"
        rows.append(_ligne(sim, h0, u, fb, "factuel", sum(nconc), fact,
                           dict(actions_h0=combo, expose=expo)))
    for u in range(sim.U):
        for k in range(-1, L):
            a = [int(j == k) for j in range(L)]
            res, dec = metriques(sim, st0.clone(), h0, H, politique=True, force=(h0, u, None, a))
            nom = "aucun" if k < 0 else hs.LEVIERS[k]
            rows.append(_ligne(sim, h0, u, fb, nom, 0 if k < 0 else dec[u][3][k], res, dict(expose=dec[u][1])))
        res, dec = metriques(sim, st0.clone(), h0, H, politique=True, force=(h0, u, None, [0, 0, 1, 0], True))
        rows.append(_ligne(sim, h0, u, fb, "renfort_soignant_pourvu", dec[u][3][2], res, dict(expose=dec[u][1])))
    # C : recommandations imposées
    for u in range(sim.U):
        for k in range(-1, L):
            r = [int(j == k) for j in range(L)]
            res, dec = metriques(sim, st0.clone(), h0, H, politique=True, force=(h0, u, r, None))
            nom = "aucune" if k < 0 else hs.LEVIERS[k]
            reco, expo, acts, nconc = dec[u]
            extra = dict(expose=expo, actions_h0="+".join(hs.LEVIERS[j] for j in range(L) if acts[j]) or "aucun")
            if k >= 0:
                extra["levier_valide"] = int(acts[k])
            rows.append(_ligne(sim, h0, u, fc, nom, 0 if k < 0 else nconc[k], res, extra))
    return rows


def _ligne(sim, h0, u, famille, scenario, n, res, extra=None):
    row = dict(h=h0, u=u, famille=famille, scenario=scenario, n_concernes=n)
    row.update(extra or {})
    for hz, m in res.items():
        s = f"_{hz}h"
        row["attente_urg_patient_h" + s] = m["attente"][u]
        row["hebergements" + s] = m["heberg"][u]
        row["hors_perimetre" + s] = m["hors"][u]
        row["deprogrammations" + s] = m["annul_prog"][u]
        row["sorties_sous_pression" + s] = m["pression"][u]
        row["ei_attendus" + s] = round(m["ei"][u], 5)
        row["occupation_moy" + s] = round(m["occ"][u], 4)
        row["ratio_charge_max" + s] = round(m["ratio_max"][u], 3)
        row["heures_ratio_sup_115" + s] = m["h_ratio_sup"][u]
        row["minutes_non_couvertes" + s] = round(m["non_couvert"][u], 1)
        row["entrees" + s] = m["entrees"][u]
        row["sorties" + s] = m["sorties"][u]
        if sim.U > 1:
            row["pole_attente_urg_patient_h" + s] = m["attente"].sum()
            row["pole_hebergements" + s] = m["heberg"].sum()
            row["pole_ei_attendus" + s] = round(m["ei"].sum(), 5)
            row["pole_sorties_sous_pression" + s] = m["pression"].sum()
            row["pole_minutes_non_couvertes" + s] = round(m["non_couvert"].sum(), 1)
    return row


def contrefactuels(sim, snaps, processus, log=print):
    global _SIM, _SNAPS
    _SIM, _SNAPS = sim, snaps
    rows = []
    t0 = time.time()
    with mp.get_context("fork").Pool(processus) as pool:
        for i, r in enumerate(pool.imap(_worker, range(len(snaps)), chunksize=4)):
            rows.extend(r)
            if (i + 1) % 73 == 0:
                log(f"  contrefactuels : {i + 1}/{len(snaps)} jours ({time.time() - t0:.0f} s)")
    return rows


def test_rejeu(sim, snaps, etats, n=4):
    """Rejoue la politique depuis des captures d'état : doit reproduire exactement la trajectoire factuelle."""
    ref = {(r["h"], r["u"]): r for r in etats}
    ecarts = 0
    for h0, st0 in snaps[:: max(1, len(snaps) // n)][:n]:
        st = st0.clone()
        for h in range(h0, min(h0 + 72, sim.h1_rec)):
            m = sim.step(st, h, politique=True)
            for u in range(sim.U):
                r = ref[(h, u)]
                if r["lits_occupes"] != m["occupes"][u] or r["attente_urgences_nb"] != m["attente"][u]:
                    ecarts += 1
    return ecarts


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------

def ecrire_csv(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})


def _json(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    raise TypeError(type(v))


def ecrire_jsonl(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as z:
        for r in rows:
            z.write((json.dumps(r, ensure_ascii=False, separators=(",", ":"), default=_json) + "\n").encode())


class _gz:
    """Fichier gzip reproductible (mtime=0) ouvert en écriture binaire ; None -> sans effet."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        if self.path is None:
            return None
        self.raw = open(self.path, "wb")
        self.z = gzip.GzipFile(fileobj=self.raw, mode="wb", filename="", mtime=0)
        return self.z

    def __exit__(self, *a):
        if self.path is not None:
            self.z.close()
            self.raw.close()


def ecrire_json(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json) + "\n")


def horodater(base_ts, h, minutes=None):
    h = np.asarray(h, float)
    t = pd.to_datetime(base_ts) + pd.to_timedelta(h, unit="h")
    if minutes is not None:
        t = t + pd.to_timedelta(np.asarray(minutes, float), unit="min")
    s = pd.Series(t).dt.strftime("%Y-%m-%dT%H:%M:%S+01:00")
    return s.where(~np.isnan(h), None)


def etats_pole(etats):
    """Lignes d'état du pôle : somme des unités ; ratio recalculé."""
    df = pd.DataFrame(etats)
    num = [c for c in df.columns if c not in ("h", "u", "ratio_charge")]
    pole = df.groupby("h")[num].sum().reset_index()
    pole["ratio_charge"] = (pole.charge_soins_min_h / pole.capacite_soins_min_h).round(4)
    pole["u"] = -1
    return pole


def ecrire(sim, journal, st_fin, st_h1, cf_rows, out: Path, units, focale, seed, echelles, rejeu_ecarts, duree,
           viol, frontieres=None):
    x = sim.x
    base = np.datetime64(x.debut.isoformat())
    base_ts = pd.Timestamp(x.debut)
    pat = x.pat
    names = np.array(units)
    h0, h1 = sim.h0_rec, sim.h1_rec

    # --- structure
    lits = []
    for u, n in enumerate(units):
        for b in range(x.nb_tot[u]):
            lits.append(dict(lit_id=f"{n}_L{b + 1:02d}", unite=n, isolement=x.lit_iso[u][b], oxygene=x.lit_oxy[u][b],
                             supplementaire=x.lit_sup[u][b]))
    ecrire_json(dict(site="SYNTH_H02", pole="POLE_MEDECINE" if len(units) > 1 else None,
                     unites=[dict(unite=n, libelle=hs.UNITS[n]["nom"], lits_installes=hs.UNITS[n]["lits"],
                                  lits_isolement=hs.UNITS[n]["lits_isolement"], lits_oxygene=hs.UNITS[n]["lits_oxygene"])
                             for n in units], lits=lits), out / "structure.json")

    # --- séjours (vérité), figés au début de l'heure h1 (31/12 24 h) : aucune information postérieure
    rows = [r for r in journal.sejours if r["exit_h"] < h1]
    for p in st_h1.patients.values():
        pret = p.ready_h if (p.ready_h < h1 and not sim.bloque(p)) else -1
        rows.append(dict(pid=p.pid, home=p.home, unit=p.unit, lit=p.bed, issue="censure", dec_h=p.dec_h,
                         admit_h=p.admit_h, ready_h=pret, exit_h=-1, hosted=p.hosted, press=p.press,
                         retard=int(p.delayed), accel=p.accel, antic=p.antic, rapat=p.rapat,
                         aide_h=p.aide_h if 0 <= p.aide_h < h1 else -1))
    for q in [*st_h1.q_urg, *st_h1.q_prog, *st_h1.q_trin]:
        for p in q:
            rows.append(dict(pid=p.pid, home=p.home, unit=-1, lit=-1, issue="censure", dec_h=p.dec_h,
                             admit_h=-1, ready_h=-1, exit_h=-1, hosted=False, press=False, retard=0,
                             accel=False, antic=False, rapat=0, aide_h=-1))
    s = pd.DataFrame(rows)
    s = s[((s.exit_h >= h0) | (s.exit_h == -1)) & (s.dec_h < h1)].copy()
    s.loc[s.ready_h >= h1, "ready_h"] = -1  # sortie sous pression avant une disponibilité postérieure au 31/12
    pid = s.pid.values
    sej = pd.DataFrame(dict(
        sejour_id=[f"S{i:06d}" for i in pid],
        unite_cible=names[s.home.values],
        unite_sortie=np.where(s.unit.values >= 0, names[np.maximum(s.unit.values, 0)], None),
        lit_sortie=[f"{names[u]}_L{b + 1:02d}" if u >= 0 and b >= 0 else None for u, b in zip(s.unit.values, s.lit.values)],
        mode_entree=np.array(hs.SRC)[pat["src"][pid]], issue=s.issue.values,
        age=pat["age"][pid], tranche_age=[ob.tranche_age(a) for a in pat["age"][pid]],
        sexe=np.where(pat["femme"][pid], "F", "H"), dependance=pat["dep"][pid],
        mobilite=np.array(hs.MOBILITE)[pat["mob"][pid]],
        isolement=pat["iso"][pid], oxygene=pat["oxy"][pid], imagerie_requise=pat["img"][pid],
        avis_requis=pat["avis"][pid], aide_domicile_requise=pat["aide"][pid]))
    adm = s.admit_h.values >= 0
    sorti = s.issue.values == "sortie"
    sej["ts_decision"] = horodater(base_ts, s.dec_h.values).values
    sej["ts_entree"] = horodater(base_ts, np.where(adm, s.admit_h, np.nan)).values
    sej["ts_sortant_medical"] = horodater(base_ts, np.where(adm & (s.ready_h.values >= 0), s.ready_h, np.nan)).values
    sej["ts_aide_organisee"] = horodater(base_ts, np.where(adm & (s.aide_h.values >= 0) & (s.aide_h.values < h1)
                                                           & (s.aide_h.values <= np.where(sorti, s.exit_h, h1)),
                                                           s.aide_h, np.nan)).values
    sej["ts_sortie"] = horodater(base_ts, np.where(sorti, s.exit_h, np.nan)).values
    fin_att = np.where(adm, s.admit_h, np.where(s.exit_h >= 0, s.exit_h, np.nan)).astype(float)
    sej["attente_avant_lit_h"] = np.where(sej.mode_entree == "urgences", fin_att - s.dec_h.values, np.nan)
    sej["destination"] = np.where(sorti, np.array(hs.DEST)[pat["dest"][pid]], None)
    sej["dms_jours"] = np.where(sorti, (s.exit_h - s.admit_h) / 24, np.nan).round(3)
    sej["heberge"] = s.hosted.values
    sej["rapatriements"] = s.rapat.values
    sej["sortie_sous_pression"] = s.press.values
    sej["retard_sortie_charge_h"] = s.retard.values
    sej["aval_accelere"] = s.accel.values
    sej["sortie_anticipee"] = s.antic.values
    sej["entree_avant_periode"] = adm & (s.admit_h.values < h0)
    p_readm = (hs.P["readmission_base"] + 0.02 * (sej.dependance.values - 1) + 0.001 * (sej.age.values - 70)).clip(0.03, 0.3)
    p_readm = p_readm * np.where(s.press.values, 2.0, 1.0) * np.where(s.hosted.values, 1.2, 1.0)
    vivant = sorti & (pat["dest"][pid] != hs.DECES)
    sej["readmission_30j"] = np.where(vivant, pat["u_readm"][pid] < p_readm, None)
    sej["_h"] = s.dec_h.values
    sej = sej.sort_values(["_h", "sejour_id"], kind="stable").drop(columns="_h").reset_index(drop=True)
    ecrire_csv(sej, out / "verite/sejours.csv.gz")
    verite_sej = {f"S{int(p):06d}": (int(a) if a >= 0 else None, int(e) if (i == "sortie") else None,
                                     int(r) if (a >= 0 and r >= 0) else None)
                  for p, a, e, r, i in zip(s.pid, s.admit_h, s.exit_h, s.ready_h, s.issue)}

    # --- états horaires vrais (unités + pôle), période enregistrée
    et = pd.DataFrame(journal.etats)
    if len(units) > 1:
        et = pd.concat([et, etats_pole(journal.etats)], ignore_index=True)
    et = et[(et.h >= h0) & (et.h < h1)].sort_values(["h", "u"]).reset_index(drop=True)
    et.insert(0, "ts", horodater(base_ts, et.h).values)
    et.insert(1, "niveau", np.where(et.u >= 0, "unite", "pole"))
    et.insert(2, "entite", np.where(et.u >= 0, names[np.maximum(et.u, 0)], "POLE"))
    et["taux_occupation"] = (et.lits_occupes / et.lits_ouverts.clip(lower=1)).round(4)
    verite = {(r["entite"], r["h"]): r for r in et.to_dict("records")}
    ecrire_csv(et.drop(columns=["u"]), out / "verite/etats_horaires.csv.gz")

    # --- effectifs par poste
    rows = []
    for u in range(sim.U):
        for d in range(h0 // 24, h1 // 24):
            for k, nom in enumerate(["matin", "apres_midi", "nuit"]):
                sid = 3 * d + k + 1
                ren = st_fin.renfort.get((u, sid), 0)
                pres = x.prevus[u, sid] - x.absents[u, sid] + x.remplaces[u, sid] + ren
                part = hs.P["part_ide_nuit"] if k == 2 else hs.P["part_ide_jour"]
                rows.append(dict(h=d * 24 + 7 + 8 * k, unite=units[u], poste=nom,
                                 soignants_prevus=x.prevus[u, sid], absences=x.absents[u, sid],
                                 remplacements=x.remplaces[u, sid], renforts=ren, soignants_presents=pres,
                                 ide_presents=int(round(pres * part)), as_presents=int(pres - round(pres * part)),
                                 granularite="EFFECTIFS_PAR_ROLE_PAS_DE_PLANNING_NOMINATIF"))
    eff = pd.DataFrame(rows)
    eff.insert(0, "debut_poste", horodater(base_ts, eff.h).values)
    ecrire_csv(eff.drop(columns="h"), out / "verite/effectifs_postes.csv.gz")

    # --- tâches des services partagés
    tk = pd.DataFrame(list(journal.taches.values()))
    tk = tk[(tk.h_demande >= h0 - 24 * 30) & (tk.h_demande < h1)].copy()
    tk["unite"] = names[tk.u.values]
    tk["sejour_id"] = [f"S{int(p):06d}" if pd.notna(p) else None for p in tk.pid]
    tk["lit_id"] = [f"{names[u]}_L{int(b) + 1:02d}" if pd.notna(b) else None for u, b in zip(tk.u, tk.lit)]
    tk["h_debut"] = tk.h_debut.where(tk.h_debut.isna() | (tk.h_debut < h1))
    tk["h_fin"] = tk.h_fin.where(tk.h_fin.isna() | (tk.h_fin < h1))
    tk.loc[tk.h_debut.isna(), "h_fin"] = np.nan
    for c in ("demande", "debut", "fin"):
        tk["ts_" + c] = horodater(base_ts, tk["h_" + c].astype(float).values).values
    tk["statut"] = np.where(tk.h_fin.notna(), "TERMINEE", np.where(tk.h_debut.notna(), "EN_COURS", "EN_FILE"))
    ecrire_csv(tk[["tache_id", "type", "unite", "sejour_id", "lit_id", "ts_demande", "ts_debut", "ts_fin", "statut"]],
               out / "verite/taches_services.csv.gz")

    # --- événements vrais et livraisons observées
    ev = evenements(journal, units, h1)
    ecrire_jsonl([dict(event_id=e["event_id"], ts_evenement=ob.iso(base, e["h"]), type=e["type"], unite=e["unite"],
                       sejour_id=e["sejour"], payload=e["payload"], synthetique=True) for e in ev],
                 out / "verite/evenements.jsonl.gz")
    livr, jour_panne = ob.observer(ev, x, seed, base)
    livr_out = []
    for o in livr:
        r = {k: v for k, v in o.items() if not k.startswith("t_")}
        for k in ("t_evenement", "t_saisie", "t_ingestion", "t_disponible"):
            r["ts_" + k[2:]] = ob.iso(base, o[k])
        r["h_disponible"] = round(o["t_disponible"], 6)
        livr_out.append(r)
    ecrire_jsonl(livr_out, out / "observe/livraisons.jsonl.gz")

    # --- vues d'apprentissage
    annee = x.dates[h0 // 24].year
    h_val, h_test = frontieres or ((dt.date(annee, 9, 1) - x.debut).days * 24, (dt.date(annee, 11, 1) - x.debut).days * 24)
    variables, cibles = ob.vues_apprentissage(livr, verite, units, h0, h1, (h_val, h_test))
    va = pd.DataFrame(variables)
    va.insert(1, "ts", horodater(base_ts, va.h).values)
    va["heure_locale"] = va.h % 24
    va["jour_semaine"] = x.dow[va.h // 24]
    va["mois"] = [x.dates[d].month for d in va.h // 24]
    va["jour_ferie"] = x.ferie[va.h // 24]
    ci = pd.DataFrame(cibles)
    ci.insert(3, "ts_cible", horodater(base_ts, ci.h_cible).values)
    ecrire_csv(va, out / "apprentissage/variables_asof.csv.gz")
    ecrire_csv(ci, out / "apprentissage/cibles.csv.gz")
    if focale:
        ecrire_csv(va[va.entite == focale], out / f"unite_{focale}/variables_asof.csv.gz")
        ecrire_csv(ci[ci.sample_id.str.startswith(focale + "@")], out / f"unite_{focale}/cibles.csv.gz")

    # --- couche séjour : trajectoires telles que connues et cibles par séjour (écriture en flux)
    jour0 = x.debut
    n_sej_var = 0
    fva, fci = out / "apprentissage/sejours_asof.csv.gz", out / "apprentissage/cibles_sejours.csv.gz"
    fva.parent.mkdir(parents=True, exist_ok=True)
    focs = []
    if focale:
        (out / f"unite_{focale}").mkdir(parents=True, exist_ok=True)
        focs = [out / f"unite_{focale}/sejours_asof.csv.gz", out / f"unite_{focale}/cibles_sejours.csv.gz"]
    with _gz(fva) as zv, _gz(fci) as zc, _gz(focs[0] if focs else None) as zfv, _gz(focs[1] if focs else None) as zfc:
        entete = True
        for var, cib in pc.iter_vues_sejours(livr, verite_sej, jour0, h0, h1, (h_val, h_test)):
            if not var:
                continue
            dv = pd.DataFrame(var, columns=pc.COLONNES_SEJOURS_ASOF)
            dv["ts"] = horodater(base_ts, dv.h).values
            dc = pd.DataFrame(cib, columns=pc.COLONNES_CIBLES_SEJOURS)
            zv.write(dv.to_csv(index=False, header=entete).encode())
            zc.write(dc.to_csv(index=False, header=entete).encode())
            if zfv is not None:
                mask = (dv.unite_actuelle == focale).values
                zfv.write(dv[mask].to_csv(index=False, header=entete).encode())
                zfc.write(dc[mask].to_csv(index=False, header=entete).encode())
            entete = False
            n_sej_var += len(dv)

    # --- notes cliniques (v0.4) : texte versionné, vérité annotée, extraction de référence
    import math as _m
    nts, anns, lat = nt.generer(sim, journal, h0, h1, h_test, seed)
    lignes_notes = []
    for n in nts:
        r = {k: v for k, v in n.items() if not k.startswith("t_")}
        r["ts_creation"], r["ts_modification"] = ob.iso(base, n["t_creation"]), ob.iso(base, n["t_modification"])
        r["ts_disponible"], r["h_disponible"] = ob.iso(base, n["t_disponible"]), round(n["t_disponible"], 6)
        lignes_notes.append(r)
    ecrire_jsonl(lignes_notes, out / "observe/notes.jsonl.gz")
    ecrire_jsonl(anns, out / "verite/notes_annotations.jsonl.gz")
    pids_sej = {int(i[1:]) for i in sej.sejour_id}
    lc = pd.DataFrame([dict(sejour_id=f"S{l['pid']:06d}", **{k: v for k, v in l.items() if k != "pid"}) for l in lat
                       if l["pid"] in pids_sej])
    lc["antecedents"] = ["|".join(a) for a in lc.antecedents]
    lc["cause_isolement"] = [nt.T.CAUSES_ISOLEMENT[int(c)][1] if pd.notna(c) else None for c in lc.cause_isolement]
    ecrire_csv(lc.sort_values("sejour_id").reset_index(drop=True), out / "verite/sejours_cliniques.csv.gz")
    rows = []
    for n in nts:
        e = ex.extraire(n["texte"])
        h_util = int(_m.ceil(n["t_disponible"]))
        r = dict(note_id=n["note_id"], version=n["version"], sejour_id=n["sejour_id"], type_note=n["type_note"],
                 unite=n["unite"], h_disponible=round(n["t_disponible"], 6), h_utilisable=h_util,
                 split=ob.split_de(h_util, h_val, h_test, h1) if h_util >= h0 else "avant_periode")
        for v in ex.VARIABLES:
            r[v] = e[v]["valeur"] if v in e else None
            r[v + "_statut"] = e[v]["statut"] if v in e else None
        r["source_ancienne_signalee"] = any(f["source_ancienne"] for f in e.values())
        rows.append(r)
    xn = pd.DataFrame(rows)
    ecrire_csv(xn, out / "apprentissage/extraction_notes.csv.gz")
    etat = pd.DataFrame(ex.etat_documentaire(rows, lignes_notes))
    ecrire_csv(etat, out / "apprentissage/etat_notes_asof.csv.gz")
    if focale:
        ecrire_csv(xn[xn.unite == focale], out / f"unite_{focale}/extraction_notes.csv.gz")
        ecrire_csv(etat[etat.sejour_id.isin(xn[xn.unite == focale].sejour_id)], out / f"unite_{focale}/etat_notes_asof.csv.gz")
    ev_extr = ex.evaluer(nts, anns, h_test)
    ecrire_json(dict(portee="Extracteur à règles, de référence. Scores élevés avant le test par construction (même "
                            "auteur, mêmes gabarits) ; la période de test mêle des tournures absentes du lexique.",
                     **ev_extr), out / "rapport_extraction.json")

    # --- couche causale
    def split_col(hh):
        return [ob.split_de(int(v), h_val, h_test, h1) for v in hh]
    ac = pd.DataFrame(journal.actions)
    ac.insert(0, "ts", horodater(base_ts, ac.h).values)
    ac.insert(1, "unite", names[ac.u.values])
    ac.insert(2, "split", split_col(ac.h))
    ecrire_csv(ac.drop(columns=["u"]), out / "causal/decisions.csv.gz")
    cad = pd.DataFrame(journal.cadre)
    cad = cad[(cad.h >= h0) & (cad.h < h1)]
    cad.insert(0, "ts", horodater(base_ts, cad.h).values)
    cad.insert(1, "unite", names[cad.u.values])
    ecrire_csv(cad.drop(columns=["u"]), out / "verite/politique_cadre.csv.gz")
    if cf_rows:
        cf = pd.DataFrame(cf_rows)
        ordre = {f: i for i, f in enumerate(FAMILLES)}
        cf["_f"] = cf.famille.map(ordre)
        cf = cf.sort_values(["h", "u", "_f", "scenario"], kind="stable").drop(columns="_f")
        cf.insert(0, "ts", horodater(base_ts, cf.h).values)
        cf.insert(1, "unite_cible", names[cf.u.values])
        cf.insert(2, "split", split_col(cf.h))
        ecrire_csv(cf.drop(columns=["u"]), out / "causal/contrefactuels.csv.gz")
    ecrire_json(dict(
        familles=FAMILLES,
        horizon_h=hs.P["horizon_cf_h"],
        estimands={
            "effet_engagement_seul": "A[levier] - A[aucun] : effet d'engager le levier (échec de pourvoi compris "
                                     "pour le renfort), sans décision ultérieure.",
            "effet_engagement_sous_politique": "B[levier] - B[aucun] : effet d'engager le levier ce jour-là (échec "
                                               "compris), la politique en vigueur s'appliquant ensuite.",
            "effet_presence_renfort": "A ou B[renfort_soignant_pourvu] - [aucun] : effet d'un renfort effectivement "
                                      "présent sur les deux postes concernés.",
            "effet_recommandation_itt": "C[levier] - C[aucune] : effet de recommander le levier, en intention de "
                                        "traiter (exposition, validation et exécution comprises).",
        },
        identification={
            "recommandation": "Identifiable sur données observées : les probabilités q_reco_* sont journalisées et "
                              "ne dépendent que des colonnes de decisions.csv.gz.",
            "execution": "Non identifiable par simple ajustement : la validation et l'initiative du cadre dépendent "
                         "d'une information cachée (verite/politique_cadre.csv.gz, confusion_z), qui pèse aussi "
                         "sur l'attente à venir. La recommandation peut servir d'instrument (exclusion vraie par "
                         "construction dans le simulateur).",
        },
        controles="Mêmes aléas dans tous les scénarios d'un même jour (nombres aléatoires communs).",
        decoupage="Colonne split : même règle que les vues d'apprentissage ; aucune fenêtre ne franchit une frontière.",
    ), out / "causal/estimands.json")

    # --- configuration et rapport
    ecrire_json(dict(version=VERSION, seed=seed, unites={n: hs.UNITS[n] for n in units}, parametres=hs.P,
                     informations_staff={k: (v if not isinstance(v, dict) else {hs.DEST[i]: w for i, w in v.items()})
                                         for k, v in hs.INFO.items()},
                     observation=ob.OBS, notes=dict(parametres=nt.P_NOTES, documentation=nt.DOC), echelles_calibrees=echelles, leviers=hs.LEVIERS, unite_focale=focale,
                     warmup_jours=WARMUP_J, debut_simulation=str(x.debut), h_debut_periode=h0, h_fin_periode=h1,
                     h_validation=h_val, h_test=h_test, horizons=ob.HORIZONS,
                     fuseau="UTC+01:00 fixe ; le changement d'heure n'est pas modélisé"),
                out / "config/parametres.json")
    ecrire_json(dict(
        version=VERSION, statut="SYNTHETIQUE_NON_CALIBRE_PAS_UNE_PREUVE_CLINIQUE", seed=seed,
        periode=[str(x.dates[h0 // 24]), str(x.dates[h1 // 24])], unites=units, unite_focale=focale,
        comptes=dict(sejours=len(sej), etats_horaires=len(et), evenements=len(ev), livraisons=len(livr_out),
                     revisions=sum(o["event_version"] == 2 for o in livr),
                     doublons=len(livr) - len({(o["event_id"], o["event_version"]) for o in livr}),
                     variables=len(va), cibles=len(ci), sejours_asof=n_sej_var, notes_versions=len(nts),
                     notes=len({n["note_id"] for n in nts}), decisions=len(ac),
                     contrefactuels=len(cf_rows), taches=len(tk)),
        decoupage=va.split.value_counts().to_dict(),
        jour_panne_si=str(x.dates[jour_panne]) if jour_panne >= 0 else None,
        pannes_imagerie=[str(x.dates[d]) for d in x.pannes_imagerie],
        test_rejeu_ecarts=rejeu_ecarts, duree_generation_s=round(duree, 1),
        violations_invariants={k: int(v) for k, v in viol.items() if k != "heures_controlees"},
        heures_controlees=int(viol["heures_controlees"]),
        empreinte_etats=hashlib.sha256(et.to_csv(index=False).encode()).hexdigest(),
        environnement=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__),
        validation_empirique="NON_REALISEE_PAS_DE_DONNEES_LOCALES_DE_REFERENCE"), out / "rapport_generation.json")


def generer(units, echelle, seed, annee, out, focale=None, contrefactuels_on=True, processus=1, ech=None, log=print):
    t0 = time.time()
    if ech is None:
        log(f"[{echelle}] calibrage")
        ech = calibrer(units, echelle, seed, annee, log=log)
    exo, h0, h1 = construire(units, seed, annee, ech)
    sim = hs.Sim(exo, echelle, h0, h1)
    journal = Journal(sim)
    snaps = []

    def snap(h, st):
        if h0 <= h < h1:
            snaps.append((h, st.clone()))
    log(f"[{echelle}] simulation factuelle ({exo.N} demandes générées)")
    viol = __import__("collections").Counter()
    capture = {}
    st_fin, _ = simuler(sim, journal, snap, viol=viol, capture=capture)
    ecarts = test_rejeu(sim, snaps, journal.etats)
    log(f"[{echelle}] test de rejeu : {ecarts} écart(s)")
    cf_rows = contrefactuels(sim, snaps, processus, log) if contrefactuels_on else []
    log(f"[{echelle}] écriture")
    ecrire(sim, journal, st_fin, capture["etat"], cf_rows, Path(out), units, focale, seed, ech, ecarts,
           time.time() - t0, viol)
    log(f"[{echelle}] terminé en {time.time() - t0:.0f} s -> {out}")
    return sim, journal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--echelle", choices=list(ECHELLES), default="pole")
    ap.add_argument("--unite-focale", default="CSG")
    ap.add_argument("--sortie", required=True)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--annee", type=int, default=2025)
    ap.add_argument("--sans-contrefactuels", action="store_true")
    ap.add_argument("--processus", type=int, default=max(1, os.cpu_count() or 1))
    a = ap.parse_args()
    units = ECHELLES[a.echelle]
    focale = a.unite_focale if a.unite_focale in units else units[0]
    generer(units, a.echelle, a.seed, a.annee, a.sortie, focale, not a.sans_contrefactuels, a.processus,
            log=lambda s: print(s, flush=True))


if __name__ == "__main__":
    main()
