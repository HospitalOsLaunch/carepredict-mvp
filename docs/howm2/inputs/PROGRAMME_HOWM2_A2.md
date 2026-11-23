# HOWM-2 — Tranche A′ : l'état présent comme état caché

**Date :** 16 novembre 2026.
**Statut :** document d'entrée, à consigner avec son empreinte. Il ne vaut autorisation que pour ce
que le message d'envoi autorise explicitement. Statuts inchangés : `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`. Données synthétiques seulement.
**Base :** tranche A close (`RAPPORT_HOWM2_A.md`, paquet `HOWM2_P2_A_FINAL.zip`, sha256
`6826601c4a46143a679637e3df1b1ce282a6aa0022bd96628378e0f777d02b87`, commit `c9969725`).
**Effet sur l'accord C1 :** `ACCORD_HOWM2_C1_A_ADOPTER.md` n'est **pas** adopté. Il reste en
attente jusqu'au point d'arrêt de A′.

---

## 1. Pourquoi A′

L'échelle de A n'a testé qu'un état caché : le régime de ralentissement (m2). Elle a conclu,
correctement, qu'il n'est pas récupérable. Mais trois mesures de A désignent un **autre** état
caché, que ni L4 ni H1 n'estiment : **l'état présent, masqué par le retard de publication.**

| Fait de A à revérifier | Source |
|---|---|
| Planificateurs partis de l'état public : L4 5 002,8 ; C_param 5 007,0 ; C_pub_snap 4 999,5 (écart ≈ 8) | `DECISION_A.json` |
| C_full, parti de l'état vrai : 4 945,2, soit ≈ 58 de mieux que L4 ; règle renforcée 4 974,1 | idem |
| V_latent = +61,8 au précontrôle HOWM-1, attribué à l'état courant vrai (régime et événements non publiés) | `evidence/howm1/PRECHECK.json` |
| Le régime m2 n'apporte presque rien de récupérable (π ≤ 0) | `LADDER_A.json`, § 5 du rapport A |
| Couverture à 90 % à 1 h : 0,573 depuis l'état public, 0,877 depuis l'état vrai | `DIAG_COVERAGE.json` |
| Retard de publication tiré par établissement : 0 à 60 min (REF), 0 à 120 min (DIAG) | `generator.py`, `theta["lag_min"]` |

Hypothèse de travail : **l'essentiel de l'écart entre C_full et les planificateurs publics vient
de l'état présent, et une partie peut être inférée de l'historique public** (lois de retard et
hasards). C'est la fonction d'estimation d'état d'un world model. Si cette part dépasse le seuil
décisionnel, HOWM-1 suffit pour tester un world model et la tranche B devient optionnelle.

Deuxième question : la marge M_pub de A (0,141 nat à H24) est la moyenne simple de quatre
familles, dont deux portent presque tout (ready 0,242 ; confirmation 0,299 ; soins 0,021 ;
arrivées 0,001). Une partie peut tenir à des faiblesses de spécification de la référence
explicite L2, et non à ce qu'un modèle appris peut apporter. Il faut le savoir avant de fixer la
référence de C1.

Troisième question : A note qu'OBJ-LEX-1 retient le plan le plus simple à 15 près et choisit
souvent un plan sans coordination depuis l'état public, alors que la règle coordonne toujours. La
défaite de L4 face à la règle peut donc tenir en partie à la **règle de sélection**, et non à
l'information.

---

## 2. Définitions

**État public S_pub(t).** L'état reconstruit par `history.PublicStream.to_engine(t)` à partir des
observations disponibles à t (`available_at ≤ t`), comme en R1 et en A.

**État vrai S_true(t).** L'état du moteur de vérité à t.

**Événements en attente E_pend(t).** Événements survenus (`event_min ≤ t`) mais non publiés
(`avail_min > t`). C'est la seule différence entre S_pub et S_true à loi et θ donnés, en dehors
du régime.

