"""
Extracteur de référence (v0.4) : règles explicites, négation et hypothèse, extrait justificatif.

Rôle : donner un point de comparaison simple et traçable, et faire tourner la chaîne de bout en bout.
Un extracteur par modèle de langage devra faire mieux que lui, mesuré contre la même vérité annotée.

Le lexique ne couvre que les tournures de la banque PRINCIPALE (celles de la période d'entraînement) ;
il a été expurgé de toute tournure propre à la banque HORS_VOCABULAIRE. La période de test mêle ces
formulations inédites : l'écart entre périodes mesure la fragilité d'un extracteur à du vocabulaire
qu'il n'a pas vu. Sur la période d'entraînement, ses scores sont élevés par construction (même auteur,
mêmes gabarits) : ils vérifient la chaîne, pas la difficulté réelle du texte clinique.
"""
from __future__ import annotations

import re
import unicodedata

# Négation : le déclencheur doit précéder le terme dans la même phrase. Les apostrophes sont normalisées
# avant la recherche ; « pas d' » se termine sur l'apostrophe, d'où l'absence de \b final.
NEG = re.compile(r"(?:\bpas d'|\bpas de\b|\bpas d\b|\babsence d'|\babsence de\b|\bsans\b|\baucune?\b|\bni\b|"
                 r"\bnon\b|\bpersonne ne\b|\bne \w+ (?:plus|pas|aucun))", re.I)
HYP = re.compile(r"(\?|\bprobable|\bpossible|\bsuspicion|\bévoqu|\bà confirmer|\bà éliminer|\bnon explor|"
                 r"\bindéterminée|\bdd\b|\bà discuter|\bà envisager|\bnon exclu|\bsuspect)", re.I)
ANCIEN = re.compile(r"\(cf\.|données dossier|observation précédente|CRH 20", re.I)


def _norm(s):
    s = unicodedata.normalize("NFC", s)
    return s.replace("\u2019", "'").replace("\u02bc", "'").replace("\u00a0", " ").replace("\u202f", " ")


def phrases(texte):
    """Découpe en phrases : (position, phrase sans rubrique, phrase complète). Les rubriques « X : » sont détachées."""
    out = []
    for m in re.finditer(r"[^.\n]+[.\n]?", texte):
        brut = m.group(0)
        seg, deb = brut, m.start()
        mm = re.match(r"^\s*([A-ZÉÈa-zéèêàçô' /-]{2,40}) :\s*", seg)
        if mm and not re.search(r"\d", mm.group(1)):
            deb += mm.end()
            seg = seg[mm.end():]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            out.append((deb + lead, seg.strip(), brut.strip()))
    return out


R = {
    "vit_seul": [(r"\bvit seule?\b|\bseule? (?:à|au) dom", True),
                 (r"\bvit (?:avec|en couple|chez)", False)],
    "aidant_present": [(r"\b(?:fille|fils|nièce|neveu)\b.*\b(?:présente?|passe|proximité|joignable|référente?|assure)|\baidante? principale?", True),
                       (r"\b(?:pas d'|aucun )(?:entourage|aidant)|\bfamille éloignée", False)],
    "aides_existantes": [(r"\baide ménagère|\bpassage ide|\bide (?:quotidien|à dom|libéral)|\bportage des repas|\btéléalarme|"
                          r"\bssiad\b|\bauxiliaire de vie|\bapa en place|\baide à domicile 3", True),
                         (r"\b(?:pas|aucune?) d?'?aide", False)],
    "troubles_cognitifs": [(r"\btroubles? (?:cognitifs?|mnésiques?)|\balzheimer|\bdémence|\bdémentiel|\bconsultation mémoire|"
                            r"\bmms\b|\bdésorientation ancienne", True),
                           (r"\bcognition préservée", False)],
    "perte_autonomie_recente": [(r"\bperte d'autonomie|\bdéclin fonctionnel|\bchutes répétées|"
                                 r"\bne (?:se lève|fait) plus|\baffaiblie?", True),
                                (r"\bautonome jusqu", False)],
    "evaluation_sociale_demandee": [(r"\bévaluation sociale|\bassistante sociale|\bbilan social|\bsituation sociale", True)],
    "oxygene": [(r"\bsous o2|\bss o2|\bo2 \d|\bmise sous o2|\blunettes\b|\boxygénothérapie|\boxygène\b|(?<![a-z])o2\b", True),
                (r"\ben (?:air ambiant|aa)\b", False)],
}
AUTONOMIE = [(4, r"\bdépendante? pour tous|\bgrabataire|\bdépendance totale"),
             (3, r"\baide pour la toilette et l'habillage|\bdépendante? pour la toilette|\bmajorité des avq"),
             (2, r"\baide partielle|\baide pour la toilette du dos|\baide pour les courses"),
             (1, r"\bautonome pour les|\btotalement autonome|\bautonome, marche")]
