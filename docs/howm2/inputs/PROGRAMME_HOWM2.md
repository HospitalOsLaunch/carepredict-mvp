# HOWM-2 — Programme de recherche proposé
## Identifiabilité d'abord, puis un world model qui s'adapte en contexte

**Date :** 16 novembre 2026.
**Statut :** document d'entrée, à consigner avec son empreinte. Il ne vaut autorisation que pour ce
que le message d'envoi autorise explicitement. Les statuts restent `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`. Données synthétiques seulement.
**Base :** paquets `HOWM1_P2_R1_END` et `HOWM1_P2_R1_FINAL` (commit `33e5b770`), rapport
`RAPPORT_HOWM1_R0_R1.md`.

---

## 1. Décision de recherche

R1 a comparé des réseaux à une référence explicite dans un monde où **l'on n'avait pas mesuré ce
qu'un modèle peut gagner à partir de l'historique public seul**. L'accord v1.1 le disait déjà :
la marge V_param + V_latent est « observée sous information privilégiée, pas la preuve d'un gain
exploitable par l'historique public ». HOWM-2 comble ce manque avant tout nouvel entraînement.

Règle du programme : **on n'entraîne aucun réseau sur un banc tant qu'un filtre de référence, qui
n'utilise que l'information publique, n'y bat pas la meilleure référence explicite d'une marge
pré-déclarée.** Ensuite seulement, on entraîne un modèle sur une distribution de mondes et on
mesure quelle part de cette marge il capte.

Résultat visé : un modèle pré-entraîné sur des mondes générés, qui s'adapte à un établissement
jamais vu en lisant son historique, sans réentraînement, avec une distance mesurée à l'optimum
bayésien. C'est le chantier « synthétique vers réel avec peu de données locales » sous une forme
réfutable.

---

## 2. Ce que R1 établit, et ce qu'il ne teste pas

Faits lus dans les paquets (à revérifier, ne pas les reprendre sur parole) :

