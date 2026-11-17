# Protocole du pilote W — apprentissage des conséquences des actions

**Version** P1 du 17 novembre 2026 (décision n° 8). Consigné au registre (note `pilot_protocol`) **avant**
la génération des données d'apprentissage et tout apprentissage comparatif. Un gel (`FREEZE_PILOT.json`,
note `pilot_freeze`) précède l'unique campagne d'évaluation finale.

**Statuts :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Question.** Un modèle appris conditionné par l'action (W) permet-il de mieux choisir les interventions
que la prédiction directe de leur coût (D) ? Quel compromis entre qualité de décision et coût de calcul
offre-t-il face à F ?

**Connaissance antérieure déclarée.** Ce pilote est conçu **après** les résultats de B-FRAG 2 :

- le gain de décision de F sur R1 est faible ;
- l'état instantané porte le signal d'anticipation ;
- l'évaluation d'une décision isolée à E = 8 est bruitée.

Ce n'est pas une hypothèse formulée avant B-FRAG 2.

## 1. Monde, catalogue, décision

- **Générateur B-FRAG 2 inchangé.** `generate2` avec le calendrier public appliqué, plan D2, définition de
  rupture, coûts.
- **Catalogue inchangé : 10 actions.**
  - `none` ;
  - `hist_coord_compat` : transports demandés à t0, puis nettoyage « compat » pendant 24 h ;
  - `cl+1_w1..w4` et `tr+1_w1..w4` : +1 agent sur un créneau de 8 h.
  - Budget de 8 heures-agents.
- **Décision unique** à l'origine `[42, 54, 66][e mod 3]` h. Le plan peut être différé ; vient ensuite la
  politique de fond commune. **Aucune boucle fermée.**

## 2. Partitions et données

| Rôle | Source | Structures | Épisodes et origines | Futurs |
|---|---|---|---|---|
| TRAIN (D et W) | `BF2_TRAIN` (B-FRAG 2, jamais en CONF), trajectoires **neuves** | 0–199 | épisode `s mod 3`, 1 origine de décision | K = 2 futurs vrais (r = 1, 2), **communs aux 10 actions** |
| VAL (sélection et arrêt) | VAL-S B-FRAG 2 enregistrée (`BF2_VAL`, structures 0–17) | 18 | 3 épisodes, 54 décisions | E = 8 (enregistré), coûts finaux seulement |
| Évaluation finale | **nouvelle partition `BF2W_CONF`** (structures neuves) | **0–15** | 3 épisodes, 48 décisions | **E = 12 futurs neufs** (r = 1–12), communs aux actions, **disjoints** des tirages de sélection de F et R1 |

- **Réservé.** L'ancienne CONF B-FRAG 2, les CEVAL et leurs variantes ne servent ni à apprendre, ni à
  régler, ni à confirmer.
