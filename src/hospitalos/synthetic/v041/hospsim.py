"""
HospitalOS - simulateur synthétique de flux et de charges hospitalières (v0.3).

Modèle causal structurel à pas horaire :
- aléas exogènes tirés une fois pour toutes (arrivées, attributs patients, absences,
  fermetures, capacités des services, tirages de la politique) : la dynamique est
  déterministe à aléas fixés, ce qui permet des contrefactuels à nombres aléatoires communs ;
- lits individuels avec compatibilités (isolement, oxygène), nettoyage, fermeture différée ;
- services partagés du pôle : nettoyage, imagerie, avis spécialisés, transport ; aval SMR et EHPAD ;
  aide à domicile à organiser pour une partie des retours à domicile ;
- mécanismes endogènes : attente aux urgences, hébergements et rapatriements, charge en soins,
  retards de sortie sous charge, sorties sous pression ;
- chaîne de décision : recommandation HospitalOS (probabilités journalisées), exposition,
  validation ou initiative du cadre (probabilités non journalisées, avec un facteur de confusion
  caché), exécution ou échec ;
- informations du staff (date de sortie prévisionnelle, destination demandée), produites en
  simulation factuelle avec un générateur aléatoire séparé : elles n'agissent jamais sur la physique.

Toutes les valeurs numériques sont des hypothèses de travail, à réestimer sur données réelles.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import deque
from copy import deepcopy

import numpy as np

# --------------------------------------------------------------------------
# Paramètres
# --------------------------------------------------------------------------

DEST = ["domicile", "SMR", "EHPAD", "deces", "transfert"]
DOM, SMR, EHPAD, DECES, TRANSF = range(5)
SRC = ["urgences", "programme", "transfert_entrant"]
URG, PROG, TRIN = range(3)
LEVIERS = ["anticipation_sorties", "lits_supplementaires", "renfort_soignant", "acceleration_aval"]
TRANSPORT_REQUIS = (SMR, EHPAD, TRANSF)
MOBILITE = ["autonome", "aide", "brancard"]

UNITS = {
    "MED_POLY": dict(
        nom="Médecine polyvalente", lits=28, lits_isolement=5, lits_oxygene=16, part=(0.85, 0.05, 0.10),
        age=(74, 14, 18), p_femme=0.50, p_isolement=0.07, p_oxygene=0.18, p_imagerie=0.35, p_avis=0.20,
        los_med_median_j=4.5, los_sigma=0.60, p_court=0.15, court_median_h=36,
        dest=(0.68, 0.18, 0.05, 0.04, 0.05),
        saison=0.10, grippe=0.18, canicule=0.12, fermeture_ete=0.15, fermeture_noel=0.00),
    "CSG": dict(
        nom="Court séjour gériatrique", lits=24, lits_isolement=5, lits_oxygene=14, part=(0.85, 0.02, 0.13),
        age=(87, 5, 75), p_femme=0.62, p_isolement=0.07, p_oxygene=0.22, p_imagerie=0.30, p_avis=0.15,
        los_med_median_j=7.0, los_sigma=0.55, p_court=0.08, court_median_h=40,
        dest=(0.42, 0.30, 0.14, 0.09, 0.05),
        saison=0.15, grippe=0.25, canicule=0.20, fermeture_ete=0.00, fermeture_noel=0.00),
    "PNEUMO": dict(
        nom="Pneumologie", lits=26, lits_isolement=7, lits_oxygene=26, part=(0.62, 0.28, 0.10),
        age=(70, 13, 18), p_femme=0.45, p_isolement=0.15, p_oxygene=0.60, p_imagerie=0.50, p_avis=0.25,
        los_med_median_j=4.5, los_sigma=0.65, p_court=0.18, court_median_h=30,
        dest=(0.74, 0.12, 0.03, 0.06, 0.05),
        saison=0.25, grippe=0.40, canicule=0.05, fermeture_ete=0.20, fermeture_noel=0.10),
    "CARDIO": dict(
        nom="Cardiologie", lits=24, lits_isolement=4, lits_oxygene=12, part=(0.55, 0.35, 0.10),
        age=(71, 13, 18), p_femme=0.42, p_isolement=0.05, p_oxygene=0.12, p_imagerie=0.45, p_avis=0.20,
        los_med_median_j=3.5, los_sigma=0.60, p_court=0.25, court_median_h=30,
        dest=(0.82, 0.09, 0.02, 0.03, 0.04),
        saison=0.08, grippe=0.08, canicule=0.06, fermeture_ete=0.15, fermeture_noel=0.10),
}

P = dict(
    occupation_cible=0.88,          # occupation moyenne visée des lits ouverts (calibrage)
    aval_smr=(4.0, 0.8),            # attente SMR après sortie médicale : médiane (j), sigma log
    aval_ehpad=(9.0, 0.8),
    aval_transfert=(1.0, 0.5),
    facteur_los_heberge=1.15,       # allongement de séjour d'un patient hébergé
    los_age=0.008, los_dep=0.07,    # effet âge / dépendance sur la durée médicale
    min24_dep=(115, 170, 235, 320), # minutes de soins / 24 h selon la dépendance 1..4
    mult_isolement=1.30, mult_oxygene=1.15, mult_entree=1.40, mult_veille_sortie=1.15, mult_heberge=1.15,
    efficacite_soignant=0.84,       # part du temps soignant disponible pour les soins
    seuil_charge_retard=1.25,       # au-delà, les sorties prennent du retard
    retard_par_point=4.0, retard_max_h=6,
    montee_median_h=1.2, montee_sigma=0.6,  # délai incompressible urgences -> lit (brancardage, transmissions)
    p_sortie_vendredi=0.50, p_sortie_samedi=0.60, p_sortie_dimanche=0.45,
    absence_base=0.07, absence_grippe=0.035, remplacement_jour=0.50, remplacement_nuit=0.35,
    part_ide_jour=0.45, part_ide_nuit=0.60,
    renfort_pourvu=0.65,
    heberg_apres_h=4, heberg_libres_min=2,
    hors_pole_min_h=12, hors_pole_median_h=8, hors_pole_sigma=0.7,
    prog_annule_heure=18, transfert_annule_h=48,
    pression_seuil_attente_h=4, pression_p_par_patient=0.06, pression_p_max=0.3,
    ei_base=0.00025, ei_charge=3.0, ei_attente_75=0.0015, ei_attente=0.0006,
    lits_sup_n=2, lits_sup_duree_h=72,
    aval_reduction=0.30,
    readmission_base=0.08,
    horizon_cf_h=72,
    # services partagés (dimensionnés pour un pôle de 102 lits, mis à l'échelle sinon)
    nettoyage_agents_jour=4, nettoyage_agents_nuit=1, nettoyage_durees_h=(1, 2, 3), nettoyage_probas=(0.70, 0.25, 0.05),
    imagerie_creneaux_ouvre=2, imagerie_creneaux_weekend=1, imagerie_pannes_par_an=2,
    transport_creneaux_ouvre=2, transport_creneaux_weekend=1,
    rapatriement_marge_h=24,
    lits_reference_services=102,
    # avis spécialisés : créneaux par heure (jours ouvrés, 9 h - 17 h), délai de rendu après le début
    avis_creneaux_ouvre=1, avis_duree_h=2,
    # mobilité selon la dépendance 1..4 (autonome, aide, brancard) ; brancard -> transport même vers le domicile
    mobilite_dep=((0.90, 0.10, 0.00), (0.60, 0.35, 0.05), (0.20, 0.60, 0.20), (0.05, 0.35, 0.60)),
    # aide à domicile : éligibles = retour à domicile et (dépendance >= 3, ou dépendance 2 et âge >= 80)
    p_aide_si_eligible=0.50, aide_median_j=4.0, aide_sigma=0.6, aide_heure=14, aide_reduction=0.30,
    # chaîne de décision
    p_exposition=0.85,               # le cadre consulte l'écran de recommandations ce jour-là
    acceptation_base=(1.0, 0.2, 0.6, 1.2),  # logit d'acceptation d'une recommandation vue, par levier
    confusion_gamma=0.8,             # poids, dans le logit du cadre, de l'information cachée sur les arrivées
    confusion_bruit=0.5,
)

# Informations produites au staff (simulation factuelle uniquement, générateur séparé)
INFO = dict(
    heure_staff=10,                 # staff des jours ouvrés
    delai_min_h=6,                  # un patient admis depuis moins longtemps n'est pas encore discuté
    p_dsp_jamais=0.30,              # séjours sans date de sortie prévisionnelle
    dsp_sigma0=0.45,                # bruit log sur le reste à faire en début de séjour
    dsp_sigma_min_frac=0.30,        # le bruit décroît avec l'avancement, jusqu'à cette fraction
    dsp_biais_log=-0.10,            # optimisme des prévisions
    dsp_informativite=1.0,          # multiplicateur du bruit : 0 = date parfaite, 2 = très bruitée
    p_revision_jour=0.25,           # révision spontanée à un staff donné
    p_destination_juste=0.80,       # destination déclarée au premier staff = destination finale
    p_revision_destination=0.50,    # par staff, dans la fenêtre avant la sortie médicale
    fenetre_revision_destination_h=48,
    attente_aval_attendue_j={0: 0.5, 1: 5.6, 2: 12.6, 3: 0.5, 4: 1.2},
)

# Profils horaires
PROFIL_DECISION_URG = np.array([3, 2.5, 2, 1.5, 1.2, 1, 1, 1.2, 1.8, 2.5, 3.5, 4.5,
                                5, 5.5, 6, 6, 6, 6, 6, 5.8, 5.5, 5, 4.5, 4], float)
PROFIL_DECISION_URG /= PROFIL_DECISION_URG.sum()
HEURES_SORTIE_DOM = np.arange(9, 20)
PROFIL_SORTIE_DOM = np.array([0.3, 0.8, 1.5, 1.6, 1.2, 1.4, 1.6, 1.5, 1.0, 0.5, 0.2])
CDF_SORTIE_DOM = np.cumsum(PROFIL_SORTIE_DOM) / PROFIL_SORTIE_DOM.sum()
PROFIL_CHARGE = np.array([0.45] * 7 + [1.6, 1.7, 1.6, 1.5, 1.3, 1.2, 1.2, 1.1,
                                       1.1, 1.1, 1.1, 1.0, 0.9, 0.8, 0.8, 0.7, 0.45])
PROFIL_CHARGE = PROFIL_CHARGE * 24 / PROFIL_CHARGE.sum()
DOW_URG = np.array([1.12, 1.03, 1.00, 0.98, 1.00, 0.92, 0.95])
DOW_PROG = np.array([1.25, 1.10, 1.05, 1.00, 0.60, 0.0, 0.0])


def jours_feries(annees):
    """Jours fériés français (métropole) pour les années demandées."""
    out = set()
    for y in annees:
        a = y % 19; b = y // 100; c = y % 100; d = b // 4; e = b % 4
        f = (b + 8) // 25; g = (b - f + 1) // 3; h = (19 * a + b - d - g + 15) % 30
        i = c // 4; k = c % 4; l_ = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l_) // 451
        mois = (h + l_ - 7 * m + 114) // 31; jour = ((h + l_ - 7 * m + 114) % 31) + 1
        paques = dt.date(y, mois, jour)
        for dd in [paques + dt.timedelta(1), paques + dt.timedelta(39), paques + dt.timedelta(50)]:
            out.add(dd)
        for (mm, jj) in [(1, 1), (5, 1), (5, 8), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25)]:
            out.add(dt.date(y, mm, jj))
    return out


# --------------------------------------------------------------------------
# Aléas exogènes
# --------------------------------------------------------------------------

class Exo:
    """Tous les tirages aléatoires de la physique et de la politique, figés avant la simulation."""

    def __init__(self, unit_names, debut, fin, seed, echelles=None, *, unit_specs=None):
        self.unit_names = list(unit_names)
        self.U = len(unit_names)
        self.specs = [deepcopy((UNITS if unit_specs is None else unit_specs)[n]) for n in unit_names]
        self.debut = debut
        self.ndays = (fin - debut).days
        self.H = self.ndays * 24
        self.seed = seed
        self.echelles = echelles or {n: 1.0 for n in unit_names}
        rng = np.random.default_rng(seed)
        self._calendrier()
        self._epidemies(rng)
        self._capacites_et_effectifs(rng)
        self._lits()
        self._services(rng)
        self._patients(rng)
        self.u_politique = rng.random((self.U, self.ndays, len(LEVIERS)))
        self.u_renfort = rng.random((self.U, 3 * (self.ndays + 1)))
        self.u_ei = rng.random((self.U, self.H))
        self.u_reco = rng.random((self.U, self.ndays, len(LEVIERS)))
        self.u_expo = rng.random((self.U, self.ndays))
        self._confusion(rng)

    def _confusion(self, rng):
        """Information cachée du cadre : arrivées des urgences des 24 h suivant la décision (appel des urgences).

        Elle pèse sur ses décisions et sur l'attente à venir ; elle n'est pas journalisée dans causal/.
        """
        n = np.zeros((self.U, self.ndays))
        for pid in range(self.N):
            if self.pat["src"][pid] != URG:
                continue
            h = int(self.pat["arr_h"][pid]) - 9
            d = h // 24
            if 0 <= d < self.ndays:
                n[int(self.pat["unit"][pid]), d] += 1
        m, s = n.mean(axis=1, keepdims=True), n.std(axis=1, keepdims=True) + 1e-9
        self.z_cache = (n - m) / s + rng.normal(0, P["confusion_bruit"], n.shape)

    def date_iso(self, jour):
        return (self.debut + dt.timedelta(int(jour))).isoformat()

    # -- calendrier
    def _calendrier(self):
        fer = jours_feries(range(self.debut.year, self.debut.year + 3))
        self.dates = [self.debut + dt.timedelta(d) for d in range(self.ndays)]
        self.dow = np.array([d.weekday() for d in self.dates])
        self.ferie = np.array([d in fer for d in self.dates])
        self.doy = np.array([d.timetuple().tm_yday for d in self.dates])
        self.ouvre = (self.dow < 5) & ~self.ferie

        def periode(d, m1, j1, m2, j2):
            return dt.date(d.year, m1, j1) <= d <= dt.date(d.year, m2, j2)
        self.ete = np.array([periode(d, 7, 14, 8, 24) for d in self.dates])
        self.noel = np.array([periode(d, 12, 22, 12, 31) or periode(d, 1, 1, 1, 2) for d in self.dates])

    def prochain_ouvre(self, d):
        while d < self.ndays and not self.ouvre[d]:
            d += 1
        return d

    # -- épidémie de grippe et canicules
    def _epidemies(self, rng):
        self.grippe = np.zeros(self.ndays)
        self.canicule = np.zeros(self.ndays)
        for y in sorted({d.year for d in self.dates}):
            centre = dt.date(y, 1, 1) + dt.timedelta(int(rng.integers(10, 45)))
            larg = rng.uniform(10, 16)
            for i, d in enumerate(self.dates):
                self.grippe[i] = max(self.grippe[i], math.exp(-0.5 * ((d - centre).days / larg) ** 2))
            for _ in range(2):
                deb = dt.date(y, 6, 20) + dt.timedelta(int(rng.integers(0, 60)))
                for k in range(int(rng.integers(4, 8))):
                    dd = deb + dt.timedelta(k)
                    if self.dates[0] <= dd <= self.dates[-1]:
                        self.canicule[(dd - self.dates[0]).days] = 1.0

    # -- lits fermés et effectifs
    def _capacites_et_effectifs(self, rng):
        U, D, H = self.U, self.ndays, self.H
        self.lits = np.array([s["lits"] for s in self.specs])
        ferme_jour = np.zeros((U, D), int)
        S = 3 * (D + 1)
        self.prevus = np.zeros((U, S), int)
        self.absents = np.zeros((U, S), int)
        self.remplaces = np.zeros((U, S), int)
        for u, s in enumerate(self.specs):
            n = s["lits"]
            base = {0: round(n / 4), 1: round(n / 4.7), 2: max(2, round(n / 9))}
            for d in range(D):
                f = 0
                if self.ete[d]:
                    f = max(f, round(s["fermeture_ete"] * n))
                if self.noel[d]:
                    f = max(f, round(s["fermeture_noel"] * n))
                ferme_jour[u, d] = f
            d = 0
            while d < D:  # fermetures ponctuelles (maintenance, travaux)
                if rng.random() < 0.03:
                    nb, duree = int(rng.integers(1, 3)), int(rng.integers(1, 6))
                    ferme_jour[u, d:d + duree] += nb
                    d += duree
                d += 1
            for d in range(D):
                taux = P["absence_base"] + P["absence_grippe"] * self.grippe[d] + rng.normal(0, 0.01)
                taux = min(max(taux, 0.02), 0.25)
                for k in range(3):
                    sid = 3 * d + k + 1
                    prev = base[k]
                    if k < 2 and (self.ete[d] or self.noel[d]):
                        prev -= round(prev * (s["fermeture_ete"] if self.ete[d] else s["fermeture_noel"]))
                    ab = rng.binomial(prev, taux)
                    rp = rng.binomial(ab, P["remplacement_jour"] if k < 2 else P["remplacement_nuit"])
                    self.prevus[u, sid], self.absents[u, sid], self.remplaces[u, sid] = prev, ab, rp
                # fermeture de lits faute de personnel : le poste du matin manque de 2 soignants
                if self.absents[u, 3 * d + 1] - self.remplaces[u, 3 * d + 1] >= 2:
                    ferme_jour[u, d] += 2
        self.ferme_jour = np.minimum(ferme_jour, self.lits[:, None] - 4)
        self.fermes = np.zeros((U, H), int)
        for u in range(U):
            for d in range(D):
                self.fermes[u, d * 24 + 7:(d + 1) * 24 + 7] = self.ferme_jour[u, d]
            self.fermes[u, :7] = self.ferme_jour[u, 0]

    # -- lits physiques (les premiers sont spécialisés : isolement, puis oxygène)
    def _lits(self):
        self.nb_std = [s["lits"] for s in self.specs]
        self.nb_tot = [s["lits"] + P["lits_sup_n"] for s in self.specs]
        self.lit_iso, self.lit_oxy, self.lit_sup = [], [], []
        for s in self.specs:
            n = s["lits"]
            self.lit_iso.append([i < s["lits_isolement"] for i in range(n)] + [False] * P["lits_sup_n"])
            self.lit_oxy.append([i < max(s["lits_oxygene"], s["lits_isolement"]) for i in range(n)] + [False] * P["lits_sup_n"])
            self.lit_sup.append([False] * n + [True] * P["lits_sup_n"])
        # ordre de fermeture : lits non spécialisés d'abord (les derniers numéros)
        self.ordre_fermeture = [list(range(n - 1, -1, -1)) for n in self.nb_std]

    # -- capacités horaires des services partagés
    def _services(self, rng):
        H, D = self.H, self.ndays
        echelle = sum(self.nb_std) / P["lits_reference_services"]
        self.cap_nettoyage = np.zeros(H, int)
        self.cap_imagerie = np.zeros(H, int)
        self.cap_transport = np.zeros(H, int)
        self.cap_avis = np.zeros(H, int)
        ouvres = [d for d in range(D) if self.ouvre[d]]
        n_pannes = max(1, round(P["imagerie_pannes_par_an"] * D / 365))
        pannes = {int(d) for d in rng.choice(ouvres, size=min(n_pannes, len(ouvres)), replace=False)}
        self.pannes_imagerie = sorted(pannes)
        for h in range(H):
            d, hd = divmod(h, 24)
            ag = P["nettoyage_agents_jour"] if 7 <= hd < 21 else P["nettoyage_agents_nuit"]
            self.cap_nettoyage[h] = max(1, round(ag * echelle))
            if 8 <= hd < 18 and d not in pannes:
                c = P["imagerie_creneaux_ouvre"] if self.ouvre[d] else P["imagerie_creneaux_weekend"]
                self.cap_imagerie[h] = max(1, round(c * echelle))
            if 9 <= hd < 19:
                c = P["transport_creneaux_ouvre"] if self.ouvre[d] else P["transport_creneaux_weekend"]
                self.cap_transport[h] = max(1, round(c * echelle))
            if 9 <= hd < 17 and self.ouvre[d]:
                self.cap_avis[h] = max(1, round(P["avis_creneaux_ouvre"] * echelle))

    # -- patients
    def _patients(self, rng):
        cols = {k: [] for k in ["unit", "src", "arr_h", "arr_min", "age", "femme", "dep", "iso", "oxy", "img",
                                "los_med_h", "dest", "aval_j", "u_heure", "u_weekend", "nett_h",
                                "u_pression", "u_readm", "u_saisie", "u_hors_pole", "montee_h",
                                "avis", "mob", "aide", "aide_delai_h"]}
        for u, s in enumerate(self.specs):
            lam = self.lambda_unite(u)
            for d in range(self.ndays):
                doy = self.doy[d]
                m_sais = 1 + s["saison"] * max(math.cos(2 * math.pi * (doy - 15) / 365), -0.3)
                m_epi = (1 + s["grippe"] * self.grippe[d]) * (1 + s["canicule"] * self.canicule[d])
                fer = 0.95 if self.ferie[d] else 1.0
                n_urg = rng.poisson(lam[URG] * m_sais * m_epi * DOW_URG[self.dow[d]] * fer)
                n_prog = 0 if not self.ouvre[d] else rng.poisson(
                    lam[PROG] * DOW_PROG[self.dow[d]] * (0.5 if self.noel[d] else 1.0) * (0.8 if self.ete[d] else 1.0))
                n_tr = rng.poisson(lam[TRIN] * (0.6 if self.dow[d] >= 5 else 1.15))
                heures = np.concatenate([
                    rng.choice(24, n_urg, p=PROFIL_DECISION_URG),
                    rng.integers(8, 14, n_prog),
                    rng.integers(9, 20, n_tr)])
                srcs = [URG] * n_urg + [PROG] * n_prog + [TRIN] * n_tr
                for src, hr in zip(srcs, heures):
                    self._un_patient(rng, cols, u, s, src, d * 24 + int(hr))
        order = np.argsort(np.array(cols["arr_h"]) * 60 + np.array(cols["arr_min"]), kind="stable")
        for k in cols:
            cols[k] = np.array(cols[k])[order]
        self.pat = cols
        self.N = len(order)
        self.arrivees = [[] for _ in range(self.H)]
        for pid in range(self.N):
            h = int(cols["arr_h"][pid])
            if h < self.H:
                self.arrivees[h].append(pid)

    def _un_patient(self, rng, cols, u, s, src, h):
        m, sd, lo = s["age"]
        age = int(np.clip(rng.normal(m, sd), lo, 104))
        if age < 65:
            pdep = [0.5, 0.3, 0.15, 0.05]
        elif age < 80:
            pdep = [0.3, 0.35, 0.25, 0.10]
        else:
            pdep = [0.12, 0.30, 0.33, 0.25]
        dep = int(rng.choice(4, p=pdep)) + 1
        iso = rng.random() < s["p_isolement"]
        oxy = rng.random() < s["p_oxygene"]
        img = rng.random() < s["p_imagerie"]
        if rng.random() < s["p_court"]:
            los = rng.lognormal(math.log(s["court_median_h"]), 0.5)
        else:
            los = rng.lognormal(math.log(s["los_med_median_j"] * 24), s["los_sigma"])
        los *= (1 + P["los_age"] * (age - 75)) * (1 + P["los_dep"] * (dep - 2))
        if src == PROG:
            los *= 0.8
        w = np.array(s["dest"], float)
        w[SMR] *= max(0.2, 1 + 0.35 * (dep - 2))
        w[EHPAD] *= max(0.1, 1 + 0.6 * (dep - 2)) if age >= 75 else 0.3
        w[DECES] *= max(0.3, 1 + 0.03 * (age - 75))
        w /= w.sum()
        dest = int(rng.choice(5, p=w))
        if dest == SMR:
            aval = rng.lognormal(math.log(P["aval_smr"][0]), P["aval_smr"][1])
        elif dest == EHPAD:
            aval = rng.lognormal(math.log(P["aval_ehpad"][0]), P["aval_ehpad"][1])
        elif dest == TRANSF:
            aval = rng.lognormal(math.log(P["aval_transfert"][0]), P["aval_transfert"][1])
        else:
            aval = 0.0
        vals = dict(unit=u, src=src, arr_h=h, arr_min=int(rng.integers(0, 60)), age=age,
                    femme=rng.random() < s["p_femme"], dep=dep, iso=iso, oxy=oxy, img=img,
                    los_med_h=max(6.0, los), dest=dest, aval_j=aval,
                    u_heure=rng.random(), u_weekend=rng.random(),
                    nett_h=int(rng.choice(P["nettoyage_durees_h"], p=P["nettoyage_probas"])),
                    u_pression=rng.random(), u_readm=rng.random(), u_saisie=rng.random(),
                    u_hors_pole=rng.random(),
                    montee_h=(rng.lognormal(math.log(P["montee_median_h"]), P["montee_sigma"]) if src == URG else 0.0))
        # v0.3 : avis spécialisé, mobilité, aide à domicile (tirés après les attributs v0.2)
        vals["avis"] = rng.random() < s["p_avis"]
        vals["mob"] = int(rng.choice(3, p=P["mobilite_dep"][dep - 1]))
        eligible = dest == DOM and (dep >= 3 or (dep == 2 and age >= 80))
        vals["aide"] = bool(eligible and rng.random() < P["p_aide_si_eligible"])
        vals["aide_delai_h"] = 24 * rng.lognormal(math.log(P["aide_median_j"]), P["aide_sigma"])
        for k, v in vals.items():
            cols[k].append(v)

    def lambda_unite(self, u):
        """Arrivées journalières par source, déduites de l'occupation visée (loi de Little)."""
        s = self.specs[u]
        los_med = s["los_med_median_j"] * math.exp(s["los_sigma"] ** 2 / 2) * (1 - s["p_court"]) \
            + s["court_median_h"] / 24 * math.exp(0.125) * s["p_court"]
        d = s["dest"]
        aval = d[SMR] * P["aval_smr"][0] * 1.4 + d[EHPAD] * P["aval_ehpad"][0] * 1.4 + d[TRANSF] * 1.2
        los_tot = los_med * 1.05 + aval + 0.7
        ouverts = s["lits"] * (1 - 0.115 * s["fermeture_ete"] - 0.03 * s["fermeture_noel"]) - 0.2
        lam = P["occupation_cible"] * ouverts / los_tot * self.echelles[self.unit_names[u]]
        return [lam * x for x in s["part"]]

    def sid(self, h):
        d, hd = divmod(h, 24)
        if hd < 7:
            return 3 * (d - 1) + 2 + 1
        return 3 * d + (0 if hd < 15 else 1) + 1


