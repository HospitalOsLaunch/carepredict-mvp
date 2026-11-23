# NORME HOWM2-C1 palier 1 (décision n° 5), consignée avant toute mesure C1

**Base adoptée par la décision n° 5 :**
- `proposition_A2/C1_AMENDE/` : conception, norme N5′, N7′, N8′, N9′ et N12′, matrice, plan ;
- les clauses inchangées de `proposition_BCD/NORME_HOWM2_C1_PROPOSEE.md` (N1 à N12).

Cette norme les applique au **palier 1 seul**. Elle fixe aussi ce que ces textes ne fixaient pas.
Aucun seuil, aucune population et aucun verdict n'est modifié.

Statuts : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

## 1. Périmètre

- Systèmes : C.1, C.2a et C.2b.
- Tailles N ∈ {100, 1 000}.
- Un passage sur le flux neuf `HOWM2_CTRAIN`.
- Sélection sur `HOWM2_CVAL`, gel F-C1, puis une campagne finale unique sur `HOWM2_CEVAL`.
- Transfert descriptif vers `HOWM2_DIAG`, sans réentraînement.
- Le palier 2 (10 000) n'est **pas** autorisé. Après ouverture de CEVAL, cette population est
  connue et ne pourra pas servir de confirmation indépendante d'un palier 2 futur.

## 2. Partitions et indépendance

**Partitions.**
- `HOWM2_CTRAIN` : REF, enregistrée à 10 000, seuls les indices 0 à 999 sont générés.
- `HOWM2_CVAL` : REF, 48 établissements.
- `HOWM2_CEVAL` : REF, 200 établissements.
- Clés `key("HOWM1", partition, i)`, enregistrées à l'exécution ; les octets du générateur ne
  changent pas.

**Indépendance**, vérifiée avant toute mesure par `PARTITIONS_CHECK.json`, sur les identifiants, les
métadonnées et le code de génération seulement :
- clés disjointes entre elles, et disjointes de G0, `HOWM2_REF` et `HOWM2_DIAG` ;
- ekeys et vecteurs θ distincts ;
- chaque établissement dépend de sa seule ekey, aucun état n'étant partagé entre établissements
  (vérifié dans le code de `establishment` et `generate`) ;
- HOWM-1 n'a pas de mondes liés.

**Ordre d'accès.** CEVAL n'est **pas** généré avant F-C1. `HOWM2_DIAG` a déjà été lu en A et A′, de
manière descriptive ; il reste descriptif ici.

## 3. Données

- Origines `range(24, 166, 3)`, soit 48 par établissement, pour toutes les partitions de C1.
- Un enregistrement par établissement contient :
  - `dataset.build(épisode, origines)`, gelé ;
  - les 8 intercepts locaux de L2 à chaque origine : `local_deltas` sur tout le passé public, avec
    l'intercept d'arrivées de `long_arrivals_delta`, c'est-à-dire exactement ceux de `l2_predict`
    (test T-C18).
- Tessons de 100 établissements, en ordre d'indice. Ils sont stockés hors dépôt (scratchpad) en
  raison de leur volume, avec leurs empreintes dans `evidence/howm2_c1/DATA_MANIFEST.json`.
  Ils sont conservés pendant le palier 1 ; l'occupation est mesurée.

## 4. Flux, un passage

- Pour N donné, le flux est le préfixe [0, N), en tessons pris dans l'ordre.
- Dans un tesson, les 100 × 48 paires (établissement, origine) sont ordonnées par la permutation
  clé `key("HOWM2-C1-order", graine, tesson, i)`.
- Ce même ordre vaut pour les trois systèmes et pour les deux tailles : à graine égale, le flux de
  N = 100 est le premier tesson de N = 1 000.
- Lots : 32 paires consécutives.
- Pas prévus : N × 48 / 32, soit 150 pour N = 100 et 1 500 pour N = 1 000.
- Chaque position consommée (tesson, décalage) est journalisée. Un contrôle vérifie l'égalité
  exacte au flux prévu : ni rejeu, ni second passage.

## 5. Entraînement

**Optimisation (R1).**
- Adam (lr = 3e-4, β et ε par défaut), sans scheduler.
- Perte `total_loss` avec les échelles s_f de R1 ; présence exclue comme en R1.
- Têtes et initialisation de R1 : `torch.manual_seed(graine)`.

