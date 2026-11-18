# HOWM-INT-1 — rapport scientifique et synthèse produit

**Décision** n° 9 (mandat `docs/howm2/inputs/MANDAT_HOWM2_DECISION_9_HOWM_INT_1.md`).

**Statuts inchangés :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Portée.** Benchmark **synthétique**. Aucune donnée clinique réelle, aucun GPU, 0 €. Aucun résultat ne vaut
transfert vers un établissement réel.

**Sources.** Tous les chiffres viennent des fichiers de `evidence/howm_int1/` cités ; le registre fait foi
(`LEDGER_INT1.jsonl`). Protocole : `PROTOCOLE_INT1.md`, consigné avant tout apprentissage comparatif. Gel :
`FREEZE_INT1.json`, avant l'unique campagne finale.

## 0. Résumé

1. **Comparaison principale pré-enregistrée** (MAIN : 200 structures à 2 unités × 3 épisodes × 4 futurs, 7 jours,
   boucle fermée).
   - B\* − W = **+1 244** patients-minutes d'attente par semaine, IC 95 % [405 ; 2 226].
   - Verdict : **`GAIN_W_ETABLI`**.
   - Gain relatif **3,5 %** [1,2 ; 6,0] : la **cible de 5 % n'est pas atteinte**, ni en estimation ni par
     l'intervalle.
2. **Ce verdict doit être lu avec trois réserves, qui viennent des mêmes données :**
   - **B\* est la référence la plus faible sur MAIN.** La règle historique a été choisie par la règle gelée, sur un
     panel VAL trop petit (écart-type de la différence ≈ 500). La référence la plus forte sur MAIN est **D-HGB**.
     Face à elle, W-M ne gagne que **142** [13 ; 260], soit **0,4 %** [0,04 ; 0,76]. C'est une comparaison
     secondaire, sans correction de multiplicité.
   - **Le gain sur B\* est concentré dans une famille** : SF1, fenêtre de nettoyage (+8 106 en moyenne sur 29
     structures). W est moins bon que B\* sur 68 % des structures (médiane −87).
   - **Garde-fous face à B\* :**
     - W dégrade les soins non couverts (+572 min [385 ; 783]) et utilise 12,9 heures-agents de plus.
     - Il améliore les minutes de rupture (−52), la file terminale (−0,2) et l'attente maximale terminale (−39 min).
     - Face à D-HGB (post-hoc), W ne dégrade **aucun** garde-fou : soins non couverts −157 [−217 ; −105],
       heures-agents −0,7 [−2,2 ; 0,8].
3. **Extension (4 et 8 unités, 24 h), combinaisons nouvelles, 12 unités.**
   - EXT : W est légèrement **moins bon** que B\* (−30 [−50 ; −11], porté par 8 unités : −60).
   - COMBO et 12 unités : écarts non significatifs (+6 [−35 ; 52] ; −22 [−54 ; 26]).
   - La qualification l'avait annoncé : à ces tailles, les règles simples suffisent dans 87–100 % des cas.
     L'extension est surtout descriptive.
