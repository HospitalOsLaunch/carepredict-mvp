# Rapport — clôture B-FRAG 2 et pilote d'apprentissage des conséquences des actions

**Décision** n° 8, 17 novembre 2026.

**Statuts inchangés :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Nature des résultats.** Benchmark **synthétique**. Aucune conclusion clinique.

**Statut du pilote :** **EVALUATION_FINALE_EXECUTEE**. C'est une campagne unique, faite après le gel, sur
16 structures neuves ; aucun résultat n'est exclu. La comparaison principale est **INDETERMINE**.

**Connaissance antérieure.** Le pilote a été conçu après les résultats de B-FRAG 2 ; ce n'est pas une
hypothèse formulée avant.

**Sources :**

- `PROTOCOLE_PILOTE_W.md` (registre `pilot_protocol`, avant les données d'apprentissage) ;
- `FREEZE_PILOT.json` (registre `pilot_freeze`, avant l'évaluation finale) ;
- `evidence/howm2_bfrag2w/RESULTS_PILOT_W.json`.

## 1. Clôture B-FRAG 2 (sans réécriture)

- **Addendum** `ADDENDUM_BFRAG2_CLOTURE.md`. Il précise :
  - la portée de l'équivalence de l'historique (marge ±0,02 fixée avant CONF, registre #71, #88 puis #90) ;
  - « aucune dégradation statistiquement mise en évidence » ;
  - qu'O n'est ni équivalent ni optimal ;
  - que la meilleure action a posteriori est un minimum empirique ;
  - que plusieurs causes sont possibles pour le déficit de F ;
  - que la stabilité Monte-Carlo était antérieure à la correction du calendrier.

  Le rapport, les gels et les verdicts historiques sont intacts (test W7).
- **Décomposition du gain F − R1** (CONF-S enregistrée, aucune nouvelle évaluation) : la somme des contributions
  vaut exactement 253,984375.

| Groupe | Contribution | Part |
|---|---|---|
| F coordination, R1 renfort | 96,4 | 38 % |
| R1 coordination, F renfort | 84,3 | 33 % |
| Même ressource, autre créneau | 73,5 | 29 % |
| Même action (35 décisions) | 0 | 0 % |

  Lecture **descriptive** : l'écart n'est pas porté par la seule action de coordination.
- **Vérification numérique sur DEV** (`VERIFICATION_NUMERIQUE_BFRAG2.md`) :
  - tous les résultats comparatifs B-FRAG 2 utilisent Mr = 32, Md = 32 et E = 8 ;
  - le choix de F est stable à Md = 32 (4/4) ; **celui de R1 ne l'est pas** (3/4, regret max 0,012 pour une
    tolérance de 0,005) ;
  - à E = 8, l'écart entre deux actions **pour une décision isolée** peut changer de signe entre deux jeux de
    futurs.

## 2. Pilote : données et modèles

- **Données.**
  - TRAIN : 200 structures `BF2_TRAIN`, 1 origine de décision chacune, 10 actions × 2 futurs vrais communs,
    soit 4 000 trajectoires de 84 pas de 2 h. Coût : 153 s de mur, 569 s de CPU (registre #137).
  - VAL : VAL-S B-FRAG 2 enregistrée (18 structures, 54 décisions, E = 8).
- **D** : base Ridge plus effet apparié. Les 4 configurations sont choisies sur VAL ; la retenue est **HGB de
  profondeur 5** (perte de décision VAL 32 393).
- **W** : encodeur MLP, GRU partagé sur 84 pas, têtes d'état (30 variables) et de coûts de pas.
  - Taille : **26 144 paramètres**.
  - Les 3 graines se sont **toutes arrêtées par patience**, et non par le plafond de 140 s :

| Graine | Époques | Checkpoint retenu (VAL) | Durée |
|---|---|---|---|
| 0 | 44 | 24 | 34 s |
| 1 | 34 | 14 | 28 s |
| 2 | 78 | 58 | 65 s |

  - Les pertes TRAIN baissaient encore (perte des effets de 1,0 à environ 0,1). La perte de décision VAL
    oscillait sans tendance, entre 32 333 et 33 182.
  - **Aucune convergence n'est revendiquée.** La règle d'arrêt était fixée d'avance ; elle n'a pas été changée
    après observation.
  - Système principal : ensemble des 3 graines (diagnostic VAL publié dans `FREEZE_PILOT.json`).
- **Défauts trouvés avant l'évaluation et consignés :**
  - chargement des modèles D, révélé par l'essai de fumée sur DEV (#145), corrigé sans changer les modèles
    (`CORRECTION_D_LOADING.json`), puis gel refait ;
  - deux exécutions de tests en échec (#129 : 2 tests ; #131 : 1 test), dues à des erreurs dans les tests eux-mêmes.

## 3. Évaluation finale (16 structures neuves `BF2W_CONF` × 3 épisodes, 48 décisions, E = 12 futurs neufs)

| Politique | Attente moyenne (pm, 168 h) |
|---|---|
| Aucune action | 61 837 |
| Règle historique | 60 390 |
| W (ensemble) | 59 521 |
| D | 59 156 |
| R1 (Md = 32) | 58 848 |
| **F (Md = 32)** | **58 595** |
| Min a posteriori (diagnostic rétrospectif) | 58 451 |

**Comparaison principale (préenregistrée, unique) : W − D = −365 pm [−1 492 ; +255] (IC 95 % apparié,
16 structures) → `INDETERMINE`.**

- L'estimation est **défavorable à W**, mais l'intervalle n'exclut ni une perte ni un gain.
- **Ce n'est pas une équivalence.**
- W et D font le même choix dans 69 % des décisions.

**Comparaisons descriptives** (IC 95 %, sans correction ; un écart positif est en faveur de la seconde
politique) :

| Comparaison | Écart [IC 95 %] |
|---|---|
| Aucune − W | **+2 316** [667 ; 4 920] |
| Historique − W | +869 [−134 ; 2 767] |
| R1 − W | −674 [−2 108 ; +54] |
| **F − W** | **−926** [−2 539 ; −101] |
| **F − D** | **−561** [−1 087 ; −174] |
| **R1 − D** | **−308** [−653 ; −39] |
| **R1 − F** | **+252** [99 ; 483] |
| Graines W 0, 1, 2 contre D | −1 261, −369, −314 (tous les IC contiennent 0) |

- Sur ces structures neuves, F choisit mieux que R1, D et W. L'écart R1 − F est de même sens et d'ordre de
  grandeur proche de celui de B-FRAG 2 ; ce n'est pas une confirmation.
- W apprend surtout à recommander la coordination historique : 38 décisions sur 48, contre 31 pour D, 19 pour
  F et 14 pour R1.
- La graine 0 fait nettement moins bien que les autres. C'est un **diagnostic d'instabilité entre graines**,
  qui ne donne pas une incertitude calibrée.

**Erreurs sur les effets d'action et classement** (par rapport aux moyennes d'évaluation) :

| Méthode | RMSE des effets (pm) | Spearman moyen | Regret moyen / min a posteriori |
|---|---|---|---|
| F | 2 104 | 0,56 | 144 |
| R1 | 2 577 | 0,36 | 396 |
| D | 2 423 | 0,38 | 705 |
| W (ensemble) | 3 015 | 0,44 | 1 070 |

W classe un peu mieux les actions que D (Spearman 0,44 contre 0,38), mais se trompe davantage sur l'**ampleur**
des effets et sur la meilleure action.

**Trajectoires de W** (déroulé ouvert, sans observation) :

- RMSE standardisé des 30 variables d'état : 0,74 en moyenne, croissant de **0,64 au jour 1 à 0,87 au jour 7**.
- **Violations** sans projection : 47 225 valeurs négatives sur 1 209 600 (3,9 %, comptes prédits négatifs) ;
  aucune occupation > 1.

**Garde-fous W − D** (IC 95 % ; aucune non-infériorité revendiquée) :

| Garde-fou | Écart [IC 95 %] |
|---|---|
| Soins non couverts | −169 min [−410 ; −35] (moins avec W) |
| Rejets | 0 |
| Minutes de rupture | +33 [−9 ; +113] |
| File terminale | +0,1 [−0,0 ; +0,2] |
| Attente terminale max | +16 min [−10 ; +58] |
| Part de l'unité A | 0 [−0,0 ; +0,0] |

- Heures-agents moyennes : W 1,7 ; D 2,8 ; F 4,5 ; R1 5,5.
- Des aggravations restent possibles d'après les bornes hautes.

**Par famille.** SF1 (fenêtre de nettoyage, attentes d'environ 170 000) pèse le plus. W y fait moins bien que D
(168 716 contre 166 115) ; D y fait aussi moins bien que F (164 374).

## 4. Compromis qualité / coût

| Système | Temps de réponse par décision | Apprentissage | Données | Attente moyenne |
|---|---|---|---|---|
| D | ≈ 0,06 s (D + W ensemble, prédiction) | 0,5 s | 4 000 trajectoires (569 s CPU) | 59 156 |
| W (3 graines) | idem | 28 à 65 s par graine, CPU | idem | 59 521 |
| R1 | 23,7 s CPU (Md = 32) | modèle L2 existant | — | 58 848 |
| F | 38,1 s CPU (Md = 32) | aucun (postérieur et simulateur) | — | **58 595** |

- D et W répondent environ **600 fois plus vite** que F, au prix d'environ 560 (D) et 930 (W) patients-minutes
  par décision en moyenne.
- Sans marge préétablie, **aucune équivalence ni non-infériorité** à F n'est affirmée.
- F accède aux lois structurelles du générateur, ce qui n'est pas le cas de D et W. W disposait de cibles de
  trajectoire en plus des coûts de D : le résultat compare **deux recettes complètes** et n'isole pas l'effet
  de la représentation latente.

## 5. Réponse à la question

> Un modèle appris conditionné par l'action permet-il de mieux choisir les interventions que la prédiction
> directe de leur coût ?

**Non démontré dans ce pilote.**

- La différence W − D est indéterminée, avec une estimation défavorable à W.
- W ne se distingue pas de D sur l'attente.
- Il réduit les soins non couverts.
- Il prédit moins bien l'ampleur des effets.
- Ses trajectoires se dégradent avec l'horizon.

Face à F, D et W offrent un temps de réponse inférieur de près de trois ordres de grandeur, avec une perte
moyenne de décision mesurable sur ces 16 structures.

## 6. Limites

1. **Effectifs faibles.** 16 structures et 48 décisions. Le bruit d'évaluation par décision est grand, même à
   E = 12 (voir § 1).
2. **Données d'apprentissage faibles.** 200 origines, 2 futurs. Les effets d'action sont petits devant la
   variance du niveau d'attente.
3. **Sélection sur VAL bruitée.** 54 décisions à E = 8. La perte de décision VAL de W oscillait sans tendance,
   et le choix du checkpoint en dépend.
4. **W non convergé.** Il est arrêté par la patience fixée d'avance, alors que ses pertes TRAIN baissaient
   encore. Aucune recherche d'architecture n'a été faite.
5. **Trajectoires non projetées.** 3,9 % de valeurs négatives.
6. **R1 instable à Md = 32** (vérification DEV). F et R1 ne sont pas des références exactes.
7. **Recettes non isolées.** La comparaison W − D porte sur deux recettes complètes.
8. **Ancienne CONF jamais utilisée.** Elle n'a servi ni à apprendre, ni à régler, ni à confirmer. VAL-S, déjà
   utilisée pour des sélections B-FRAG 2, a resservi ici à des sélections.

## 7. Budget (registre B, cumul non remis à zéro)

| Lot | Mur (s) | Plafond |
|---|---|---|
| CLOSE | 0,4 | 40 |
| STAB | 179,4 | 200 |
| DATA | 184,8 | 330 |
| LEARN | 81,9 | 400 |
| EVAL | 1 094,5 | 1 250 |

- Total avant livraison : **1 541,0 s** sur 2 636,728 s. Les chiffres finaux, avec REST, sont dans le message
  de livraison.
- Aucun dépassement, aucune expiration ; CPU local seulement, 0 €.

## 8. Suites possibles (propositions, non lancées)

1. **Évaluation plus large**, à plus de structures et à E plus grand, avant toute conclusion sur W contre D.
2. **Données d'apprentissage plus riches** : plusieurs origines par épisode, plus de futurs.
3. **Critère de sélection VAL moins bruité** pour W, préenregistré : par exemple l'erreur sur les effets.
4. **Contrôle de supervision.** Un D entraîné avec les mêmes cibles intermédiaires, pour séparer la recette de
   la représentation.
5. **Projection documentée** des comptes négatifs dans W.