**Évaluation sur CVAL.**
- Tous les 500 pas, et à la fin.
- Meilleur checkpoint : perte CVAL normalisée la plus basse, au sens de R1 (Σ moyenne_f / s_f).
- Patience : 6 évaluations.
- À chaque évaluation, on journalise la perte d'entraînement par famille et la perte CVAL par
  famille.

**Graines** : {0, 1, 2}.

**Exécution.**
- 1 fil torch par processus, au plus 4 processus en parallèle.
- Checkpoint au plus toutes les 400 s et en fin de commande : poids, optimiseur, état RNG torch,
  position, journal. Python et numpy n'interviennent pas dans l'entraînement.
- La reprise est exacte, ce qu'un test vérifie.

**C.2a.** Fenêtre [0, H), alignée à droite dans le lot. Les heures antérieures au début d'une origine
sont absentes : ni nœud présent, ni arête. Le reste est l'encodeur H1, inchangé, dérivé du source
gelé par substitutions déclarées (test T-C06′).

**C.2b.**
- Les 8 intercepts L2 bruts, sans normalisation, sont ajoutés à l'entrée de la tête de lecture.
- Les colonnes supplémentaires partent de 0. Tous les autres paramètres sont initialisés comme C.1
  à graine égale (test T-C17).

## 6. Sélection, sur CVAL seulement

- **Checkpoint**, par (système, N, graine) : `best.pt` selon CVAL.
- **Point retenu** : la plus grande N où les 3 graines sont achevées, soit 1 000 si tout s'achève.
  Si une exécution ne peut pas s'achever dans le budget, elle est signalée ; aucun point n'est
  substitué en silence.
- **Système de tête** : la plus faible moyenne, sur les 3 graines, de la meilleure perte CVAL
  normalisée, au point retenu.

## 7. Gel F-C1, avant toute génération de CEVAL

**Contenu consigné** (`F_C1.json`) :
- empreintes du code : `src/hospitalos/howm2/*.py`, `scripts/howm2_c1*.py`, `corpus.code_hashes()` ;
- empreintes des poids `best.pt` et des configurations des 18 exécutions ;
- définitions des références :
  - L2 = `ladder.l2_predict` avec `B0_PARAMS.json` ;
  - L2c = `L2C_PARAMS.json`, avec son empreinte ;
  - L4 = filtre de l'échelle de A ;
- empreinte du script d'analyse ;
- liste fermée des comparaisons finales (§ 8 à § 11).

Aucune adaptation n'est permise après l'ouverture de CEVAL.

## 8. Campagne finale unique

**Populations.** CEVAL (200) et DIAG (100), origines C1, horizons 1, 6 et 24, protocole de score de
R1.

**Systèmes et références évalués :**
- **Modèles** : pour chaque système et chaque N ∈ {100, 1 000}, le mélange équipondéré des 3
  graines (`ensemble_logscores`).
- **Références** : L0 à L5 par le code de l'échelle de A (dont L2 et L4), et L2c par le code de
  A2.L2C, tous sur les origines C1.

**Sortie.** Par établissement : [somme des NLL, n] par (système ou niveau, horizon, famille).

## 9. Critère principal (N7′)

**Statistique.** ΔC(h) = L(R) − L(modèle), où :
- L est l'agrégation de R1 : moyenne non pondérée des NLL moyennes par famille présente, sur
  ready, transport, nettoyage, confirmation, présence, arrivées et soins, autorisation exclue ;
  calculée par établissement, puis moyennée sur les établissements, équipondérés ;
- le modèle est le mélange des 3 graines au point retenu.

**Choix de la référence R.**
- **Niveau** : l'agrégat de R1, **par horizon**, et non par famille.
- **Règle** : R est celle de {L2, L2c} qui a le plus petit L moyen sur CEVAL.
- **Incertitude** : le choix est **refait dans chaque réplique** du bootstrap, ce qui inclut
  l'incertitude de sélection. Le choix est symétrique et n'utilise jamais les résultats des
  modèles.

**Bootstrap.** Grappes d'établissements, B = 2 000, graine `key("HOWM2", "C1", "bootstrap") mod 2^31`.

