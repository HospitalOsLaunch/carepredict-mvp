# HOWM-1 — Note normative v1.2 (avant G0 et avant tout entraînement)

**Date :** 14 novembre 2026.
**Accord adopté :** `inputs/accord/ACCORD_HOWM1_v1_1_ADOPTE.txt`, SHA-256 `1f530d66…60daef`.
Le relevé de décision est `HOWM1_DECISION_ACCORD.json` (registre HOWM n° 2).

**Ordre de préséance :**
1. l'accord ;
2. cette note ;
3. l'amendement v1.1 ;
4. les documents v1.

Les originaux v1 et v1.1 ne sont **pas** modifiés. Le JSON harmonisé est
`EXPERIMENT_HOWM1_R0_R1_v1_2.json`. Les tests bloquants associés sont ajoutés à la matrice
(§ 8).

## N1. Normalisation des pertes (HOWM-C11-01)

1. **Toutes les pertes sont des NLL de lois discrètes** : probabilité d'un intervalle de
   15 min (hazards), d'un entier (binomiale négative), d'une issue (Bernoulli) ou d'un intervalle
   de 5 min (soins, N3.3). Chaque terme est donc ≥ 0. **Aucune densité continue** n'entre dans
   une perte.
   - La paramétrisation log-normale des soins sert seulement à calculer P(intervalle).
   - Ce choix remplace, pour l'entraînement, la « NLL log-normale » de la conception (§ 4.1) ;
     l'évaluation en utilisait déjà la version discrète (amendement A1.1).
2. **Échelles.** Pour chaque famille f, s_f = NLL moyenne de **B0-pool** ajusté sur TRAIN,
   calculée sur TRAIN seulement.
   - Règle fixée ici.
   - Valeurs calculées après l'ajustement de B0-pool, consignées au registre et gelées avant
     tout entraînement de B2/H1.
   - Elles sont **communes** à tous les modèles, taux d'apprentissage et graines.
3. **Refus.** Le code lève une erreur, et la tranche s'arrête, si s_f ≤ 0, si s_f n'est pas fini,
   ou si s_f < 1e-6 (déclaré « quasi nul »). Il n'y a pas d'epsilon ajouté.
4. **Perte totale :** L = Σ_f moyenne_f(NLL) / s_f. La perte de validation utilise les mêmes
   s_f.

Tests T-NORM-01 à T-NORM-04 :
- refus de s_f négatif, nul, quasi nul ou non fini ;
- NLL discrète toujours ≥ 0 ;
- sens d'amélioration : une loi plus proche de la vérité donne une perte normalisée plus faible.

## N2. Oracle, contrôleurs, marge (HOWM-C11-02)

1. **Disjonction choix/évaluation.** Elle s'applique à B0-pool, B0-local, B2, H1, C_pub-snap,
   C_param et C_full :
   - réalisations de choix : r ∈ {101, …, 108} ;
   - réalisations d'évaluation : r ∈ {1, …, 4} (K_eval = 4) ;
   - les déroulés des modèles utilisent leurs propres graines d'échantillonnage.

   **L'oracle clairvoyant en est exclu.** U\*(w) = min_a U(a, w) est le minimum exact de U sur
   les 16 candidats publics, pour **chaque** réalisation d'évaluation w elle-même. Il n'y a pas de
   tolérance lexicographique. Un éventuel « oracle métier » avec la tolérance 15 et les heures de
   renfort serait étiqueté séparément ; il n'est pas utilisé en R1.

   Ceci corrige T-PLAN-03 v1, remplacé par T-PLAN-03b.
2. **C_full est un contrôleur privilégié évalué, pas un optimum certifié.** Il choisit sur 8
   réalisations de choix, avec un budget fini.
3. **V_param + V_latent est la « marge observée sous information privilégiée ».** Ce n'est ni
   une marge publiquement accessible certifiée, ni la preuve qu'un gain est récupérable depuis
   l'historique public.
4. **Conventions inchangées :**
   - δ_dec = 15 sert au précontrôle seulement ;
   - l'ambition décisionnelle reste 5. Elle est calculée comme
     **D_dec = moyenne [U(choix B0-local) − U(choix H1)]** sur les mêmes cas et réalisations, ce
     qui équivaut à la différence des regrets contre C_full ;
   - une marge faible rend seulement la lecture décisionnelle non informative ; l'étude
     prédictive continue.
