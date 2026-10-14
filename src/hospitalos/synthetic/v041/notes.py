"""
Notes cliniques synthétiques (v0.4) : observation des urgences, observation d'entrée, recueil infirmier.

Principes :
- La physique du monde v0.3 est inchangée. Les variables cliniques et sociales latentes (motif,
  antécédents, vit seul, aidant, aides, troubles cognitifs, perte d'autonomie récente, besoin
  d'évaluation sociale) sont tirées après coup, en cohérence avec les attributs que le moteur
  simule déjà (unité, âge, dépendance, oxygène, isolement, destination, aide à domicile, durée).
  Elles décrivent la situation du patient à son arrivée : elles sont connues dès les urgences.
- Une note ne contient que ce qui est connu à l'heure où elle est écrite. Jamais de date de sortie,
  de durée de séjour, de destination réalisée.
- Chaque note est versionnée : une version ajoute un complément daté, sans réécrire le texte
  précédent. Chaque version a ses horloges : création, modification, disponibilité (signature).
- Chaque version a sa vérité annotée : faits affirmés, statut (documenté, négation, hypothèse),
  exactitude (vrai, faux, périmé, prévision), extrait et position dans le texte.
- Générateurs aléatoires séparés, un par séjour et par type de note : la note d'un séjour ne dépend
  ni des autres séjours ni de ce qui se passe après son écriture.
"""
from __future__ import annotations

import math
import re

import numpy as np

from . import hospsim as hs
from . import textes_notes as T

VARIABLES_NOTES = ["motif", "incertitude_diagnostique", "vit_seul", "aidant_present", "aides_existantes",
                   "troubles_cognitifs", "perte_autonomie_recente", "evaluation_sociale_demandee",
                   "orientation_envisagee", "autonomie", "mobilite", "oxygene", "isolement", "imagerie_prevue",
                   "avis_prevu"]
VARIABLES_INTERDITES = {"destination_finale", "date_sortie", "duree_sejour", "date_sortant_medical", "dms"}
TYPES = ["OBS_URGENCES", "OBS_ENTREE", "RECUEIL_IDE"]

# Marqueurs explicites : toute phrase qui en contient un doit porter une annotation de la variable
# (ou d'une variable voisine listée dans COUVRE). Sert au contrôle de complétude de la vérité.
MARQUEURS = {
    "oxygene": r"\bO2\b|SpO2|oxygénothérapie|air ambiant",
    "vit_seul": r"\bvit seule?\b|\bvit (?:avec|en couple|chez)|seule? (?:à|au) dom|habite seule?|partage son logement|"
                r"hébergée? par|personne ne vit|présente? au domicile",
    "aidant_present": r"aidante? principale?|entourage proche|aucun aidant|famille éloignée|assure l'essentiel|"
                      r"passe (?:tous les jours|chaque soir|2 fois)|joignable|référente",
    "aides_existantes": r"aide ménagère|SSIAD|portage des repas|téléalarme|auxiliaire de vie|\bAPA\b|passage IDE|IDE à dom|femme de ménage|"
                        r"repas livrés|(?:pas|aucune?) d'?aide\b|aucun intervenant",
    "troubles_cognitifs": r"cognitif|cognition|mnésique|alzheimer|démence|démentiel|\bMMS\b|\bMNC\b|fonctions supérieures",
    "autonomie": r"\bAVQ\b|actes de la vie|habillage|grabataire|dépendance totale|totalement autonome|gestes du quotidien",
    "mobilite": r"\bcanne\b|déambulateur|fauteuil roulant|déambulation|sans aide technique|deux personnes|aide d'une personne",
    "isolement": r"isolement (?:contact|gouttelettes)|précautions (?:complémentaires|contact|gouttelettes|air)",
}
COUVRE = {v: {v} for v in MARQUEURS}
COUVRE["autonomie"] = {"autonomie", "perte_autonomie_recente"}
COUVRE["aides_existantes"] = {"aides_existantes", "aidant_present"}

# Paires de formulations incompatibles dans les faits « vrais » d'un même séjour
INCOMPATIBLES = {
    "seul_et_conjoint_present": (r"veuve?\b|divorcée?|célibataire|décès du conjoint|vit seule?|seule? (?:à|au) dom",
                                 r"époux|épouse|\bmari\b|en couple|partage son logement"),
    "alite_et_marche": (r"grabataire|alitée?|ne quitte plus le lit",
                        r"\bcanne\b|déambulateur|aide d'une personne|marche seule?|déambulation"),
    "marche_sans_aide_et_aide_technique": (r"marche sans aide|sans aide technique|déambulation autonome",
                                           r"\bcanne\b|déambulateur|fauteuil|aide d'une personne|deux personnes|alitée?"),
    "aucune_aide_et_aide": (r"pas d'aide|aucune aide|aucun intervenant|aucun service",
                            r"aide ménagère|ssiad|portage des repas|téléalarme|auxiliaire|\bapa\b|passage ide|femme de ménage|repas livrés"),
    "sans_aidant_et_aidant": (r"pas d'entourage|aucun aidant|famille éloignée",
                              r"aidante? principale?|assure l'essentiel|passe (?:tous|chaque)|joignable|référente"),
}