# --------------------------------------------------------------------------
# État dynamique
# --------------------------------------------------------------------------

class Pat:
    """Patient. img / avis : examen ou avis demandé et non rendu ; tr : transport de sortie demandé ;
    aide_h : heure à laquelle l'aide à domicile est organisée (-1 si non requise).
    Champs d'information (journal uniquement, sans effet sur la physique) : dsp, dsp_n, dsp_jamais,
    dest_decl, info0, conf, aide_log, aval_dem."""
    __slots__ = ("pid", "unit", "home", "dec_h", "admit_h", "ready_h", "dis_h", "hosted",
                 "press", "delayed", "accel", "antic", "base24", "bed", "img", "tr", "rlog", "rapat",
                 "avis", "aide_h",
                 "dsp", "dsp_n", "dsp_jamais", "dest_decl", "info0", "conf", "aide_log", "aval_dem")

    def copy(self):
        q = Pat.__new__(Pat)
        for k in Pat.__slots__:
            setattr(q, k, getattr(self, k))
        return q


class State:
    def __init__(self, exo):
        U = exo.U
        self.patients = {}  # pid -> Pat, patients admis présents
        self.occ = [dict() for _ in range(U)]
        self.bed_pid = [[-1] * exo.nb_tot[u] for u in range(U)]
        self.bed_sale = [[0] * exo.nb_tot[u] for u in range(U)]  # 0 propre, 1 sale en file, 2 en nettoyage
        self.q_net = deque()   # (u, lit, durée, h_demande)
        self.net_cours = []    # (h_fin, u, lit, h_demande, h_debut)
        self.q_img = deque()   # (pid, h_demande)
        self.img_cours = []    # (h_fin, pid, h_demande, h_debut)
        self.q_tr = deque()    # (pid, h_demande)
        self.q_avis = deque()  # (pid, h_demande)
        self.avis_cours = []   # (h_fin, pid, h_demande, h_debut)
        self.derniere = {}     # u -> (reco, exposition, actions, n_concernes) de la dernière décision
        self.q_urg = [deque() for _ in range(U)]
        self.q_prog = [deque() for _ in range(U)]
        self.q_trin = [deque() for _ in range(U)]
        self.surge_until = [0] * U
        self.renfort = {}
        self.ratio = [0.8] * U

    def clone(self):
        s = State.__new__(State)
        s.patients = {k: p.copy() for k, p in self.patients.items()}
        s.occ = [{k: s.patients[k] for k in o} for o in self.occ]
        s.bed_pid = [list(b) for b in self.bed_pid]
        s.bed_sale = [list(b) for b in self.bed_sale]
        s.q_net = deque(self.q_net)
        s.net_cours = list(self.net_cours)
        s.q_img = deque(self.q_img)
        s.img_cours = list(self.img_cours)
        s.q_tr = deque(self.q_tr)
        s.q_avis = deque(self.q_avis)
        s.avis_cours = list(self.avis_cours)
        s.derniere = dict(self.derniere)
        s.q_urg = [deque(p.copy() for p in q) for q in self.q_urg]
        s.q_prog = [deque(p.copy() for p in q) for q in self.q_prog]
        s.q_trin = [deque(p.copy() for p in q) for q in self.q_trin]
        s.surge_until = list(self.surge_until)
        s.renfort = dict(self.renfort)
        s.ratio = list(self.ratio)
        return s