5. **C_pub-snap** est le vrai opérateur avec :
   - le **centre du prior de population** pour les paramètres d'établissement ;
   - un régime de ralentissement tiré de sa loi stationnaire ;
   - l'état public à τ seulement.

## N3. Score : cohorte, masque, bornes, cas nuls (HOWM-C11-03)

1. **Cohorte publique C_t.** Ce sont les éléments définis par l'état **public** à t (filtre
   `available_at ≤ t`) :
   - séjours présents ;
   - tâches en service ;
   - demandes en attente ;
   - offres acceptées ;
   - unités × heures.
2. **Labels et masque.** Ils sont dérivés des réalisations **futures** et servent **seulement**
   au score et à la perte, jamais à l'entrée.
   - Pour les soins : M(s, j) = 1 si le séjour s ∈ C_t est **réellement présent** à l'heure j.
   - Ce masque est commun à tous les modèles et indépendant de leurs départs prédits.
   - Le score de soins est donc **conditionnel aux séjours effectivement présents**. La charge
     totale inconditionnelle reste mesurée par le CRPS des trajectoires (minutes de soins
     demandées par compétence, sur déroulés).
   - Test T-MASK-01 : modifier une présence future change le masque et le label, jamais une
     prédiction.
3. **Bornes.**
   - **Hazards** : 192 intervalles de 15 min sur 48 h, depuis le début de l'élément ; le dernier
     état « ≥ 48 h » est la survie S(192).
   - **Soins** : intervalles [0, 5), [5, 10), …, [595, 600), puis [600, ∞), soit 121 intervalles,
     en minutes entières observées. Les soins nuls tombent dans [0, 5), de probabilité F(5) > 0.
     Il n'y a ni epsilon ni retrait.
   - **Arrivées** : entiers ≥ 0.
4. **Correspondance des familles A1.1.**

   | Famille A1.1 | Événement noté |
   |---|---|
   | « départ » | **sortie prête** (`ready`) des séjours publiquement autorisés et non encore prêts à t, tête hazard de la conception § 2.2. Le départ effectif résulte de l'opérateur ; il est évalué par le CRPS |
   | « transport » | durée de service restante des transports **en service** à t |
   | « nettoyage » | durée de service restante des nettoyages **en service** à t |
   | « confirmation » | latence restante des demandes (transport, renfort) en attente de réponse |

   Les éléments en file non démarrés ne sont pas notés en score logarithmique ; ils entrent
   dans le CRPS des files.

   La famille **autorisation médicale** (délai jusqu'à l'autorisation des séjours non
   autorisés) est **apprise et utilisée en déroulé, mais non notée dans Δ_LS**, car elle n'est
   pas listée en A1.1. Elle est rapportée de façon descriptive.
5. **Cas nuls fixés maintenant :**
   - si s_c = 0 sur TRAIN (cible constante), la cible est exclue du CRPS agrégé, et cette exclusion
     est rapportée. La décision dépend de TRAIN seulement, pas d'un modèle ;
   - si la somme du CRPS de référence (B0-local) est nulle, R(h) est déclaré « non défini », sans
     epsilon ;
   - une famille sans élément pour un établissement est exclue pour lui et rapportée (A1.1) ;
   - un élément dont l'issue dépasse la fin des données est censuré à la fin des données.

## N4. Volumes d'évaluation et pilote (HOWM-C11-04)

**M = 16 désigne le total par système.** Un ensemble de 3 graines se partage les 16
trajectoires : 6, 5 et 5.

H1/H6/H24 sont lus dans **les mêmes** trajectoires ; elles ne sont pas multipliées par trois.

| Bloc | Unités | Trajectoires de 24 h (grille pleine) |
|---|---|---|
| Prévision DEVTEST + DIAG-DEV | 36 établissements × 120 origines (heures des jours 2 à 6) × 4 systèmes × 16 | **276 480** |
| Score logarithmique (têtes, sans déroulé) | 36 × 120 × 4 systèmes | 0 déroulé ; 17 280 évaluations de têtes |
| Diagnostic décisionnel | 36 × 4 instants × 16 candidats × (4 systèmes × 16 + 4 évaluation + 8 C_param + 8 C_full) | **193 536** (l'oracle réutilise l'évaluation) |
| Précontrôle VAL | 12 × 4 × 16 × (8 C_pub-snap + 8 C_param + 8 C_full + 4 évaluation) | **21 504** |
| Restauration | sous-ensemble déclaré (§ N5) | ≤ 2 % du bloc Prévision |