DOC = {  # probabilité qu'un champ soit documenté dans la version initiale, par type de note
    "OBS_URGENCES": dict(vit_seul=0.45, aidant_present=0.25, aides_existantes=0.30, troubles_cognitifs=0.35,
                         perte_autonomie_recente=0.40, evaluation_sociale_demandee=0.50, orientation_envisagee=0.10,
                         autonomie=0.45, mobilite=0.30, oxygene=0.85, isolement=0.80, imagerie_prevue=0.60,
                         avis_prevu=0.40, atcd=0.85),
    "OBS_ENTREE": dict(vit_seul=0.75, aidant_present=0.50, aides_existantes=0.60, troubles_cognitifs=0.60,
                       perte_autonomie_recente=0.60, evaluation_sociale_demandee=0.70, orientation_envisagee=0.30,
                       autonomie=0.70, mobilite=0.50, oxygene=0.85, isolement=0.95, imagerie_prevue=0.85,
                       avis_prevu=0.80, atcd=0.95),
    "RECUEIL_IDE": dict(vit_seul=0.85, aidant_present=0.75, aides_existantes=0.80, troubles_cognitifs=0.70,
                        perte_autonomie_recente=0.40, evaluation_sociale_demandee=0.30, orientation_envisagee=0.0,
                        autonomie=0.90, mobilite=0.90, oxygene=0.90, isolement=0.95, imagerie_prevue=0.0,
                        avis_prevu=0.0, atcd=0.0),
}
P_NOTES = dict(p_v2_urg=0.55, p_v3_urg=0.10, p_v2_entree=0.30, p_ide=0.80, p_perime_entree=0.12, p_faux_urg=0.05,
               p_signature_tardive=0.15, p_typo=0.03, p_abrev_urg=0.30, p_hors_vocabulaire_test=0.5,
               p_confusion_aigue_ecrite_desorientation=0.8)


# --------------------------------------------------------------------------
# Variables latentes
# --------------------------------------------------------------------------