**L4-N (filtre de l'état présent).** Système public seulement. Il tire des réalisations de
S_true(t) sachant l'historique public :
1. postérieure de θ, du mécanisme et du régime : celle de L4, inchangée ;
2. postérieure du retard de publication de l'établissement, inférée des paires
   (`event_min`, `avail_min`) déjà publiées, avec la loi de retard du générateur ;
3. pour chaque élément public en cours, probabilité que son événement de fin soit survenu sans
   être publié, par conditionnement sur la non-publication à t (hasard de l'élément × loi de
   retard) ; tirage du moment de survenue ;
4. même traitement pour les arrivées et les autres événements dont le générateur peut retarder
   la publication ;
5. application des événements tirés à S_pub(t) par l'opérateur explicite, avec ses
   préconditions. Un tirage qui viole une précondition est rejeté et compté, jamais corrigé.

Seules les lois et a priori du générateur sont utilisés, comme pour L4. Aucune grandeur privée
(θ vrai, régime vrai, retard vrai, journal de vérité) n'entre dans L4-N.

**L5-N (témoin privilégié).** Même construction avec θ, régime et retard vrais. Il sert de témoin
positif de calibration, jamais de système comparé.

**Part récupérée de l'état présent.**
κ = [U(L4) − U(L4-N)] / [U(L4) − U(C_full)], sur les mêmes instants et les mêmes tirages.

**L2c (référence explicite corrigée).** B0-local-long (L2) avec deux corrections seulement :
- confirmation séparée en deux familles internes, transport et offre du pool, chacune avec sa
  loi de base, son profil horaire et son intercept local ;
- offres du pool incluses dans la fenêtre locale (la fenêtre de B0-local ne compte aujourd'hui
  que les confirmations de transport : `dataset._window`, dictionnaire `starts`).

τ choisis sur TRAIN 0–31 avec la grille de B0, comme pour L2. Rien d'autre ne change. Le score
reste celui de la famille « confirmation » du protocole R1 (les deux familles internes sont
réunies au score).

---

## 3. Validation de L4-N, avant tout usage

Un filtre faux invalide tout. L4-N doit passer, dans cet ordre :

- **(N-c) Identité.** Sur un monde de test où tous les retards sont nuls, L4-N = L4 à l'octet près
  (aucun événement en attente). Test automatisé.
- **(N-o) Ordre.** Sur les instants de décision, la NLL de l'état vrai sous L4-N est meilleure
  que sous l'état public seul (masse ponctuelle sur S_pub), intervalle à 95 % hors de zéro. Sinon,
  L4-N n'estime rien.
- **(N-a) Calibration, règle de l'addendum 2.** Par type d'événement en attente, nombre
  d'événements en attente à t : un PIT randomisé par instant, seuil D ≤ max(0,02 ; 1,63/√n), L5-N
  comme témoin positif. Une famille où L5-N échoue aussi est signalée comme limite du test, pas
  comme échec de L4-N.

Si (N-c) ou (N-o) échoue, s'arrêter et poser la question. Si (N-a) échoue pour un type, le
rapporter et poursuivre en le signalant dans chaque verdict concerné.

---

## 4. Mesures

### 4.1 Décision (A2.DEC)

**Instants :**
- les 48 instants VAL de A (comparabilité) ;
- 48 instants neufs : `HOWM2_REF` indices 0 à 11, jour 5, 07, 11, 15 et 19 h, mêmes règles que
  le précontrôle HOWM-1. Ces établissements ont servi à l'échelle de A, jamais à une décision.

**Dispositif :** celui de A.DEC, inchangé : 16 candidats, OBJ-LEX-1, M = 8, clés 201–208, U
d'évaluation du précontrôle pour VAL, calculés de la même façon pour les instants neufs.

**Systèmes :** habituel, règle renforcée, planificateur L4, **planificateur L4-N**, C_param,
C_pub_snap, C_full, oracle.

**Critère principal :** marge_N = U(règle) − U(L4-N) sur les 96 instants (positif = L4-N meilleur),
bootstrap par grappes d'établissement, B = 2 000.
- `NOWCAST_MARGE_GE_15` si la borne basse de l'IC à 95 % est ≥ 15 ;
- `NOWCAST_MARGE_LT_15` si la borne haute est < 15 ;
- `NOWCAST_INDETERMINE` sinon.

Rapportés aussi : marge_N sur VAL seul et sur les instants neufs seuls ; κ avec IC ; L4-N contre
L4 apparié ; nombre de tirages rejetés par l'opérateur.

**Diagnostic secondaire, pré-déclaré, sans effet sur le verdict :** même comparaison avec une
sélection par U minimal pur (sans tolérance lexicographique de 15), pour L4, L4-N et C_full. Il
mesure la part de la défaite de L4 qui tient à OBJ-LEX-1. La règle renforcée n'est pas modifiée.

### 4.2 Prévision depuis l'état présent (A2.COV)

Mêmes cibles, origines et clés que `DIAG_COVERAGE.json` (VAL, 48 origines de décision, M = 16),
avec trois départs : public, **L4-N**, vrai.

Rapportés à 1, 6 et 24 h : couverture à 50 % et 90 % ; couverture hors intervalles dégénérés ;
KS du PIT randomisé ; part de l'écart public → vrai récupérée par L4-N. Descriptif seulement.

### 4.3 Décomposition de M_pub (A2.L2C)

Sur les 200 `HOWM2_REF`, protocole de score de A inchangé :
- tableau par famille et par horizon : L0, L1, L2, **L2c**, L3, L4, L5 ;
- M_pub recalculé avec la meilleure de {L2, L2c} comme référence, même règle de bootstrap que A,
  avec un choix refait à chaque réplique ;
- ρ_f = part de l'écart (meilleure de L2, L2c) − L4 qu'il reste à capter, par famille.

**Règle pour C1, fixée ici :** la référence du critère principal de C1 devient la meilleure de
{L2, L2c}. Si M_pub recalculé a une borne basse < δ_id = 0,02 à H6 ou à H24, le signaler : C1
ne pourrait plus départager.

Le verdict `HOWM1_DISCRIMINANT` de A n'est pas modifié ; A2.L2C est une mesure supplémentaire.

---

## 5. Ce qui suit le point d'arrêt (rédigé, non exécuté)

Une seule proposition bornée, adaptée aux verdicts, avec conception, note normative, JSON
d'expérience, matrice de tests, plan de calcul et texte d'accord :

| Verdict A2.DEC | Proposition |
|---|---|
| `NOWCAST_MARGE_GE_15` | **HOWM2-N** : un modèle appris d'estimation de l'état présent sur HOWM-1, entraîné sur un flux d'établissements neufs, évalué en ρ_N = part de (L4 − L4-N) récupérée, en prévision puis en décision. B reste reporté. |
| `NOWCAST_MARGE_LT_15` | **C1 amendé** (§ 6) et proposition séparée de B, avec la mesure de κ comme justification. |
| `NOWCAST_INDETERMINE` | Note de puissance (nombre d'instants nécessaire) et **C1 amendé** ; pas de nouveau modèle de décision. |

---

## 6. Amendements de C1, valables quel que soit le verdict

1. **C.2 doit isoler une seule variation.** H1 n'utilise aujourd'hui aucune statistique de
   fenêtre (seule `b2_window` existe dans `nets.py`). Donner à C.2 les statistiques de L2 ajoute
   des entrées en plus du contexte long ; et si C.2 apprend une correction au-dessus de L2, battre
   L2 devient presque automatique. Scinder en C.2a (contexte long seul) et C.2b (statistiques
   explicites en entrée), ou n'en garder qu'une, et le déclarer.
2. **Référence du critère :** la meilleure de {L2, L2c} (§ 4.3).
3. **Lecture principale :** ρ par famille, à côté du critère « battre la référence ».
4. **Budget par paliers :** variante courte (100 et 1 000) d'abord ; le point 10 000 n'est lancé
   que si la perte CVAL baisse entre 100 et 1 000 au-delà de la dispersion entre graines. C'est
   une échelle de réduction déclarée, non une question nouvelle.

---

## 7. Interdits

- Aucune descente de gradient, aucun réseau entraîné.
- Ni la réserve HOWM-1, ni DEVTEST, ni DIAG-DEV ne sont lus.
- Aucun fichier gelé en G0 ou F1, ni v6, P5, `mvp/computer-use`, ni les résultats R1 et A livrés
  ne sont modifiés. Code nouveau dans `src/hospitalos/howm2/`.
- Les règles de validation et de verdict ci-dessus sont consignées au registre **avant** toute
  mesure. Un écart d'implémentation nécessaire est consigné en addendum avant la mesure
  concernée, jamais après.
- Ni B, ni C1, ni HOWM2-N ne sont exécutés.
- Push, merge, rebase : non. Le dépôt est public.
- JEPA, boucle fermée, P6, AJ-H : fermés.

---

## Annexe — Mesure exploratoire sur la confirmation (non normative)

Faite hors registre le 16 novembre, avec le générateur du paquet R1 FINAL. 180 établissements
neufs (clés TRAIN 48 à 227 ; 60 d'ajustement, 120 d'évaluation), durées complètes en pas de
15 min, sans censure ni retard de publication. NLL moyenne (nats par élément) :

| Modèle | NLL |
|---|---:|
| Loi commune aux deux types | 2,750 |
| Loi séparée par type (transport, offre) | 2,715 |
| θ de l'établissement connu | 2,395 |

Lecture : séparer les types n'explique qu'environ 10 % de l'écart ; l'essentiel tient à
l'inférence de θ, que la fenêtre locale de B0 réalise mal. A2.L2C le mesure dans le protocole.

```python
"""Confirmation family: how much of L2->L3 is B0 pooling two kinds (transport vs pool offer)?"""
import sys, math, json
import numpy as np
sys.path.insert(0, sys.argv[1])
from hospitalos.howm import generator as G
from scipy.stats import norm
from scipy.optimize import minimize
G.PARTITION_SIZES["TRAIN"] = 100000
def lp(k, m, s):
    k = np.asarray(k, float)
    hi = norm.cdf((np.log(15 * k) - m) / s)
    lo = np.where(k > 1, norm.cdf((np.log(15 * np.maximum(k - 1, 1e-9)) - m) / s), 0.0)
    return np.log(np.maximum(hi - lo, 1e-12))
def items(i):
    sp = G.establishment("TRAIN", i); ep = G.generate(sp)
    req, out = {}, []
    for ev, av, kind, subj, un, v in ep.observations:
        if kind == "transport_requested": req[("T", subj)] = ev
        elif kind == "offer_requested" and v.get("source") == "pool": req[("O", subj)] = ev
        elif kind == "transport_accepted" and ("T", subj) in req:
            s = req.pop(("T", subj)); out.append(("T", s, max(1, (ev - s) // 15)))
        elif kind == "offer_confirmed" and ("O", subj) in req:
            s = req.pop(("O", subj)); out.append(("O", s, max(1, (ev - s) // 15)))
    return sp, out
D = [items(i) for i in range(48, 228)]
fit, ev = D[:60], D[60:]
k = lambda dd, kind=None: np.array([x[2] for _, d in dd for x in d if kind is None or x[0] == kind])
th = {"T": ("conf_tr_min", 0.6), "O": ("conf_off_min", 0.5)}
r = minimize(lambda p: -lp(k(fit), p[0], math.exp(p[1])).sum(), [4.3, -0.3], method="Nelder-Mead").x
pk = {}
for kd in "TO":
    pk[kd] = minimize(lambda p: -lp(k(fit, kd), p[0], math.exp(p[1])).sum(), [4.3, -0.3], method="Nelder-Mead").x
res = {"pooled": [], "split_by_kind": [], "theta_known": []}
cnt = {"T": 0, "O": 0}
for sp, d in ev:
    for kd, s, kk in d:
        if s < 1440: continue
        cnt[kd] += 1
        res["pooled"].append(-lp(kk, r[0], math.exp(r[1])))
        res["split_by_kind"].append(-lp(kk, pk[kd][0], math.exp(pk[kd][1])))
        name, sig = th[kd]
        res["theta_known"].append(-lp(kk, math.log(sp.theta[name]), sig))
print(json.dumps({"n": cnt, **{m: round(float(np.mean(v)), 3) for m, v in res.items()},
                  "fitted_medians_min": {kd: round(math.exp(pk[kd][0]), 1) for kd in "TO"}}, indent=1))
```