**Pilote (lot R1.PILOT, sur VAL uniquement) :**
- il mesure le coût par trajectoire de chaque système et de la vérité, le coût des têtes par
  origine, le temps d'un pas d'entraînement et d'une époque, la mémoire, et le coût d'un paquet ;
- il projette **chaque** lot (R0.PRE, R1.B2, R1.H1, R1.EVAL, R1.REST) à grille pleine × 1,25.

Seuls les paliers déjà déclarés (plan de calcul, § 5) peuvent s'appliquer :
- le palier 1 réduit **le seul diagnostic décisionnel** : 4 → 2 instants, M 16 → 8 ;
- **les origines du score prédictif ne sont jamais réduites.**

Si la projection reste au-delà, c'est l'arrêt, avec livraison de l'état. Aucun repli n'est
décidé sur un résultat d'évaluation.

## N5. Persistance P2 renforcée (HOWM-C11-05)

**Aucun push, merge, rebase ni écriture distante.**

**Quand un paquet est livré** (envoi de fichier dans la conversation) :
- à **G0** ;
- **après chaque exécution complète** (modèle × taux × graine) ;
- à **F1** ;
- en **fin de R1** ;
- **avant toute fin de tour** laissant la tranche inachevée.

**Contenu de chaque paquet :**
- `source_tree.tar.gz` : l'arbre exact de HEAD (`git archive`), commit local fait juste avant ;
  il ne dépend d'aucune base ;
- les checkpoints locaux existants, dernier et meilleur par exécution : poids, optimiseur,
  ordonnanceur, RNG, position ;
- le registre et son ancre ;
- G0 et le manifeste du corpus (le corpus se régénère par sa recette ; il est joint s'il fait
  moins de 50 Mo) ;
- le gel de l'environnement ;
- `RESTORE.md` et `howm_restore.py` ;
- un `SHA256SUMS`.

**Vérification de chaque paquet :**
- extraction dans un dossier neuf ;
- vérification des empreintes ;
- chargement `weights_only=True` d'un checkpoint depuis ce dossier.

Le paquet final s'accompagne d'un **reçu de restauration complet** :
- reprise d'un pas égale au pas ininterrompu ;
- recalcul d'un sous-ensemble déclaré de métriques DEVTEST : 2 établissements, toutes leurs
  origines ;
- corpus régénéré **dans le dossier neuf**, sans lecture de l'espace de travail.

**Coûts imputés :**
- paquets G0 : R0.GEN ;
- paquets intermédiaires : lot du modèle ;
- F1 : R1.F1 ;
- fin : R1.REST.

Les checkpoints locaux sont écrits toutes les ≤ 400 s et en fin de commande.

## N6. Choix d'implémentation fixés avant G0

Chacun vaut pour tous les modèles.