def latents(exo, seed):
    """Une ligne par demande d'admission : situation clinique et sociale à l'arrivée."""
    pat = exo.pat
    out = []
    med_los = {u: hs.UNITS[n]["los_med_median_j"] * 24 for u, n in enumerate(exo.unit_names)}
    for pid in range(exo.N):
        r = np.random.default_rng(np.random.SeedSequence([seed, 13, pid]))
        u = int(pat["unit"][pid])
        nom = exo.unit_names[u]
        age, dep, dest = int(pat["age"][pid]), int(pat["dep"][pid]), int(pat["dest"][pid])
        oxy, iso, aide = bool(pat["oxy"][pid]), bool(pat["iso"][pid]), bool(pat["aide"][pid])
        zl = math.log(max(pat["los_med_h"][pid], 6) / med_los[u]) / 0.6
        za = (age - 75) / 12
        noms, w = [], []
        for k, m in T.MOTIFS.items():
            b = m["unites"].get(nom, 0)
            if b <= 0:
                continue
            x = b * (m["oxy"] if oxy else 1 / max(1.0, m["oxy"]) ** 0.5) * (m["iso"] if iso else 1.0)
            x *= math.exp(0.5 * m["los"] * zl + 0.4 * m["age"] * za)
            noms.append(k)
            w.append(x)
        w = np.array(w) / sum(w)
        motif = noms[int(r.choice(len(noms), p=w))]
        incert = r.random() < 0.6 * T.MOTIFS[motif]["incert"]
        # antécédents
        p_atcd = dict(hta=0.25 + 0.4 * (age >= 65), dt2=0.22, fa=0.08 + 0.12 * (age >= 75), ic=0.08, coronarien=0.10,
                      bpco=0.08, irc=0.06 + 0.10 * (age >= 80), avc=0.07, cancer=0.10, depression=0.10,
                      osteoporose=0.05 + 0.10 * (age >= 80 and pat["femme"][pid]), parkinson=0.02 + 0.03 * (age >= 75),
                      saos=0.05, obesite=0.08, hypothyroidie=0.07)
        if nom == "CARDIO":
            p_atcd.update(fa=0.35, ic=0.30, coronarien=0.35)
        if nom == "PNEUMO":
            p_atcd.update(bpco=0.45)
        p_atcd.update({"bpco": 0.95} if motif == "bpco" else {})
        p_atcd.update({"ic": 0.70} if motif == "insuffisance_cardiaque" else {})
        p_atcd.update({"dt2": 1.0} if motif == "diabete" else {})
        p_atcd.update({"cancer": 0.45} if motif in ("aeg", "neoplasie_pulm") else {})
        atcd = [k for k in T.ATCD if r.random() < min(0.98, p_atcd.get(k, 0.05))]
        # situation sociale et cognitive
        aval = dest in (hs.SMR, hs.EHPAD)
        p_seul = (0.25 if age < 65 else 0.35 if age < 80 else 0.45) + (0.10 if age >= 80 and pat["femme"][pid] else 0)
        p_seul = min(0.85, p_seul * (1.6 if (aide or aval) else 1.0))
        vit_seul = r.random() < p_seul
        aidant = True if not vit_seul else bool(r.random() < 0.55)
        p_aides = [0.15, 0.35, 0.60, 0.80][dep - 1] * (1.2 if vit_seul else 0.8)
        aides = r.random() < min(0.95, p_aides)
        p_cog = (0.03 if age < 65 else 0.10 if age < 80 else 0.30) * (1.8 if dest == hs.EHPAD else 1.0) \
            * (1.3 if dep >= 3 else 1.0) + (0.10 if nom == "CSG" else 0.0)
        cognitif = r.random() < min(0.9, p_cog)
        p_perte = (0.08 + (0.27 if dest == hs.SMR else 0.37 if dest == hs.EHPAD else 0.0) + (0.30 if aide else 0.0)
                   + (0.10 if motif in ("chute", "aeg") else 0.0)) * (0.5 if dep == 1 else 1.0)
        perte = r.random() < min(0.9, p_perte)
        fragile = (vit_seul and (perte or dep >= 3)) or (cognitif and vit_seul)
        evalsoc = r.random() < (0.60 if fragile else 0.05)
        # situation détaillée, unique pour toutes les notes du séjour
        if vit_seul:
            x = r.random()
            pv = 0.65 if age >= 75 else 0.25
            statut = "veuf" if x < pv else ("divorce" if x < pv + 0.2 else "celibataire")
            cohabitant, enfant = None, None
        else:
            cohabitant = "conjoint" if r.random() < (0.8 if age < 85 else 0.55) else "enfant"
            enfant = ("fille" if r.random() < 0.6 else "fils") if cohabitant == "enfant" else None
            statut = "marie" if cohabitant == "conjoint" else ("veuf" if age >= 75 and r.random() < 0.7 else "divorce")
        if not aidant:
            aidant_type = None
        elif cohabitant == "conjoint":
            aidant_type = "conjoint"
        elif cohabitant == "enfant":
            aidant_type = enfant
        else:
            aidant_type = ["fille", "fils", "niece"][int(r.choice(3, p=[0.45, 0.35, 0.20]))]
        aides_types = []
        if aides:
            pool = ["ssiad", "auxiliaire", "apa", "ide"] if dep >= 3 else ["aide_menagere", "portage", "telealarme", "ide"]
            k = 1 + int(r.random() < 0.4)
            aides_types = [pool[i] for i in sorted(r.choice(len(pool), size=k, replace=False))]
        logement = list(T.LOGEMENT)[int(r.integers(0, len(T.LOGEMENT)))]
        mob = hs.MOBILITE[int(pat["mob"][pid])]
        if mob == "autonome":
            aide_tech = "aucune"
        elif mob == "aide":
            aide_tech = ["canne", "deambulateur", "tierce_personne"][int(r.choice(3, p=[0.35, 0.45, 0.20]))]
        else:
            aide_tech = (["alite", "transfert_deux", "fauteuil"][int(r.choice(3, p=[0.5, 0.3, 0.2]))] if dep == 4
                         else ["transfert_deux", "fauteuil"][int(r.integers(0, 2))])
        cause_iso = None
        if iso:
            cands = [i for i, (t, _) in enumerate(T.CAUSES_ISOLEMENT) if (t == "gouttelettes") == (motif == "grippe")]
            if motif in ("pneumopathie", "neoplasie_pulm") and nom == "PNEUMO" and r.random() < 0.2:
                cands = [i for i, (t, _) in enumerate(T.CAUSES_ISOLEMENT) if t == "air"]
            cause_iso = int(cands[int(r.integers(0, len(cands)))])
        out.append(dict(pid=pid, motif=motif, incertitude_diagnostique=bool(incert), antecedents=atcd,
                        vit_seul=bool(vit_seul), aidant_present=bool(aidant), aides_existantes=bool(aides),
                        troubles_cognitifs=bool(cognitif), perte_autonomie_recente=bool(perte),
                        evaluation_sociale_demandee=bool(evalsoc), cause_isolement=cause_iso,
                        statut_marital=statut, cohabitant=cohabitant, enfant=enfant, aidant_type=aidant_type,
                        aides_types=aides_types, logement=logement, aide_technique=aide_tech))
    return out


# --------------------------------------------------------------------------
# Rédaction
# --------------------------------------------------------------------------