- **Unité.** Toutes les origines, actions et futurs d'une structure restent dans une seule partition.
- **Trajectoires TRAIN.** Pas de 2 h ; 84 pas sur 168 h.
  - État vrai : les 30 variables S1, calculées sur le moteur vrai.
  - Coût du pas : attente en patients-minutes, par unité.
  - Totaux par déroulé : attente, soins non couverts, rejets, minutes de rupture, file terminale, attente
    terminale max.
  - Coût mesuré : 3,3 s de CPU par origine (pilote de coût, registre #127).
- **Sous-ensemble réalisable préenregistré.** Si le budget interrompt l'évaluation, on retient les structures
  complètes par indice croissant, jusqu'à la première incomplète. Sous 10 structures, le statut est
  **VALIDATION_FINALE_NON_EXECUTEE**.

## 3. Entrées (identiques pour D et W)

1. **Vue publique S2** à l'origine (S0 + S1 + S2, 84 variables, ordre de `LEARN.json` B-FRAG 2), identique au
   pilote B-FRAG 2 (test W2).
2. **Descripteur de calendrier** (4) : baisse planifiée dans l'horizon, début et fin relatifs, intensité.
3. **Descripteur d'action** (10) : nature (aucune, coordination, renfort), ressource, intensité, début et
   durée du créneau relatifs, durée du mode « compat », heures-agents.

W développe les deux descripteurs, de façon déterministe, en un calendrier par pas de 2 h :

- renfort nettoyage et renfort transport ;
- baisse ;
- mode « compat » ;
- coordination à t0 ;
- heure (sin, cos) et index de pas.

Une borne qui tombe à l'intérieur d'un pas est représentée par une fraction (test W5). D reçoit les mêmes
descripteurs sous forme vectorielle : c'est la **même information**.

**Interdits dans les entrées** : état vrai privé, θ, graines et clés, famille, futurs réalisés, scores de F
(test W2).

## 4. Référence directe D

- **Forme de cible, fixée avant apprentissage :** coût = base(x) + effet(x, a).
  - `base` : Ridge (α = 10) sur x standardisé, ajusté au coût moyen de `none`.
  - `effet` : ajusté aux effets **appariés** `moyenne_k(C_a,k − C_none,k)` ; effet de `none` = 0.
- **Quatre configurations :**
  - Ridge à interactions (x ⊗ action), α = 10 ;
  - Ridge à interactions, α = 1 000 ;
  - HGB de profondeur 3 ;
  - HGB de profondeur 5.

  Les HGB ont `lr` = 0,05, 300 itérations, `min_leaf` = 20, `l2` = 1.
- **Sélection** sur la perte de décision VAL (attente vraie moyenne de l'action choisie, par structure) ;
  égalité → RMSE des effets sur VAL.
- Normalisations ajustées sur TRAIN uniquement.

## 5. Modèle de dynamique W (gradient autorisé)

- **Architecture :**
  - encodeur MLP (88 → 64 → 64, tanh) → h0 ;
  - transition GRUCell(8 → 64), réutilisée sur 84 pas de 2 h, pilotée **uniquement** par le calendrier
    exogène ;
  - têtes : 30 variables d'état (standardisées) et 2 coûts de pas par unité (softplus) ;
  - coût du plan = somme des coûts prédits.
- **Taille :** latent 64, **26 144 paramètres** (calcul : encodeur 9 856 + GRU 14 208 + têtes 2 080) (plafond : 1 M).
- **Pendant un déroulé :** aucune observation, aucun état futur vrai, aucun teacher forcing (test W6).
- **Pertes** (poids fixés ici) :
  - MSE des états ;
  - MSE des coûts de pas ;
  - 1 × MSE du coût cumulé (normalisé) ;
  - 5 × MSE des **effets appariés** (C_a − C_none, normalisés).

  Toutes sont calculées sur le déroulé complet de 84 pas.
- **Optimisation :** Adam (lr 2·10⁻³, décroissance des poids 10⁻⁵), lots de 16 origines × 10 actions,
  écrêtage du gradient à 1, plusieurs passages sur TRAIN.
- **Arrêt :**
  - évaluation VAL toutes les 2 époques ;
  - patience de 10 évaluations ;
  - plafond de 400 époques ;
  - plafond de **140 s** de mur par graine (les 3 graines en parallèle).
- **Sélection du checkpoint :** plus faible perte de décision VAL ; égalité → RMSE des effets VAL.
  Courbes, dernier checkpoint et sélection publiés. Aucune convergence n'est revendiquée si le plafond arrête
  un apprentissage encore en progrès.
- **Graines :** 3 (0, 1, 2).
- **Système principal, fixé avant l'évaluation :** **ensemble** des 3 graines, soit la moyenne des coûts de
  plan prédits, chacune à son checkpoint sélectionné sur VAL. Les graines séparées servent de diagnostic de
  stabilité, pas d'incertitude calibrée.
- **Projection :** aucune ; on rapporte les violations (comptes négatifs, occupation hors [0, 1]).

## 6. Planificateur commun et politiques comparées

| Politique | Coût utilisé pour choisir |
|---|---|
| Règle historique | gelée : toujours `hist_coord_compat` |
| R1 | moyenne sur Md = 32 déroulés L2 |
| D | prédiction directe |
| W | ensemble W |
| F | moyenne sur Md = 32 déroulés du simulateur F, version historique |

Pour R1, D, W et F, l'opérateur est commun : même catalogue, choix du coût prédit minimal, égalité → moins
d'heures-agents puis indice.

- **F** accède aux lois structurelles du générateur (classe de modèle exacte, paramètres inférés), traite
  l'historique par son postérieur L4 et son nowcast, et tire ses propres futurs. Ce n'est pas le cas de D et W.
- **W** reçoit des cibles de trajectoire intermédiaires en plus des coûts de D. Un gain éventuel compare deux
  recettes complètes et n'isole pas l'effet de la représentation latente.
- **Md = 32.** Le choix de F y était stable sur le panel DEV, celui de R1 ne l'était pas : ni l'un ni l'autre
  n'est une référence exacte.

## 7. Évaluation et analyse (campagne finale unique)

- **Évaluation vraie** des 10 actions sur 12 futurs neufs communs.
- **Critère principal :** attente cumulée sur 168 h.
- **Rapportés séparément :** soins non couverts, rejets, minutes de rupture, file terminale, attente terminale
  max, heures-agents, part de l'unité A.
- **Comparaison principale unique : W − D.**
  - Δ = attente(choix D) − attente(choix W), moyenne par structure.
  - IC **apparié à 95 %** par bootstrap des structures (B = 2 000, graine 20261117).
  - Verdicts :
    - `GAIN_W` si la borne basse est > 0 ;
    - `W_INFERIEUR` si la borne haute est < 0 ;
    - sinon `INDETERMINE`.
  - « Non significatif » n'est jamais lu comme « équivalent ».
- **Descriptifs (IC à 95 %, sans correction ; aucune équivalence ni non-infériorité revendiquée) :**
  - W face à R1, à la règle historique et à F ; D face à F ; F face à R1 ; chaque graine W ;
  - erreurs sur les effets d'action (RMSE contre les moyennes d'évaluation) et classement (Spearman) pour D,
    W, F et R1 ;
  - qualité des trajectoires de W (RMSE standardisé des états aux pas de 24 h ; violations) ;
  - coût d'entraînement, données (trajectoires, CPU) et **temps de réponse complet par décision** ;
  - meilleure action a posteriori : diagnostic rétrospectif seulement.
- **Garde-fous W − D :** estimations et IC à 95 % seulement.

## 8. Budget (décision n° 8)

- **Lots :**

| Lot | Plafond (s) |
|---|---|
| CLOSE | 40 |
| STAB | 200 |
| DATA | 330 |
| LEARN | 400 |
| EVAL | 1 100, porté à **1 250** par une note préalable qui prend 150 s sur la marge non allouée |
| REST | 360 |

- **Projection de l'évaluation :** 48 décisions × environ 75 s de CPU (F ≈ 35, R1 ≈ 20, évaluation
  10 × 12 × 0,165 ≈ 20) / 4 cœurs, soit environ 1 000 s de mur.
- ≤ 540 s par commande ; plafonds de temps par commande ; aucun épisode en cours n'est interrompu.

## 9. Tests (avant apprentissage comparatif)

| Test | Objet |
|---|---|
| W1 | partition nouvelle et disjointe |
| W2 | entrées publiques identiques au pilote B-FRAG 2 ; aucun nom privé |
| W3 | calendrier corrigé, appliqué dans la trajectoire et dans le calendrier par pas |
| W4 | origine commune, clés appariées ; totaux = `rollout_sched` ; somme des coûts de pas = attente |
| W5 | créneaux, inaction, coordination, fractions de pas |
| W6 | déroulé W causal, sans état futur ; rechargement identique ; taille |
| W7 | sources et résultats historiques gelés intacts |

Résultat : 17/17 avec les tests B-FRAG 2 (registre #133).