MOBILITE = [("brancard", r"\bdeux personnes|\bfauteuil roulant|\bne marche plus|\bbrancard"),
            ("aide", r"\bcanne\b|\bdéambulateur|\baide d'une personne"),
            ("autonome", r"\bsans aide technique|\bdéambulation autonome|\bmarche seule?\b")]
ISOLEMENT = [("air", r"\bprécautions air|\btuberculose"),
             ("gouttelettes", r"\bgouttelettes"),
             ("contact", r"\bisolement contact|\bprécautions (?:complémentaires )?contact|\bbmr\b|\bblse\b|\bclostridi|\bgale\b")]
IMAGERIE = r"\b(?:tdm|scanner|angioscanner|uro-scanner|échographie|écho-doppler|irm|tep|radio|coronarographie|ett)\b"
ORIENTATION = [("EHPAD", r"\behpad"), ("SMR", r"\bsmr\b|\bssr\b"), ("domicile", r"\bretour à domicile")]
MOTIFS = [
    ("bpco", r"\bbpco\b|\beabpco|\bdécompensation respiratoire"), ("embolie", r"\bembolie|\bep\b"),
    ("epanchement", r"\bépanchement"), ("neoplasie_pulm", r"\bopacité|\bnodule|\bhémoptysie|\bnéoplasie pulmonaire|\bcarcinome bronchique"),
    ("grippe", r"\bgrippe|\bcovid|\bvirose|\bgrippal"), ("asthme", r"\basthme"),
    ("insuffisance_cardiaque", r"\bdécompensation cardiaque|\bica\b|\boap\b|\binsuffisance cardiaque aiguë|\bomi\b"),
    ("fa", r"\bfa rapide|\bpalpitations|\btachyarythmie|\bfa probable"), ("sca", r"\bsca\b|\bdouleur thoracique"),
    ("syncope", r"\bsyncope|\bperte de connaissance|\bpc brève"), ("bav", r"\bbav\b|\bbradycardie"),
    ("inhalation", r"\binhalation|\bfausse route"), ("pneumopathie", r"\bpneumopathie|\bpac\b|\btoux fébrile|\bdyspnée fébrile"),
    ("infection_urinaire", r"\bpyélonéphrite|\burinaire|\bmictionnelles|\bdouleur lombaire"),
    ("aeg", r"\baeg\b|\baltération de l'état général|\banorexie"), ("chute", r"\bchute"),
    ("confusion", r"\bconfusion|\bconfusionnel|\bdésorientation|\btroubles du comportement"),
    ("deshydratation", r"\bdéshydratation|\bhypernatrémie"), ("hyponatremie", r"\bhyponatrémie|\bna bas"),
    ("diabete", r"\bglycémi|\bhyperglyc|\bdiabétique"), ("erysipele", r"\bérysipèle|\bdermohypodermite|\bjambe rouge"),
    ("anemie", r"\banémie|\bhb basse"), ("malaise", r"\bmalaise|\blipothymie"),
]
PRIORITAIRES = ("inhalation",)
VARIABLES = ["motif", "incertitude_diagnostique", "vit_seul", "aidant_present", "aides_existantes", "troubles_cognitifs",
             "perte_autonomie_recente", "evaluation_sociale_demandee", "orientation_envisagee", "autonomie", "mobilite",
             "oxygene", "isolement", "imagerie_prevue", "avis_prevu"]


def _statut(ph, m_start, defaut_neg=False):
    avant = ph[:m_start]
    if HYP.search(ph):
        return "hypothese"
    if defaut_neg or NEG.search(avant[-40:] + " "):
        return "negation"
    return "documente"