class _Redac:
    """Accumulateur de segments : texte final et faits annotés avec leur position."""

    def __init__(self, femme, age, r, abrev, horsvoc):
        self.segs, self.femme, self.age, self.r, self.abrev, self.horsvoc = [], femme, age, r, abrev, horsvoc
        self.droite = r.random() < 0.5  # même côté dans toute la note
        self.sit = None                 # situation du patient (latents), commune à toutes ses notes

    def accorder(self, s):
        f = self.femme
        rep = {"{Mme}": "Mme" if f else "M.", "{e}": "e" if f else "", "{il}": "elle" if f else "il",
               "{Il}": "Elle" if f else "Il", "{le}": "la" if f else "le", "{lui}": "elle" if f else "lui",
               "{Veuf}": "Veuve" if f else "Veuf", "{conjoint}": "son époux" if f else "son épouse",
               "{Conjoint_aidant}": "Époux aidant principal" if f else "Épouse aidante principale",
               "{Conjoint_present}": "Mari" if f else "Épouse", "{ce}": "" if f else "e",
               "{fumeur}": "fumeuse" if f else "fumeur", "{age}": str(self.age),
               "{logement}": T.LOGEMENT[self.sit["logement"]] if self.sit else "appartement",
               "{enfant}": {"fille": "sa fille", "fils": "son fils"}.get(self.sit.get("enfant") if self.sit else None, "sa fille"),
               "{cotem}": "droit" if self.droite else "gauche", "{cote}": "droite" if self.droite else "gauche"}
        for k, v in rep.items():
            s = s.replace(k, v)
        s = re.sub(r"\{n\}", lambda _: str(int(self.r.integers(2, 8))), s)
        s = re.sub(r"\{k\}", lambda _: str(int(self.r.integers(3, 12))), s)
        s = re.sub(r"\{m\}", lambda _: str(int(self.r.integers(1, 6))), s)
        s = re.sub(r"\{d\}", lambda _: str(int(self.r.integers(1, 9))), s)
        return s

    def bruit(self, s):
        if self.abrev:
            for a, b in T.ABREVIATIONS:
                if self.r.random() < 0.5:
                    s = s.replace(a, b)
        if self.r.random() < P_NOTES["p_typo"]:
            mots = [i for i, w in enumerate(s.split(" ")) if len(w) > 5 and w.isalpha()]
            if mots:
                ws = s.split(" ")
                i = mots[int(self.r.integers(0, len(mots)))]
                j = int(self.r.integers(1, len(ws[i]) - 1))
                w = ws[i]
                ws[i] = w[:j - 1] + w[j] + w[j - 1] + w[j + 1:]
                s = " ".join(ws)
        return s

    def choisir(self, liste):
        return liste[int(self.r.integers(0, len(liste)))]

    def ajout(self, texte, fait=None, sep="\n"):
        texte = self.bruit(self.accorder(texte))
        self.segs.append((sep, texte, fait))
        return texte

    def banque(self, cle):
        """Banque principale, ou hors vocabulaire sur la période de test (si la clé y existe)."""
        if self.horsvoc and cle in T.HORS_VOCABULAIRE and self.r.random() < P_NOTES["p_hors_vocabulaire_test"]:
            return T.HORS_VOCABULAIRE[cle]
        return T.PRINCIPALE[cle]

    @staticmethod
    def statut_de(txt):
        """Négation : le fait est exprimé en niant (« Pas de… », « Aucun… », « personne ne vit avec… »,
        « ne bénéficie d'aucun… »). « Ne fait plus ses courses » affirme une perte : ce n'est pas une négation."""
        return "negation" if (re.match(r"^(Pas |Aucun|Personne )", txt) or re.search(r"\bpersonne ne\b|\bne \w+ d'aucun", txt)) \
            else "documente"

    def texte(self):
        out, faits, pos = "", [], 0
        for i, (sep, t, f) in enumerate(self.segs):
            if i > 0:
                out += sep
            deb = len(out)
            out += t
            if f is not None:
                faits.append(dict(f, extrait=t, debut=deb, fin=deb + len(t)))
        return out, faits


def _date(debut, h):
    t = np.datetime64(debut.isoformat()) + np.timedelta64(int(math.floor(h * 60)), "m")
    s = str(t.astype("datetime64[m]"))
    return f"{s[8:10]}/{s[5:7]}/{s[0:4]}", f"{s[11:13]}h{s[14:16]}"


def _phrase_sociale(rd, L, var, val, correct):
    """Formulation d'un fait social, tirée de la situation du patient. val peut différer de la vérité
    (erreur volontaire « faux » ou copier-coller « perime ») : la formulation reste plausible."""
    if var == "vit_seul":
        if val:
            b = rd.banque("seul")
            cands = b.get(L["statut_marital"], []) + b["generique"] if correct == "vrai" else b["generique"]
            txt = rd.choisir(cands)
            return txt, rd.statut_de(txt)
        b = rd.banque("cohabite")
        coh = L["cohabitant"] if (correct == "vrai" and L["cohabitant"]) else "conjoint"
        txt = rd.choisir(b[coh])
        return txt, rd.statut_de(txt)
    if var == "aidant_present":
        if val:
            typ = L["aidant_type"] if (correct == "vrai" and L["aidant_type"]) else "fille"
            return rd.choisir(T.PRINCIPALE["aidant"][typ]), "documente"
        txt = rd.choisir(T.PRINCIPALE["aidant_absent"])
        return txt, rd.statut_de(txt)
    if var == "aides_existantes":
        if val:
            types = L["aides_types"] if (correct == "vrai" and L["aides_types"]) else ["aide_menagere"]
            morceaux = [rd.choisir(rd.banque("aides").get(t) or T.PRINCIPALE["aides"][t]) for t in types]
            txt = " et ".join(morceaux) + "."
            return txt[0].upper() + txt[1:], "documente"
        txt = rd.choisir(rd.banque("aides_absentes"))
        return txt, rd.statut_de(txt)
    cle = {"troubles_cognitifs": "cognitif", "perte_autonomie_recente": "perte"}[var]
    if var == "troubles_cognitifs" and val and rd.r.random() < 0.15:
        return rd.choisir(T.PRINCIPALE["cognitif_hypo"]), "hypothese"
    txt = rd.choisir(rd.banque(f"{cle}_{'vrai' if val else 'faux'}"))
    return txt, rd.statut_de(txt)


