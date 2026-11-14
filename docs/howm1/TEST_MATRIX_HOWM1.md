# HOWM-1 — Matrice de tests R0+R1

**Statut :** proposition. Aucun de ces tests n'existe encore ni n'a été exécuté.

Chaque ligne est une **assertion vérifiable**, avec son mode d'échec attendu. Une suite verte
signifie seulement que ces assertions tiennent. Ce n'est pas une déclaration d'absence de
défauts.

**Conventions des colonnes :**
- **Quand** : `R0` pour le code du monde, `G0` pour le gel du générateur, `P` pour le pilote,
  `R1` pour l'entraînement, `F1` pour le gel des modèles, `REST` pour la restauration.
- **Bloquant** : un échec arrête l'étape suivante.

## 1. Frontière d'information (T-INF)

| ID | Assertion | Construction du test | Quand | Bloquant |
|---|---|---|---|---|
| T-INF-01 | Toute entrée à t ne contient que des observations avec `available_at ≤ t` et `event_time ≤ t` | injecter une observation `available_at = t + 1 min` ; l'empreinte du tenseur d'entrée est identique avec ou sans elle | R0 | oui |
| T-INF-02 | Aucun champ privé n'atteint `howm.history.build` | liste blanche du schéma ; recherche récursive des clés privées (`true_*`, `theta`, `regime`, `seed`, `establishment_id`) dans l'entrée sérialisée → 0 occurrence | R0 | oui |
| T-INF-03 | Deux vérités privées différentes avec le **même** historique public donnent des sorties identiques (B0, B2, H1, planificateur), au bit près sur CPU déterministe | patron v6 `check_isolation` et P5 T03/T04 ; 20 paires sur VAL | R0, F1 | oui |
| T-INF-04 | Décaler toutes les dates d'un nombre entier de semaines ne change pas les sorties (|Δ| ≤ 1e-6) | décalage +7 j, +364 j (même jour de semaine) | R1 | oui |
| T-INF-05 | Graines, empreintes et identifiants d'établissement absents des variables | recherche des valeurs connues dans les tenseurs ; corrélation nulle exacte (variables absentes) | R0 | oui |
| T-INF-06 | Les caches sont indexés par empreinte de contenu **et** partition ; aucun cache partagé entre partitions | lecture croisée VAL→TRAIN refusée ; empreintes distinctes | R0 | oui |
| T-INF-07 | La sélection des actions candidates ne lit que l'état public | candidats identiques sous deux vérités privées (empreinte) | R0 | oui |
| T-INF-08 | Étiquettes permutées entre établissements de TRAIN : la NLL de VAL ne fait pas mieux que B0-pool au-delà du bruit | entraînement court sur étiquettes permutées (pilote) | P | non (diagnostic de fuite) |
| T-INF-09 | Les chemins `reads_private=True` (sondes, C_param, C_full, oracle) sont refusés comme fournisseurs du planificateur produit | `assert_product_backend` → exception | R0 | oui |

## 2. Invariance (T-EQV)

| ID | Assertion | Construction | Quand | Bloquant |
|---|---|---|---|---|
| T-EQV-01 | Renommer tous les identifiants ne change pas les prévisions par entité, à la permutation près | bijection aléatoire des `subject_ref` ; comparaison entité par entité, tolérance 1e-6 | R1 | oui |
| T-EQV-02 | L'ordre des événements de même horodatage ne change pas l'état construit | 10 permutations ; même x_t et même empreinte d'entrée | R0 | oui |
| T-EQV-03 | H1 est équivariant à la permutation des nœuds dans le lot | permuter les nœuds ; les sorties sont permutées identiquement | R1 | oui |
| T-EQV-04 | Le nombre d'entités est variable sans case fixe : 8, 16, 24 lits ; 2 et 3 unités | passage avant sans erreur ; pas de troncature silencieuse (compte d'entités en sortie = en entrée) | R1 | oui |
| T-EQV-05 | B2 ne dépend que des agrégats : mêmes agrégats et mêmes attributs statiques d'entité ⇒ mêmes sorties | permutation des affectations lit ↔ séjour à agrégats égaux | R1 | oui |