4. **Anticipation** (W, rupture d'une unité dans les 24 h) : AUC 0,92, Brier 0,031 pour un taux de base de 2,8 %.
   Le décile le plus haut est **surconfiant** (0,47 prédit contre 0,24 observé).
5. **Propagation selon W** (VAL, 4 et 8 unités) : sur les unités non ciblées par l'action, les effets par unité
   prédits suivent la vérité.
   - Pearson 0,67 ; signe correct à 98 % quand |effet vrai| ≥ 60 patients-minutes.
   - Le transport est mal capté (r = 0,07, effets faibles).
   - L'achat de créneaux d'aval est trop diffusé vers l'amont.
6. **Apprentissage.**
   - Le palier 2 (10 000 structures) **n'a pas amélioré** le regret VAL hors ligne ; les deux tailles s'arrêtent à
     patience après 6 000–8 000 mises à jour de continuation.
   - La suppression des **messages** double le regret ; celle de l'**historique** ne change rien.
   - M n'est pas meilleur que S hors ligne, mais l'est en boucle fermée sur MAIN (+114 [2 ; 220]).
7. **Sous-panel F/R1** (32 structures × 3 × 4, comparateurs secondaires) :
   - F − W = +861 [4 ; 1 757] et R1 − W = +624 [308 ; 1 014] : W fait mieux que la chaîne simulateur F et que
     R1, pour un coût de décision 60 à 70 fois plus faible (0,25 s contre 17 et 10 s de CPU) ;
   - sur ces 32 structures, la règle historique est la meilleure politique, et l'écart avec W n'est pas
     significatif (−180 [−890 ; 511]) : le sous-panel ne reproduit pas l'avantage de W observé sur MAIN.

**Ce que ces résultats ne disent pas.**

- Ils ne disent pas que « les world models échouent » : W bat toutes les références de MAIN, y compris la plus
  forte, mais de peu.
- Ils ne disent pas que « l'objectif est atteint » : la cible de 5 % n'est pas atteinte, et le gain sur B\* repose
  sur un choix de B\* défavorable à B\*.

## 1. Monde et tâche

**Monde.** Moteur HOWM-1 gelé au pas de 15 minutes, étendu par sous-classe (`EngineN`, `ProvN`) avec les
mécanismes M1–M8 du protocole (§ 1). Les tests I1–I10 et M1–M7 passent (31 tests,
`tests/howm_int1/`).

**Deux unités.** C'est le monde B-FRAG 2 : familles SC4–SC6 et SF1–SF3, décisions quotidiennes sur 7 jours,
projection sur 48 h.

**Extension.** 4, 8 et 12 unités : régimes nominal, tendu et fragile ; goulots ; topologie amont → aval ;
décisions toutes les 6 h sur 24 h.

**Qualification DEV** (`QUALIFICATION_DEV.json`), sous politiques fixes. Les structures avec rupture représentent
0–7 % en nominal, 10–43 % en tendu et 44–80 % en fragile. Une règle simple fait aussi bien (à moins de 1 % près)
que la meilleure séquence :

| Taille | Règle simple suffisante |
|---|---|
| 2 unités, fragile | 63 % |
| 2 unités, nominal ou tendu | 93–95 % |
| 4–12 unités | 87–100 % |

Deux révisions ont été faites à la qualification, **avant toute comparaison** : renforts partagés à intensité
k = n/2, et action d'achat de créneaux d'aval.

## 2. Corpus

| Élément | Contenu |
|---|---|
| `INT_TRAIN` | palier 1 = structures 0–999, palier 2 = 0–9 999 ; tailles 2 / 4 / 8 unités à 60 / 20 / 20 % |
| Situations | 3 par structure (une par épisode) ; provenance historique 40 %, exploratoire 40 %, robuste 20 % |
| Séquences | toutes les candidates à 2 unités ; 20 à 4 et 8 unités |
| Futurs | K = 2 (K = 8 si s mod 20 = 0) ; enregistrement toutes les 2 h |
| VAL | 300 structures, K = 4 |
| Manifestes | `MANIFEST_CORPUS.json` (empreintes par fichier) |

**Couverture du palier 1** (`DIAG_SF1.json`) : SF1 compte 372 situations (la famille la plus fournie à 2 unités) ;
l'action `av` a été vue en première position 984 fois.

**Débit mesuré :** 2,1 s de mur par structure à 4 processus seuls, 4 fois moins en concurrence (§ 12).

## 3. Modèles

**W (`GraphWM`).**

- Nœuds unités et ressources, messages, GRU, état explicite de 9 variables.
- Contraintes par construction ; logits de rupture.
- Tailles : S = 317 460 paramètres (d = 128), M = 1 899 540 (d = 320).
- 3 graines par taille et par palier.
- Pertes : états, coûts par pas, coût cumulé, effets appariés ×5, rupture ×0,5. Curriculum d'horizon 12 → 24 → 36.

**D (mêmes entrées publiques et mêmes descripteurs).**

- Ridge base + effet avec interactions. Au palier 2, sur un sous-échantillon fixe de 10 % des structures : 30 % a
  dépassé la mémoire (#479).
- HGB, profondeur 4 ou 8.
- **DSet**, DeepSets de capacité comparable à W-S, sans cibles de trajectoire.

**Sélection des configurations** (`SYSTEMS_CANDIDATES.json`) : regret relatif VAL à 2 unités, égalité → RMSE des
effets. Systèmes retenus :

| Système | Choix |
|---|---|
| D-Ridge | α = 100, palier 2 |
| D-HGB | profondeur 4, palier 2 |
| D-DSet | palier 1 |
| W-S, W-M | ensembles des 3 graines, palier 2 |

## 4. Apprentissage : courbes données, capacité et calcul

Source : `CURVES.json`, à partir des `result.json` de chaque run.

| Run | Paramètres | Structures | Mises à jour (meilleure) par graine | Regret relatif VAL à 2 unités | RMSE des effets | MSE des états |
|---|---|---|---|---|---|---|
| S palier 1 | 317 460 | 1 000 | 28k (20k), 30k (25k), 30k (22k) | 2,11 / 1,73 / 2,12 % | 355 / 367 / 376 | 0,20 / 0,21 / 0,20 |
| M palier 1 | 1 899 540 | 1 000 | 18k (10k), 20k (13k), 20k (14k) | 2,18 / 3,23 / 2,31 % | 388 / 393 / 359 | 0,21 / 0,21 / 0,21 |
| S palier 2 | 317 460 | 10 000 | +15k (7k), +14k (6k), +14k (6k) | 2,39 / 2,25 / 2,08 % | 388 / 389 / 384 | 0,24 / 0,20 / 0,19 |
| M palier 2 | 1 899 540 | 10 000 | +14k (6k), +9k (1k), +16k (8k) | 2,19 / 3,52 / 2,78 % | 372 / 391 / 397 | 0,20 / 0,28 / 0,22 |

**Lecture.**

- **Données.** Le passage de 1 000 à 10 000 structures n'améliore pas le critère hors ligne (S : 1,99 → 2,24 %
  en moyenne ; M : 2,57 → 2,83 %). C'est une **courbe défavorable, conservée**. Deux causes possibles ne sont pas
  départagées :
  - le palier 2 est une continuation avec patience de 8 évaluations, sur un critère bruité ;
  - la capacité ou la recette plafonne.
- **Bruit du critère.** D'une évaluation à la suivante, le regret VAL saute de 1 à 1,5 point (ex. S graine 0 :
  0,021 à 20 000, 0,035 à 22 000). Le meilleur checkpoint profite donc d'un optimisme de sélection.