def _social(rd, L, typ, deja, correct_force=None):
    """Faits sociaux et cognitifs documentés selon les probabilités du type de note, depuis la situation unique."""
    d = DOC[typ]
    r = rd.r
    for var in ("vit_seul", "aidant_present", "aides_existantes", "troubles_cognitifs", "perte_autonomie_recente"):
        if var in deja or r.random() >= d[var] * (1.3 if L[var] and var != "vit_seul" else 1.0):
            continue
        val, correct = L[var], "vrai"
        if correct_force and correct_force[0] == var:
            val, correct = not val, correct_force[1]
        txt, statut = _phrase_sociale(rd, L, var, val, correct)
        if correct == "perime" and r.random() < 0.5:
            txt = txt.rstrip(".") + " " + rd.choisir(T.SOURCE_ANCIENNE) + "."
        rd.ajout(txt, dict(variable=var, valeur=bool(val), statut=statut, correct=correct), sep=" ")
        deja.add(var)
    if L["evaluation_sociale_demandee"] and "evaluation_sociale_demandee" not in deja and r.random() < d["evaluation_sociale_demandee"]:
        rd.ajout(rd.choisir(T.PRINCIPALE["evalsoc_vrai"]),
                 dict(variable="evaluation_sociale_demandee", valeur=True, statut="documente", correct="vrai"), sep=" ")
        deja.add("evaluation_sociale_demandee")


def _fonctionnel(rd, L, typ, deja, dep, mob):
    """Autonomie et mobilité : formulations compatibles entre elles (même aide technique)."""
    d, r = DOC[typ], rd.r
    tech = L["aide_technique"]
    if "autonomie" not in deja and r.random() < d["autonomie"]:
        cands = [t for t, comp in rd.banque("autonomie")[dep] if comp is None or tech in comp]
        if not cands:
            cands = [t for t, comp in T.PRINCIPALE["autonomie"][dep] if comp is None or tech in comp]
        rd.ajout(rd.choisir(cands), dict(variable="autonomie", valeur=int(dep), statut="documente", correct="vrai"), sep=" ")
        deja.add("autonomie")
    if "mobilite" not in deja and r.random() < d["mobilite"]:
        rd.ajout(rd.choisir(T.PRINCIPALE["mobilite"][tech]),
                 dict(variable="mobilite", valeur=mob, statut="documente", correct="vrai", detail=tech), sep=" ")
        deja.add("mobilite")


def _besoins(rd, S, L, typ, deja):
    d, r = DOC[typ], rd.r
    if "oxygene" not in deja and r.random() < d["oxygene"] * (1.1 if S["oxy"] else 0.5):
        txt = rd.choisir(T.PRINCIPALE["oxygene_vrai" if S["oxy"] else "oxygene_faux"])
        rd.ajout(txt, dict(variable="oxygene", valeur=bool(S["oxy"]), statut=rd.statut_de(txt), correct="vrai"), sep=" ")
        deja.add("oxygene")
    if S["iso"] and "isolement" not in deja and r.random() < d["isolement"]:
        typ_iso, txt = T.CAUSES_ISOLEMENT[L["cause_isolement"]]
        rd.ajout(txt, dict(variable="isolement", valeur=typ_iso, statut="documente", correct="vrai"))
        deja.add("isolement")


