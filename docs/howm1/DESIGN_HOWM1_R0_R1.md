# HOWM-1 — Conception de la tranche R0+R1

**Date :** 14 novembre 2026.
**Statut :** document de préparation. Il n'autorise rien : ni dépense, ni installation, ni
génération de corpus, ni entraînement, ni lecture de réserve.

Ce document décrit la tâche R0, les modèles R1, leurs interfaces, leurs pertes et leur
périmètre. Les valeurs non encore fixées sont marquées **[À FIXER]** et listées dans
`EXPERIMENT_HOWM1_R0_R1.json` (`unfixed_values`).

**Entrées :**
- `inputs/PROGRAMME_HOWM1.md`
- `inputs/PROMPT_CODEX_CLAUDE_HOWM1.txt`
- les références hachées dans `INPUT_PROVENANCE.json`.

**Historique conservé tel quel :**
- P5b : `insufficient`, Δ_rep R1 = +2,27 [−2,54 ; +6,94], seuil 15.
- P5a : exploratoire.
- v6 : référence et socle de contraintes, pas plafond.
- Statuts inchangés : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

---

## 0. Périmètre

| Dans R0+R1 | Hors R0+R1 |
|---|---|
| Monde synthétique à **2 unités** et ressources partagées (le générateur accepte 3 unités, testé mais non entraîné) | 3 unités en entraînement, nouveaux établissements de taille hors loi (R2) |
| Contrat d'événements public/privé, confirmations retardées, cycle de vie des actions | Données réelles, connecteur SIH, action réelle |
| Opérateur de transition explicite et vérificateur indépendant | Décisions médicales (autorisations de sortie, prolongations) |
| B0 (mécanismes recalibrés), B2 (mémoire agrégée), H1 (mémoire par entités + graphe typé) | H2 (contexte d'établissement activé), H3 (contraste d'interventions, ablation JEPA) : interfaces seulement |
| Prévisions probabilistes H1/H6/H24 + déroulé libre ; diagnostic décisionnel par instant sur développement | Boucle fermée à replanification événementielle (R3) ; actions d'information (innovation C) |
| Checkpoints, optimiseur et RNG restaurables ; reçu de restauration | Courbes d'échelle 0,25/1/4 M × 1/4/16× (R2/R4) |
| Réserve **nouvelle** : graines scellées, jamais générée en R1 | Lecture de toute réserve, nouvelle ou P5 |

**Séparation du code.**
- Nouveau paquet `src/hospitalos/howm/`, nouvelles commandes `scripts/howm_*.py`, nouvelles
  preuves `evidence/howm1/`.
- `src/hospitalos/decision_support` (v6) et `src/hospitalos/p5` sont importés **en lecture
  seule**. Un test vérifie `git diff 856a57c -- src/hospitalos/decision_support` vide.
- Aucun poids antérieur n'est chargé : `rssm_checkpoint.pt` et les lots 15/16, hachés comme
  octets seulement.
- `mvp/computer-use` n'est pas touché.

## 1. Tâche dynamique R0

### 1.1 Monde et entités

Un **établissement** h contient :
- 2 unités (A, B) de 8–24 lits chacune **[À FIXER : loi des tailles]** ;
- une équipe de transport partagée ;
- une équipe de bionettoyage partagée ;
- un pool de renfort partagé ;
- un prêt possible entre A et B, sous le minimum déclaré du prêteur. C'est la règle v6 V5-R01 :
  une capacité par prêteur × compétence × heure.

| Type de nœud | Attributs publics (exemples) | Attributs privés (vérité, jamais en entrée) |
|---|---|---|
| `stay` (séjour) | unité, lit, profil de soins publié, statut d'autorisation médicale **publié**, estimation publiée de disponibilité (distribution), contraintes (isolement, O₂) | heure vraie de disponibilité, besoin de soins réalisé |
| `bed` (lit) | unité, compatibilités, état observé (occupé / départ / sale / nettoyage / libre / réservé) | heure vraie de fin de nettoyage |
| `unit` | capacité, minimum de personnel par compétence | — |
| `task` (transport, nettoyage, soin) | type, demandé à, statut publié | durée vraie |
| `team` (transport, nettoyage, équipe soignante par compétence) | effectif planifié publié | régime de ralentissement caché |
| `offer` (renfort) | compétence, créneau, source (pool / prêteur), statut (demandé / accepté / présent / absent) | présence réalisée |
| `shared_resource` | capacité horaire publiée | indisponibilités non annoncées |