## 3. Opérateur de transition et vérificateur (T-OP)

| ID | Assertion | Construction | Quand | Bloquant |
|---|---|---|---|---|
| T-OP-01 | Conservation : patients entrés − sortis = présents, par unité et à chaque pas | sur 100 déroulés G_main et 100 déroulés de chaque modèle | R0, R1 | oui |
| T-OP-02 | Un lit a exactement un état ; jamais deux séjours dans un lit | vérificateur indépendant sur journal | R0, R1 | oui |
| T-OP-03 | Pas de nettoyage avant le départ ; pas d'admission dans un lit non libre ou incompatible | journaux adverses construits à la main → violation détectée | R0 | oui |
| T-OP-04 | Capacité horaire du transport et du nettoyage jamais dépassée | idem | R0 | oui |
| T-OP-05 | Un renfort ne compte dans la couverture qu'à l'état `present` ; `requested`/`accepted` ne comptent pas | offre acceptée puis absente → couverture inchangée | R0 | oui |
| T-OP-06 | Une sortie n'a lieu que pour une autorisation publiée et non retirée ; le planificateur ne crée aucune autorisation | candidat forgé avec séjour non autorisé → refusé ; retrait d'autorisation → demande annulée et réservation restituée | R0 | oui |
| T-OP-07 | Minimum du prêteur respecté (capacité par prêteur × compétence × heure, règle V5-R01) | deux prêts simultanés au même prêteur → le second refusé | R0 | oui |
| T-OP-08 | Un événement proposé par un modèle qui viole une précondition est **rejeté et compté**, jamais appliqué ni corrigé | sortie adverse « lit libre » pour un lit occupé → `rejected_events += 1`, état inchangé | R1 | oui |
| T-OP-09 | Aucune ressource fantôme : la somme des lits, agents et offres présentes ne dépasse jamais la capacité publiée + offres présentes | 1 000 déroulés libres par modèle | R1 | oui |
| T-OP-10 | Le catalogue d'actions ne contient aucune action médicale ni d'information | énumération du catalogue = {a0, a1, a2, a3} | R0 | oui |
| T-OP-11 | Non-négativité des files, durées et effectifs | propriété sur tous les états visités | R0, R1 | oui |
| T-OP-12 | Le vérificateur est indépendant du simulateur : il ne partage pas sa logique | il recalcule à partir du journal seul ; mutation d'une règle du simulateur → violation détectée | R0 | oui |

## 4. Cycle de vie et mode manuel (T-LIFE)

| ID | Assertion | Quand | Bloquant |
|---|---|---|---|
| T-LIFE-01 | `executed` impossible sans `accepted` antérieur ; `completed` impossible sans `executed` | R0 | oui |
| T-LIFE-02 | Un `refused` ne produit aucun effet sur les ressources | R0 | oui |
| T-LIFE-03 | Une confirmation retardée (`available_at > event_time`) n'est visible qu'à `available_at` | R0 | oui |
| T-LIFE-04 | Les verrous manuels deviennent des contraintes du même générateur de candidats : même empreinte de code, univers restreint | R0 | oui |
| T-LIFE-05 | Une hypothèse non autorisée est simulable mais `approvable=false` | R0 | oui |

## 5. Générateur, appariement, partitions (T-GEN)