def _plan(rd, S, L, typ, deja):
    d, r = DOC[typ], rd.r
    m = T.MOTIFS[L["motif"]]
    if S["img"] and "imagerie_prevue" not in deja and r.random() < d["imagerie_prevue"]:
        ex = rd.choisir(m["imagerie"])
        fem = "e" if ex.lower().startswith(("échographie", "radio", "coronarographie", "irm")) else ""
        rd.ajout(rd.choisir([f"{ex[0].upper() + ex[1:]} demandé{fem}.", f"{ex[0].upper() + ex[1:]} à prévoir.",
                             f"Prévoir {ex}."]),
                 dict(variable="imagerie_prevue", valeur=True, statut="documente", correct="vrai", detail=ex))
        deja.add("imagerie_prevue")
    if S["avis"] and "avis_prevu" not in deja and r.random() < d["avis_prevu"]:
        av = rd.choisir(m["avis"])
        rd.ajout(rd.choisir([f"{av[0].upper() + av[1:]} à demander.", f"{av[0].upper() + av[1:]} demandé.",
                             f"Solliciter un {av}."]),
                 dict(variable="avis_prevu", valeur=True, statut="documente", correct="vrai", detail=av))
        deja.add("avis_prevu")
    if "orientation_envisagee" not in deja and r.random() < d["orientation_envisagee"] and (L["perte_autonomie_recente"] or L["vit_seul"]):
        if L["troubles_cognitifs"] and L["vit_seul"]:
            i, val = 2, "EHPAD"
        elif L["perte_autonomie_recente"]:
            i, val = 1, "SMR"
        else:
            i, val = 0, "domicile"
        rd.ajout(T.PRINCIPALE["orientation_hypo"][i],
                 dict(variable="orientation_envisagee", valeur=val, statut="hypothese", correct="prevision"))
        deja.add("orientation_envisagee")


def _motif(rd, L, entete_court=True):
    m = T.MOTIFS[L["motif"]]
    if entete_court:
        rd.ajout("Motif : " + rd.choisir(m["court"]))
    return m


def _atcd(rd, L, typ):
    if rd.r.random() >= DOC[typ]["atcd"]:
        return
    if not L["antecedents"]:
        rd.ajout("ATCD : aucun antécédent notable.")
        return
    items = [rd.choisir(T.ATCD[k][0]) for k in L["antecedents"]]
    rd.ajout("ATCD : " + ", ".join(items) + ".")
    ttt = [x for k in L["antecedents"] for x in T.ATCD[k][1][:1 + int(rd.r.integers(0, 2))]]
    if ttt and rd.r.random() < 0.7:
        rd.ajout("TTT : " + ", ".join(ttt) + ".")
    else:
        rd.ajout(rd.choisir(T.TTT_ABSENT))


def _conclusion(rd, L, m, deja):
    if L["incertitude_diagnostique"]:
        rd.ajout("Conclusion : " + rd.choisir(m["hypo"]),
                 dict(variable="motif", valeur=L["motif"], statut="hypothese", correct="vrai"))
    else:
        rd.ajout("Conclusion : " + rd.choisir(m["diag"]),
                 dict(variable="motif", valeur=L["motif"], statut="documente", correct="vrai"))
    deja.add("motif")