- **Capacité.** Hors ligne, M n'est pas meilleur que S. En boucle fermée sur MAIN, l'ensemble M bat l'ensemble S
  de 114 [2 ; 220] patients-minutes par semaine (descriptif).
- **Calcul.** W-S fait 10,1 mises à jour/s sur un fil, W-M 2,7/s. Le palier 1 a coûté ≈ 6 000–6 400 s par graine
  pour S. La courbe calcul → regret est plate après ≈ 5 000 mises à jour, avec des pics isolés de meilleur regret.
- **D sur le même critère VAL hors ligne :** Ridge 4,1 %, HGB 3,6–3,7 %. W est meilleur hors ligne, mais estime
  moins bien l'ampleur des effets en SF1 (§ 5).

**Ablations** (VAL, S palier 1, graine 0) :

| Variante | Regret relatif | RMSE des effets | Spearman |
|---|---|---|---|
| Complet (graine 0) | 2,11 % | 355 | 0,53 |
| Sans historique | 2,13 % | 357 | 0,58 |
| **Sans messages** | **4,29 %** | 503 | 0,16 |

Les messages entre nœuds sont nécessaires ; l'historique public à t − 6 h et t − 24 h n'apporte rien de mesurable.

## 5. Diagnostic SF1

Source : `DIAG_SF1.json`, palier 1, W-S contre D-HGB8.

- **Erreur d'ajustement, pas de généralisation.**
  - Sur SF1, W choisit mieux que D (regret relatif TRAIN 1,1 % contre 1,6 %).
  - Mais il estime moins bien l'ampleur des effets : RMSE TRAIN 797 contre 477 ; VAL 671 contre 540.
  - Sur VAL SF1, les regrets sont égaux (1,83 % contre 1,83 %).
- **Petit lot.** L'ajustement de 16 situations SF1 à horizon complet réussit (RMSE 270 → 98 ; regret ≈ 0) :
  l'implémentation et l'optimiseur ne sont pas en cause.
- **Dérive avec l'horizon.** La MSE des états passe de 0,16 (2 h) à ≈ 0,25 (72 h).
- **Défaut du diagnostic, conservé.** La première exécution était limitée à 12 pas
  (`DIAG_SF1_run1_horizon12.json`).
- **Évaluation finale.** SF1 est la famille où W gagne le plus, contre B\* (+8 106) comme contre D-HGB (+318,
  post-hoc). Le déficit du pilote W en SF1 ne se retrouve pas en boucle fermée.

## 6. Choix de B\* et de W, gel

**Panel VAL en boucle fermée** (`VAL_PANEL.json`) : 40 structures VAL à 2 unités × 1 épisode × 2 futurs, 7 jours.
Attente moyenne :

| Politique | Attente moyenne |
|---|---|
| Historique | 33 848 |
| W-M | 33 878 |
| D-HGB | 33 939 |
| W-S | 33 983 |
| D-Ridge | 34 090 |
| Robuste | 34 219 |
| D-DSet | 34 538 |

**Règle gelée :** attente minimale, égalité → plus simple. Elle donne **B\* = historique** et **W principal = W-M**.
L'écart-type de B\* − W y est ≈ 500–570 : le panel ne départage aucun système.

**Conséquence.** Sur MAIN, la règle historique est la **pire** des 7 politiques. Le choix de B\* était conforme au
protocole, mais il rend la comparaison principale moins exigeante qu'une comparaison à la meilleure référence.
D'où le § 8.3.