| Fait | Source |
|---|---|
| Éléments d'entraînement par famille : soins 1 608 714 ; arrivées 73 728 ; autorisation 34 810 ; sortie prête 1 534 ; confirmation 832 ; nettoyage 217 ; transport 195 | `evidence/howm1/LOSS_SCALES.json` |
| L'avantage de B0-local à H24 vient de la sortie prête (−0,057), du transport (−0,084) et du nettoyage (−0,051), les familles les moins représentées | `RESULTS_R1_DEVTEST.json`, `LS_by_family_h24` |
| Meilleur gain VAL : 0,004 à 0,009 sur 7,215 ; la perte VAL remonte ensuite (jusqu'à 7,45 pour B2 à 1e-3) | `checkpoints/*/state.json` |
| La perte d'entraînement n'est pas journalisée : on ne peut pas distinguer non-apprentissage et sur-apprentissage | `src/hospitalos/howm/train.py` |
| T-INF-08 (entrées permutées) gagne 0,0088 en 60 pas, du même ordre que le meilleur gain réel ; échelles différentes (48 contre 32 établissements), donc indicatif | `DIAG_T_INF_08.json` |
| 32 établissements d'entraînement : 32 exemples pour apprendre à estimer un établissement | `PILOT.json` |
| Seul indice positif : H1 est le meilleur sur la confirmation (3,152 contre 3,166 pour B0-local à H24), famille où B0-local n'apporte rien | `RESULTS_R1_DEVTEST.json` |
| Marge décisionnelle faible : C_full 214,3 contre règle renforcée 200,2 ; oracle 236 | idem |

Ce que R1 ne teste pas : la capacité d'un modèle à estimer l'état caché, puisque rien n'établit
que cet état est inférable ; ni l'adaptation locale apprise, puisque 32 établissements ne
permettent pas de l'apprendre.

---

## 3. Mesure exploratoire du 16 novembre (hors registre)

**Nature :** faite hors de l'espace de travail, hors registre, sans torch, avec le générateur du
paquet FINAL. Elle motive le programme ; elle n'est pas une preuve. La tranche A doit la refaire
dans le registre, avec le score du protocole.

**Méthode :**
- 180 établissements REF neufs, clés `("HOWM1", "TRAIN", i)` pour i de 48 à 227 : 60 pour
  l'ajustement (48–107), 120 pour l'évaluation (108–227). Réserve, DEVTEST et DIAG-DEV non touchés.
- Familles transport et nettoyage seulement ; durées vraies complètes en pas de 15 min, sans
  censure ni retard de publication ; origines après 24 h.
- Estimateur local réécrit (mise à jour normale conjuguée de la médiane logarithmique), pas le
  B0-local gelé.
- Filtre exact : chaîne de Markov cachée à trois états (pas de m2, m2 normal, m2 lent), θ connu,
  a priori 0,5 / 0,4 / 0,1 ; les éléments en cours ne sont pas exploités.

**Résultat (log-vraisemblance négative moyenne, nats par élément) :**

| Niveau d'information | Transport (n = 3 147) | Nettoyage (n = 5 022) |
|---|---:|---:|
| Modèle commun | 2,256 | 2,083 |
| Recalibration explicite sur 24 h (3,6 et 6,1 éléments de contexte en moyenne) | 2,145 | 1,961 |
| Recalibration explicite sur tout le passé (16 et 26 éléments) | 2,096 | 1,937 |
| θ connu, régime inconnu (mélange stationnaire) | 2,063 | 1,913 |
| θ connu + filtre bayésien exact du régime | 2,053 | 1,893 |
| θ et régime connus | 1,962 | 1,800 |

Gain du filtre sur le mélange stationnaire, bootstrap par établissement : transport 0,010
[0,005 ; 0,016], nettoyage 0,019 [0,012 ; 0,027].

**Lecture :**
1. Le régime caché vaut 0,10 à 0,11 nat par élément, mais un filtre exact n'en récupère que 10 à
   17 %. Une équipe termine 4 à 6 éléments par 24 h alors qu'un ralentissement dure 6 h en
   moyenne. Des sondes au niveau du hasard sont donc attendues de tout modèle.
2. Au-dessus d'une recalibration sur 24 h, la marge accessible est de 0,07 à 0,09 nat sur ces deux
   familles, surtout par un contexte plus long. Rapportée à la moyenne sur sept familles, elle est
   de l'ordre de la demi-largeur de l'intervalle DEVTEST (0,02).
3. Conséquence : ouvrir H2 ou un latent stochastique dans le monde HOWM-1 tel quel risque un
   second résultat nul qui ne dirait rien de l'architecture.

Les trois scripts sont en annexe. Coût mesuré : 180 épisodes générés en 33 s sur un cœur (sans
`dataset.build`).

---

## 4. Définitions communes

**Échelle d'information.** Pour chaque famille et chaque horizon (1, 6, 24 h), avec le score de
R1 (cohorte publique, masque, censure, intervalles, retard de publication) :

| Niveau | Système | Information utilisée |
|---|---|---|
| L0 | B0-pool gelé | aucune information locale |
| L1 | B0-local gelé | fenêtre publique de 24 h |
| L2 | B0-local-long | même estimateur, tout le passé public de l'épisode |
| L3 | θ connu | paramètres vrais de l'établissement, état caché inconnu |
| L4 | **Filtre de référence public** | historique public seul ; connaît la structure et les lois a priori du générateur, ni θ, ni régime, ni indicateurs de mécanismes |
| L5 | État connu | θ et état caché vrais |

L3 et L5 sont privilégiés et servent de bornes. **L4 est le plafond de tout modèle appris sur
l'historique public.**

**Marge accessible.** M_pub(h) = L(meilleur de L1, L2) − L(L4), en nats par élément, même
agrégation que le critère principal de R1, intervalle à 95 % par bootstrap sur les établissements.

**Part de plafond captée.** ρ(h) = [L(L2) − L(modèle)] / [L(L2) − L(L4)].

**Validité du filtre de référence.** Un plafond faux invalide tout. Le filtre doit passer, avant
usage : (a) un contrôle de calibration par simulation (rangs uniformes sur des mondes tirés de
l'a priori) ; (b) L5 ≤ L4 ≤ L3 en moyenne, dans les marges d'erreur ; (c) égalité avec le calcul
exact là où il existe (chaîne cachée transport et nettoyage). S'il ne peut pas être validé pour
une famille, cette famille est rapportée entre bornes (L2, L5) et sort du critère.

---

## 5. Tranches

### Tranche A — Audit d'identifiabilité de HOWM-1 (aucun entraînement)

**But :** établir dans le registre si HOWM-1 peut départager un world model d'une référence
explicite recalibrée.

**Périmètre :**
1. Échelle L0 à L5 complète, toutes familles, horizons 1, 6 et 24 h, score de R1.
2. Établissements : TRAIN et VAL existants, plus 200 établissements REF et 100 DIAG neufs sous
   un espace de clés déclaré, distinct de toutes les partitions de G0. Les fichiers gelés en G0
   et en F1 ne sont pas modifiés ; code nouveau dans `src/hospitalos/howm2/`. Si une clé neuve
   exige de toucher un fichier gelé, s'arrêter et le signaler.
3. Marge décisionnelle accessible, sur les instants VAL : planificateur de R1 alimenté par L4,
   comparé à la règle renforcée, à C_full et à l'habituel.
4. Instrumentation manquante de R1, en passe avant seule sur les checkpoints livrés : perte
   TRAIN et perte VAL par famille, pour `best.pt` et `last.pt` des six exécutions. Cela tranche
   entre non-apprentissage et sur-apprentissage.
5. Deux défauts de mesure à expliquer : la couverture à 90 % de 0,72 à H1 commune à tous les
   systèmes, B0 compris ; l'indicateur « ne sait pas » constant à 1,0. Proposer une correction ou
   une redéfinition, sans l'appliquer aux résultats R1 livrés.

**Interdits :** aucune descente de gradient ; aucune lecture de la réserve ; DEVTEST et DIAG-DEV
ne sont pas relus ; aucune modification de v6, P5, `mvp/computer-use` ni des résultats R1.

**Règles de verdict, fixées ici :**
- δ_id = 0,02 nat (demi-largeur de l'intervalle DEVTEST de R1).
- `HOWM1_DISCRIMINANT` si la borne basse de l'intervalle à 95 % de M_pub est ≥ δ_id à H6 et à H24
  sur les 200 établissements REF neufs.
- `HOWM1_NON_DISCRIMINANT` si la borne haute est < δ_id à H6 et à H24.
- `HOWM1_INDETERMINE` sinon.
- Verdict séparé pour l'état caché : part de (L3 − L5) récupérée par L4, par famille.
- Verdict décisionnel : marge accessible ≥ 15 minutes-soignant (convention Δ_dec inchangée), ou non.

**Livrables :** `RAPPORT_HOWM2_A.md` ; `evidence/howm2/LADDER_A.json` ; validation du filtre ;
tableau des pertes TRAIN/VAL des checkpoints ; note sur la taille d'évaluation nécessaire pour
détecter M_pub/2 avec une puissance de 80 % ; paquet P2 et reçu de restauration.

**Budget proposé :** 3 600 s de temps mural, CPU, 0 €, registre séparé `BUDGET_LEDGER_HOWM2`.

**Point d'arrêt :** verdicts livrés. Rien d'autre n'est lancé.

### Tranche B — Monde v2 et porte d'identifiabilité (aucun entraînement)

**But :** un monde où l'état caché laisse des traces publiques, et où les décisions en dépendent.

**Leviers à instruire, chacun déclaré comme hypothèse d'ingénierie :**
- un pôle de 6 à 12 unités avec équipes partagées, pour des dizaines d'événements d'équipe par
  jour au lieu de 4 à 6 ;
- des régimes qui durent un poste ou plus et se manifestent sur plusieurs unités à la fois ;
- des épisodes de 4 à 8 semaines, avec dérive lente des paramètres et changements d'effectif ;
- des actions dont l'effet dépend de l'état caché.

**Garde-fous contre un monde taillé pour le modèle :**
- le monde est réglé avec le filtre de référence et les références explicites, **jamais avec un
  modèle appris** ;
- trois itérations de conception au plus, toutes consignées avec leurs mesures ;
- gel G0-v2 (générateur, a priori, partitions, réserve scellée) avant tout entraînement ;
- un second générateur indépendant G_alt-v2 est écrit avant le gel et servira au transfert,
  cette fois pour évaluer les modèles (écart § 1.7 de R1 à ne pas répéter).

**Porte G_ID :** borne basse de M_pub ≥ δ_id à H6 et H24 sur REF-v2, et marge décisionnelle
accessible (planificateur sur L4 moins règle renforcée) ≥ 15.

**Si aucune des trois itérations ne passe :** verdict `PAS_DE_MARGE_IDENTIFIABLE_A_CETTE_ECHELLE`.
C'est un résultat : les mécanismes explicites recalibrés suffisent à cette échelle, et la valeur
d'un world model est à chercher ailleurs (couplage, actions, échelle). Arrêt et décision humaine.

### Tranche C — Apprentissage en contexte sur une distribution de mondes

**Principe :** chaque pas d'entraînement tire des établissements neufs, vus une seule fois. Le
sur-apprentissage à un petit corpus disparaît, et le nombre d'établissements devient la variable
d'échelle.

**Systèmes, une variation à la fois :**
1. H1 inchangé, données à l'échelle : isole le facteur « données ».
2. H1 avec contexte long (tout le passé public au lieu de 24 h) : isole le facteur « contexte ».
3. C1, modèle de séquence sur les événements publics bruts, avec plongements par type et par
   entité : l'adaptation d'établissement (H2 du programme) réalisée en contexte.

**Références :** B0-pool, B0-local, B0-local-long, et le filtre L4 comme plafond.

**Exigences :** perte d'entraînement journalisée ; échantillonnage des origines et pondération
des familles fixés avant le gel ; au moins 3 graines au point d'échelle retenu ; loi d'échelle à
100, 1 000 et 10 000 établissements (100 000 sur décision de calcul).

**Critère principal, fixé avant lecture :** borne basse de l'intervalle à 95 % de
L(B0-local-long) − L(modèle) > 0 à H6 et à H24 sur les établissements d'évaluation neufs.
**Ambition :** ρ ≥ 0,5. La loi d'échelle est rapportée quel que soit le résultat.

**Secondaires :** calibration ; sondes de l'état caché comparées à l'AUC de la postérieure du
filtre L4, pas au hasard ; effets d'actions.

**Repères de coût (R1) :** pas d'entraînement H1 de 0,43 s pour 32 origines. 10 000 établissements
× 48 origines font 15 000 pas, soit environ 1,8 h par passage sur CPU. Au-delà, GPU à décider.

### Tranche D — Transfert, puis décisions

- Transfert sans réentraînement vers DIAG-v2 et vers les mondes G_alt-v2.
- Diagnostic décisionnel seulement si le critère principal de C est atteint, face à la règle
  renforcée, avec l'indicateur « ne sait pas » redéfini en A.
- La réserve v2 n'est lue qu'une fois, sur décision humaine, pour un résultat confirmatoire.

---

## 6. Ce qu'un échec apprendra

| Issue | Ce qu'on saura |
|---|---|
| A : non discriminant | R1 ne dit rien de H1 ; ni H2 ni un latent stochastique ne doivent être lancés dans HOWM-1 |
| A : discriminant | Le nul de R1 vient de l'apprentissage ; passer directement à C sur HOWM-1 |
| B : aucune itération ne passe | Pas de marge identifiable à cette échelle ; revoir l'ambition ou l'échelle |
| C : H1 à l'échelle suffit | Le facteur limitant était la donnée |
| C : seul C1 gagne | Le facteur limitant était la lecture en contexte |
| C : rien ne bat B0-local-long | La loi d'échelle dit si plus de mondes y changerait quelque chose |
| D : gain en REF, pas en G_alt | Le modèle a appris le générateur, pas l'hôpital |

---

## 7. Continuité

- Persistance P2 renforcée, sans push ; dépôt public, aucun push, merge ni rebase.
- La réserve HOWM-1 (48 + 16) reste scellée. R1 n'est pas confirmatoire et n'a pas à le devenir.
- JEPA, boucle fermée, P6, AJ-H restent fermés.
- Résultats favorables et défavorables livrés de la même façon.
- Aucun bénéfice hospitalier réel n'est revendiqué.

## 8. Décisions qui reviennent à l'utilisateur

1. Valeur de δ_id (proposé : 0,02 nat) et seuil d'ambition ρ (proposé : 0,5).
2. Budget de la tranche A (proposé : 3 600 s, CPU, 0 €).
3. Location d'un GPU pour la tranche C au-delà de 10 000 établissements.
4. Revue par l'advisor avant l'accord sur B et C.

---

## Annexe — Scripts exploratoires (non normatifs)

À consigner sous `docs/howm2/inputs/exploratory/`. Ils ne font pas partie du code du programme.
Usage : `python ladder.py <racine>/src 60 120` puis
`PYTHONPATH=. python filt.py <racine>/src`. numpy et scipy seulement.

### `ladder_lib.py`

```python
import sys, math
from hospitalos.howm import generator as G
G.PARTITION_SIZES["TRAIN"] = 100000
SIG = {"transport": 0.4, "cleaning": 0.35}
TH = {"transport": "tr_min", "cleaning": "cl_min"}
def items(i):
    spec = G.establishment("TRAIN", i); ep = G.generate(spec)
    out = {"transport": [], "cleaning": []}; tr, cl = {}, {}
    for ev, av, kind, subj, un, v in ep.observations:
        if kind == "transport_start": tr[subj] = ev
        elif kind == "transport_done" and subj in tr: out["transport"].append((tr.pop(subj), ev))
        elif kind == "cleaning_start": cl[subj] = ev
        elif kind == "cleaning_done" and subj in cl: out["cleaning"].append((cl.pop(subj), ev))
    res = {}
    for f, lst in out.items():
        team = "common" if spec.mech["m2_common"] else f
        reg = ep.regimes.get(team, [0] * 400) if spec.mech["m2"] else None
        res[f] = [(s, e, max(1, (e - s) // 15), (reg[min(s // 60, len(reg) - 1)] if reg else 0)) for s, e in lst]
    return spec, res
DATA = [items(i) for i in range(108, 228)]
```

### `ladder.py`

```python
"""Exploratory predictive ladder (numpy only) on fresh REF establishments (TRAIN keys >= 48).
Simplified: true event durations in 15-min ticks, complete items only, transport & cleaning."""
import sys, types, math, json, time
import numpy as np
sys.path.insert(0, sys.argv[1])
from hospitalos.howm import generator as G
from scipy.stats import norm
from scipy.optimize import minimize

G.PARTITION_SIZES["TRAIN"] = 100000
N_FIT, N_EVAL = int(sys.argv[2]), int(sys.argv[3])
SIG = {"transport": 0.4, "cleaning": 0.35}
TH = {"transport": "tr_min", "cleaning": "cl_min"}

def items(i):
    spec = G.establishment("TRAIN", i)
    ep = G.generate(spec)
    out = {"transport": [], "cleaning": []}
    tr, cl = {}, {}
    for ev, av, kind, subj, un, v in ep.observations:
        if kind == "transport_start": tr[subj] = ev
        elif kind == "transport_done" and subj in tr:
            out["transport"].append((tr.pop(subj), ev))
        elif kind == "cleaning_start": cl[subj] = ev
        elif kind == "cleaning_done" and subj in cl:
            out["cleaning"].append((cl.pop(subj), ev))
    res = {}
    for f, lst in out.items():
        team = "common" if spec.mech["m2_common"] else f
        reg = ep.regimes.get(team, [0] * 400) if spec.mech["m2"] else None
        rows = []
        for s, e in lst:
            k = max(1, (e - s) // 15)
            r = (reg[min(s // 60, len(reg) - 1)] if reg else 0)
            rows.append((s, e, k, r))
        res[f] = rows
    return spec, res

def lp(k, logmed, sig):  # discretised lognormal: K = max(1, ceil(T/15))
    k = np.asarray(k, float)
    hi = norm.cdf((np.log(15 * k) - logmed) / sig)
    lo = np.where(k > 1, norm.cdf((np.log(15 * np.maximum(k - 1, 1e-9)) - logmed) / sig), 0.0)
    return np.log(np.maximum(hi - lo, 1e-12))

t0 = time.time()
data = [items(i) for i in range(48, 48 + N_FIT + N_EVAL)]
print("generated", len(data), "establishments in", round(time.time() - t0), "s", file=sys.stderr)
fit, ev = data[:N_FIT], data[N_FIT:]
out = {}
for f in ("transport", "cleaning"):
    kf = np.array([r[2] for _, d in fit for r in d[f]])
    # M0 pooled: 2 params
    r0 = minimize(lambda p: -lp(kf, p[0], math.exp(p[1])).sum(), [4.0, -0.5], method="Nelder-Mead")
    mu0, s0 = r0.x[0], math.exp(r0.x[1])
    # Mtheta (theta known, regime unknown): global log-gain + sigma, 2 params
    thf = np.concatenate([np.full(len(d[f]), math.log(sp.theta[TH[f]])) for sp, d in fit])
    r1 = minimize(lambda p: -lp(kf, thf + p[0], math.exp(p[1])).sum(), [0.0, -0.8], method="Nelder-Mead")
    g1, s1 = r1.x[0], math.exp(r1.x[1])
    # prior variance of log-median between establishments (for the explicit local estimator)
    v_prior = np.var(thf)
    nll = {m: [] for m in ("pool", "local24h", "local_all_past", "theta", "theta+regime")}
    n_ctx = {"local24h": [], "local_all_past": []}
    for sp, d in ev:
        rows = sorted(d[f])
        lt = math.log(sp.theta[TH[f]])
        for j, (s, e, k, r) in enumerate(rows):
            if s < 24 * 60:  # same burn-in as the protocol origins
                continue
            nll["pool"].append(-lp(k, mu0, s0))
            nll["theta"].append(-lp(k, lt + g1, s1))
            nll["theta+regime"].append(-lp(k, lt + math.log(sp.mech["slow"] if r else 1.0), SIG[f]))
            for name, lo in (("local24h", s - 1440), ("local_all_past", -1)):
                past = [math.log(15 * (kk - 0.5)) for (ss, ee, kk, _) in rows if ee <= s and ss >= lo]
                n = len(past)
                # conjugate normal update of the log-median around the pooled centre
                w = v_prior / (v_prior + s1**2 / n) if n else 0.0
                m = mu0 + w * (np.mean(past) - mu0) if n else mu0
                sd = math.sqrt(s1**2 + (v_prior * (1 - w)))
                nll[name].append(-lp(k, m, sd if n else s0))
                n_ctx[name].append(n)
    out[f] = {"n_items": len(nll["pool"]), **{m: round(float(np.mean(v)), 4) for m, v in nll.items()},
              "mean_context_items": {m: round(float(np.mean(v)), 1) for m, v in n_ctx.items()},
              "pooled_fit": [round(mu0, 3), round(s0, 3)], "theta_fit": [round(g1, 3), round(s1, 3)]}
    # per-establishment bootstrap of key gaps
print(json.dumps(out, indent=1))
```

### `filt.py`

```python
"""Achievable part of the hidden regime: exact Bayes filter (theta known, regime & m2 flag hidden)."""
import sys, math, json
import numpy as np
sys.path.insert(0, sys.argv[1])
import ladder_lib as L
from scipy.stats import norm

def lp(k, logmed, sig):
    hi = norm.cdf((math.log(15 * k) - logmed) / sig)
    lo = norm.cdf((math.log(15 * (k - 1)) - logmed) / sig) if k > 1 else 0.0
    return math.log(max(hi - lo, 1e-12))

P01, P10 = 1 / 24, 1 / 6
T = np.array([[1, 0, 0], [0, 1 - P01, P01], [0, P10, 1 - P10]])  # states: no-m2, m2&normal, m2&slow
PI = np.array([0.5, 0.5 * 0.8, 0.5 * 0.2])
out = {}
for f in ("transport", "cleaning"):
    tot, tot_th, tot_or, n = 0.0, 0.0, 0.0, 0
    per = []
    for sp, d in L.DATA:
        rows = sorted(d[f]); lt = math.log(sp.theta[L.TH[f]]); slow = math.log(sp.mech["slow"])
        byh = {}
        for (s, e, k, r) in rows:
            byh.setdefault(s // 60, []).append((s, e, k))
        a = b = c = 0.0; m = 0
        for (s, e, k, r) in rows:
            if s < 1440: continue
            bel = PI.copy()
            H = s // 60
            for h in range(0, H + 1):
                for (s2, e2, k2) in byh.get(h, []):
                    if e2 <= s:
                        l0, l1 = math.exp(lp(k2, lt, L.SIG[f])), math.exp(lp(k2, lt + slow, L.SIG[f]))
                        bel = bel * np.array([l0, l0, l1]); bel /= bel.sum()
                if h < H: bel = bel @ T
            p_slow = bel[2]
            pr = (1 - p_slow) * math.exp(lp(k, lt, L.SIG[f])) + p_slow * math.exp(lp(k, lt + slow, L.SIG[f]))
            a += -math.log(pr)
            # static mixture with stationary prior (theta known, no filtering)
            ps = PI[2]
            b += -math.log((1 - ps) * math.exp(lp(k, lt, L.SIG[f])) + ps * math.exp(lp(k, lt + slow, L.SIG[f])))
            c += -lp(k, lt + (slow if r else 0.0), L.SIG[f]); m += 1
        if m: per.append((a / m, b / m, c / m, m))
        tot += a; tot_th += b; tot_or += c; n += m
    per = np.array(per); rng = np.random.default_rng(0)
    gaps = []
    for _ in range(2000):
        ix = rng.integers(0, len(per), len(per)); w = per[ix, 3]
        gaps.append(((per[ix, 1] - per[ix, 0]) * w).sum() / w.sum())
    out[f] = {"n": n, "theta_static_mixture": round(tot_th / n, 4), "theta_bayes_filter": round(tot / n, 4),
              "theta_regime_oracle": round(tot_or / n, 4),
              "filter_gain_ci95": [round(float(np.percentile(gaps, 2.5)), 4), round(float(np.percentile(gaps, 97.5)), 4)]}
print(json.dumps(out, indent=1))
```