Relations typées : `occupies`, `needs`, `waits_for`, `precedes`, `reserves`, `depends_on`,
`belongs_to`, `lends_to`. Les ressources partagées relient A et B.

### 1.2 Contrat d'observation (schéma `HOWM1_EVENTS_1`, à implémenter)

Chaque observation porte les champs suivants :
- `event_id`, `kind`, `subject_type`, `subject_ref`, `unit` ;
- `event_time` et `available_at`, des instants UTC ;
- `source`, `confirmation` (`requested` | `accepted` | `refused` | `executed` | `completed` |
  `cancelled` | `observed`), `value`, `missing: bool`.

Conventions reprises de v6 (`contracts.py`, `snapshot.py`, `clock.py`) :
- UTC partout, résolution civile Europe/Paris explicite ;
- `None` signifie inconnu, jamais zéro ;
- modèles Pydantic fermés.

Règles d'information :
1. L'entrée à l'instant t est **exactement** `{o : o.available_at ≤ t ∧ o.event_time ≤ t}`. Le
   filtre est appliqué par un seul constructeur d'historique (`howm.history.build`), seul
   chemin vers les modèles.
2. Une heure prévue n'est pas un événement. Un renfort `requested` ou `accepted` n'est pas
   `present`.
3. Les identifiants (`subject_ref`) servent aux jointures. Ils sont remplacés par des index
   locaux permutés avant l'encodeur et ne sont jamais des valeurs d'entrée.
4. Le temps entre dans les modèles sous trois formes :
   - temps **relatif** à t ;
   - heure locale (sin/cos) ;
   - jour ouvré ou non.

   Les dates absolues, graines et identifiants d'établissement n'y entrent jamais.

### 1.3 Cycle de vie des actions

Une action passe par `requested → accepted | refused → executed → completed (résultat)` ou
`cancelled`.
- L'acceptation dépend du propriétaire de la ressource, avec une latence privée.
- L'exécution n'est possible qu'après acceptation et sous les préconditions.
- Le résultat est un événement observé, éventuellement retardé (`available_at > event_time`).

### 1.4 Catalogue d'actions automatiques

Aucune décision médicale.

| Famille | Action | Préconditions (vérifiées hors réseau) |
|---|---|---|
| a1 Logistique de sortie | demander un créneau de transport à τ pour un séjour **autorisé publiquement** à t | autorisation publiée et non retirée ; créneau dans la capacité publiée ; jamais avant la disponibilité publiée au plus tôt (règle v6 `eligibility`) |
| a2 Ordonnancement des tâches | ordre de priorité des nettoyages ou transports en file | tâche existante ; pas de nettoyage avant départ |
| a3 Renfort | demander compétence × unité × créneau × source (pool ou prêteur) | minimum du prêteur ; créneau sur grille horaire ; pas de double comptage d'une offre (`offer_key` unique, repris de P5) |
| a0 | conserver le plan en cours / ne rien faire | — |

L'**autorisation médicale** est un événement exogène public. Le planificateur ne peut ni la
créer ni l'anticiper : test T-OP-06.

Le **mode manuel** fixe des actions ou hypothèses (`locks`), qui deviennent des contraintes du
**même** générateur de candidats et du même opérateur. Une hypothèse non autorisée reste
simulable et marquée non approuvable, comme `ScenarioLocks` en v6.

### 1.5 Instants de décision

- Les instants sont aux heures locales 07, 11, 15 et 19 **[À FIXER]**.
- R1 évalue **chaque instant séparément** (§ 5.3) : après l'instant, la suite suit la règle
  habituelle.