**Verdict, par système :**

| Verdict | Condition |
|---|---|
| `C1_BAT_REF` | borne basse > 0 à H6 **et** à H24 |
| `C1_NE_BAT_PAS_REF` | borne haute < 0 à H6 **et** à H24 |
| `C1_INDETERMINE` | sinon |

Le verdict de la tranche est celui du système de tête (§ 6). Les verdicts des trois systèmes sont
rapportés.

**Portée.** Ce verdict porte sur la **prévision** sur HOWM-1, dans ce protocole. Il ne dit rien d'un
avantage décisionnel, ni d'hôpitaux réels.

## 10. Lecture principale : ρ (N8′)

**Familles** validées en A : ready, confirmation, présence, arrivées, soins.

**Agrégat.** ρ(h) = (L_R − L_modèle)/(L_R − L_L4) sur ces familles. R est le choix de l'agrégat
pour l'horizon (§ 9), refait dans chaque réplique.

**Par famille.** ρ_f, avec le même R.

**Publié à chaque horizon et pour chaque famille :**
- L_modèle, L2, L2c et L4 ;
- le gain absolu L_R − L_modèle ;
- le dénominateur L_R − L_L4 ;
- tous avec leur IC à 95 % (bootstrap ci-dessus).

**Ratio instable.** Un ratio est déclaré **instable**, et non présenté comme une estimation robuste,
si l'IC à 95 % de son dénominateur contient 0 ou si sa borne basse est < 0,02 nat (δ_id). Aucun
autre seuil n'est introduit.

**Ambition.** ρ ≥ 0,5 sur l'agrégat, à H6 et à H24, en estimation ponctuelle. Libellé
`AMBITION_ATTEINTE` ou `AMBITION_NON_ATTEINTE`.

## 11. Autres comparaisons pré-listées (descriptives)

- **Loi d'échelle** : L(modèle, N) pour N ∈ {100, 1 000} sur CEVAL. Avec deux points seulement,
  aucun ajustement de forme n'est revendiqué.
- **DIAG** : mêmes grandeurs qu'au § 9 et au § 10, sans verdict, sans sélection ni réentraînement.
  Les empreintes des poids sont égales à celles de F-C1.
- **Pertes** : entraînement et CVAL par famille, issues des journaux.
- **Calibration** (PIT à la première apparition) et **sondes de θ** : exécutées seulement s'il reste
  du budget après la campagne finale ; sinon rapportées comme **non exécutées**. Elles n'ont aucun
  effet sur le verdict.

## 12. Budget (`BUDGET_LEDGER_HOWM2_C1`)

17 400 s de temps mural, CPU, 0 €. Plafonds : 540 s par commande, 120 s par commande de test. Aucun
transfert depuis une autre enveloppe.

| Lot | Plafond (s) | Note |
|---|---:|---|
| C.SETUP | 700 | consignation, tests, contrôle des partitions |
| C.GEN | 700 | CTRAIN 0–999, CVAL 48 |
| C.PILOT | 300 | facteur de coût, empreinte mémoire, projection |
| C.TRAIN.100 | 1 100 | |
| C.TRAIN.1000 | 9 900 | |
| C.EVAL | 3 000 | F-C1, génération de CEVAL et des origines DIAG, références et modèles |
| C.REST | 600 | rapport, paquet, reçu |
| Non alloué (réserve) | 1 100 | |

**Écart avec le plan de calcul C1 amendé.** Les lots C.GEN1, C.REF, C.EVAL1 et C.REST1 sont
regroupés autrement : les références sur CEVAL sont calculées **dans** la campagne finale, après
F-C1, pour ne pas ouvrir CEVAL avant le gel. Le total, 17 400 s, est inchangé.

**Arrêt.** Si le pilote projette un dépassement, la partie dépendante est arrêtée et une question
précise est préparée. Aucune exigence n'est réduite en silence.

## 13. Invocations hors registre, déclarées

Avant l'ouverture du registre C1 ou en dehors de lui, trois invocations de développement ont été
faites, sans mesure ni lecture de données d'évaluation :
- deux imports de vérification du module `c1` (environ 2 s chacun) ;
- une collecte pytest échouée sur le chemin d'import (environ 1 s).