**Gel.** `FREEZE_INT1.json` (note `int1_freeze`, #562) contient les systèmes, les panels, les futurs, Md = 16, le
planificateur, l'analyse et les empreintes des scripts.

**Défaut après gel** (`INCIDENT_SUB32_R1.json`, #599). R1, comparateur secondaire, échouait au-delà de 192 h,
parce que les tableaux de la fonction gelée `origins()` sont dimensionnés pour HOWM-1. Il est corrigé par une
fonction dérivée (horizon de 400 h) **avant tout résultat SUB32**. W, D, B\*, les règles, les panels et l'analyse
sont inchangés.

## 7. Évaluation finale (campagne unique)

**Taille.**

| Panel | Structures × épisodes × futurs | Politiques |
|---|---|---|
| MAIN | 200 × 3 × 4 | historique, robuste, D-Ridge, D-HGB, D-DSet, W-S, W-M |
| EXT | 96 × 3 × 4 | mêmes |
| COMBO | 48 × 3 × 4 | mêmes |
| SIZE12 | 48 × 3 × 4 | mêmes |
| SUB32 | 32 × 3 × 4 | F et R1 |

**Protocole d'évaluation.** Chaque politique voit son propre historique public. Les futurs sont communs à toutes
les politiques. Analyse gelée : `scripts/int1/analyse.py` → `RESULTS_INT1.json`. Bootstrap par grappes de
structures, B = 2 000, graine 20261117.

## 8. Résultats de la tâche principale (MAIN)

### 8.1 Comparaison principale et gain relatif

| Mesure | Valeur | IC 95 % |
|---|---|---|
| Attente B\* (historique), patients-minutes / 7 j | 35 646 | [31 398 ; 40 125] |
| Attente W-M | 34 402 | [30 588 ; 38 341] |
| **B\* − W** (apparié) | **+1 244** | **[405 ; 2 226]** → `GAIN_W_ETABLI` |
| Gain relatif | 3,49 % | [1,22 ; 6,01] ; cible de 5 % non atteinte (estimation ni IC) |

**Distribution des différences par structure.**

| Quantile | 5 % | 25 % | 50 % | 75 % | 95 % |
|---|---|---|---|---|---|
| B\* − W | −1 165 | −403 | −87 | +9 | +7 618 |

- W est moins bon sur **68 %** des structures.
- Les dix pires cas vont de −1 255 à −6 973 (structure 24).
- Le gain moyen vient d'une queue droite (SF1, SF2).

**Par famille** (B\* − W) :

| Famille | B\* − W |
|---|---|
| SF1 | +8 106 |
| SF2 | +1 130 |
| SC4 | −161 |
| SC5 | −309 |
| SC6 | −124 |
| SF3 | −93 |

### 8.2 Garde-fous (W − B\*)

Une valeur négative signifie que W fait mieux.

| Garde-fou | W − B\* | IC 95 % |
|---|---|---|
| Soins non couverts (min) | **+572** | [385 ; 783] |
| Heures-agents | **+12,9** | [10,8 ; 15,2] |
| Minutes de rupture | −52 | [−94 ; −17] |
| Débuts de rupture | +0,01 | [−0,02 ; 0,03] |
| File terminale | −0,22 | [−0,38 ; −0,08] |
| Attente maximale terminale (min) | −39 | [−68 ; −12] |
| Rejets, aval bloqué, transferts en attente | 0 | — |

**Lecture des soins non couverts.** Ils augmentent pour **toutes** les politiques qui libèrent des lits plus vite
que la règle historique :

| Politique | Soins non couverts (min) |
|---|---|
| Historique | 13 183 |
| W-M | 13 755 |
| D-HGB | 13 912 |
| Robuste | 13 767 |

L'hypothèse la plus simple est que plus de patients placés font plus de soins à couvrir, à effectif constant.
**Elle n'est pas vérifiée ici**, et aucune non-infériorité n'est revendiquée.

### 8.3 Références secondaires et lecture face à la meilleure référence

**Référence − W-M** (attente ; > 0 si W-M est meilleur) :

| Référence | Différence | IC 95 % |
|---|---|---|
| D-HGB | +142 | [13 ; 260] |
| W-S | +114 | [2 ; 220] |
| D-Ridge | +685 | [494 ; 888] |
| Robuste | +1 010 | [730 ; 1 313] |
| D-DSet | +1 129 | [862 ; 1 401] |
| Historique (B\*) | +1 244 | [405 ; 2 226] |

**Post-hoc descriptif** (`POSTHOC_MAIN.json`, écrit après l'analyse gelée, sans verdict) : W-M − D-HGB.

| Mesure | W-M − D-HGB | IC 95 % |
|---|---|---|
| Attente | −142 | [−260 ; −13] |
| Gain relatif de W-M sur D-HGB | 0,41 % | [0,04 ; 0,76] |
| Soins non couverts | −157 | [−217 ; −105] |
| Heures-agents | −0,7 | [−2,2 ; 0,8] |
| Minutes de rupture | −3,5 | [−11,4 ; 4,6] |
| Attente maximale terminale | −9,5 | [−23,7 ; 4,8] |

**Par famille** (D-HGB − W-M) :

| Famille | D-HGB − W-M |
|---|---|
| SF1 | +318 |
| SC4 | +322 |
| SC6 | +199 |
| SF3 | +189 |
| SC5 | +113 |
| SF2 | **−280** |

**Lecture.** Face à la référence la plus forte, W est meilleur sur l'attente, de façon petite mais soutenue par
l'intervalle, sans dégrader de garde-fou. Ce n'est pas la comparaison pré-enregistrée, et l'intervalle n'est pas
corrigé pour la multiplicité. Ce résultat est à confirmer.

### 8.4 Coût de décision (CPU, séparé du mur)

| Système | Moyenne | p95 |
|---|---|---|
| W-M | 0,25 s | 0,30 s |
| W-S | 0,10 s | 0,14 s |
| D (les trois variantes) | 0,03 s | 0,05–0,06 s |
| F (Md = 16) | 17,0 s | — |
| R1 (Md = 16) | 10,4 s | — |

Les valeurs de F et R1 viennent de SUB32 (§ 9).

## 9. Sous-panel F / R1 (SUB32)

**Dispositif.** Structures MAIN 0–31 × 3 épisodes × 4 futurs, mêmes futurs que MAIN. F et R1 sont rejoués à
chaque décision sur l'historique public propre de la politique, avec Md = 16 tirages. Les autres politiques sont
celles de MAIN, sur les mêmes structures. Sources : `RESULTS_INT1.json` → `SUB32` (analyse gelée),
`POSTHOC_MAIN.json` → `SUB32_descriptive` (post-hoc).

**Attente moyenne sur 7 jours** (32 structures) :

| Politique | Attente |
|---|---|
| Historique | 33 664 |
| **W-M** | **33 845** |
| W-S | 33 997 |
| D-HGB | 34 066 |
| D-Ridge | 34 207 |
| D-DSet | 34 449 |
| R1 | 34 469 |
| Robuste | 34 516 |
| F | 34 706 |

**Différences appariées** (> 0 si la seconde politique est meilleure) :

| Comparaison | Différence | IC 95 % | Source |
|---|---|---|---|
| F − W-M | +861 | [4 ; 1 757] | analyse gelée |
| R1 − W-M | +624 | [308 ; 1 014] | analyse gelée |
| F − R1 | +237 | [−465 ; 990] | post-hoc |
| F − historique | +1 042 | [196 ; 1 943] | post-hoc |
| Historique − W-M | −180 | [−890 ; 511] | post-hoc |
| D-HGB − W-M | +221 | [−25 ; 465] | post-hoc |

**Coût de décision** (CPU par décision, moyenne) : F 17,0 s ; R1 10,4 s ; W-M 0,25 s.

**Lecture.**

- **W bat F et R1.** F a accès aux lois structurelles du générateur, W non. W fait pourtant mieux que F (borne
  basse proche de 0) et que R1, pour un coût de décision 60 à 70 fois plus faible.
- **F ne fait pas mieux que R1.** C'est cohérent avec le gain faible de F sur R1 trouvé dans B-FRAG 2.
- **La règle historique est la meilleure sur ce sous-panel.** L'écart avec W n'y est pas significatif, et F fait
  nettement pire qu'elle. Sur 32 structures, la famille SF1 — où W gagne surtout face à la règle historique —
  pèse moins que sur MAIN. Le sous-panel ne contredit pas MAIN, mais ne le reproduit pas.
- **Lecture d'ensemble.** La simulation explicite rejouée à chaque décision (F, R1) n'apporte pas d'avantage face
  aux références apprises ou à la règle simple dans ce monde ; W n'en a pas besoin pour faire au moins aussi
  bien.

## 10. Extension et généralisation (descriptif)

**B\* − W-M** (> 0 si W est meilleur) :

| Panel | B\* − W | IC 95 % |
|---|---|---|
| EXT (96 ; 4 et 8 unités, 24 h) | −30 | [−50 ; −11] |
| dont 4 unités | −0,3 | [−20 ; 23] |
| dont 8 unités | −60 | [−92 ; −35] |
| COMBO (48 ; combinaisons réservées, intensité 1,3, fragile) | +6 | [−35 ; 52] |
| SIZE12 (48 ; 12 unités, jamais vues) | −22 | [−54 ; 26] |

**Lecture.**

- **Les écarts sont petits.** Ils représentent 0,1–0,5 % d'attentes de 12 700 à 27 300 patients-minutes. C'est
  cohérent avec la qualification : à ces tailles, une règle simple suffit presque toujours.
- **La meilleure politique varie** : règle robuste sur EXT, COMBO et SIZE12 ; historique et D-DSet sont proches.
- **Généralisation.** W n'est pas dégradé de façon notable sur les combinaisons réservées ni à 12 unités, alors
  que 12 unités n'ont jamais été vues. Il n'y a pas non plus d'avantage. W est légèrement moins bon à 8 unités.

## 11. Anticipation et propagation

### 11.1 Anticipation

Source : `RESULTS_INT1.json`, `anticipation_W`, MAIN.

| Mesure | Valeur |
|---|---|
| Décisions × unités | 102 720 |
| Positifs | 2 918 (taux 2,8 %) |
| AUC | 0,924 |
| Brier | 0,031 |

**Calibration.**

- Les déciles 1 à 8 sont sous-estimés en relatif, mais tous inférieurs à 0,6 % en fréquence.
- Le décile 9 prédit 3,2 % pour 1,3 % observé.
- Le décile 10 prédit 47 % pour 24 % observé.

W ordonne bien les situations à risque, mais **surestime la probabilité dans le décile le plus risqué**. Aucune
calibration probabiliste n'est revendiquée (protocole § 5).

### 11.2 Propagation dans le monde vrai (DEV)

Source : `PROPAGATION_DEV.json`. Contrôles appariés à un seul canal, sur 72 h, régime fragile, 6 structures par
cellule.

| Cellule | Canal coupé | Effet amont | Effet aval |
|---|---|---|---|
| n = 4, transfert | lit retenu | +4 073 ± 1 065 | −26 |
| n = 8, transfert | lit retenu | +8 289 ± 2 273 | −41 |
| n = 4, aval | aval limité | +1 979 ± 680 | +4 214 ± 1 292 |

- Le lit retenu en transfert crée de l'attente **en amont** ; sa suppression soulage l'amont sans changer l'aval.
- L'aval externe limité crée de l'attente **en aval puis en amont**.
- Les canaux sont mesurables séparément. Quand deux goulots sont actifs, la cellule est signalée « mélange ».

### 11.3 Propagation selon W (VAL, 4 et 8 unités)

Source : `PROPAGATION_W_VAL.json`, script `scripts/int1/propagation_w.py`, exécuté après le gel sur VAL, sans
usage de test.

**Pourquoi un autre dispositif.** Les contrôles DEV changent le monde ; ce ne sont pas des actions, et W ne peut
pas être interrogé dessus. On compare donc, pour chaque séquence candidate de 381 situations VAL, l'effet **par
unité** sur 24 h : vrai (moyenne des 4 futurs du corpus) et prédit par W-M.

**Unités indirectes** (non ciblées par l'action), 39 068 paires :

| Groupe | Pearson | Signe correct (vrai ≥ 60) | Remarque |
|---|---|---|---|
| Toutes actions | 0,67 | 98 % | moyennes vraie −9,0, W −7,5 |
| Coordination | 0,65 | 99 % | effet vrai moyen −117 par unité |
| (rien, coordination) | 0,55 | 99 % | W sous-estime de ≈ 35 % (−76 contre −116) |
| Nettoyage | 0,73 | 93 % | n = 4 : 0,86–0,91 ; n = 8 : 0,27–0,45 |
| Aval | 0,31 | 95 % | voir ci-dessous |
| Transport | 0,07 | 70 % (10 paires) | effets vrais quasi nuls |

**Achat de créneaux d'aval, à 4 unités :**

| Position | Effet vrai | Effet W |
|---|---|---|
| Aval | −21,8 | −10,5 |
| Amont | −2,3 | −8,5 |

W diffuse l'effet vers l'amont plus que le monde.

**Renforts infirmiers :** l'effet vrai sur l'attente est exactement nul (ils agissent sur les soins couverts) ; W
prédit ≈ 0.

**Lecture.** W propage les effets des ressources partagées entre unités, avec un bon signe et une ampleur
correcte pour la coordination et le nettoyage à 4 unités. La propagation est plus faible à 8 unités et pour l'aval.

## 12. Budget : temps calendaire et budget comptabilisé

Situation au registre le 18 novembre à 14 h 05 UTC : fin de l'évaluation, analyse finale faite. L'archive, le
reçu et l'enveloppe ajoutent ≈ 0,5–1 ks de mur, consignés au registre final (§ 17).

| Grandeur | Valeur |
|---|---|
| Temps calendaire écoulé (genèse 17 nov. 15 h 43 → 18 nov. 14 h 05 UTC) | ≈ 22,4 h |
| Mur comptabilisé (somme des commandes ; concurrentes comptées chacune) | 131 424 s = 36,5 h sur 259 200 (51 %) |
| CPU | 288 171 s + corrections déclarées de 2 640 s (#610, #678) = 80,8 h sur 288 (28 %) |
| Commandes | 372 (7 dépassements de 540 s, 26 codes de sortie non nuls ; tous conservés) |
| Coût | 0 € ; aucun GPU ; aucun service payant |

**Par lot** (mur / CPU, en s) :

| Lot | Mur | CPU |
|---|---|---|
| L0 | 907 | 1 939 |
| DATA | 39 689 | 91 425 |
| LEARN | 62 610 | 97 379 |
| EVAL | 27 590 | 96 732 (dont SUB32 ≈ 72 500) |
| REST | 629 | 696 |

Aucune réallocation n'a été nécessaire ; la réserve de 7 h n'est pas utilisée.

**Pourquoi le mur comptabilisé dépasse le calendaire.** Pendant la phase de données, 6 à 8 commandes concurrentes
comptaient chacune leur mur. La note d'exécution (#155) a regroupé les graines dans une seule commande et limité la
concurrence à 2 commandes.

## 13. Incidents et écarts

Tous sont au registre ; aucun essai défavorable n'a été retiré.

| # | Incident | Traitement |
|---|---|---|
| 39 | Course d'écriture concurrente sur le registre (ligne 38) | registre archivé (`LEDGER_INT1.broken_at_line38.*`), reconstruit, verrou fcntl exclusif |
| 87 | Course de lecture (JSONDecodeError) | verrou partagé |
| 87 | Corpus au-delà de 540 s | budget 380 s |
| 87 | HGB au-delà de 540 s | un fil OpenMP, modèle de base par situation, une configuration par commande |
| 87 | Ridge non sérialisable | classe au niveau module |
| 155 | Concurrence excessive | graines regroupées, au plus 2 commandes |
| 432, 535 | Deux redémarrages du conteneur | enregistrements reconstruits (249 s et 319 s) |
| 479 | Ridge palier 2 hors mémoire | sous-échantillon déclaré de 10 % |
| — | Arrêt d'une commande par la limite de 2 h des tâches d'arrière-plan | échéance de chaîne alignée sur le créneau |
| 599 | Défaut post-gel de R1 (horizon) | voir § 6 |
| 610 | Groupe de processus SUB32 orphelin, après l'arrêt d'une chaîne (tâches recalculées en double, sans corruption) | arrêt ; comptabilité conservatrice : 49 s de mur comptés deux fois, +560 s de CPU déclarés |
| 678 | Dépassement de 540 s d'une commande SUB32 (#677) : tâche lancée à 330 s, durée jusqu'à 276 s ; travail en vol perdu, recalculé | budget de lancement 200 s ; +2 080 s de CPU déclarés (processus tués non comptés par le runner) |

**Défauts de code corrigés avant le gel :** ordre départ/nettoyage au même tick dans la relecture publique ;
collision d'identifiants de séjour en transfert ; périmètre du test I10.

**Écarts au protocole.**

1. **Ridge au palier 2** : sous-échantillon de 10 % (mémoire).
2. **Propagation selon W** : faite sur les effets par unité des actions (VAL), pas sur les contrôles DEV, que W ne
   peut pas représenter (§ 11.3).
3. **Tables post-hoc face à D-HGB** : ajoutées après l'analyse gelée, signalées comme telles.

## 14. Limites

- **Monde synthétique.** Les lois du générateur sont connues de F, pas de W ni de D. Aucune validité clinique.
- **Une seule mesure de résultat principale** (attente cumulée). Les garde-fous montrent un arbitrage
  attente / soins non couverts face à la règle historique.
- **Choix de B\* sur un panel VAL sous-dimensionné** (40 × 1 × 2). Un panel plus grand aurait probablement choisi
  D-HGB ou W, ce qui aurait rendu la comparaison principale plus exigeante.
- **Apprentissage.**
  - Le critère de sélection par checkpoint est bruité.
  - La continuation au palier 2 s'arrête tôt.
  - L'effet des données n'est pas séparé de celui de la recette.
  - Le budget total n'a pas été épuisé : ≈ 51 % du mur et 28 % du CPU en fin d'évaluation. D'autres recettes étaient
    possibles dans l'enveloppe ; elles n'ont pas été tentées après le gel, conformément au protocole.
- **Anticipation non calibrée** dans le décile haut.
- **Extension.** Le monde à 4–12 unités laisse peu de marge aux décisions : les règles simples suffisent. Il ne
  permet pas de juger W à grande taille.

## 15. Synthèse produit (HospitalOS)

**Ce qui est démontré, en synthétique.**

- Un modèle du monde hospitalier appris, structuré en graphe d'unités et de ressources, entraîné uniquement sur
  des conséquences simulées, peut servir de **moteur de projection** à un planificateur commun.
- En boucle fermée sur une semaine, il produit des décisions au moins aussi bonnes que :
  - la règle historique : +3,5 % sur l'attente, établi ;
  - des modèles directs de coût : +0,4 % sur le meilleur, descriptif.
- Le coût est de 0,25 s de CPU par décision, contre 17 s pour la chaîne simulateur F, qu'il bat sur le sous-panel (+861 [4 ; 1 757]).
- Il prédit aussi la rupture d'une unité à 24 h (AUC 0,92) et les effets d'une action sur les unités non
  ciblées.

**Ce qui ne l'est pas.**

- La cible de 5 % d'attente en moins.
- L'absence d'effet indésirable : face à la règle historique, plus de soins non couverts et plus d'heures-agents.
- Tout bénéfice à 4–12 unités.
- Toute validité sur données réelles.

**Usage possible, à ce stade.** Démonstrateur de recherche : projection explicable par unité, alertes de rupture
ordonnées, comparaison d'actions candidates. Aucun usage décisionnel. `G2=NO-GO` maintenu.

**Ce qui ferait avancer le plus,** en suggestion et non en engagement :

1. un panel de choix de référence correctement dimensionné, ou la comparaison principale directement contre la
   meilleure référence apprise ;
2. un critère de sélection de checkpoint moins bruité (plus de futurs VAL) ;
3. un monde à 4–12 unités où les décisions comptent ;
4. un objectif multi-critères (attente et soins couverts).

## 16. Reproduire

| Étape | Fichiers |
|---|---|
| Tests | `tests/howm_int1/` |
| Moteur et modèles | `src/hospitalos/howmint/` |
| Scripts | `scripts/int1/` |
| Registre | `scripts/howm_int1_run.py` |
| Analyse gelée | `python scripts/int1/analyse.py` (à partir de `int1_eval/`) |
| Démonstration | `python scripts/int1/demo.py` → `docs/howm_int1/DEMO.md` (illustrations, pas des résultats agrégés) |
| Archive et reçu en environnement neuf | § 17, `ARCHIVE_INT1` et `RECU_INT1` |

## 17. Archive, reçu en environnement neuf, enveloppe

### Archive scientifique

| Élément | Valeur |
|---|---|
| Fichier | `HOWM_INT1_FINAL.zip` |
| SHA-256 | `fb46fab31231172d3e879cbd07f89ca963289eb14a798369fc124001b38d0490` |
| Commit archivé | 7af2e10 |
| Taille | 121 Mo, 4 245 fichiers |
| Description | `evidence/howm_int1_receipt/PACKAGE_FINAL.json` |

**Contenu.**

- Arbre source (git) avec registre, résultats, manifestes et rapport.
- Tous les runs : checkpoints retenus, normalisations, courbes, résultats, pickles D. Les états d'optimiseur ne
  sont pas archivés.
- Les 1 560 fichiers de l'évaluation finale.
- Le corpus VAL, le palier 1 et un échantillon du palier 2.
- La liste figée des paquets.

### Reçu

Source : `evidence/howm_int1_receipt/RESTORE_RECEIPT_INT1.json`, **ok = true**, commandes #762–#774.

**Environnement neuf.** Répertoire extrait de l'archive et venv reconstruit depuis la liste figée.

- L'empreinte pip est identique à celle approuvée (`e93a3617…`).
- Les modules sont importés depuis l'arbre extrait, pas depuis le dépôt.
- Le venv de campagne n'est pas utilisé.

| Section | Contenu | Résultat |
|---|---|---|
| Intégrité | 4 245 empreintes ; modèles gelés ; 1 301 fichiers de corpus contre le manifeste | identiques |
| Tests | 30 tests ; M7 remplacé par son contrôle sur les 46 fichiers historiques présents dans l'archive (34 binaires absents de git, listés) | réussis |
| Chargement | toutes les politiques de MAIN, EXT et SUB32 ; métriques VAL enregistrées de W-S, W-M (graine 0, palier 2), D-HGB, D-Ridge réévaluées | identiques (tolérance relative 1e-6) |
| Analyse | `RESULTS_INT1`, `POSTHOC_MAIN`, `PROPAGATION_W_VAL`, `CURVES` reproduits dans un répertoire séparé | identiques |
| Régénérations annoncées | MAIN (17, e1), SIZE12 (5, e2), SUB32 (0, e2, futur 2), corpus TRAIN 137 et 9001, VAL 5 (K = 4), démonstration ; paramètres lus dans chaque fichier ; sorties séparées | identiques |
| Réajustements | D-Ridge et D-HGB du palier 1, dans un répertoire séparé | prédictions identiques bit à bit |

**Règle des champs de temps.** Avant comparaison, on retire récursivement les clés `seconds`, `fit_seconds`,
`train_seconds`, `wall_s`, et toute clé contenant `cpu_s`. Rien d'autre n'est exclu, à une exception près : la
taille du pickle (`bytes`) des réajustements, qui dépend du nom de module.

**Ce qui n'est pas refait.**

- Les apprentissages W.
- D au palier 2 et DSet.
- Les autres fichiers d'évaluation et de corpus : ils sont archivés, vérifiés par empreinte et utilisés par
  l'analyse reproduite.
- Panel VAL, qualification, propagation DEV, diagnostic SF1.

**Répétition préalable.** `REHEARSAL_SUMMARY.json` : six défauts du script de reçu ont été trouvés et corrigés avant
le reçu final.

### Enveloppe de clôture

`HOWM_INT1_CLOSURE_ENVELOPE.zip` (voir `evidence/howm_int1_receipt/CLOSURE_ENVELOPE_INT1.json`). Elle contient
l'archive intacte, le reçu externe, le rapport, le protocole, la démonstration, la décision, le mandat et le
registre final.

Aucun push, aucune publication externe.