def rediger_sejour(S, L, debut, h_test, seed):
    """Toutes les versions de toutes les notes d'un séjour. S : faits du séjour connus du monde ; L : latents.

    S : pid, sejour_id, src, dec_h, admit_h (-1 si non admis), unite_home, unite_admission, heberge,
        age, femme, dep, mob, oxy, iso, img, avis.
    Renvoie une liste de versions : dict(type, auteur, version, t_creation, t_modif, t_dispo, unite, texte, faits).
    """
    versions = []
    svc = lambda u: T.UNITES_LIBELLE[u]  # noqa: E731
    # ---------------- observation des urgences
    if S["src"] == hs.URG:
        r = np.random.default_rng(np.random.SeedSequence([seed, 17, S["pid"], 0]))
        senior = r.random() < 0.3
        tc = S["dec_h"] - r.uniform(0.3, 2.5)
        horsvoc = tc >= h_test
        rd = _Redac(S["femme"], S["age"], r, abrev=(not senior and r.random() < P_NOTES["p_abrev_urg"]), horsvoc=horsvoc)
        rd.sit = L
        dd, hh = _date(debut, tc)
        da, ha = _date(debut, tc - r.uniform(0.5, 4))
        rd.ajout(rd.choisir(T.ENTETES["OBS_URGENCES"]) + f" - {dd} {hh}", sep="")
        rd.ajout(f"{{Mme}} X, {{age}} ans, arrivé{{e}} le {da} à {ha}.")
        m = _motif(rd, L)
        _atcd(rd, L, "OBS_URGENCES")
        deja = set()
        faux = None
        if r.random() < P_NOTES["p_faux_urg"]:
            faux = (["vit_seul", "aides_existantes", "troubles_cognitifs"][int(r.integers(0, 3))], "faux")
        rd.ajout("Mode de vie :", sep="\n")
        n0 = len(rd.segs)
        _social(rd, L, "OBS_URGENCES", deja, faux)
        _fonctionnel(rd, L, "OBS_URGENCES", deja, S["dep"], S["mob"])
        if len(rd.segs) == n0:
            rd.segs.pop()
        rd.ajout("HDM : " + rd.choisir(m["hdm"]))
        rd.ajout("Examen : " + rd.choisir(m["examen"]))
        _besoins(rd, S, L, "OBS_URGENCES", deja)
        _conclusion(rd, L, m, deja)
        _plan(rd, S, L, "OBS_URGENCES", deja)
        rd.ajout(rd.choisir(T.CAT_URG).replace("{service}", rd.choisir(svc(S["unite_home"]))))
        t_mod = tc + r.uniform(0.2, 1.0)
        versions += _versionner(rd, "OBS_URGENCES", "senior_urgences" if senior else "interne_urgences", tc, t_mod,
                                S["unite_home"], r)
        # compléments
        if r.random() < P_NOTES["p_v2_urg"]:
            t2 = max(S["dec_h"] + r.uniform(0.5, 6), versions[-1]["t_modif"] + 0.1)
            dd2, hh2 = _date(debut, t2)
            rd.ajout(f"{rd.choisir(T.COMPLEMENTS)} du {dd2} à {hh2} : " + rd.choisir(T.CONTACT_FAMILLE[L["aidant_type"] or "aucun"]),
                     sep="\n\n")
            n1 = len(rd.segs)
            _social(rd, L, "OBS_ENTREE", deja)
            _fonctionnel(rd, L, "OBS_ENTREE", deja, S["dep"], S["mob"])
            _plan(rd, S, L, "OBS_URGENCES", deja)
            if len(rd.segs) == n1:
                rd.ajout("Pas d'élément nouveau.", sep=" ")
            versions += _versionner(rd, "OBS_URGENCES", "senior_urgences" if senior else "interne_urgences", tc, t2,
                                    S["unite_home"], r, base=versions[-1])
            if r.random() < P_NOTES["p_v3_urg"]:
                t3 = (math.floor(t2 / 24) + 1) * 24 + r.uniform(9, 11)
                dd3, hh3 = _date(debut, t3)
                rd.ajout(f"Relecture du {dd3} à {hh3} : " + rd.choisir(["RAS.", "Dossier relu, pas de modification.",
                                                                       "Bilan biologique de sortie des urgences vu."]),
                         sep="\n\n")
                versions += _versionner(rd, "OBS_URGENCES", "senior_urgences", tc, t3, S["unite_home"], r,
                                        base=versions[-1])
    if S["admit_h"] < 0:
        return versions
    # ---------------- observation d'entrée dans le service
    r = np.random.default_rng(np.random.SeedSequence([seed, 17, S["pid"], 1]))
    tc = S["admit_h"] + r.uniform(1, 14)
    if (tc % 24 >= 22 or tc % 24 < 8) and r.random() < 0.7:
        tc = (math.floor(tc / 24) + (1 if tc % 24 >= 22 else 0)) * 24 + r.uniform(8, 11)
    rd = _Redac(S["femme"], S["age"], r, abrev=False, horsvoc=tc >= h_test)
    rd.sit = L
    u_adm = S["unite_admission"]
    dd, hh = _date(debut, tc)
    rd.ajout(rd.choisir(T.ENTETES["OBS_ENTREE"]).replace("{service}", rd.choisir(svc(u_adm)).upper()) + f" - {dd} {hh}", sep="")
    if S["heberge"]:
        rd.ajout(rd.choisir(T.HEBERGE).replace("{hote}", rd.choisir(svc(u_adm))).replace("{service}", rd.choisir(svc(S["unite_home"]))))
    rd.ajout(f"{{Mme}} X, {{age}} ans.")
    m = _motif(rd, L)
    _atcd(rd, L, "OBS_ENTREE")
    deja = set()
    perime = None
    if r.random() < P_NOTES["p_perime_entree"]:
        perime = (["vit_seul", "aides_existantes", "troubles_cognitifs", "aidant_present"][int(r.integers(0, 4))], "perime")
    rd.ajout("Mode de vie :")
    n0 = len(rd.segs)
    _social(rd, L, "OBS_ENTREE", deja, perime)
    _fonctionnel(rd, L, "OBS_ENTREE", deja, S["dep"], S["mob"])
    if len(rd.segs) == n0:
        rd.segs.pop()
    rd.ajout("Histoire : " + rd.choisir(m["hdm"]))
    rd.ajout("Examen d'entrée : " + rd.choisir(m["examen"]))
    _besoins(rd, S, L, "OBS_ENTREE", deja)
    _conclusion(rd, L, m, deja)
    rd.ajout("Projet :")
    n0 = len(rd.segs)
    _plan(rd, S, L, "OBS_ENTREE", deja)
    if len(rd.segs) == n0:
        rd.ajout(rd.choisir(["Poursuite de la prise en charge.", "Traitement en cours, réévaluation à 48 h."]), sep=" ")
    auteur = "senior_service" if r.random() < 0.5 else "interne_service"
    versions += _versionner(rd, "OBS_ENTREE", auteur, tc, tc + r.uniform(0.3, 1.5), u_adm, r)
    if r.random() < P_NOTES["p_v2_entree"]:
        t2 = versions[-1]["t_modif"] + r.uniform(2, 30)
        dd2, hh2 = _date(debut, t2)
        rd.ajout(f"{rd.choisir(T.COMPLEMENTS)} du {dd2} à {hh2} :", sep="\n\n")
        n1 = len(rd.segs)
        _social(rd, L, "RECUEIL_IDE", deja)
        _plan(rd, S, L, "OBS_ENTREE", deja)
        if len(rd.segs) == n1:
            rd.ajout("Évolution favorable, pas d'élément nouveau.", sep=" ")
        versions += _versionner(rd, "OBS_ENTREE", auteur, tc, t2, u_adm, r, base=versions[-1])
    # ---------------- recueil infirmier d'entrée
    r = np.random.default_rng(np.random.SeedSequence([seed, 17, S["pid"], 2]))
    if r.random() < P_NOTES["p_ide"]:
        tc = S["admit_h"] + r.uniform(0.3, 5)
        rd = _Redac(S["femme"], S["age"], r, abrev=r.random() < 0.3, horsvoc=tc >= h_test)
        rd.sit = L
        dd, hh = _date(debut, tc)
        rd.ajout(rd.choisir(T.ENTETES["RECUEIL_IDE"]) + f" - {dd} {hh}", sep="")
        if r.random() < 0.5:
            rd.ajout("Motif d'entrée : " + rd.choisir(T.MOTIFS[L["motif"]]["court"]))
        deja = set()
        rd.ajout("Lieu de vie / entourage :")
        _social(rd, L, "RECUEIL_IDE", deja)
        rd.ajout("Autonomie :")
        _fonctionnel(rd, L, "RECUEIL_IDE", deja, S["dep"], S["mob"])
        rd.ajout("Soins / précautions :")
        _besoins(rd, S, L, "RECUEIL_IDE", deja)
        if not (L["troubles_cognitifs"] or "troubles_cognitifs" in deja) and r.random() < 0.4:
            rd.ajout(rd.choisir(["Orienté{e}, cohérent{e}.", "Calme et coopérant{e}."]), sep=" ")
        rd.ajout(rd.choisir(["Risque de chute : élevé.", "Risque de chute : modéré.", "Risque escarre à surveiller.",
                             "Personne de confiance désignée."]))
        versions += _versionner(rd, "RECUEIL_IDE", "ide", tc, tc + r.uniform(0.2, 1.0), u_adm, r)
    return versions


