# Protocole HOWM-INT-1 — campagne intégrée du world model hospitalier

**Version** P1 du 17 novembre 2026 (décision n° 9).

**Consignation.** Ce protocole est consigné au registre INT-1 (note `int1_protocol`) **avant tout apprentissage
comparatif**. Le plan réalisable (§ 10) y est ajouté après le profilage d'apprentissage, par une note
`int1_plan`, elle aussi avant les apprentissages comparatifs. Un gel (`FREEZE_INT1.json`, note `int1_freeze`)
précède l'unique campagne finale.

**Statuts :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Portée.** Benchmark **synthétique**. Aucun résultat ne vaut transfert vers des établissements réels.

**Connaissance antérieure.** La campagne est conçue après B-FRAG 2 et le pilote W :

- gain faible de F sur R1 ;
- comparaison W − D indéterminée ;
- déficit de W concentré dans SF1.

## 1. Monde (code `src/hospitalos/howmint/`)

Opérateur HOWM-1 gelé au pas de 15 minutes. Les extensions sont dans une sous-classe (`EngineN`) et un fournisseur
dérivé (`ProvN`) ; aucune source gelée n'est modifiée.

| Mécanisme | Rôle | Paramètres et unités | Test |
|---|---|---|---|
| M1 nettoyage partagé | lits sales → libres | `c_cl` agents, `cl_min` minutes | I1, I5 |
| M2 transport partagé | sortants prêts → départ | `c_tr` agents, `tr_min` minutes | I5 |
| M3 compatibilité isolement | placement | lits isolables par unité | I8 |
| M4 effectifs et renforts infirmiers | soins couverts | effectifs par heure, offres du pool (latence, absence) | I4 |
| M5 transfert interne avec lit retenu | couplage amont → aval | probabilités de transfert par paire d'unités | I2 |
| M6 aval externe | sorties limitées | créneaux par jour, part des séjours concernés | I3 |
| M7 calendrier public de baisse du nettoyage | contrainte connue | jour, heures, agents en moins | (B-FRAG) |
| M8 régimes cachés et préparation selon la charge | aléa interne | `m2`, `m3_kappa` | (HOWM-1) |

**Deux unités = monde B-FRAG 2.**

- Plan D2, unités A et B, mêmes lois.
- Famille tirée par clé de structure, donc décorrélée de l'indice.
- M5 et M6 désactivés ; occupation initiale selon la règle gelée (test I9).

**4, 8 et 12 unités.**

- **Régimes :** nominal (30 %), tendu (35 %), fragile (35 %), tirés par clé ; marge physique de 0,40–0,60, 0,25–0,40 et 0,15–0,30.
- **Goulots :** 0, 1 ou 1–2 parmi nettoyage, transport, aval, transfert, calendrier.
- **Topologie :** la moitié amont alimente l'aval.
- **Combinaisons réservées au test** (exclues de TRAIN, VAL et DEV par une règle déterministe) : {aval, calendrier} et {transfert, transport}, à l'intensité 1,3.

**Aléas.** Ils sont indexés par (épisode, réalisation, primitive, entité ou événement), ce qui donne des nombres
aléatoires communs entre politiques (test I7).

**Convention temporelle.** Une décision au tick t ne voit que les observations disponibles strictement avant 15·t
minutes (test I6). Chaque politique reçoit **son propre** historique public ; aucun état observé sous une autre
politique n'est réutilisé.