- La replanification en boucle fermée est R3. Le monde la permet déjà, car des événements
  publics arrivent entre les instants : confirmation, absence d'un renfort, retrait
  d'autorisation.

### 1.6 Mécanismes privés du générateur

Ce sont des hypothèses d'ingénierie. Aucun n'a été validé sur données réelles ni par entretien.

| Code | Mécanisme | Pourquoi l'historique peut aider | Population |
|---|---|---|---|
| m0 | Délais indépendants, lois fixes par établissement (type v6) | Seulement l'estimation des paramètres | REF (toujours) |
| m1 | Paramètres d'établissement θ_h : durées de transport et nettoyage, profil horaire des sorties, absence des renforts, latence de confirmation | Inférables depuis un préfixe public | REF |
| m2 | Régime caché de ralentissement d'équipe (2 états, persistance de quelques heures) | Détectable sur les durées récentes | REF, avec part **[À FIXER]** ; DIAG renforcé |
| m3 | Interaction : la charge soignante élevée retarde les sorties prêtes | Non visible dans un instantané | REF (faible), DIAG (fort) |
| m4 | Retards d'observation (`available_at − event_time`) propres à l'établissement | Calibrage de la fraîcheur | REF |
| m5 | Retards corrélés transport ↔ nettoyage ; capacité modifiée en cours d'épisode ; ordre des tâches qui compte | Interactions entre entités | **DIAG seulement** |

La population **REF** comprend explicitement des établissements où m2 et m3 sont éteints, et
où B0 doit suffire. La part de ces cas **[À FIXER]** est déclarée avant toute génération et
n'est **jamais** ajustée selon le gain d'un modèle.

Tous les tirages sont **indexés par clé** :
- clé `H(engagement, partition, établissement, réalisation, primitive, entité)` ;
- même convention que `hybrid/innovations.uniform` et P5 ;
- aucune dépendance au nombre ou à l'ordre des appels.

### 1.7 Générateur indépendant G_alt

Une deuxième implémentation est écrite séparément pour **une** famille : file de transport et
nettoyage, mécanismes m0+m1.
- Elle est à **pas de temps fixe**, quand G_main est à événements.
- Elle sert de contrôle hors générateur sur développement uniquement.
- Réussir sur G_alt reste une preuve synthétique.

## 2. Architecture commune

```
historique public (≤ t, fenêtre W)
  -> encodeur (B2 : agrégats ; H1 : graphe typé)    -> mémoire récurrente  -> état latent z_t
(x_t explicite, z_t, [c_h : interface désactivée], action candidate)
  -> têtes probabilistes : prochains événements / durées / comptes / besoins de soins
événements échantillonnés + opérateur de transition explicite  -> x_{t+Δ} admissible
déroulé  -> trajectoires par séjour / lit / unité / ressource ; agrégats horaires ; risques
```

### 2.1 État explicite x_t et opérateur T

- `x_t` contient : lits et états exclusifs, séjours et localisation, files de tâches,
  personnel par compétence et par heure, offres et statuts, réservations, engagements.
- `T(x, e)` applique un événement **seulement si** ses préconditions tiennent. Sinon, l'événement
  est **rejeté et compté** (`rejected_events`), jamais corrigé silencieusement.
- Un vérificateur indépendant relit le journal produit, comme `check_invariants` en v6 :
  - conservation des patients ;
  - un lit = un état ;
  - pas de nettoyage avant départ ;
  - pas de dépassement de capacité ;
  - pas de personnel compté sans présence ;
  - minimum du prêteur respecté.
- Le réseau ne peut **pas** créer de lit, d'agent ni d'autorisation : il ne produit que des
  distributions sur des événements que T peut refuser.

### 2.2 Têtes probabilistes (identiques pour B0, B2 et H1)

| Cible | Forme | Domaine garanti par paramétrage |
|---|---|---|
| Délai jusqu'à l'événement e d'une entité (sortie prête, transport réalisé, fin de nettoyage, confirmation, présence du renfort) | hazard discret par pas de 15 min sur 48 h, modulé par l'heure locale | sigmoïde, survie monotone ; censure à droite exacte |
| Arrivées (admissions par unité et par heure) | binomiale négative | moyenne softplus, dispersion > 0 |
| Besoin de soins par séjour, heure et compétence (minutes) | log-normale tronquée à 0 | σ > 0 |
| Absence d'un renfort accepté | Bernoulli | sigmoïde |