def _versionner(rd, typ, auteur, tc, t_mod, unite, r, base=None):
    texte, faits = rd.texte()
    delai = r.lognormal(math.log(0.3), 0.6)
    if r.random() < P_NOTES["p_signature_tardive"]:
        delai += r.uniform(2, 8)
    t_dispo = t_mod + delai
    v = 1
    if base is not None:
        v = base["version"] + 1
        t_dispo = max(t_dispo, base["t_dispo"] + 1 / 60)
    return [dict(type=typ, auteur=auteur, version=v, t_creation=tc, t_modif=t_mod, t_dispo=t_dispo, unite=unite,
                 texte=texte, faits=faits)]


def generer(sim, journal, h0, h1, h_test, seed):
    """Notes de tous les séjours dont la décision tombe dans [h0 - 30 j, h1), coupées à h1.

    Renvoie (notes, annotations, latents) ; notes et annotations triées par disponibilité.
    """
    x = sim.x
    pat = x.pat
    lat = latents(x, seed)
    adm = {}
    for e in journal.events:
        if e["type"] == "ADMISSION" and e["pid"] not in adm:
            adm[e["pid"]] = (e["h"], e["u"], bool(e["payload"].get("heberge")))
    notes, ann = [], []
    for e in journal.events:
        if e["type"] != "DEMANDE_ADMISSION" or not (h0 - 24 * 30 <= e["h"] < h1):
            continue
        pid = e["pid"]
        a = adm.get(pid)
        admit_h = a[0] if (a is not None and a[0] < h1) else -1
        S = dict(pid=pid, src=int(pat["src"][pid]), dec_h=e["h"], admit_h=admit_h,
                 unite_home=x.unit_names[int(pat["unit"][pid])],
                 unite_admission=x.unit_names[a[1]] if admit_h >= 0 else None, heberge=bool(a and a[2]),
                 age=int(pat["age"][pid]), femme=bool(pat["femme"][pid]), dep=int(pat["dep"][pid]),
                 mob=hs.MOBILITE[int(pat["mob"][pid])], oxy=bool(pat["oxy"][pid]), iso=bool(pat["iso"][pid]),
                 img=bool(pat["img"][pid]), avis=bool(pat["avis"][pid]))
        for v in rediger_sejour(S, lat[pid], x.debut, h_test, seed):
            if v["t_dispo"] >= h1:
                continue
            nid = f"N{pid:06d}-{TYPES.index(v['type']) + 1}"
            notes.append(dict(note_id=nid, version=v["version"], remplace_version=v["version"] - 1 or None,
                              sejour_id=f"S{pid:06d}", type_note=v["type"], auteur=v["auteur"], unite=v["unite"],
                              t_creation=v["t_creation"], t_modification=v["t_modif"], t_disponible=v["t_dispo"],
                              texte=v["texte"], synthetique=True))
            ann.append(dict(note_id=nid, version=v["version"], sejour_id=f"S{pid:06d}", faits=v["faits"]))
    ordre = sorted(range(len(notes)), key=lambda i: (notes[i]["t_disponible"], notes[i]["note_id"], notes[i]["version"]))
    return [notes[i] for i in ordre], [ann[i] for i in ordre], lat