| ID | Assertion | Construction | Quand | Bloquant |
|---|---|---|---|---|
| T-GEN-01 | Tirages indexés : même clé ⇒ même tirage, quel que soit l'ordre ou le nombre d'appels | ordre inversé, appels supplémentaires intercalés | R0 | oui |
| T-GEN-02 | Branches action/témoin : les primitives non descendantes de l'action sont identiques | diff des innovations par primitive × entité | R0 | oui |
| T-GEN-03 | Un établissement n'appartient qu'à une partition ; graines disjointes entre partitions | intersection vide | G0 | oui |
| T-GEN-04 | Aucune graine P5 réutilisée | intersection avec `SEEDS_SEALED.json` (comparaison d'empreintes, sans desceller) vide | G0 | oui |
| T-GEN-05 | RESERVE refusée sans jeton ; le refus est journalisé au registre | appel → code de refus, aucun fichier écrit | G0 | oui |
| T-GEN-06 | Les parts du mélange REF (m2/m3 éteints, etc.) observées sur TRAIN correspondent aux parts déclarées dans G0 (test binomial, informatif) | comptage | R0 | non |
| T-GEN-07 | Le corpus est régénérable : régénérer 3 établissements donne des empreintes identiques au manifeste | — | R0, REST | oui |
| T-GEN-08 | G_alt et G_main donnent des lois marginales compatibles sur m0+m1 (même θ) ; écarts rapportés, non corrigés vers un modèle | test KS par délai, informatif | R0 | non |
| T-GEN-09 | Le générateur ne lit aucun résultat de modèle (aucune importation de `howm.models` ni des sorties) | analyse statique des importations | G0 | oui |

## 6. Distributions, calibration, déroulés (T-DIST, T-ROLL)

| ID | Assertion | Quand | Bloquant |
|---|---|---|---|
| T-DIST-01 | Hazards dans (0, 1), survie monotone décroissante, densité sommant à 1 − S(48 h) | R1 | oui |
| T-DIST-02 | La NLL censurée égale la valeur analytique sur un cas jouet (loi géométrique connue) à 1e-9 près | R1 | oui |
| T-DIST-03 | Couverture calculée à partir des réalisations, pas de la dispersion : un ensemble volontairement sur-dispersé et mal centré donne une couverture fausse détectée | R1 | oui |
| T-DIST-04 | Le PIT d'un prédicteur exact (vraie loi du générateur) est uniforme (KS non rejeté à 1 %) | R1 | non |
| T-ROLL-01 | Aucun NaN ou Inf sur 1 000 déroulés libres de 24 h par modèle | R1 | oui |
| T-ROLL-02 | Agrégats = sommes exactes des entités dans chaque trajectoire | R1 | oui |
| T-ROLL-03 | Les modes « déroulé » et « marginal latent » sont rapportés tous les deux ; leur écart est une mesure, pas un critère de réussite | R1 | non |
| T-ROLL-04 | Échantillons communs (CRN) : pour un modèle donné, tous les candidats d'un instant utilisent les mêmes graines d'échantillonnage | R1 | oui |

## 7. Planificateur et comparateurs (T-PLAN)

| ID | Assertion | Quand | Bloquant |
|---|---|---|---|
| T-PLAN-01 | Ensemble de candidats identique (empreinte) pour B0-pool, B0-local, B2, H1, C_param, C_full, oracle | R1 | oui |
| T-PLAN-02 | Le planificateur ne reçoit aucune observation future, que des historiques construits par `howm.history.build` | R0 | oui |
| T-PLAN-03 | Les réalisations de choix (C_*, oracle) et d'évaluation sont disjointes (clés différentes) | R0 | oui |
| T-PLAN-04 | L'oracle est étiqueté plafond dans toutes les sorties ; il n'est jamais comparé comme système | R1 | oui |
| T-PLAN-05 | « Conserver le plan » (a0) et la pratique habituelle sont toujours dans l'univers | R0 | oui |
| T-PLAN-06 | Budget d'échantillons M identique entre modèles ; le temps de calcul est rapporté séparément | R1 | oui |

## 8. Configuration et interfaces désactivées (T-CFG)

| ID | Assertion | Quand | Bloquant |
|---|---|---|---|
| T-CFG-01 | `context=off` : 0 paramètre de contexte ; sorties identiques avec un préfixe d'établissement vide ou plein | R1 | oui |
| T-CFG-02 | `contrast_weight=0` : la perte ne lit aucune branche appariée (compteur d'accès = 0) | R1 | oui |
| T-CFG-03 | `jepa=off` : aucun module JEPA instancié | R1 | oui |
| T-CFG-04 | `stochastic_latent=off` : la mémoire est déterministe ; deux passages donnent la même sortie | R1 | oui |
| T-CFG-05 | Le compte de paramètres rapporté = `sum(p.numel())` mesuré, par module | P, F1 | oui |

## 9. Checkpoints et restauration (T-CKPT)

| ID | Assertion | Quand | Bloquant |
|---|---|---|---|
| T-CKPT-01 | Le checkpoint contient poids, optimiseur, ordonnanceur, RNG torch/numpy/python, position du chargeur, configuration et empreintes de code | R1 | oui |
| T-CKPT-02 | Reprise : n pas interrompus puis k pas repris = n + k pas d'un seul tenant (pertes égales au bit près en mode déterministe CPU, sinon tolérance 1e-6 déclarée) | P | oui |
| T-CKPT-03 | Un checkpoint dont l'empreinte de code ne correspond pas est refusé à la reprise | R1 | oui |
| T-CKPT-04 | Reçu de restauration : extraction neuve, restauration, recalcul d'un sous-ensemble de métriques DEVTEST → égalité | REST | oui |
| T-CKPT-05 | Une graine divergente est journalisée et reprise une seule fois depuis le dernier checkpoint ; sinon elle est déclarée en échec, jamais retirée silencieusement | R1 | oui |

## 10. Non-régression et historique (T-V0)

| ID | Assertion | Quand | Bloquant |
|---|---|---|---|
| T-V0-01 | `git diff 856a57c -- src/hospitalos/decision_support` est vide | R0, F1 | oui |
| T-V0-02 | `tests/decision_support` passe inchangé | R0, F1 | oui |
| T-V0-03 | Régression P5b : sur un échantillon déclaré de parents réservés **déjà lus**, le planificateur v6 retrouve les `plan_id` de `EVAL_CHOICES.json` | R0 | oui |
| T-V0-04 | Les fichiers P5 (rapports, résultats, gels, registre P5) ont les empreintes de `INPUT_PROVENANCE.json` à la livraison | F1 | oui |
| T-V0-05 | Aucun fichier de poids antérieur (`*.pt` hors `evidence/howm1/`) n'est ouvert : aucune occurrence de `torch.load` sur ces chemins (garde-fou par liste de refus) | R1 | oui |

## 11. Budget et exécution (T-RUN)

| ID | Assertion | Quand | Bloquant |
|---|---|---|---|
| T-RUN-01 | Le registre HOWM-1 est chaîné ; toute modification d'un enregistrement bloque le compteur | R0 | oui |
| T-RUN-02 | Lot non autorisé, plafond de lot dépassé, durée prévue > plafond par commande, ou couple (Python, gel) non approuvé ⇒ refus journalisé avant lancement | R0 | oui |
| T-RUN-03 | Aucun processus laissé en arrière-plan : à la fin de chaque commande, aucun processus fils vivant | R0 | oui |
| T-RUN-04 | Le registre P5 n'est ni lu pour du crédit ni prolongé (empreinte d'ancre inchangée) | F1 | oui |

## 12. Ce que cette matrice ne couvre pas

- La **pertinence** des mécanismes synthétiques pour un hôpital réel : aucun entretien, aucune
  donnée.
- La **causalité** réelle des effets d'actions.
- La qualité en **boucle fermée** (R3).
- Les défauts des tests eux-mêmes. Chaque test bloquant aura au moins un cas négatif construit
  (mutation ou journal adverse) qui doit échouer.