def extraire(texte):
    """Renvoie {variable: dict(valeur, statut, extrait, debut, fin, source_ancienne)} ; absent = inconnu."""
    texte = _norm(texte)
    res = {}

    def poser(var, valeur, statut, deb, ph):
        res[var] = dict(valeur=valeur, statut=statut, extrait=ph, debut=deb, fin=deb + len(ph),
                        source_ancienne=bool(ANCIEN.search(ph)))

    for deb, ph, brut in phrases(texte):
        low = _norm(ph).lower()
        for var, regles in R.items():
            for motif, val in regles:
                m = re.search(motif, low)
                if not m:
                    continue
                if val is False and NEG.search(low[:m.start()][-40:]):
                    poser(var, True, "negation", deb, ph)  # négation d'une formulation négative : « personne ne vit avec »
                elif val is False:  # négation seulement si elle porte la formulation elle-même (« pas d'aide »)
                    poser(var, False, "negation" if NEG.match(m.group(0)) else "documente", deb, ph)
                elif NEG.search(low[:m.start()][-40:]):
                    poser(var, False, "negation", deb, ph)
                elif var == "troubles_cognitifs" and HYP.search(low):
                    poser(var, True, "hypothese", deb, ph)
                else:
                    poser(var, True, "documente", deb, ph)
                break
        for niv, motif in AUTONOMIE:
            if re.search(motif, low):
                poser("autonomie", niv, "documente", deb, ph)
                break
        for mob, motif in MOBILITE:
            if re.search(motif, low):
                poser("mobilite", mob, "documente", deb, ph)
                break
        lb = brut.lower()
        for typ, motif in ISOLEMENT:
            if re.search(motif, lb) and ("isol" in lb or "précaution" in lb):
                poser("isolement", typ, "documente", deb, ph)
                break
        if re.search(IMAGERIE, low) and re.search(r"demandée?|à prévoir|\bprévoir|programmer", low) and "avis" not in low:
            poser("imagerie_prevue", True, "documente", deb, ph)
        if re.search(r"\bavis\b", low) and re.search(r"à demander|demandée?|solliciter", low):
            poser("avis_prevu", True, "documente", deb, ph)
        if HYP.search(low):
            for val, motif in ORIENTATION:
                if re.search(motif, low) and ("envisag" in low or "discuter" in low or "projet" in low):
                    poser("orientation_envisagee", val, "hypothese", deb, ph)
                    break
    conc = re.search(r"Conclusion :\s*([^\n]+)", texte)
    if conc:
        ph, low = conc.group(0), conc.group(1).lower()
        trouves = [(m.start(), k) for k, motif in MOTIFS for m in [re.search(motif, low)] if m]
        if trouves:
            k = min(trouves)[1]
            specifiques = [x for _, x in trouves if x in PRIORITAIRES]
            if specifiques:  # « pneumopathie d'inhalation » : le motif le plus spécifique l'emporte
                k = specifiques[0]
            st = "hypothese" if HYP.search(low) else "documente"
            poser("motif", k, st, conc.start(), ph)
            res["incertitude_diagnostique"] = dict(valeur=st == "hypothese", statut="documente", extrait=ph,
                                                   debut=conc.start(), fin=conc.start() + len(ph), source_ancienne=False)
    return res


def evaluer(notes, annotations, h_test):
    """Compare l'extraction à la vérité annotée, par variable et par période (avant / pendant le test).

    Détection : la variable est trouvée là où la vérité la mentionne. Triplet : variable, valeur et statut
    tous exacts ; c'est la mesure qui compte (une valeur inversée est une détection, pas un triplet exact).
    """
    import collections
    stats = {p: collections.defaultdict(collections.Counter) for p in ("avant_test", "periode_test")}
    perimes = collections.Counter()
    for n, a in zip(notes, annotations):
        per = "periode_test" if n["t_creation"] >= h_test else "avant_test"
        ext = extraire(n["texte"])
        gold = {f["variable"]: f for f in a["faits"]}
        if "motif" in gold:
            gold["incertitude_diagnostique"] = dict(valeur=gold["motif"]["statut"] == "hypothese", statut="documente",
                                                    correct="vrai")
        for v in VARIABLES:
            g, e = gold.get(v), ext.get(v)
            c = stats[per][v]
            if g and e:
                c["vp"] += 1
                c["valeur_ok"] += e["valeur"] == g["valeur"]
                c["triplet_ok"] += e["valeur"] == g["valeur"] and e["statut"] == g["statut"]
                if g.get("correct") in ("faux", "perime"):
                    perimes["extraits"] += 1
                    perimes["signales_source_ancienne"] += e["source_ancienne"]
            elif g:
                c["fn"] += 1
            elif e:
                c["fp"] += 1
    out = {}
    for per, d in stats.items():
        out[per] = {}
        for v in VARIABLES:
            c = d[v]
            vp, fn, fp = c["vp"], c["fn"], c["fp"]
            out[per][v] = dict(mentions_verite=vp + fn, mentions_extraites=vp + fp,
                               rappel_triplet=round(c["triplet_ok"] / max(vp + fn, 1), 3),
                               precision_triplet=round(c["triplet_ok"] / max(vp + fp, 1), 3),
                               rappel_detection=round(vp / max(vp + fn, 1), 3),
                               precision_detection=round(vp / max(vp + fp, 1), 3),
                               valeurs_inversees=int(vp - c["valeur_ok"]))
    out["faits_faux_ou_perimes_extraits_comme_vrais"] = dict(perimes)
    return out


PROVENANCE = ("_source", "_h_source", "_note_id_source", "_version_source",
              "_ts_redaction_source", "_extrait_source")