Les sorties métier sont calculées **par déroulé**, pas prédites directement :
- charge par compétence, lits compatibles disponibles, délai de remise à disposition ;
- files, reports, pression ;
- le score de pression résume ces trajectoires sans les remplacer.

Les agrégats sont des sommes exactes des entités du même déroulé. La cohérence
agrégats/entités est donc vraie par construction et testée.

### 2.3 Deux modes de prévision

1. **Déroulé par événements :**
   - échantillonner des événements, appliquer T, réinjecter les événements échantillonnés dans
     la mémoire, M trajectoires ;
   - c'est le mode du planificateur.
2. **Marginal latent :**
   - propager z sans observation sur k pas (« overshooting ») ;
   - décoder directement les niveaux et les comptes à t+k ;
   - sert à l'entraînement multi-pas et au diagnostic de cohérence avec le mode 1.

## 3. Modèles R1

Mêmes historiques, mêmes têtes, même opérateur, même planificateur, mêmes candidats et même
budget d'échantillons M.

### B0 — mécanismes explicites recalibrés (référence forte)

- Les familles de lois sont celles de m0+m1 : délais par type et heure locale, absence,
  arrivées.
- Elles sont estimées par **maximum de vraisemblance avec censure** sur TRAIN. Il n'y a pas de
  réseau, seulement numpy et scipy.
- Deux versions :
  - **B0-pool** : paramètres communs ;
  - **B0-local** : rétrécissement bayésien empirique vers B0-pool, à partir de la **même
    fenêtre publique W** que les modèles appris.
- B0-local est la référence obligatoire « simulateur calibré sur les mêmes données ». L'écart
  B0-pool/B0-local mesure ce que l'estimation locale seule apporte.
- B0 ignore volontairement m2, m3 et m5. C'est ce qui le distingue d'un modèle appris, pas une
  information qu'on lui cache.

### B2 — mémoire temporelle latente agrégée, probabiliste