**Qualification sous politiques fixes** (`QUALIFICATION_DEV.json`, registre #13 puis #19) :

- **Ruptures.** Les régimes ne sont pas tous saturés. Structures avec rupture : nominal 0–7 %, tendu 10–43 %,
  fragile 44–80 %.
- **Règles simples.** Elles suffisent dans une partie des cas :
  - 2 unités, une seule décision : 63 % des structures fragiles et 93–95 % des nominales et tendues ;
  - 4 à 12 unités sur 24 h : 87–100 %.

  L'extension est donc surtout descriptive.
- **Révision faite à la qualification, avant toute comparaison :** les renforts partagés passent à une intensité
  k = n/2 agents, et une action d'achat de créneaux d'aval est ajoutée.

## 2. Décisions, catalogue, engagements

- **Tâche principale (2 unités) :** décisions à t = 0, 24, …, 144 h ; horizon de 168 h.
- **Extension :** t = 0, 6, 12, 18 h ; horizon de 24 h.
- **Origine H0** tirée par clé d'épisode (36–72 h, ou 36–84 h).
- **Catalogue :**

| Action | Contenu | Coût |
|---|---|---|
| `none` | aucune | 0 |
| `coord` | action historique : transports + nettoyage « compat » 24 h ; admissible seulement si elle agit | 0 |
| `cl_w1..4`, `tr_w1..4` | +k agents sur un créneau de 8 h différé | 8k heures-agents |
| `staff_<unité>_w1..2` | +1 IDE du pool | 8 h |
| `av` | +max(1, n/4) créneaux d'aval pendant 24 h | 8 h |

- **Budgets :** 8·n/2 heures-agents par jour, 7 fois plus par semaine (2 unités : 8 et 56).
- **Interdits :** cumul sur un même créneau, annulation, répétition gratuite de la coordination, remise à zéro du
  budget en projection (budgets lus dans les engagements du moteur), accès aux arrivées futures.
- **Séquences candidates** (communes à tous les planificateurs) :
  - (a0, rien) pour tout a0 admissible ;
  - (a0, a0 redécidé à la décision suivante) pour les renforts ;
  - (rien, coordination).

  Seul a0 est exécuté.
- **Horizon de projection :** 48 h (décisions quotidiennes) ou 24 h (toutes les 6 h).
- **Opérateur de choix :** coût prédit minimal ; égalité → moins d'heures-agents, puis indice.

## 3. Partitions (par structure, nouvelles)

| Partition | Structures | Usage |
|---|---|---|
| `INT_TRAIN` | palier 1 = 0–999 ⊂ palier 2 = 0–9 999 ; tailles par clé 60 / 20 / 20 % (2 / 4 / 8 unités) | apprentissage |
| `INT_VAL` | 0–299 (même mélange), K = 4 futurs communs | sélection et arrêt |
| `INT_DEV` | qualification, diagnostics, propagation, diagnostic privilégié | développement |
| `INT_TEST_MAIN` | 200 structures à 2 unités × 3 épisodes × 4 futurs | comparaison principale ; sous-panel F/R1 = structures 0–31 |
| `INT_TEST_EXT` | 96 (paires → 4 unités, impaires → 8 unités) × 3 × 4 | extension descriptive |
| `INT_TEST_COMBO` | 48 (combinaisons réservées, intensité 1,3, régime fragile) × 3 × 4 | généralisation descriptive |
| `INT_TEST_12` | 48 à 12 unités × 3 × 4 | généralisation de taille, jamais vue en apprentissage |

Les anciennes CONF et CEVAL, la réserve HOWM-1, DEVTEST et DIAG-DEV restent fermées.

## 4. Corpus

- **Situations.** 3 situations de décision par structure, une par épisode e = 0, 1, 2. Pour chacune :
  - l'heure H0 est tirée par clé ;
  - la **provenance** est tirée par clé : règle historique 40 %, exploratoire admissible 40 %, règle robuste 20 % ;
  - 0 à 2 décisions de provenance précèdent la situation.
- **Modèles intermédiaires.** Ils peuvent servir de provenance sur TRAIN seulement ; c'est alors journalisé.
- **Séquences.** Toutes les séquences candidates à 2 unités ; à 4 et 8 unités, `none`, `coord` et 18 autres tirées
  par clé.
- **Futurs.** K = 2 futurs vrais communs par séquence ; K = 8 sur le sous-ensemble fixé `s mod 20 = 0`.
- **Enregistrement** toutes les 2 h, sur 72 h (2 unités) ou 24 h : état vrai par unité (9 variables), attente par
  unité, patients ≥ 24 h.
- **Entrées publiques** : graphe de `features.py`, identique pour W et D.
- **Pas de distillation.** Les conséquences viennent du moteur vrai ; F n'intervient pas.

## 5. Modèles

- **W (`GraphWM`)** :
  - encodeurs de l'historique public (nœuds unités 54, ressources 10, global 8) ;
  - état explicite de 9 variables réinjecté à chaque pas, latent récurrent par nœud ;
  - messages unités ↔ ressources et unités ↔ unités (transferts observés) ;
  - GRU partagés, pilotés par le calendrier des interventions ;
  - sorties sous contraintes par construction : fractions de lits par softmax (conservation), files emboîtées ≥ 0,
    coûts ≥ 0, probabilité de rupture ;
  - **S** : d = 128, 317 460 paramètres ; **M** : d = 320, 1 899 540 paramètres ;
  - 3 graines par taille et par palier. Le palier 2 continue le palier 1 depuis son meilleur checkpoint : c'est une
    trajectoire d'apprentissage avec curriculum, pas un entraînement indépendant.
- **Incertitude.** W prédit une **espérance**, plus une probabilité de rupture par unité. Aucune calibration
  probabiliste n'est revendiquée ; l'anticipation est évaluée à part (AUC, Brier, déciles de calibration).
- **Pertes** (poids fixés) :
  - états standardisés ×1 ;
  - coûts par pas ×1 ;
  - coût cumulé de l'horizon de projection ×1 ;
  - **effets appariés** ×5 ;
  - rupture (BCE) ×0,5.

  Normalisation sur TRAIN seulement ; curriculum d'horizon de 12 → 24 → 36 pas.
- **Optimisation.** Adam (S 10⁻³, M 5·10⁻⁴), lots de 4 situations, écrêtage à 1. Au plus **4 variantes courtes de
  recette** avant les apprentissages retenus.
- **Sélection et arrêt (fixés avant chaque apprentissage comparatif) :**
  - évaluation VAL toutes les 1 000 mises à jour, sur 300 structures et les mêmes futurs ;
  - **critère** : regret relatif moyen de décision sur les situations VAL à 2 unités ; égalité → RMSE des effets ;
  - rapportés ensemble : regret, RMSE des effets, Spearman, MSE des états, par taille ;
  - arrêt sur patience de 8 évaluations, plafond de mises à jour ou part de mur allouée.
- **D (références directes, mêmes entrées et mêmes descripteurs de séquence) :**
  - Ridge base + effet (α ∈ {1, 100}, interactions descripteur × unités agrégées) ;
  - HGB (profondeur 4 ou 8) ;
  - **DSet**, DeepSets direct de capacité comparable à W-S, entraîné sur coût cumulé et effets appariés, **sans**
    cibles de trajectoire.

  Le développement de D a son propre budget (§ 10).

## 6. Références et planification

| Référence | Méthode |
|---|---|
| Règle historique | gelée |
| Règle robuste | publique : seuils fixés a priori sur les lits sales et les sortants en attente, puis aval, puis coordination |
| R1 | dynamique L2, rejouée à chaque décision sur l'historique propre |
| F | chaîne historique B-FRAG (postérieur L4, nowcast L4-N, simulateur), rejouée à chaque décision ; 2 unités seulement |

- **Opérateur commun** pour R1, F, D et W : mêmes séquences, horizon, contraintes et départage.
- **F** accède aux lois structurelles du générateur, ce qui n'est pas le cas de D et W. **W** a des cibles de
  trajectoire que D n'a pas.
- **B\*** : meilleure référence peu coûteuse parmi D (Ridge, HGB, DSet) et les règles. Elle est choisie sur un
  panel VAL en boucle fermée (40 structures VAL à 2 unités × 1 épisode × 2 futurs, 7 jours), par attente moyenne.
- **W principal** : ensemble des 3 graines de la taille choisie sur ce même panel, au palier 2.

## 7. Questions et analyses

- **Comparaison principale unique :** sur MAIN, attente sur 7 jours de B\* moins celle de W (> 0 si W est
  meilleur).
  - IC apparié à 95 % par bootstrap des structures (B = 2 000, graine 20261117).
  - `GAIN_W_ETABLI` si la borne basse est > 0 ; `W_INFERIEUR` si la borne haute est < 0 ; sinon `INDETERMINE`.
  - Une différence non significative n'établit pas l'équivalence.
- **Gain relatif.** Il est calculé sur les moyennes agrégées, avec ratio rééchantillonné. On rapporte si la cible
  de 5 % est atteinte en estimation et si elle est soutenue par l'intervalle.
- **Garde-fous :** soins non couverts, rejets, ruptures, état terminal, blocages, heures-agents, répartition par
  unité. Aucune non-infériorité n'est revendiquée.
- **Descriptif :**
  - distribution des effets et pires cas ;
  - familles ;
  - sous-panel F/R1 (sur les mêmes structures que W, D et les règles) ;
  - EXT, COMBO, 12 unités ;
  - anticipation ;
  - coûts de décision (CPU, séparés du mur) ;
  - courbes données / capacité / calcul.
- **Ablations VAL** (palier 1, 1 graine) : sans historique, sans messages, S contre M. Diagnostiques seulement.
- **Propagation** (DEV, contrôles appariés) : suppression du lit retenu en transfert (le transfert a toujours
  lieu), et aval illimité. Mesure de Δ attente par unité, en vérité et selon W ; tout mélange de canaux est
  signalé.
- **Diagnostic SF1** (TRAIN et VAL) : ajustement d'un petit lot, erreurs d'effets, erreurs sur la meilleure action
  et sur les écarts, dérive avec l'horizon, couverture des créneaux et des régimes.

## 8. Tests

- **Monde :** I1–I9.
- **À ajouter avant le gel :**
  - partitions disjointes et combinaisons réservées absentes de TRAIN/VAL ;
  - absence d'entrée privée ;
  - déroulé W causal ;
  - rechargement des checkpoints ;
  - invariance des sources historiques.

## 9. Règles d'arrêt et d'intégrité

- Une seule campagne finale, après le gel ; aucun changement d'effectif après observation.
- Un défaut d'implémentation se corrige avant le gel, avec une note.
- Pas de push ni de publication externe.

## 10. Plan réalisable (consigné avant les apprentissages comparatifs)

**Mesures, en concurrence réelle** (génération sur 4 processus, plus 2 apprentissages) :

| Élément | Mesure |
|---|---|
| Corpus | 2,1 s de mur par structure à 4 processus (palier 1 : 2 120 s pour 1 000 structures, 48 Mo) |
| W-S | 10,1 mises à jour/s sur 1 fil (lots de 4 situations, environ 94 séquences) |
| W-M | 2,7 mises à jour/s |
| Mémoire | 2,1 Go par processus au palier 1 |
| Décision W (non entraîné) | environ 0,1–0,3 s de CPU hors contention |
| F à Md = 4 | 3,2 s de CPU par décision |
| R1 à Md = 4 | 1,6 s de CPU par décision |

Coût du branchement par mesure (`COSTPILOT0`) : 0,03 s (2 unités, 48 h) ; 0,08 s (8 unités, 24 h) ; 0,09 s (12 unités).

**Plan :**

| Élément | Plan | Allocation |
|---|---|---|
| Corpus | palier 2 = `INT_TRAIN` 1 000–9 999, même générateur ; VAL 300 structures à K = 4 | ≈ 6 h de mur |
| W-S palier 1 | 3 graines × ≤ 30 000 mises à jour, patience 8 | ≈ 1 h de mur par graine |
| W-M palier 1 | 3 graines × ≤ 20 000 mises à jour | ≈ 2 h par graine |
| Palier 2 | continuation depuis le meilleur checkpoint du palier 1 : S ≤ +30 000, M ≤ +20 000, même patience | — |
| Mémoire au palier 2 | tableaux empaquetés en memmap partagé | — |
| D | Ridge et HGB (paliers 1 et 2) ; DSet (paliers 1 et 2, mêmes règles d'arrêt) | ≈ 1 h |
| Ablations VAL | W-S palier 1, graine 0, sans historique et sans messages (≤ 30 000 mises à jour) | — |
| Panel VAL de choix de B\* et de la taille de W | 40 structures VAL à 2 unités × 1 épisode × 2 futurs, en boucle fermée sur 7 jours | — |
| Évaluation finale | MAIN 200 × 3 × 4 ; SUB32 (F, R1 à **Md = 16**) ; EXT 96 × 3 × 4 ; COMBO 48 × 3 × 4 ; SIZE12 48 × 3 × 4 | projetée à ≈ 9–11 h de mur, dont F et R1 ≈ 6 h |

Les politiques de MAIN sont : historique, robuste, D (Ridge, HGB, DSet), W-S et W-M (ensembles).

**Précision attendue.** Sur le pilote VAL, le regret par situation a un écart-type d'environ 300 à 400
patients-minutes sur 48 h. Avec 200 structures, 3 épisodes et 4 futurs sur 7 jours, la demi-largeur attendue de
l'IC de B\* − W est de l'ordre de quelques centaines de patients-minutes par semaine. À préciser avec le panel
VAL en boucle fermée.

**Réserve.** Le coût de l'évaluation finale (lot INT.EVAL, 12 h) et de la livraison (INT.REST, 2 h) est réservé
avant tout apprentissage. Le lot INT.LEARN (30 h) couvre ≈ 21 h projetées. La réserve est de 7 h.
