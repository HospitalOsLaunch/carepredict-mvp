# HOWM-2 — Tranche A : note normative (consignée avant toute mesure)

Cette note s'appuie sur la décision HOWM-2 n° 1 (registre HOWM-2, n° 2) et sur
`inputs/PROGRAMME_HOWM2.md` (`05fc9aae…`).

- Aucun entraînement ni aucune descente de gradient.
- Données synthétiques seulement.
- Les fichiers gelés en G0 et F1 ne sont pas modifiés : le code est neuf, dans
  `src/hospitalos/howm2/` et `scripts/howm2_*.py`.

## A0. Établissements neufs : espace de clés déclaré

**Partitions ajoutées :**
- `HOWM2_REF` (200 établissements, population REF) ;
- `HOWM2_DIAG` (100, population DIAG).

Clé de chaque établissement : `key("HOWM1", "HOWM2_REF" | "HOWM2_DIAG", i)`.

**Enregistrement.** Les deux partitions sont ajoutées **à l'exécution** dans les tables
`PARTITION_SIZES` et `POPULATION_OF` du générateur, en mémoire, par `howm2/space.py`.
- Les octets de `generator.py` ne changent pas ; `g0check` le vérifie à chaque commande.
- La loi de population, les mécanismes et le code de génération sont exactement ceux de G0.
- Un test vérifie que ces clés sont disjointes de toutes les clés G0, réserve scellée comprise.
  Cette vérification compare des clés : la réserve n'est ni générée ni lue.

Les établissements TRAIN 0–47 et VAL 0–11 existants sont utilisés en lecture. DEVTEST, DIAG-DEV et
la réserve ne sont ni générés ni lus.

## A1. Échelle d'information (§ 4 du programme)