# --------------------------------------------------------------------------
# Simulateur
# --------------------------------------------------------------------------

class Sim:
    def __init__(self, exo: Exo, echelle: str, debut_enreg_h: int, fin_enreg_h: int):
        self.x = exo
        self.U = exo.U
        self.pole = echelle == "pole"
        self.h0_rec, self.h1_rec = debut_enreg_h, fin_enreg_h
        pat = exo.pat
        self.p_age, self.p_dep, self.p_dest = pat["age"], pat["dep"], pat["dest"]
        self.p_iso, self.p_oxy, self.p_src = pat["iso"], pat["oxy"], pat["src"]
        self.p_montee = pat["montee_h"]
        self.p_mob, self.p_aide = pat["mob"], pat["aide"]
        self.p_hors = P["hors_pole_min_h"] + np.exp(
            math.log(P["hors_pole_median_h"]) + P["hors_pole_sigma"] * _norm_ppf(pat["u_hors_pole"]))
        # générateur des informations du staff : consommé uniquement en simulation factuelle (journal actif)
        self.rng_info = np.random.default_rng(np.random.SeedSequence([exo.seed, 11]))
        prior = np.array([[s["dest"][k] for k in (DOM, SMR, EHPAD, TRANSF)] for s in exo.specs], float)
        self.prior_dest = prior / prior.sum(axis=1, keepdims=True)

    def transport_requis(self, pid):
        d = self.p_dest[pid]
        return d in TRANSPORT_REQUIS or (d == DOM and self.p_mob[pid] == 2)

    # ---- planification des sorties
    def jour_sortie_dom(self, d, u_we):
        x = self.x
        if d >= x.ndays:
            return d
        if x.dow[d] == 5 and not x.ferie[d]:
            return d if u_we < P["p_sortie_samedi"] else x.prochain_ouvre(d)
        if x.dow[d] == 6 or x.ferie[d]:
            return d if u_we < P["p_sortie_dimanche"] else x.prochain_ouvre(d)
        return d

    def planifier(self, p: Pat):
        pid = p.pid
        ready = p.ready_h
        dest = self.p_dest[pid]
        pat = self.x.pat
        x = self.x
        if dest == DECES:
            return ready
        if dest == DOM and p.aide_h > ready:  # retour à domicile conditionné à l'aide organisée
            ready = p.aide_h
        day, hd = divmod(ready, 24)
        if dest == DOM:
            d = day if hd <= 11 else day + 1
            hour = int(HEURES_SORTIE_DOM[np.searchsorted(CDF_SORTIE_DOM, pat["u_heure"][pid])])
            # sortie du vendredi : patient attendu sortant le week-end, libéré le dernier jour ouvré
            if d < x.ndays and not x.ouvre[d] and pat["u_weekend"][pid] > 1 - P["p_sortie_vendredi"]:
                veille = d - 1
                while veille >= 0 and not x.ouvre[veille]:
                    veille -= 1
                t_ven = veille * 24 + 15 + int(pat["u_heure"][pid] * 4)
                if veille >= 0 and 0 <= ready - t_ven <= 30 and t_ven >= p.admit_h + 12:
                    return t_ven
            d = self.jour_sortie_dom(d, pat["u_weekend"][pid])
            return max(d * 24 + hour, ready + 1)
        d = day + max(1, int(round(pat["aval_j"][pid])))
        if dest in (SMR, EHPAD):
            ferme = (lambda j: x.dow[j] == 6 or x.ferie[j]) if dest == SMR else (lambda j: not x.ouvre[j])
            if d < x.ndays and ferme(d):
                av = d - 1
                while av > 0 and ferme(av):
                    av -= 1
                if pat["u_weekend"][pid] < 0.45 and av * 24 >= ready + 24:
                    d = av
                else:
                    while d < x.ndays and ferme(d):
                        d += 1
            hour = 10 + int(pat["u_heure"][pid] * 5)
        else:
            hour = 10 + int(pat["u_heure"][pid] * 7)
        return max(d * 24 + hour, ready + 1)

    # ---- lits
    def demande_fermeture(self, st, u, b, h):
        x = self.x
        if x.lit_sup[u][b]:
            return st.surge_until[u] <= h
        n = x.fermes[u, h]
        return n > 0 and b in x.ordre_fermeture[u][:n]

    def lit_compatible(self, st, u, pid, h):
        """Lit propre, vacant, ouvert et compatible ; le moins spécialisé possible."""
        x = self.x
        iso, oxy = self.p_iso[pid], self.p_oxy[pid]
        best, cle = -1, 9
        for b in range(x.nb_tot[u]):
            if st.bed_pid[u][b] != -1 or st.bed_sale[u][b] or self.demande_fermeture(st, u, b, h):
                continue
            if (iso and not x.lit_iso[u][b]) or (oxy and not x.lit_oxy[u][b]):
                continue
            k = int(x.lit_iso[u][b]) + int(x.lit_oxy[u][b])
            if k < cle:
                best, cle = b, k
                if k == 0:
                    break
        return best

    def compte_lits(self, st, u, h):
        """(physiques, fermés, ouverts, occupés, sales ou en nettoyage, propres libres)."""
        x = self.x
        phys = ferm = sale = libre = occ = 0
        for b in range(x.nb_tot[u]):
            vac = st.bed_pid[u][b] == -1
            if x.lit_sup[u][b] and st.surge_until[u] <= h and vac and not st.bed_sale[u][b]:
                continue  # lit supplémentaire non installé
            phys += 1
            if not vac:
                occ += 1
            elif self.demande_fermeture(st, u, b, h):
                ferm += 1
            elif st.bed_sale[u][b]:
                sale += 1
            else:
                libre += 1
        return phys, ferm, phys - ferm, occ, sale, libre

    def libres(self, st, u, h):
        return self.compte_lits(st, u, h)[5]

    def liberer(self, st, p, h, log):
        u, b = p.unit, p.bed
        st.bed_pid[u][b] = -1
        st.bed_sale[u][b] = 1
        st.q_net.append((u, b, int(self.x.pat["nett_h"][p.pid]), h))
        if log is not None:
            log.tache("NETTOYAGE", f"NET-{u}-{b}-{h}", u, None, b, h)
        del st.occ[u][p.pid]

    def admettre(self, st, p: Pat, u, b, h, hosted, log):
        pid = p.pid
        los = self.x.pat["los_med_h"][pid] * (P["facteur_los_heberge"] if hosted else 1.0)
        p.unit, p.bed, p.admit_h, p.hosted = u, b, h, hosted
        p.ready_h = h + int(math.ceil(los))
        p.img = bool(self.x.pat["img"][pid])
        p.avis = bool(self.x.pat["avis"][pid])
        p.aide_h = self.heure_aide(h, self.x.pat["aide_delai_h"][pid]) if self.p_aide[pid] else -1
        p.dis_h = self.planifier(p)
        b24 = P["min24_dep"][self.p_dep[pid] - 1]
        b24 *= (P["mult_isolement"] if self.p_iso[pid] else 1.0) * (P["mult_oxygene"] if self.p_oxy[pid] else 1.0)
        p.base24 = b24 * (P["mult_heberge"] if hosted else 1.0)
        st.occ[u][pid] = p
        st.patients[pid] = p
        st.bed_pid[u][b] = pid
        if p.img:
            st.q_img.append((pid, h))
            if log is not None:
                log.tache("IMAGERIE", f"IMG-{pid}", u, pid, None, h)
        if p.avis:
            st.q_avis.append((pid, h))
            if log is not None:
                log.tache("AVIS", f"AVIS-{pid}", u, pid, None, h)
        if log is not None:
            log.event(h, "ADMISSION", u, pid, lit=b, unite_cible=p.home, heberge=hosted, attente_h=h - p.dec_h)

    def sortir(self, st, p, h, log, m):
        u = p.unit
        self.liberer(st, p, h, log)
        del st.patients[p.pid]
        m["sorties"][u] += 1
        if log is not None:
            log.event(h, "SORTIE", u, p.pid, lit=p.bed, destination=DEST[self.p_dest[p.pid]])
            log.sejour(self, p, h, "sortie")

    def heure_aide(self, h_depart, delai_h):
        """Aide à domicile organisée un jour ouvré à 14 h, au plus tôt après le délai."""
        t = h_depart + delai_h
        d = int(t // 24) + (1 if t % 24 > P["aide_heure"] else 0)
        return self.x.prochain_ouvre(d) * 24 + P["aide_heure"]

    @staticmethod
    def bloque(p):
        """Examen ou avis non rendu : la sortie médicale attend."""
        return p.img or p.avis

    # ---- leviers
    def appliquer(self, st, u, levier, h, garanti=False):
        """Applique un levier à l'unité u à l'heure h ; renvoie le nombre de patients ou de postes concernés.

        garanti : pour le renfort, ignore l'échec de pourvoi (scénario « renfort réellement présent »)."""
        x = self.x
        n = 0
        if levier == 0:  # anticipation des sorties à domicile du jour et du lendemain
            today = h // 24
            for p in st.occ[u].values():
                if self.p_dest[p.pid] != DOM or p.antic or p.press or self.bloque(p):
                    continue
                dd = p.dis_h // 24
                if dd == today and p.dis_h % 24 >= 12:
                    new = today * 24 + 11
                elif dd == today + 1:
                    new = (today + 1) * 24 + 10
                else:
                    continue
                if new >= p.ready_h and new >= p.aide_h and new > h and new < p.dis_h:
                    p.dis_h, p.antic = new, True
                    n += 1
        elif levier == 1:  # lits supplémentaires pendant 72 h
            if st.surge_until[u] <= h:
                st.surge_until[u] = h + P["lits_sup_duree_h"]
                n = P["lits_sup_n"]
        elif levier == 2:  # renfort : poste de l'après-midi et poste du matin suivant
            d = h // 24
            for sid in (3 * d + 1 + 1, 3 * (d + 1) + 0 + 1):
                if sid < x.u_renfort.shape[1] and (garanti or x.u_renfort[u, sid] < P["renfort_pourvu"]):
                    st.renfort[(u, sid)] = st.renfort.get((u, sid), 0) + 1
                    n += 1
        elif levier == 3:  # accélération de l'aval : demandes SMR / EHPAD et aides à domicile relancées
            for p in st.occ[u].values():
                if (self.p_dest[p.pid] == DOM and p.aide_h > h + 24 and not p.accel and not p.antic):
                    red = int(math.ceil(P["aide_reduction"] * (p.aide_h - h) / 24))
                    nd = x.prochain_ouvre(max(p.aide_h // 24 - red, h // 24 + 1))
                    new = nd * 24 + P["aide_heure"]
                    if new < p.aide_h:
                        p.aide_h, p.accel = new, True
                        p.dis_h = max(self.planifier(p), h + 1)
                        n += 1
                    continue
                if self.p_dest[p.pid] not in (SMR, EHPAD) or p.accel or p.tr or p.dis_h <= h + 24:
                    continue
                debut = max(h, p.ready_h)
                rest_j = (p.dis_h - debut) / 24
                red = int(math.ceil(P["aval_reduction"] * rest_j))
                if red < 1:
                    continue
                nd = x.prochain_ouvre(max(p.dis_h // 24 - red, debut // 24 + 1))
                new = nd * 24 + p.dis_h % 24
                if new < p.dis_h:
                    p.dis_h, p.accel = new, True
                    n += 1
        return n

    def presents(self, st, u, h):
        x = self.x
        sid = x.sid(h)
        return x.prevus[u, sid] - x.absents[u, sid] + x.remplaces[u, sid] + st.renfort.get((u, sid), 0), sid

    def caracteristiques(self, st, u, h):
        phys, ferm, ouv, occ, sale, libre = self.compte_lits(st, u, h)
        q = st.q_urg[u]
        b4 = sum(1 for p in q if h - p.dec_h >= 4)
        pres, sid = self.presents(st, u, h)
        prev = self.x.prevus[u, sid]
        ready = [p for p in st.occ[u].values() if p.ready_h <= h and not self.bloque(p)]
        return dict(occupation=occ / max(ouv, 1), attente_urg=len(q), attente_urg_4h=b4,
                    sortants_medicaux=len(ready),
                    attente_aval=sum(1 for p in ready if self.p_dest[p.pid] in (SMR, EHPAD)),
                    attente_aide_domicile=sum(1 for p in st.occ[u].values() if p.aide_h > h),
                    ecart_effectif=int(prev - pres), ratio_charge=st.ratio[u],
                    lits_sup_actifs=int(st.surge_until[u] > h))

    @staticmethod
    def recommandations(f):
        """Politique du recommandeur HospitalOS : probabilité de recommander chaque levier.

        Tirage aléatoire à probabilités journalisées (exploration), bornées pour la positivité ;
        0 quand le levier est inapplicable.
        """
        p0 = _sig(-1.0 + 4 * (f["occupation"] - 0.85) + 0.3 * f["attente_urg"], 0.05, 0.95)
        p1 = 0.0 if f["lits_sup_actifs"] else _sig(-2.5 + 6 * (f["occupation"] - 0.95) + 0.5 * f["attente_urg_4h"], 0.02, 0.80)
        p2 = _sig(-2.0 + 1.2 * f["ecart_effectif"] + 3 * (f["ratio_charge"] - 1), 0.05, 0.90)
        n_aval = f["attente_aval"] + f["attente_aide_domicile"]
        p3 = 0.0 if n_aval == 0 else _sig(-1.5 + 0.3 * n_aval, 0.05, 0.95)
        return [p0, p1, p2, p3]

    @staticmethod
    def propensions(f, z=0.0):
        """Politique habituelle du cadre, sans recommandation vue. z : information cachée (logit)."""
        g = P["confusion_gamma"] * z
        p0 = _sig(-2.2 + 3.5 * (f["occupation"] - 0.85) + 0.35 * f["attente_urg"] + g, 0.03, 0.90)
        p1 = 0.0 if f["lits_sup_actifs"] else _sig(-4.0 + 5 * (f["occupation"] - 0.95) + 0.4 * f["attente_urg_4h"] + g, 0.01, 0.60)
        p2 = _sig(-3.0 + 1.2 * f["ecart_effectif"] + 3 * (f["ratio_charge"] - 1) + 0.5 * g, 0.02, 0.85)
        n_aval = f["attente_aval"] + f["attente_aide_domicile"]
        p3 = 0.0 if n_aval == 0 else _sig(-2.8 + 0.25 * n_aval + 2 * (f["occupation"] - 0.9) + 0.5 * g, 0.03, 0.85)
        return [p0, p1, p2, p3]

    def proba_action(self, f, z, reco, expo):
        """Probabilité que le cadre engage chaque levier : validation d'une recommandation vue, sinon habitude."""
        hab = self.propensions(f, z)
        g = P["confusion_gamma"] * z
        return [_sig(P["acceptation_base"][k] + g, 0.02, 0.98) if (reco[k] and expo) else hab[k]
                for k in range(len(LEVIERS))]

    # ---- informations du staff (journal uniquement)
    def _declarer_destination(self, p, decl, h, u, log):
        old = p.dest_decl
        p.dest_decl = decl
        log.event(h, "DESTINATION_DEMANDEE", u, p.pid, destination_demandee=DEST[decl], revision=int(old >= 0))
        if decl in (SMR, EHPAD) and (not p.aval_dem or old != decl):
            p.aval_dem = True
            log.event(h, "DEMANDE_AVAL", u, p.pid, type_aval=DEST[decl])
        elif decl not in (SMR, EHPAD) and p.aval_dem:
            p.aval_dem = False
            log.event(h, "DEMANDE_AVAL_ANNULEE", u, p.pid)
        if getattr(self, "documentary", None) is not None:
            self.documentary.destination(p.pid, old, decl, h)

    def confirmer_aval(self, st, p, h, u, log):
        if getattr(self, "documentary", None) is not None and self.documentary.confirm(self, st, p, h, u, log):
            return
        dp = self.p_dest[p.pid]
        if dp in (SMR, EHPAD) and not p.conf and h >= p.dis_h - 18:
            p.conf = True
            log.event(h, "PLACE_AVAL_CONFIRMEE", u, p.pid, type_aval=DEST[dp])

    def _estimer_dsp(self, p, h, R):
        """Jour de sortie prévu par l'équipe : lit le cours clinique prévu (ready_h courant, sans les files
        futures), les blocages visibles et la destination déclarée ; jamais la sortie réalisée."""
        I = INFO
        att = I["attente_aval_attendue_j"][p.dest_decl] * 24
        if p.ready_h <= h and not self.bloque(p):
            reste = max(12.0, att - (h - p.ready_h)) if p.dest_decl in (SMR, EHPAD, TRANSF) else 12.0
            if self.p_dest[p.pid] == DOM and p.aide_h > h:
                reste = max(reste, p.aide_h - h)
            reste *= math.exp(R.normal(0, 0.3 * I["dsp_informativite"]))
        else:
            total = max(1.0, p.ready_h - p.admit_h)
            rem = max(0.0, p.ready_h - h)
            frac = min(1.0, max(I["dsp_sigma_min_frac"], rem / total))
            sigma = I["dsp_sigma0"] * frac * I["dsp_informativite"]
            reste = rem * math.exp(R.normal(I["dsp_biais_log"], sigma)) + (12 if self.bloque(p) else 0) + att
        return max(h // 24, int((h + reste) // 24))

    def infos_staff(self, st, h, log):
        if getattr(self, "documentary", None) is not None and self.documentary.staff(self, st, h, log):
            return
        R, I = self.rng_info, INFO
        d = h // 24
        for u in range(self.U):
            for p in list(st.occ[u].values()):
                if h - p.admit_h < I["delai_min_h"]:
                    continue
                dest = self.p_dest[p.pid]
                if not p.info0:
                    p.info0 = True
                    p.dsp_jamais = R.random() < I["p_dsp_jamais"]
                    if dest != DECES and R.random() < I["p_destination_juste"]:
                        decl = dest
                    else:
                        decl = (DOM, SMR, EHPAD, TRANSF)[int(R.choice(4, p=self.prior_dest[p.home]))]
                    self._declarer_destination(p, decl, h, u, log)
                elif (dest != DECES and p.dest_decl != dest and p.ready_h <= h + I["fenetre_revision_destination_h"]
                      and (p.ready_h <= h or R.random() < I["p_revision_destination"])):
                    self._declarer_destination(p, dest, h, u, log)
                if p.dsp_jamais:
                    continue
                pret = p.ready_h <= h and not self.bloque(p)
                u_rev = R.random()
                if not (p.dsp < 0 or p.dsp < d or (p.dsp == d and not pret) or u_rev < I["p_revision_jour"]):
                    continue
                new = self._estimer_dsp(p, h, R)
                if new != p.dsp:
                    p.dsp = new
                    p.dsp_n += 1
                    log.event(h, "DATE_SORTIE_PREVISIONNELLE", u, p.pid, date_prevue=self.x.date_iso(new),
                              revision=p.dsp_n - 1)

    # ---- un pas horaire
    def hosting_candidates(self, st, u, p, h):
        return sorted(((self.libres(st, v, h), v) for v in range(self.U) if v != u), reverse=True)

    def start_transports(self, st, h, log, m):
        x = self.x
        # 4. transports de sortie
        cap_tr = int(x.cap_transport[h])
        while cap_tr > 0 and st.q_tr:
            pid, hdem = st.q_tr.popleft()
            p = st.patients.get(pid)
            cap_tr -= 1
            if p is None:
                continue
            if log is not None:
                log.tache_debut(f"TR-{pid}", h)
                log.tache_fin(f"TR-{pid}", h)
            self.sortir(st, p, h, log, m)

        return cap_tr

    def repatriate(self, st, h, log, m, cap_tr):
        U, hd = self.U, h % 24
        # 8. rapatriement des patients hébergés (créneaux de transport restants, 9 h - 17 h)
        if self.pole and 9 <= hd < 17 and cap_tr > 0:
            for v in range(U):
                for p in list(st.occ[v].values()):
                    if cap_tr <= 0:
                        break
                    if (p.home == v or p.dis_h - h < P["rapatriement_marge_h"] or p.tr or st.q_urg[p.home]
                            or st.q_prog[p.home]):
                        continue
                    b = self.lit_compatible(st, p.home, p.pid, h)
                    if b < 0:
                        continue
                    cap_tr -= 1
                    ancien = p.bed
                    self.liberer(st, p, h, log)
                    p.unit, p.bed, p.rapat = p.home, b, p.rapat + 1
                    st.occ[p.home][p.pid] = p
                    st.bed_pid[p.home][b] = p.pid
                    m["transf_out"][v] += 1
                    m["transf_in"][p.home] += 1
                    if log is not None:
                        log.event(h, "TRANSFERT_INTERNE", p.home, p.pid, depuis=self.x.unit_names[v],
                                  lit_origine=ancien, lit=b)

    def start_services(self, st, h, log):
        x = self.x
        # 9. démarrage des services : nettoyage et imagerie
        en_cours = len(st.net_cours)
        while st.q_net and en_cours < x.cap_nettoyage[h]:
            u, b, duree, hdem = st.q_net.popleft()
            st.bed_sale[u][b] = 2
            st.net_cours.append((h + duree, u, b, hdem, h))
            en_cours += 1
            if log is not None:
                log.tache_debut(f"NET-{u}-{b}-{hdem}", h)
        cap_img = int(x.cap_imagerie[h])
        while cap_img > 0 and st.q_img:
            pid, hdem = st.q_img.popleft()
            if pid not in st.patients:
                continue
            st.img_cours.append((h + 1, pid, hdem, h))
            cap_img -= 1
            if log is not None:
                log.tache_debut(f"IMG-{pid}", h)
        cap_av = int(x.cap_avis[h])
        while cap_av > 0 and st.q_avis:
            pid, hdem = st.q_avis.popleft()
            if pid not in st.patients:
                continue
            st.avis_cours.append((h + P["avis_duree_h"], pid, hdem, h))
            cap_av -= 1
            if log is not None:
                log.tache_debut(f"AVIS-{pid}", h)

    def step(self, st: State, h: int, politique=True, log=None, snap=None, force=None):
        """Avance d'une heure et renvoie un dict de métriques par unité.

        politique : la décision journalière (9 h) est active ; log : Journal en simulation factuelle ;
        snap : fonction appelée à 9 h avant la décision (capture d'état pour les contrefactuels) ;
        force : (h, u, reco, actions[, garanti]) impose, à l'heure h et pour l'unité u, les recommandations
        (liste 0/1, la suite de la chaîne étant tirée normalement) ou les actions (liste 0/1) ; garanti=True
        rend le renfort imposé effectivement présent (pas d'échec de pourvoi).
        """
        x = self.x
        U = self.U
        d, hd = divmod(h, 24)
        m = {k: np.zeros(U) for k in ("entrees", "sorties", "transf_in", "transf_out", "heberg_sortants",
                                      "hors_perimetre", "annul_prog", "annul_tr", "pression", "ei_att",
                                      "attente", "occ", "ratio", "ouverts", "occupes", "non_couvert")}

        # 1. décision journalière (9 h) : recommandation -> exposition -> validation ou initiative -> exécution
        if hd == 9 and politique:
            if snap is not None:
                snap(h, st)
            for u in range(U):
                f = self.caracteristiques(st, u, h)
                q = self.recommandations(f)
                fo = force if (force is not None and force[0] == h and force[1] == u) else None
                if fo is not None and fo[2] is not None:
                    reco = list(fo[2])
                else:
                    reco = [int(x.u_reco[u, d, k] < q[k]) for k in range(4)]
                expo = int(x.u_expo[u, d] < P["p_exposition"])
                z = float(x.z_cache[u, d])
                pa = self.proba_action(f, z, reco, expo)
                if fo is not None and fo[3] is not None:
                    acts = list(fo[3])
                else:
                    acts = [int(x.u_politique[u, d, k] < pa[k]) for k in range(4)]
                garanti = bool(fo is not None and len(fo) > 4 and fo[4])
                nconc = [self.appliquer(st, u, k, h, garanti) if a else 0 for k, a in enumerate(acts)]
                st.derniere[u] = (tuple(reco), expo, tuple(acts), tuple(nconc))
                if log is not None:
                    log.action(h, u, f, q, reco, expo, pa, z, acts, nconc)
                    log.event(h, "RECOMMANDATION", u, None, exposee=bool(expo),
                              **{LEVIERS[k]: reco[k] for k in range(4)})
                    log.event(h, "DECISION", u, None, **{LEVIERS[k]: acts[k] for k in range(4)})

        # 2. services terminés : nettoyage, imagerie
        if st.net_cours:
            garde = []
            for t in st.net_cours:
                if t[0] <= h:
                    st.bed_sale[t[1]][t[2]] = 0
                    if log is not None:
                        log.tache_fin(f"NET-{t[1]}-{t[2]}-{t[3]}", h)
                else:
                    garde.append(t)
            st.net_cours = garde
        if st.img_cours:
            garde = []
            for t in st.img_cours:
                if t[0] <= h:
                    p = st.patients.get(t[1])
                    if p is not None:
                        p.img = False
                        if h + 1 > p.ready_h:  # le résultat conditionne la sortie médicale
                            p.ready_h = h + 1
                            p.dis_h = self.planifier(p)
                    if log is not None:
                        log.tache_fin(f"IMG-{t[1]}", h)
                else:
                    garde.append(t)
            st.img_cours = garde
        if st.avis_cours:
            garde = []
            for t in st.avis_cours:
                if t[0] <= h:
                    p = st.patients.get(t[1])
                    if p is not None:
                        p.avis = False
                        if h + 1 > p.ready_h:  # l'avis conditionne la sortie médicale
                            p.ready_h = h + 1
                            p.dis_h = self.planifier(p)
                    if log is not None:
                        log.tache_fin(f"AVIS-{t[1]}", h)
                else:
                    garde.append(t)
            st.avis_cours = garde

        # 3. sorties (retard sous forte charge ; transport requis vers l'aval)
        for u in range(U):
            for p in [p for p in st.occ[u].values() if p.dis_h <= h and not p.tr and (not self.bloque(p) or self.p_dest[p.pid] == DECES)]:
                if (not p.delayed and self.p_dest[p.pid] != DECES and st.ratio[u] > P["seuil_charge_retard"]):
                    retard = min(P["retard_max_h"], int(math.ceil(P["retard_par_point"] * (st.ratio[u] - P["seuil_charge_retard"]))))
                    p.dis_h = h + retard
                    p.delayed = retard
                    continue
                if self.transport_requis(p.pid):
                    p.tr = True
                    st.q_tr.append((p.pid, h))
                    if log is not None:
                        log.tache("TRANSPORT", f"TR-{p.pid}", u, p.pid, None, h)
                    continue
                self.sortir(st, p, h, log, m)

        cap_tr = self.start_transports(st, h, log, m)

        # 5. arrivées
        for pid in x.arrivees[h]:
            p = Pat.__new__(Pat)
            p.pid, p.home, p.dec_h = pid, int(x.pat["unit"][pid]), h
            p.unit, p.admit_h, p.ready_h, p.dis_h, p.bed = -1, -1, -1, -1, -1
            p.hosted, p.press, p.delayed, p.accel, p.antic, p.base24 = False, False, 0, False, False, 0.0
            p.img, p.tr, p.rlog, p.rapat = False, False, False, 0
            p.avis, p.aide_h = False, -1
            p.dsp, p.dsp_n, p.dsp_jamais, p.dest_decl, p.info0 = -1, 0, False, -1, False
            p.conf, p.aide_log, p.aval_dem = False, 0, False
            src = self.p_src[pid]
            (st.q_urg if src == URG else st.q_prog if src == PROG else st.q_trin)[p.home].append(p)
            if log is not None:
                log.event(h, "DEMANDE_ADMISSION", p.home, pid, mode_entree=SRC[src], age=int(self.p_age[pid]),
                          dependance=int(self.p_dep[pid]), isolement=bool(self.p_iso[pid]), oxygene=bool(self.p_oxy[pid]))

        # 6. sorties sous pression (10 h)
        if hd == 10:
            for u in range(U):
                n4 = sum(1 for p in st.q_urg[u] if h - p.dec_h >= P["pression_seuil_attente_h"])
                if n4 >= 2 or (n4 >= 1 and self.libres(st, u, h) <= 0):
                    pp = min(P["pression_p_max"], P["pression_p_par_patient"] * n4)
                    for p in st.occ[u].values():
                        if (self.p_dest[p.pid] == DOM and not p.press and not self.bloque(p) and h + 4 < p.ready_h <= h + 24
                                and p.aide_h <= h + 4 and x.pat["u_pression"][p.pid] < pp):
                            p.dis_h, p.press = h + 4, True
                            m["pression"][u] += 1

        # 7. attribution des lits : programmés, urgences, transferts entrants (lit compatible requis)
        for u in range(U):
            for q in (st.q_prog[u], st.q_urg[u], st.q_trin[u]):
                if not q:
                    continue
                garde = deque()
                while q:
                    p = q.popleft()
                    b = self.lit_compatible(st, u, p.pid, h) if h - p.dec_h >= self.p_montee[p.pid] else -1
                    if b >= 0:
                        self.admettre(st, p, u, b, h, False, log)
                        m["entrees"][u] += 1
                    else:
                        garde.append(p)
                q.extend(garde)
        # hébergement dans une autre unité du pôle
        if self.pole:
            for u in range(U):
                q = st.q_urg[u]
                garde = deque()
                while q:
                    p = q.popleft()
                    if h - p.dec_h >= P["heberg_apres_h"]:
                        cand = self.hosting_candidates(st, u, p, h)
                        fait = False
                        for lv, v in cand:
                            if lv < P["heberg_libres_min"]:
                                break
                            b = self.lit_compatible(st, v, p.pid, h)
                            if b >= 0:
                                self.admettre(st, p, v, b, h, True, log)
                                m["heberg_sortants"][u] += 1
                                m["entrees"][v] += 1
                                fait = True
                                break
                        if fait:
                            continue
                    garde.append(p)
                st.q_urg[u] = garde
        # hébergement hors périmètre (reste de l'hôpital), annulations
        for u in range(U):
            garde = deque()
            for p in st.q_urg[u]:
                if h - p.dec_h >= self.p_hors[p.pid]:
                    m["hors_perimetre"][u] += 1
                    if log is not None:
                        log.event(h, "ORIENTATION_HORS_PERIMETRE", u, p.pid, attente_h=h - p.dec_h)
                        log.sejour(self, p, h, "hors_perimetre")
                else:
                    garde.append(p)
            st.q_urg[u] = garde
            if hd == P["prog_annule_heure"] and st.q_prog[u]:
                for p in st.q_prog[u]:
                    m["annul_prog"][u] += 1
                    if log is not None:
                        log.event(h, "DEPROGRAMMATION", u, p.pid)
                        log.sejour(self, p, h, "deprogramme")
                st.q_prog[u].clear()
            if st.q_trin[u]:
                garde = deque()
                for p in st.q_trin[u]:
                    if h - p.dec_h >= P["transfert_annule_h"]:
                        m["annul_tr"][u] += 1
                        if log is not None:
                            log.event(h, "TRANSFERT_REFUSE", u, p.pid)
                            log.sejour(self, p, h, "transfert_refuse")
                    else:
                        garde.append(p)
                st.q_trin[u] = garde

        self.repatriate(st, h, log, m, cap_tr)

        self.start_services(st, h, log)

        # informations du staff (simulation factuelle uniquement)
        if log is not None and hd == INFO["heure_staff"] and x.ouvre[d]:
            self.infos_staff(st, h, log)

        # 10. charge en soins, effectifs, événements indésirables, état
        for u in range(U):
            demande = 0.0
            for p in st.occ[u].values():
                b = p.base24
                if h - p.admit_h < 24:
                    b *= P["mult_entree"]
                elif p.dis_h - h <= 12:
                    b *= P["mult_veille_sortie"]
                demande += b
            demande = demande / 24 * PROFIL_CHARGE[hd]
            pres, sid = self.presents(st, u, h)
            capacite = max(pres, 1) * 60 * P["efficacite_soignant"]
            ratio = demande / capacite
            st.ratio[u] = ratio
            q = st.q_urg[u]
            n75 = sum(1 for p in q if self.p_age[p.pid] >= 75)
            nocc = len(st.occ[u])
            ei = (nocc * P["ei_base"] * (1 + P["ei_charge"] * max(0.0, ratio - 1))
                  + n75 * P["ei_attente_75"] + (len(q) - n75) * P["ei_attente"])
            m["ei_att"][u] = ei
            m["attente"][u] = len(q)
            m["ratio"][u] = ratio
            m["occupes"][u] = nocc
            m["non_couvert"][u] = max(0.0, demande - capacite)
            if log is None:
                phys, ferm, ouv, occ_, sale, libre = self.compte_lits(st, u, h)
                m["occ"][u] = nocc / max(ouv, 1)
                m["ouverts"][u] = ouv
                continue
            phys, ferm, ouv, occ_, sale, libre = self.compte_lits(st, u, h)
            m["occ"][u] = nocc / max(ouv, 1)
            m["ouverts"][u] = ouv
            ready = [p for p in st.occ[u].values() if p.ready_h <= h and not self.bloque(p)]
            for p in ready:
                if not p.rlog:
                    p.rlog = True
                    log.event(h, "SORTANT_MEDICAL", u, p.pid)
                self.confirmer_aval(st, p, h, u, log)
            for p in st.occ[u].values():
                if p.aide_log == 1 and h >= p.aide_h:
                    p.aide_log = 2
                    log.event(h, "AIDE_DOMICILE_ORGANISEE", u, p.pid)
            if hd == 7:
                for p in st.occ[u].values():
                    log.event(h, "EVALUATION_CHARGE", u, p.pid, minutes_soins_24h=round(p.base24, 1),
                              dependance=int(self.p_dep[p.pid]), mobilite=MOBILITE[int(self.p_mob[p.pid])],
                              proxy_non_siips=True)
                    if p.aide_h >= 0 and p.aide_log == 0:
                        p.aide_log = 1
                        log.event(h, "AIDE_DOMICILE_DEMANDE", u, p.pid)
            part_ide = P["part_ide_nuit"] if (hd < 7 or hd >= 23) else P["part_ide_jour"]
            ide = int(round(pres * part_ide))
            log.etat(h, u, dict(
                lits_physiques=phys, lits_fermes=ferm, lits_ouverts=ouv, lits_occupes=occ_,
                lits_sales_ou_nettoyage=sale, lits_propres_libres=libre,
                lits_supplementaires_actifs=P["lits_sup_n"] if st.surge_until[u] > h else 0,
                patients_heberges_presents=sum(1 for p in st.occ[u].values() if p.home != u),
                attente_urgences_nb=len(q), attente_urgences_4h_plus=sum(1 for p in q if h - p.dec_h >= 4),
                programmes_en_attente=len(st.q_prog[u]), transferts_entrants_en_attente=len(st.q_trin[u]),
                entrees_h=int(m["entrees"][u]), sorties_h=int(m["sorties"][u]),
                transferts_internes_entrants_h=int(m["transf_in"][u]),
                transferts_internes_sortants_h=int(m["transf_out"][u]),
                sortants_medicaux_presents=len(ready),
                en_attente_aval=sum(1 for p in ready if self.p_dest[p.pid] in (SMR, EHPAD)),
                en_attente_transport=sum(1 for p in st.occ[u].values() if p.tr),
                en_attente_imagerie=sum(1 for p in st.occ[u].values() if p.img),
                en_attente_avis=sum(1 for p in st.occ[u].values() if p.avis),
                en_attente_aide_domicile=sum(1 for p in st.occ[u].values() if p.aide_h > h),
                charge_soins_min_h=round(demande, 2), capacite_soins_min_h=round(capacite, 2),
                minutes_non_couvertes_h=round(max(0.0, demande - capacite), 2),
                soignants_prevus=int(x.prevus[u, sid]), soignants_presents=int(pres),
                ide_presents=ide, as_presents=int(pres - ide), ratio_charge=round(ratio, 4),
                ei_attendus_h=round(ei, 5), ei_observes_h=_poisson_inv(ei, x.u_ei[u, h])))
        if log is not None and hd in (7, 15, 23):
            for u in range(U):
                pres, sid = self.presents(st, u, h)
                log.event(h, "PRISE_DE_POSTE", u, None, poste={7: "matin", 15: "apres_midi", 23: "nuit"}[hd],
                          soignants_prevus=int(x.prevus[u, sid]), soignants_presents=int(pres))
        return m


def _sig(z, lo, hi):
    return min(hi, max(lo, 1 / (1 + math.exp(-z))))


def _poisson_inv(lam, u):
    k, p = 0, math.exp(-lam)
    c = p
    while u > c and k < 50:
        k += 1
        p *= lam / k
        c += p
    return k


def _norm_ppf(u):
    """Quantile de la loi normale (approximation d'Acklam), vectorisé."""
    u = np.clip(np.asarray(u, float), 1e-9, 1 - 1e-9)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549671636246879e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    out = np.empty_like(u)
    lo, hi = u < 0.02425, u > 1 - 0.02425
    mid = ~(lo | hi)
    q = np.sqrt(-2 * np.log(u[lo]))
    out[lo] = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = np.sqrt(-2 * np.log(1 - u[hi]))
    out[hi] = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = u[mid] - 0.5
    r = q * q
    out[mid] = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    return out