1. **Monde.**
   - Pas de 15 min. `event_time` est un multiple de 15 min ; `available_at` est en minutes
     entières (retards m4).
   - Épisodes de 8 jours débutant un lundi 00:00 (Europe/Paris), entre le 4 janvier et le
     15 mars 2027 (sans changement d'heure).
2. **Politique de collecte du corpus**, identique dans toutes les partitions :
   - aux instants 07/11/15/19 de chaque jour, pratique habituelle avec probabilité 0,5 ;
   - sinon, un candidat tiré uniformément parmi les 16 (clé indexée) ;
   - les actions sont des événements publics.

   Sans ces actions, aucun modèle ne verrait de demande de renfort, et les effets d'actions
   seraient inobservables. Ce n'est pas un choix favorable à un modèle.
3. **Candidats (16)** : a1 {rien, coordonner maintenant les transports des séjours autorisés} ×
   a2 {FIFO, compatibilité d'abord} × a3 {rien, pool IDE→A, pool IDE→B, prêt IDE B→A}.
   - Créneau de renfort : 4 h à partir de l'heure pleine suivante.
   - a0 est le triplet (rien, FIFO, rien) ; c'est la pratique habituelle et « conserver le
     plan », qui coïncident en R1 (instant isolé).
4. **Instants évalués** (précontrôle VAL et diagnostic DEVTEST/DIAG-DEV) : 07/11/15/19 du
   **jour 5**.
5. **Hazards (tous les modèles).** logit h_b = base_f[b] + tod_f[quart d'heure local] + δ.
   δ vaut :
   - 0 pour B0-pool ;
   - l'ordonnée locale rétrécie pour B0-local ;
   - MLP([z, variables publiques de l'élément]) pour B2 ;
   - MLP([état du nœud, état d'unité]) pour H1.
6. **Mode 1 (déroulé).**
   - La mémoire de B2/H1 est calculée sur l'historique public jusqu'à t, puis **propagée sans
     observation** (mode 2) pour les heures futures.
   - Les événements échantillonnés sont réinjectés dans l'**état explicite** x, via l'opérateur
     et les variables d'élément, **pas** dans la mémoire récurrente. Les paramètres des têtes
     sont précalculés par origine (éléments présents, et tables des nouveaux éléments par heure
     et profil), puis échantillonnés par le moteur numpy.
   - **Écart assumé** à la conception § 2.3 point 1 : la réinjection dans la mémoire
     multiplierait le coût du bloc Prévision par environ 24 × la taille du graphe. Il
     s'applique également à B2 et H1.
7. **Historique.** Les variables de l'heure h utilisent les observations disponibles à la fin
   de l'heure h, convention en flux ; l'état des entités à t utilise `available_at ≤ t`. Aucune
   observation postérieure à t n'est jamais lue (T-INF-01).
8. **Entraînement.**
   - Origines d'entraînement toutes les **3 h** (de 24 h à 165 h) dans chaque établissement
     TRAIN, identiques pour B2 et H1 ; B0 s'ajuste sur tous les éléments TRAIN.
   - VAL utilise toutes les heures de 24 h à 143 h.
   - Au plus **60 époques**, patience 20 (A4).
   - Lot de 32 origines ; Adam.
9. **Graphe H1.** Types de nœuds : séjour, lit, unité, équipe (transport, nettoyage,
   IDE/AS × unité), offre.
   - Les tâches de transport et de nettoyage sont des **attributs** de l'arête `waits_for`
     séjour/lit → équipe.
   - Les ressources partagées sont les nœuds d'équipe.
   - Relations : `occupies`, `belongs_to` (séjour→unité, lit→unité), `waits_for`, `serves`
     (équipe→unité), `reserves` (offre→unité), `lends_to` (unité→unité).

   C'est une mise en œuvre réduite du graphe de la conception (§ 1.1), déclarée ici.
10. **m5 (DIAG)** est réduit à deux mécanismes :
    - régime de ralentissement **commun** au transport et au nettoyage ;
    - **baisse non annoncée** d'un agent de nettoyage pendant 4 à 8 h.

    L'interdépendance d'ordre des tâches **n'est pas implémentée** ; c'est un écart déclaré.
11. **Renfort du pool.** Toujours accepté après une latence de confirmation ; sa présence est
    tirée au début du créneau, avec le taux d'absence de l'établissement. Le prêt entre unités
    est accepté immédiatement, présent, et soumis au minimum du prêteur.

## N7. Installation (constat)

- Route A utilisée : index CPU officiel, après autorisation par vous des hôtes
  `download.pytorch.org` et `download-r2.pytorch.org` dans l'environnement personnel
  `carepredict-mvp`.
- torch **2.15.0+cpu** est la version **retenue explicitement**, sans prétention d'unicité
  vis-à-vis des avis de sécurité. Route B non utilisée.
- Couple approuvé : Python 3.11.18 et gel `e93a3617…1218` (registre n° 9).
- Point de contrôle : checkpoint et RNG validés en `weights_only=True` (registre n° 8).

## N8. Tests ajoutés à la matrice

| ID | Assertion | Bloquant |
|---|---|---|
| T-NORM-01..04 | N1 | oui |
| T-PLAN-03b | disjonction choix/évaluation pour tous les systèmes publics et C_* ; oracle = minimum exact sur les réalisations d'évaluation | oui |
| T-PLAN-07 | ensemble d'éléments notés identique pour tous les modèles (empreinte) | oui |
| T-MASK-01 | une présence future modifie le masque, jamais une prédiction | oui |
| T-BIN-01 | les intervalles de soins couvrent [0, ∞) sans recouvrement ; Σ P = 1 | oui |
| T-PKG-01 | paquet extrait ailleurs : empreintes vérifiées et checkpoint chargé en `weights_only=True` | oui |