**Protocole de score de R1, inchangé :**
- cohorte publique à t ;
- labels et masque du côté score seulement ;
- censure à l'horizon et à la fin des données ;
- intervalles de 15 min (60 min pour l'autorisation) ;
- intervalles de soins de 5 min ;
- durée **publique** : de l'événement de début jusqu'à la disponibilité de l'événement de fin.

Origines : toutes les heures de 24 h à 143 h. Horizons : 1, 6 et 24 h.

| Niveau | Mise en œuvre |
|---|---|
| L0 | B0-pool gelé (`B0_PARAMS.json` de F1), `predict.b0_predict(local=False)` |
| L1 | B0-local gelé, fenêtre de 24 h, `b0_predict(local=True)` |
| L2 | même estimateur B0-local (mêmes τ_f, mêmes fonctions de rétrécissement), avec une fenêtre couvrant **tout le passé public** de l'épisode. L'écart d'arrivées est réestimé sur toutes les heures passées connues, avec la même formule |
| L3 | **privilégié** : θ_h et indicateurs de mécanismes vrais ; état caché inconnu (régime remplacé par sa loi marginale a priori, chaîne partant de l'état 0 à l'heure 0) ; charge m3 remplacée par sa valeur publique à l'heure de l'autorisation, connue à t |
| L4 | **filtre de référence public**, défini ci-dessous |
| L5 | **privilégié** : θ_h, mécanismes, régime vrai à l'heure de début, charge m3 vraie (journal de vérité) |

Pour L3, L4 et L5, les lois sont les **lois exactes du générateur** :
- log-normales discrétisées par excès au pas de 15 min ;
- recalage nocturne de la sortie prête (07–21 h) et de l'autorisation (08–18 h), avec décalage
  uniforme ;
- retard de publication exponentiel arrondi par défaut, θ_lag ;
- binomiale négative des arrivées (r = 3) ;
- log-normale arrondie des soins ;
- Bernoulli de présence.

Ces lois sont convoluées avec la loi du retard de publication de l'événement de fin.

## A2. Filtre de référence L4

L4 n'utilise que l'historique public jusqu'à t et l'a priori de **sa population** (REF ou DIAG),
c'est-à-dire les intervalles uniformes de θ, le mélange des mécanismes, les durées de régime, le
facteur lent et les lois.

**Ce qu'il ne reçoit pas :** θ, régime, indicateurs de mécanismes, clés, journal de vérité.

**Postérieure par grilles :**
- grille uniforme de 41 points par paramètre, prise sur les intervalles de l'a priori ;
- DIAG : grille jointe 21 × 21 pour transport et nettoyage, parce que le régime y est commun.

| Paramètres | Familles concernées |
|---|---|
| θ_lag | tous les retards publics observés |
| tr_min + régime | transport |
| cl_min + régime | nettoyage |
| ready_h + type de mécanisme | sortie prête |
| conf_tr, conf_off | confirmation |
| los × arr_mult | arrivées, par amincissement binomial des heures récentes non encore publiées |
| care_mult | soins |
| noshow | présence |

**Type de mécanisme.** Il est inféré par la vraisemblance marginale jointe des familles transport,
nettoyage et sortie prête. En REF : simple 0,3 ; m3 seul 0,2 ; m3 + m2 0,5.

**Régime.** Avant-arrière exact sur les heures 0 à t, pour chaque point de grille. Le régime à
l'heure de début de chaque élément est **lissé**.

**Approximations déclarées :**
1. **Charge m3.** Elle entre dans la vraisemblance et la prédiction de la sortie prête par sa
   valeur publique à l'heure de l'autorisation, qui sert de substitut.
2. **Arrivées.** L'amincissement par retard (binomiale négative amincie) est utilisé.
3. **Grilles finies.**

Ces approximations sont contrôlées par la validation A3.

## A3. Validation de L4 (avant usage comme plafond)

Validation faite sur les 200 établissements REF neufs, puis sur les 100 DIAG pour l'information.

- **(a) Calibration.** PIT randomisé sur la partition discrète des issues ({T = b}, {T ≥ c}, NB,
  intervalles de soins, Bernoulli), par famille, à H24. La famille passe si la statistique de KS
  vérifie D ≤ max(0,02 ; 1,63/√n).
- **(b) Ordre.** Par famille et par horizon :
  - violation si l'intervalle à 95 % de L4 − L5 est entièrement < 0 ;
  - violation si l'intervalle à 95 % de L3 − L4 est entièrement < 0.

  La famille passe si aucun horizon n'est en violation.
- **(c) Exactitude.** Pour le transport et le nettoyage, avec θ fixé à la vérité, la postérieure du
  régime calculée par le filtre est égale, à 1e-9 près, à celle d'une implémentation indépendante
  par énumération directe, sur 200 éléments tirés.

**Si une famille échoue à (a), (b) ou (c)** : elle est rapportée entre les bornes (L2, L5) et
**sort du critère**. L'agrégat L est alors calculé sur les familles restantes, pour tous les
niveaux.

## A4. Agrégation, marges et verdicts (§ 5 du programme, appliqués tels quels)

**Agrégation.** L(s, e, h) suit la règle de R1 : moyenne non pondérée, sur les familles présentes,
autorisation exclue, des NLL moyennes par famille. Les établissements ont un poids égal.

**Bootstrap.** Par grappes d'établissements, B = 2 000, graine `key("HOWM2", "bootstrap") mod 2^31`.

**Marge publique.**
- M_pub(h) = L(meilleure référence parmi L1, L2) − L(L4).
- La meilleure référence est celle de plus faible L agrégé sur l'échantillon. **Le choix est refait
  dans chaque réplique bootstrap.**

**Verdict principal**, sur `HOWM2_REF` (200 établissements), avec δ_id = 0,02 nat :

| Verdict | Condition |
|---|---|
| `HOWM1_DISCRIMINANT` | borne basse de l'intervalle à 95 % de M_pub ≥ 0,02 à H6 **et** à H24 |
| `HOWM1_NON_DISCRIMINANT` | borne haute < 0,02 à H6 **et** à H24 |
| `HOWM1_INDETERMINE` | sinon |

**État caché**, par famille : part récupérée π_f = (L3 − L4)/(L3 − L5), avec intervalle à 95 %.
Elle est déclarée « sans état caché » si l'intervalle à 95 % de L3 − L5 contient 0.

**Décision.** Sur les 48 instants VAL (12 établissements × 07/11/15/19 h du jour 5) :
- On réutilise les U d'évaluation du précontrôle HOWM-1 : 4 réalisations, 16 candidats.
- Planificateur de R1 nourri par L4 :
  - M = 8 trajectoires par candidat ;
  - chaque trajectoire tire (θ, mécanisme, régime à τ) dans la postérieure L4 ;
  - simulation par la structure du générateur depuis l'état **public** ;
  - clés de choix r ∈ 201–208, disjointes de l'évaluation ;
  - sélection OBJ-LEX-1.
- Marge = U(règle renforcée) − U(planificateur L4), moyenne par instant.
- Verdict : `MARGE_DECISIONNELLE_GE_15` si l'estimation ponctuelle est ≥ 15, sinon
  `MARGE_DECISIONNELLE_LT_15`. L'intervalle (bootstrap par établissement) est toujours rapporté.
- Comparateurs rapportés : C_full, habituel, oracle.

**Puissance.** n requis = ((1,96 + 0,8416) · s_e / (M_pub/2))², où s_e est l'écart-type entre
établissements de la différence par établissement, à H6 et H24.

## A5. Instrumentation et défauts de mesure

- **Pertes TRAIN et VAL par famille**, en passe avant seule (`torch.no_grad`), pour `best.pt` et
  `last.pt` des six exécutions R1. TRAIN = origines d'entraînement TRAIN 0–31 ; VAL = toutes les
  origines VAL. Ni les résultats R1 ni les fichiers gelés ne sont modifiés.
- **Couverture à 90 % de 0,72 à H1.** Diagnostic sur VAL avec B0-local :
  - déroulés depuis l'état public, comme en R1, contre déroulés depuis l'état vrai ;
  - part d'intervalles dégénérés ;
  - PIT randomisé.
- **Indicateur « ne sait pas ».** Redéfinition proposée : écart entre les deux meilleurs candidats
  < 1,96 × erreur type de leur **différence appariée** (CRN). Elle est démontrée sur les décisions
  VAL ci-dessus et **n'est pas appliquée aux résultats R1 livrés**.

## A6. Budget

3 600 s de temps mural au total.

| Lot | Plafond (s) |
|---|---:|
| A.TEST | 400 |
| A.FACTS | 60 |
| A.INSTR | 300 |
| A.LADDER | 1 600 |
| A.VALID | 300 |
| A.DEC | 300 |
| A.DIAG | 240 |
| A.REST | 400 |

Plafonds par commande : 540 s, et 120 s par commande de test.

**En cas de dépassement projeté**, l'arrêt et la question priment. Aucun seuil, aucune population
et aucun verdict n'est redéfini.

**Ordre de traitement de l'échelle** : `HOWM2_REF`, puis `HOWM2_DIAG`, puis VAL, puis TRAIN. Les
deux derniers sont descriptifs. Les établissements non traités faute de budget seront déclarés
comme tels ; le verdict exige les 200 REF.