def mentions_nouvelles(note, precedente=None):
    """Extrait uniquement le texte introduit par cette version en ajout seul.

    Un « RAS » ne réaffirme pas implicitement tous les faits recopiés. Une phrase
    explicitement répétée dans le complément est en revanche une nouvelle mention.
    Les positions restent exprimées dans le texte complet normalisé de la version.
    """
    texte = _norm(note["texte"])
    version = int(note["version"])
    if precedente is None:
        if version != 1:
            raise ValueError("Première version manquante : impossible de dater les mentions")
        debut = 0
    else:
        ancien = _norm(precedente["texte"])
        if (note["note_id"] != precedente["note_id"]
                or note["sejour_id"] != precedente["sejour_id"]
                or version != int(precedente["version"]) + 1
                or not texte.startswith(ancien)):
            raise ValueError("Historique non consécutif ou réécriture : seul l'ajout daté est pris en charge")
        debut = len(ancien)
    nouveaux = extraire(texte[debut:])
    for fait in nouveaux.values():
        fait["debut"] += debut
        fait["fin"] += debut
    return nouveaux


def etat_documentaire(lignes, notes=None):
    """État documentaire par séjour et par variable, mis à jour à chaque version de note disponible.

    lignes : sorties d'extraction, une par version (sejour_id, note_id, version, type_note, h_disponible,
    h_utilisable, <variable>, <variable>_statut). Règles :
    - une absence de mention n'efface jamais une valeur connue ;
    - seules les mentions du texte nouvellement ajouté actualisent la valeur et sa source ;
    - h_source est la disponibilité de la version qui introduit la mention, pas celle
      d'une version ultérieure qui la recopie ; ts_redaction_source date cette rédaction,
      sans prétendre dater l'événement clinique sous-jacent ;
    - chaque note garde sa dernière valeur ; « conflit » signale que les notes disponibles divergent.
    Renvoie une ligne par version appliquée, avec l'état complet après application.

    notes est le journal observé (jamais les annotations privilégiées). Sans ce journal,
    seules des versions initiales sont acceptées : le CSV d'extraction seul ne permet
    pas de distinguer un fait recopié d'une réaffirmation explicite.
    """
    ordre = sorted(lignes, key=lambda r: (r["h_disponible"], r["note_id"], r["version"]))
    index = {(n["note_id"], int(n["version"])): n for n in notes} if notes is not None else None
    etats, precedentes, out = {}, {}, []
    for r in ordre:
        nid, version = r["note_id"], int(r["version"])
        if index is not None:
            note = index[(nid, version)]
            if (note["sejour_id"] != r["sejour_id"]
                    or abs(note["h_disponible"] - r["h_disponible"]) > 1e-6
                    or r["h_utilisable"] < r["h_disponible"]):
                raise ValueError("Extraction et note observée non alignées")
            nouveaux = mentions_nouvelles(note, precedentes.get(nid))
            precedentes[nid] = note
        else:
            if version != 1:
                raise ValueError("Le texte des versions est requis pour fusionner les compléments")
            note = {}
            nouveaux = {v: dict(valeur=r[v], statut=r[v + "_statut"], extrait=None)
                        for v in VARIABLES if r.get(v) is not None}
        e = etats.setdefault(r["sejour_id"], {})
        for v, fait in nouveaux.items():
            s = e.setdefault(v, dict(sources={}))
            s["sources"][nid] = fait["valeur"]
            s.update(valeur=fait["valeur"], statut=fait["statut"], source=r["type_note"], h=r["h_disponible"],
                     note_id=nid, version=version, redaction=note.get("ts_modification"), extrait=fait["extrait"])
        ligne = dict(sejour_id=r["sejour_id"], h_utilisable=r["h_utilisable"], h_disponible=r["h_disponible"],
                     note_id=r["note_id"], version=r["version"], type_note=r["type_note"], split=r["split"])
        for v in VARIABLES:
            s = e.get(v)
            ligne[v] = s["valeur"] if s else None
            ligne[v + "_statut"] = s["statut"] if s else None
            ligne[v + "_source"] = s["source"] if s else None
            ligne[v + "_h_source"] = round(s["h"], 6) if s else None
            ligne[v + "_note_id_source"] = s["note_id"] if s else None
            ligne[v + "_version_source"] = s["version"] if s else None
            ligne[v + "_ts_redaction_source"] = s["redaction"] if s else None
            ligne[v + "_extrait_source"] = s["extrait"] if s else None
            ligne[v + "_n_notes"] = len(s["sources"]) if s else 0
            ligne[v + "_conflit"] = (len({str(x) for x in s["sources"].values()}) > 1) if s else False
        out.append(ligne)
    return out
