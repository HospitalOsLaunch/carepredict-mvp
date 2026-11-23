# HOWM-2 — Proposition bornée après la tranche A : « C sur HOWM-1, puis transfert »

Statut : **proposition, non exécutée**. Rien n'est lancé sans un accord adopté (voir
`ACCORD_HOWM2_C1_A_ADOPTER.md`). Statuts inchangés : `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`.

## 1. Pourquoi cette proposition, à partir des verdicts de A

| Constat de A | Conséquence pour B, C et D |
|---|---|
| `HOWM1_DISCRIMINANT` : M_pub = 0,099 nat à H6 et 0,141 à H24, n ≈ 22 à 34 établissements suffisent pour M_pub/2 | Le programme (§ 6) prévoit : « le nul de R1 vient de l'apprentissage ; passer directement à C sur HOWM-1 ». Le monde v2 (B) n'est pas un préalable à la question de **prévision**. |
| R1 sur-apprend (instrumentation) : la perte TRAIN baisse, la perte VAL monte après 1 à 20 époques ; 195 et 217 items de transport et de nettoyage | Le premier facteur à isoler est la **donnée** (C.1), avec des établissements neufs vus une seule fois. |
| Aucun état caché récupérable : π ≤ 0 ; la marge est structurelle (lois et θ) | Le seul « contexte » utile sur HOWM-1 est l'**adaptation de θ par établissement**, d'où un contexte public long (C.2). Le modèle de séquence C1 (événements bruts, plongements d'entités) n'apporte pas d'hypothèse distincte testable ici ; il est **reporté** (§ 6). |
| `MARGE_DECISIONNELLE_LT_15` : même L4 perd 28,7 contre la règle depuis l'état public | Le diagnostic **décisionnel** de D n'est **pas ouvert** sur HOWM-1 : aucun prédicteur ne peut y atteindre le seuil depuis l'état public. D se limite au transfert du **score**. |
| La sous-couverture à H1 vient du départ depuis l'état public | La couverture est rapportée hors intervalles dégénérés, avec PIT randomisé, et à titre secondaire. |
| G_alt de HOWM-1 ne simule qu'une file (transport et nettoyage) | Le transfert vers « G_alt » n'est pas possible sur HOWM-1. Il est reporté à B (G_alt-v2). |

**B est reporté, non abandonné.** Le constat décisionnel (marge < 15 même avec L4) est exactement
la raison d'être de B : un monde où l'état caché laisse des traces publiques et où les décisions en
dépendent. B sera proposé séparément, quel que soit le résultat de C1, et après la revue de
l'advisor (§ 8.4 du programme).

## 2. Ce que C1 mesure

Une seule question : **un réseau de la famille H1, entraîné sur assez d'établissements neufs, bat-il
B0-local-long (L2) sur HOWM-1, et quelle part de l'écart L2 − L4 récupère-t-il ?**

Systèmes, une variation à la fois (§ 5 C du programme) :

| Système | Définition | Facteur isolé |
|---|---|---|
| **C.1** `H1-scale` | H1 de R1 inchangé (code gelé F1, W = 24 h), entraîné en un seul passage sur un flux d'établissements neufs | Données |
| **C.2** `H1-long` | Même architecture et mêmes têtes. Le contexte couvre **tout le passé public** depuis l'heure 0, et les statistiques de fenêtre locales sont remplacées par celles de L2 (`howm2.ladder.window_long`). Nouveau code dans `src/hospitalos/howm2/`, sans toucher `nets.py`. | Contexte |

**Références**, toutes déjà implémentées en A : B0-pool (L0), B0-local (L1), B0-local-long (L2), et
le filtre L4 comme plafond.

## 3. Données

- **Flux d'entraînement.** Nouvelle partition `HOWM2_CTRAIN`, REF, de taille 10 000, enregistrée à
  l'exécution comme en A avec les clés `key("HOWM1", "HOWM2_CTRAIN", i)`. Les points d'échelle sont
  des préfixes du flux : 100, 1 000, 10 000. Chaque établissement est vu **une seule fois**
  (un passage), et un journal des clés consommées le prouve.
- **Origines.** Celles de TRAIN dans R1 : `range(24, 166, 3)`, soit 48 par établissement. Elles sont
  fixées avant le gel et identiques pour l'entraînement, la sélection et l'évaluation, ce qui corrige
  le décalage d'origines TRAIN/VAL constaté en A (§ 7.1).
- **Sélection et arrêt.** Nouvelle partition `HOWM2_CVAL`, 48 REF, mêmes origines.
- **Évaluation.** Nouvelle partition `HOWM2_CEVAL`, 200 REF, mêmes origines. Elle est lue une fois
  par système, **après** le gel F-C1. L2 et L4 y sont calculés par le code de A, inchangé.
- **Transfert (D).** `HOWM2_DIAG` (100), dont l'échelle est déjà mesurée en A, sans réentraînement.
- **Interdits.** Ne sont lus ni la réserve HOWM-1, ni DEVTEST, ni DIAG-DEV. `HOWM2_REF` n'est pas
  utilisé pour entraîner ni sélectionner.

## 4. Entraînement

- Optimiseur, lot (32 origines), têtes et pondération des familles **identiques à R1** : échelles
  s_f de `LOSS_SCALES.json`, inchangées, pour isoler la donnée.
- Un seul passage sur le flux, sans répétition d'établissement.
- Arrêt sur la perte normalisée de `HOWM2_CVAL`, évaluée tous les 500 pas. On garde le meilleur
  checkpoint, avec une patience de 6 évaluations.
- **La perte d'entraînement est journalisée** par famille, à chaque évaluation (défaut F4 de R1).
- Graines : 3 à 100 et à 1 000 pour C.1 et C.2. À 10 000, une graine par système, puis 2 graines
  supplémentaires du meilleur système selon `HOWM2_CVAL`, si le budget le permet (échelle de
  réduction déclarée dans le plan de calcul).
- Le point d'échelle retenu est le plus grand où 3 graines existent.
- lr = 3e-4, la valeur sélectionnée en R1 pour H1. Il n'y a pas de recherche d'hyperparamètres.

## 5. Mesures

- **Critère principal**, fixé avant lecture (§ 5 C du programme), sur `HOWM2_CEVAL` :
  - borne basse de l'IC à 95 % de L(L2) − L(modèle) **> 0 à H6 et à H24** ;
  - modèle = moyenne des graines au point retenu ;
  - agrégation R1 (familles présentes, autorisation exclue) ;
  - bootstrap par grappes, B = 2 000, graine `key("HOWM2", "C1", "bootstrap")`.
- **Ambition** : ρ = (L2 − modèle)/(L2 − L4) ≥ 0,5 à H6 et à H24, sur les familles validées en A
  (ready, confirmation, présence, arrivées, soins). La valeur ρ toutes familles est rapportée à titre
  descriptif.
- **Loi d'échelle** : L(modèle) à 100, 1 000 et 10 000, avec un ajustement descriptif
  a + b·N^(−c), rapporté quel que soit le résultat.
- **Secondaires** :
  - calibration (PIT à la première apparition, couverture hors intervalles dégénérés) ;
  - sondes linéaires de θ (médianes transport, nettoyage, ready) depuis l'état du réseau, comparées
    au R² de la moyenne postérieure L4, et non au hasard ;
  - pertes TRAIN et VAL par famille.
- **D, transfert** : mêmes mesures sur `HOWM2_DIAG`, sans réentraînement (hash des poids identique),
  comparées à L2 et L4 déjà mesurés en A. Pas de diagnostic décisionnel.

## 6. Hors périmètre de cette proposition

- B (monde v2, G_alt-v2, porte G_ID) : proposé séparément.
- C1 « modèle de séquence » : reporté.
- 100 000 établissements et tout GPU.
- Décisions et lecture de la réserve.
- JEPA, boucle fermée, P6, AJ-H.
- Push, merge, rebase.

## 7. Issues et ce qu'elles apprendront

| Issue | Lecture |
|---|---|
| C.1 passe le critère | Le facteur limitant de R1 était la donnée. |
| Seul C.2 passe | Le facteur limitant était le contexte (adaptation de θ). |
| Aucun ne passe, mais la loi d'échelle descend | Plus de mondes pourraient suffire ; décision humaine sur 100 000 ou le GPU. |
| Aucun ne passe, loi d'échelle plate | La famille H1 n'apprend pas ces lois ; revoir l'architecture avant B. |
| Gain en REF, perte en DIAG | Le modèle a appris la population REF, pas le mécanisme commun DIAG. |