- Entrée : un vecteur horaire par unité et par ressource partagée (comptes, files, durées
  récentes, personnel, statuts d'offres), soit environ 100 dimensions.
- Puis : linéaire → GRU(64) → z_t.
- Têtes d'entité : `MLP([z_t, attributs publics statiques de l'entité])`. Il n'y a ni mémoire
  par entité ni échange entre entités.
- Taille attendue : ~0,08 M paramètres **[compte exact après construction]**.

### H1 — mémoire latente par entités avec échanges sur graphe typé

- Encodeur par type de nœud, à poids partagés entre entités du même type.
- 2 tours de messages par pas horaire, avec un MLP par type de relation et une agrégation par
  somme normalisée. Elle est invariante à l'ordre et au nombre.
- GRU par nœud, partagé entre types, avec plongement de type, de dimension 48.
- Lecture d'unité par attention-pooling.
- Têtes identiques à B2, appliquées à l'état du nœud concerné et à celui de son unité.
- Taille attendue : ~0,15–0,25 M paramètres **[compte exact après construction]**.
- Pas de Transformer.

### Interfaces présentes et désactivées en R1

Une seule variation sera activée à la fois, en R2.

| Interface | Drapeau | État en R1 | Test |
|---|---|---|---|
| Contexte d'établissement c_h inféré d'un préfixe public | `context=off` | absent du graphe de calcul | T-CFG-01 : 0 paramètre, sorties identiques avec un préfixe vide ou plein |
| Perte de contraste d'interventions (branches appariées) | `contrast_weight=0` | branches générées pour l'évaluation seulement | T-CFG-02 |
| Prédicteur JEPA de représentations futures | `jepa=off` | absent | T-CFG-03 |
| Latent stochastique (RSSM) | `stochastic_latent=off` | mémoire déterministe ; incertitude par têtes et ensemble | T-CFG-04 |
| Actions d'information (innovation C) | — | hors catalogue | T-OP-10 |

**Limite assumée.** Sans latent stochastique, l'incertitude sur un régime caché passe seulement
par la dispersion des événements échantillonnés et par l'ensemble de 3 graines. Elle ne passe
pas par une croyance latente explicite. C'est la première candidate à une variation en R2 si le
diagnostic m2 l'indique.

## 4. Apprentissage

### 4.1 Pertes de R1

L = Σ_types NLL_hazard_censurée + λ_n · NLL_binomiale_négative(arrivées)
  + λ_c · NLL_lognormale(soins) + λ_o · NLL_Bernoulli(absences)
  + Σ_{k ∈ K_os} w_k · NLL_marginale(cibles agrégées à t+k | z propagé sans observation)

Les termes de la somme sur k sont l'overshooting.

- K_os = {1, 6, 24} h, avec poids w_k **[À FIXER sur VAL, puis figés]**.
- Les λ normalisent chaque terme par sa valeur initiale sur TRAIN. Ils sont figés après le
  pilote.
- Aucune perte n'entraîne à imiter les choix de v6.
- Il n'y a pas de perte de décision en R1. L'objectif orienté décision (§ 4.4 du programme)
  vient après stabilisation prédictive.

### 4.2 Multi-pas et déroulé libre

- Forçage par l'enseignant sur 1 pas, plus l'overshooting latent.
- Le déroulé libre (mode 1) n'est pas différentiable à travers l'échantillonnage. Il est
  **mesuré** : écart entre prévision forcée et déroulé libre à H1/H6/H24.
- Un entraînement en déroulé libre progressif est une variation de R2 si l'écart est important.

### 4.3 Supervision privilégiée nommée (diagnostic seulement)

Des sondes linéaires sont entraînées **après gel** sur les représentations figées. Elles
prédisent le régime m2, θ_h et l'heure vraie de disponibilité.

Diagnostic de décomposition, pour séparer l'erreur d'**estimation d'état** de l'erreur de
**dynamique** :
- B0 déroulé avec θ_h et l'état latent vrais ;
- B0 déroulé avec les valeurs estimées.

Ces chemins lisent la vérité privée. Ils sont déclarés `reads_private=True` et refusés comme
fournisseurs du planificateur, selon le patron v6 `assert_product_backend`.

### 4.4 Sélection

- Hyperparamètres : seulement taux d'apprentissage ∈ {3e-4, 1e-3} × arrêt précoce sur la
  NLL de VAL, avec patience **[À FIXER]**, pour B2 et H1.
- 3 graines par configuration retenue, gardées comme ensemble.
- Le gel **F1** couvre code, poids, λ, w_k et cibles de progrès. Il précède la lecture
  unique de DEVTEST.

## 5. Évaluation sur développement (R1)

### 5.1 Prévision (DEVTEST REF, puis DIAG-DEV)

- Par horizon H1, H6 et H24, par unité et par compétence :
  - NLL d'événements ;
  - CRPS des niveaux ;
  - MAE et RMSE en unités métier ;
  - couverture des intervalles 50 % et 90 % ;
  - histogrammes PIT.
- Pics : erreur sur le maximum de charge et sur les heures au-dessus du seuil, calculées sur
  la trajectoire complète.
- Écart prévision forcée / déroulé libre ; taux d'événements rejetés par T.
- **Dispersion de l'ensemble et couverture sont rapportées séparément.** La dispersion n'est
  jamais présentée comme une calibration.

### 5.2 Interventions (branches appariées, sémantique du simulateur)

Pour chaque instant de décision de DEVTEST, un couple action/témoin est construit sur les mêmes
innovations, en plus des actions candidates.

Mesures :
- erreur sur Δ ;
- signe de Δ ;
- reconnaissance des **effets nuls** ;
- effets indirects sur l'autre unité ;
- écart entre renfort demandé et renfort présent.

Les paires peu informatives restent dans l'échantillon. Ce sont des effets **simulés**, sans
identification causale réelle.

### 5.3 Diagnostic décisionnel par instant

Même ensemble de candidats ≤ 16, avec empreinte identique pour tous les comparateurs.

| Comparateur | Information | Rôle |
|---|---|---|
| Pratique habituelle | règle | référence basse |
| Règle métier renforcée | règle, état public | meilleure heuristique simple |
| B0-pool / B0-local / B2 / H1 + planificateur | historique public W | systèmes comparés |
| C_param | θ_h vrai, état public | contrôle non anticipatif privilégié |
| C_full | θ_h et état latent courant vrais, sans innovations futures | meilleur non anticipatif privilégié |
| Oracle clairvoyant | réalisation future | **plafond**, jamais cible |

- Les réalisations servant à **choisir** sont disjointes de celles servant à **évaluer** :
  K_eval = 4 réalisations fraîches.
- Mesures :
  - regret contre C_full ;
  - écart à l'oracle ;
  - gain contre l'habituel ;
  - cas où le modèle **se trompe** (choix pire que l'habituel) ;
  - cas où il **ne sait pas** (écart entre ses deux meilleurs candidats inférieur à sa propre
    dispersion) ;
  - cas où **conserver le plan** était meilleur.
- Coût de calcul par méthode : temps d'entraînement, latence d'un déroulé, latence du
  planificateur.

### 5.4 Précontrôle de marge décisionnelle (R0, avant tout modèle appris)

Le précontrôle utilise les contrôleurs privilégiés seulement, sur VAL :

- V_param = U(C_pub-snap) − U(C_param) ;
- V_latent = U(C_param) − U(C_full) ;
- plafond = U(C_full) − U(oracle).

C_pub-snap est le vrai simulateur avec les paramètres du prior commun et l'instantané public
seul.

V_param + V_latent est une **borne de ce que l'historique peut rapporter en décision** dans
cette population. C'est une approximation de V_info du programme : différence entre contrôles
non anticipatifs, réalisations de choix et d'évaluation séparées.

**Règle.** Si cette borne est inférieure à δ_dec **[À FIXER]**, la comparaison décisionnelle de
R1 sur REF est déclarée **non informative avant toute lecture de modèle**. La comparaison
prédictive reste conduite. Le générateur n'est **pas** modifié pour agrandir la marge.

## 6. Partitions, réserve, preuves

- **Unité de partition : l'établissement.** Ses jours, fenêtres, branches et instants restent
  ensemble.
- Partitions : TRAIN 48, VAL 12, DEVTEST 24 (REF) ; DIAG-DEV 12 (DIAG).
- **RESERVE** : 48 REF + 16 DIAG, graines **scellées** par empreinte en G0, générateur verrouillé
  (refus journalisé sans jeton). Elle n'est **pas générée** en R1. Les tailles sont
  **[À FIXER]** ; ce sont des propositions.
- Graines : espace de noms neuf `HOWM1`. Aucune graine P5 n'est réutilisée.
- Les réserves P5 déjà lues servent seulement de **régression historique**, test V0.
- Preuves automatisées :
  - registre chaîné propre à HOWM-1, sans reliquat P5 ;
  - engagements G0 (générateur et graines) et F1 (modèles) ;
  - manifeste du corpus avec empreinte par établissement ;
  - journaux, coûts, états RNG ;
  - reçu de restauration.

## 7. Ce que R1 pourra conclure et ce qu'il ne pourra pas

**Pourra :**
- B0, B2 et H1 prévoient-ils mieux les événements et trajectoires de ce monde synthétique, à
  H1/H6/H24, sur des établissements non vus ?
- À quel coût de calcul ?
- Leurs différences d'effets d'actions sont-elles justes ?
- Le diagnostic décisionnel par instant en profite-t-il, dans la limite de la marge mesurée en
  R0 ?

**Ne pourra pas :**
- résultat confirmatoire (aucune réserve lue) ;
- transfert hospitalier ou calibration réelle ;
- causalité réelle ;
- bénéfice en boucle fermée (R3) ;
- valeur du contexte d'établissement ou de JEPA (R2).
