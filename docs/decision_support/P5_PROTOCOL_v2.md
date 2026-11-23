# P5 — Protocole de qualification expérimentale bornée — P5-PROTO-2 (proposition, non exécutée)

**Version :** P5-PROTO-2, 14 novembre 2026, amendement documentaire de P5-PROTO-1.
**Statut : `PROPOSED_NOT_AUTHORISED_NOT_EXECUTED`.**
Paramètres lisibles par machine : `P5_PROTOCOL_PARAMS_v2.json` (même version ; en cas d'écart, le
protocole n'est pas gelable tant que l'écart n'est pas corrigé). Changements et décisions :
`P5_CHANGES_v1_to_v2.md`. Les originaux P5-PROTO-1 (`P5_PROTOCOL.md`, SHA-256 `f669fe3d…5885` ;
`P5_PROTOCOL_PARAMS.json`, `9f61123b…3872`) sont conservés à l'identique.

Ce document ne vaut aucune autorisation. Pour le rédiger : aucune simulation, aucune génération de
corpus, aucun chronométrage, aucun ajustement, aucun test produit, aucune installation, aucun
chargement de poids. Seule une lecture statique des sources v6 et du rapport de revue a été faite.
Le reliquat P0–P4 (178,675 s) reste réservé aux portes P0–P4 et ne finance pas P5.

Statuts inchangés quoi qu'il arrive : `PARTIAL_WITH_CHECKPOINT` (portes ouvertes : Python 3.11.9
exact, rejeu React/navigateur indépendant), `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`,
`G2=NO-GO`. V5-R01 reste clos sur les cas audités. Aucune v7 du moteur n'est demandée : le moteur
v6 (`4fca8aec…7f90`, arbre `856a57c`) est utilisé **inchangé** ; tout ce que P5 ajoute vit dans un
paquet d'évaluation séparé (`p5/`, à écrire). P5 est entièrement synthétique. P6 reste fermé.

## 1. Questions

**P5a — valeur potentielle du contrôle.** Sur un univers d'actions petit et énuméré complètement,
de combien le planificateur de référence v6 (information publique) réduit-il les minutes-soignant
non couvertes par rapport à la pratique habituelle, quelle part de la marge jusqu'au minimum
exact de U sur le même univers capture-t-il, et avec quel **risque de dégradation limité** (taux
d'épisodes dégradés de plus de δ borné, et non « aucune dégradation ») ?

**P5b — test de représentation.** À budget de modèle égal, un modèle qui relie chaque action du plan
au séjour et à l'offre qu'elle vise (M_ent) choisit-il de meilleurs plans qu'un modèle qui ne voit
que des agrégats et un descripteur de plan (M_agg) ? L'écart mesuré est un **bénéfice empirique de
représentation dans ce simulateur**, pas une quantité exacte d'information perdue, ni une preuve
de causalité réelle, de calibration réelle, de généralisation hospitalière ou de la nécessité d'une
architecture JEPA. P5b ajuste des modèles simples U(état, plan), pas une dynamique de trajectoires
ni AJ-H.

Un échec de P5a ou P5b borne ce périmètre ; il ne justifie pas l'arrêt de tout HospitalOS.

## 2. Unités, hiérarchie et estimands (P5-M04)

Hiérarchie fixée, du plus haut au plus bas :

| Niveau | Indice | Définition |
|---|---|---|
| Structure | s | configuration d'unité tirée du générateur (6–8 lits, planning, capacités transport/nettoyage, offres de renfort, profils de soins, motif d'arrivées) |
| Épisode parent | p | un instantané public `PublicSnapshot` à `as_of` (heure pleine, horizon 24 h) d'une structure |
| Jumeau | t ∈ {A, B} | P5b seulement : A = parent, B = parent dont les vecteurs logistiques sont permutés (§ 6.1). P5a : t = A seul |
| Réalisation privée | k = 1…K, par régime r ∈ {R1, R2} | une vérité privée complète tirée pour l'instantané (t) ; **K = 3** |
| Plan | a ∈ 𝒜(x) | plan de l'univers public admissible de l'instantané x, ≤ 16 plans, habituel compris |

**Univers public.** 𝒜(x) = `candidates.enumerate_plans` v6 sur l'instantané public, limite 16,
`complete=True` exigé. 𝒜(x) ne dépend que de x : il est identique pour toutes les réalisations k,
les deux régimes et tous les comparateurs. Les futurs cachés ne modifient **ni les autorisations
médicales ni l'univers des actions** ; l'oracle ne peut ni ajouter une action ni lever une
autorisation. Garde-fou : empreinte de 𝒜(x) identique sur toutes les (k, r).

**Estimand principal (P5a-1, P5b-1).** Moyenne à poids égaux par structure, puis par parent dans la
structure, puis par jumeau (P5b), puis par réalisation k :
Δ = E_s E_p E_t E_k [ U(référence) − U(comparé) ]. Les comparaisons sont **appariées** : mêmes
(s, p, t, k, r) et mêmes innovations privées pour tous les plans.

**Population de jumeaux.** Les jumeaux sont construits par une règle de permutation (stress-test de
représentation). Leur fréquence ne représente pas une fréquence réaliste de situations ; les
résultats P5b sont conditionnels à cette population construite.

**Tailles = nombre d'instantanés publics.** Les mêmes instantanés sont évalués sous R1 et, quand
c'est prévu, sous R2 ; chaque instantané reçoit K = 3 réalisations **par régime évalué**.

| Volet | Structures | Parents / structure | Jumeaux | Régimes | Lignes / simulations vérité |
|---|---:|---:|---:|---|---|
| P5a développement | 10 | 10 | — | R1, R2 | 100 × ≤16 × 3 × 2 = ≤ 9 600 |
| P5a évaluation réservée | 30 | 10 | — | R1, R2 | 300 × ≤16 × 3 × 2 = ≤ 28 800 |
| P5b entraînement | 24 | 15 | 2 | **R1 seul** | ≤ 11 520 lignes (24×15×2×16) ; ≤ 34 560 simulations |
| P5b validation | 8 | 15 | 2 | R1 seul | ≤ 3 840 lignes ; ≤ 11 520 simulations |
| P5b évaluation réservée | **30** (option recommandée D5 ; v1 : 8) | **4** (v1 : 15) | 2 | R1, R2 | 240 jumeaux × ≤16 × 3 × 2 = ≤ 23 040 |

Les deux options d'évaluation P5b ont le même coût (240 instantanés jumeaux). 30 × 4 rend la borne de
dégradation atteignable (§ 8.3) ; 8 × 15 la rend inatteignable et laisse P5b exploratoire.

**R1 / R2.** Les modèles P5b sont **entraînés et sélectionnés sous R1 seulement**. R2 n'est utilisé
que pour **lire** l'évaluation réservée (P5a et P5b), rapportée séparément ; R2 ne peut pas améliorer
un verdict R1 ; une inversion de signe sous R2 est rapportée comme limite.

**Partition.** Par structure : tous les parents, jumeaux, réalisations et plans d'une structure
restent dans une seule partition ; aucune structure n'appartient à deux volets.

## 3. Population synthétique et générateur (à écrire, non écrit)

Familles paramétriques autour de `UNIT_PROFILE.json`. Bornes publiques : ≤ 8 séjours présents,
≤ 4 offres de renfort dans l'instantané, ≤ 4 admissions attendues, univers ≤ 16 plans (`complete`),
≤ 2 coordinations et ≤ 2 options de renfort par plan (limites v6).

**Exclusions.** Comptées sur **tous** les parents candidats générés, **avant** tout filtrage, avec
motif : `universe_incomplete` (> 16 plans), `too_many_stays`, `too_many_offers`,
`too_many_admissions`, `twin_degenerate` (P5b, § 6.1). Critères **publics uniquement** ; jamais sur la
vérité ni sur un résultat. Un parent exclu est remplacé par la graine suivante de la liste engagée
(ordre fixé à l'engagement). Taux d'exclusion > 5 % : rapporté, verdict « non concluant ». Une
exception du générateur n'est pas une exclusion : c'est une règle d'arrêt (§ 11).

**Abstentions.** Si le planificateur v6 ne recommande rien (`habitual_practice_preferred…`,
`habitual_practice_invariant_failure`, refus), l'épisode est **évalué comme pratique habituelle**
(U_hab), compté et conservé. Jamais retiré pour améliorer un gain.

**Innovations privées à clés stables.** Toute primitive privée (disponibilité, délai de transport,
nettoyage, arrivée, présence de renfort) est tirée d'une innovation uniforme indexée par
`H(engagement, partition, s, p, r, k, type_de_primitive, clé_stable_d'entité)` — clé d'entité =
`stay_id`, `bed_id`, `request_id` ou clé d'offre (§ 5.2) —, **jamais selon l'ordre des appels**.
Conséquences : mêmes innovations pour tous les plans d'un (s, p, t, k, r) (comparaisons appariées) ;
mêmes innovations pour les deux jumeaux sur une même entité ; R1 et R2 partagent les innovations
uniformes, seule la loi de transformation change.

## 4. Comparateurs

| Comparateur | Rôle |
|---|---|
| **HABITUAL-1** (plan vide) | référence principale ; « pas de recommandation » ≠ « ne rien faire ». Pratique habituelle **simulée, non validée sur le terrain** ; n'emploie aucun renfort dans le profil v6 |
| **Planificateur v6** (`recommend`, information publique, 4 graines de sélection, inchangé) | objet évalué en P5a ; comparateur en P5b. Politique **conditionnelle** v6 : elle ne lit pas la probabilité de présence des renforts (§ 5) |
| **Minimum exact U\*** | U\*(x, w) = min_{a ∈ 𝒜(x)} U(x, a, w) par réalisation w ; évaluation seulement ; plafond **certifié sur cet univers** pour la métrique U |
| **Oracle métier O_lex** | OBJ-LEX-1 appliqué à U réalisé (tolérance 15 min, puis heures de renfort prévues, puis interventions) ; diagnostic seulement, **pas un plafond sur U** |
| **M_agg / M_ent** (P5b) | § 6 |

Le plan choisi par chaque comparateur doit appartenir à 𝒜(x) (garde-fou). HABITUAL-1 ∈ 𝒜(x).

## 5. Métriques et vérité des renforts

### 5.1 Oracle, plafond et regrets (P5-M01)

U = minutes-soignant de soins non couvertes sur 24 h réalisées sous la vérité privée (palier 1 de
OBJ-LEX-1, travail d'admission dû compris). Pour chaque (s, p, t, r, k) :

- G = U_hab − U\* ≥ 0 (marge disponible) ; regrets R_plan = U_plan − U\* ≥ 0,
  R_hab = U_hab − U\*, R_lex = U_lex − U\* (0 ≤ R_lex, attendu ≤ 15 par construction de la tolérance).
- **P5a-1 (principal)** : Δ_hab = E[U_hab − U_plan].
- **P5a-2 (descriptif)** : part capturée C = Σ (U_hab − U_plan) / Σ G, **ratio de sommes** pondérées
  comme l'estimand, jamais une moyenne de ratios par épisode. Comme U_plan ≥ U\*, C ≤ 1 ; C peut
  être négatif ; **aucun écrêtage**.
- **Dénominateur nul ou quasi nul** : si la marge moyenne Ḡ = E[G] < δ = 15 min/épisode, C est
  déclaré **« non défini — marge insuffisante »** et seuls les regrets moyens et Δ_hab sont
  rapportés. La règle est appliquée sur l'estimation ponctuelle ; l'IC de C n'est calculé que si
  Ḡ ≥ δ, et les rééchantillonnages où Ḡ\* < δ sont comptés et rapportés (pas retirés silencieusement).
- **Diagnostic (non décisionnel)** : U_fix = min_a E_k[U(a, w_k)] (meilleur plan fixe pour la loi
  des réalisations). Avec K = 3, U_fix est **biaisé vers le bas** ; il ne sert qu'à séparer
  qualitativement la part due au futur inaccessible (U_fix − U\*) de la part améliorable.
- O_lex est rapporté (U_lex, R_lex, heures de renfort) mais **n'entre dans aucun dénominateur**.

Exemple arithmétique du rapport de revue (non simulé) : U_hab = 150, A = 90 (2 h de renfort),
B = 100 (1 h). O_lex choisit B ; U\* = 90. Un plan A donne C = (150−90)/(150−90) = 100 %, pas 120 %.

### 5.2 Vérité des renforts (P5-M03)

Lecture statique v6 : `ReinforcementOption` porte confirmation et créneau, pas de probabilité ;
`staff_per_hour` compte les offres sélectionnées ; `ReferenceForecaster.runs` calcule le plan
conditionnel et sa variante sans renforts non confirmés ; aucun tirage de présence. **La v6 n'est pas
modifiée** et reste décrite comme une politique conditionnelle.

**Schéma public P5 (fichier annexe, hors `PublicSnapshot`)** `HOSPITALOS_P5_REINFORCEMENT_1`, par
offre : `offer_key` (clé stable = `source | lending_unit | skill | start | end`, sans `option_id`),
`p_pub` (probabilité publique de présence), `pool_key` (`lending_unit` pour `shared_unit`, sinon
`source`), `planned_hours` (= `hours`). Valeurs : offre `confirmed` → p_pub = 1 ;
`requested` → p_pub ∈ {0,4 ; 0,5 ; … ; 0,9} tirée par le générateur ; `not_requested` / `unknown`
→ non sélectionnable (comme en v6). Le modèle public déclaré est : présences **indépendantes** entre
offres. L'annexe est visible de M_agg/M_ent (variables publiques) ; le planificateur v6 ne la lit pas.

**Réalisation privée** (une présence 0/1 par offre et par (s, p, t, r, k), tout ou rien sur le créneau) :

| | Offre confirmée | Offre demandée non confirmée | Corrélation |
|---|---|---|---|
| R1 (bien spécifié) | présente (prob. 1) | Bernoulli(p_pub) | aucune (ρ = 0, comme déclaré) |
| R2 (mal spécifié) | présente (prob. 1) | marginale **0,5** quelle que soit p_pub | copule gaussienne, ρ = 0,5 au sein d'un même `pool_key` |

Tirage : présence = 1[ √ρ·Φ⁻¹(u_pool) + √(1−ρ)·Φ⁻¹(u_offre) < Φ⁻¹(p) ], u indexées par clé stable.
R2 ajoute aussi les décalages v1 : délai de transport +1 h (prob. 0,3), nettoyage +1 h (prob. 0,2).

**Coûts.** Heures de renfort **prévues** = Σ heures des offres sélectionnées (palier 2 de OBJ-LEX-1,
utilisé pour tous les départages, y compris O_lex). Heures **réalisées** = Σ heures des offres
sélectionnées et présentes (descriptif). Effet prêteur réalisé : heures effectivement prêtées.

**Règle d'exécution.** Évaluation en boucle ouverte à `as_of` : une offre absente apporte 0 soignant
sur son créneau ; ni remplacement, ni replanification, ni révélation au planificateur.

**Adaptateur d'évaluation** `p5/eval_adapter.py` (à écrire, tracé par empreinte, distinct de v6) :
reçoit (instantané public, plan choisi, réalisation privée) ; retire **de la copie d'évaluation**
du plan les actions `reinforcement` dont l'offre est absente ; appelle la simulation sous vérité
v6 (`TruthProvider` / `PrivateOracle.outcome`) inchangée. Le planificateur ne reçoit jamais la
réalisation. L'empreinte de l'arbre v6 est vérifiée avant chaque lot.

**Tests futurs spécifiés (non écrits, non exécutés)** :
- **T-P5-R1** : même instantané public, même plan sélectionnant une offre demandée dont les heures
  couvrent une demande non couverte ; deux réalisations ne différant que par la présence de cette
  offre ⇒ U réalisé différent (strictement plus grand si absente) ; recommandation publique v6
  identique (même empreinte de décision) dans les deux cas.
- **T-P5-R2** : permuter l'ordre des offres et renommer `option_id` ⇒ présences tirées identiques
  par `offer_key` ; tirages identiques quel que soit l'ordre des appels.

### 5.3 Autres métriques

- **P5b-1 (principal)** : Δ_rep = E[U(choix M_agg) − U(choix M_ent)].
- **Décomposition à ressources comparables (descriptive, sans coût supplémentaire : plans déjà
  simulés).** Pour un plan choisi a\* = coordinations c\* ∪ renforts r\* (sous-plans ∈ 𝒜(x) car
  `complete` et ordre v6 par nombre d'actions) :
  Δ_hab = [U_hab − U(r\* seul)] (mêmes renforts seuls) + [U(r\* seul) − U(a\*)] (coordination à
  renforts égaux) ; ordre inverse rapporté aussi : [U_hab − U(c\* seul)] (coordination seule) +
  [U(c\* seul) − U(a\*)] ; l'écart entre les deux ordres = interaction. Rapporter aussi U\* par classe
  (coordination seule, renforts seuls, combinaison) et les heures de renfort prévues/réalisées et
  effets prêteurs. **Seule la composante « coordination à renforts égaux » peut être présentée comme
  valeur du choix des patients** ; un gain venant de moyens supplémentaires n'est pas attribué à
  l'intelligence du modèle. Même décomposition pour les choix M_agg et M_ent.
- **Secondaires descriptives** : attente de lit (patients·h), interventions, lits remis, pic et
  heures au-dessus du seuil PS-EXP-1, MAE et RMSE des modèles, variance par structure, complexité.

## 6. Conception de P5b

### 6.1 Jumeaux

Pour un parent x_A, le vecteur logistique d'un séjour autorisé est
L_j = (`destination`, `transport_need`, `transport_lead`, `ready_earliest`, `ready_delay`,
`planned_departure`, `obstacles`). x_B = x_A où les L_j sont permutés par σ entre séjours
**autorisés** (`medical_authorization="authorized"`) ; soins, tâches, lits, effectifs, offres et
admissions inchangés ; identifiants inchangés. σ est un décalage circulaire sur les séjours
autorisés triés par empreinte de `stay_id`, de pas tiré dans le flux de graines engagé — jamais
conditionné à la vérité ni à un résultat. Si moins de deux séjours autorisés ont des L_j différents :
`twin_degenerate`, exclusion publique comptée. Égalité exacte du bloc agrégé B0 (§ 6.2) : assertion.

**Actions homologues.** Un plan de x_A et un plan de x_B sont homologues s'ils ont le même tuple
(type, cible `stay_id` ou `offer_key`, fenêtre) pour chacune de leurs actions. Les plans sans homologue
(univers différents si l'éligibilité dépend de L) restent dans les données d'entraînement et
d'évaluation, sont comptés, et sont hors du précontrôle.

### 6.2 Contrat `features(PublicSnapshot, Plan, annexe P5)` (P5-M02)

Entrées : uniquement l'instantané public, le plan et l'annexe publique du § 5.2. Version de schéma
`HOSPITALOS_P5_FEATURES_1`, empreinte gelée. Encodage : catégories en one-hot sur un **vocabulaire
fixe déclaré** (énumérations de `contracts.py` v6 ; obstacles : vocabulaire déclaré par le
générateur, catégorie hors vocabulaire = arrêt) ; « sans objet » = 0 **plus** un indicateur explicite ;
heures relatives à `as_of` (0–23).

| Bloc | M_agg | M_ent | Contenu |
|---|:-:|:-:|---|
| B0 agrégats publics | ✓ | ✓ | lits par statut, séjours présents/autorisés, histogrammes horaires (24) des départs prévus, des besoins de transport par type, des minutes de soins par compétence, effectifs prévus par compétence et heure, capacités transport/nettoyage par heure, admissions attendues par heure, offres par source/confirmation, Σ p_pub × heures ; heure du jour (sin, cos), jour de semaine |
| B1 descripteur de plan | ✓ | ✓ | nombre d'actions par type, histogramme des heures cibles par type, heures de renfort prévues par heure (24), Σ p_pub × heures sélectionnées, interventions, indicateur habituel |
| B2 emplacements séjour (8) | | ✓ | masque ; attributs publics du séjour (autorisation, destination, transport, délai déclaré, `ready_earliest`, `planned_departure`, minutes de soins 24 h en 4 tranches de 6 h, tâches, obstacles one-hot, statut du lit) ; **lien plan** : ciblé (0/1), type d'action, heure cible (+ indicateur) |
| B3 emplacements offre (4) | | ✓ | masque ; compétence, début, fin, heures, source, confirmation, p_pub, marge prudente du prêteur (capacité v6 min planifié − max minimum), conflit prêteur ; **lien plan** : sélectionnée (0/1) |
| B4 emplacements admission (4) | | ✓ | masque ; heure d'arrivée attendue, loi de délai (moyenne, écart), minutes de soins, minutes d'admission, exigences |

**Jointures.** `stay_id`, `option_id`, `request_id`, `lending_unit` servent **uniquement** à relier
une action à son emplacement et à calculer les marges prêteur ; ils ne sont jamais émis comme
valeurs, ni hachés en variables. **Ordre canonique** des emplacements : tri lexicographique sur le
tuple des attributs publics, puis sur le tuple du lien plan. Deux séjours aux attributs publics
identiques sont échangeables : cibler l'un ou l'autre donne le même vecteur (attendu, l'espérance
de U est la même). Emplacement absent : tous champs 0, masque 0. Dépassement des capacités
d'emplacements : exclusion publique (§ 3), jamais troncature.

**Tests futurs spécifiés (non écrits, non exécutés)** : F1 confidentialité (deux vérités, même
vecteur) ; F2 renommage (bijection aléatoire sur tous les identifiants de l'instantané et du plan ⇒
vecteur identique et même plan choisi) ; F3 permutation de l'ordre des listes d'entrée ⇒ vecteur
identique ; F4 distinguabilité : « coordonner X1 à 10 h » vs « coordonner X2 à 10 h » avec X1, X2
d'attributs pertinents différents ⇒ vecteurs M_ent différents, vecteurs M_agg identiques (le
manque de M_agg est documenté, non supposé) ; F5 jumeaux ⇒ B0 identique ; F6 empreinte de schéma
stable.

### 6.3 Étiquettes, poids et précontrôle

**Lignes d'entraînement** : une ligne par (s, p, t, a) sous R1 ; étiquette = moyenne des K = 3
réalisations de U(a). Poids `sample_weight` = (1 / n_plans(s, p, t)) × (P_s_nominal / P_s_valides),
de sorte que chaque instantané pèse 1 quel que soit le nombre de plans et chaque structure pèse
autant. ≤ 11 520 lignes en entraînement (≤ 24 × 15 × 2 × 16).

**Précontrôle des jumeaux** — partition : **entraînement P5b** (24 structures), R1, K = 3, avant
toute génération de validation ou d'évaluation. Actions comparées : toutes les paires de plans
homologues non habituels. Pour chaque (s, p, a) et chaque réalisation k (innovations partagées) :
g_k = [U_A,k(a) − U_A,k(hab)] − [U_B,k(a) − U_B,k(hab)] ; d̂ = moyenne_k g_k ; v̂ = s²(g)/K ;
θ̂_{s,p,a} = d̂² − v̂ (sans biais pour d²). θ = moyenne pondérée (structure, parent, plans égaux).
**Statistique non signée** : des effets de sens opposés ne s'annulent pas. **Informatif** si la borne
inférieure unilatérale 95 % (bootstrap structure puis parent) de θ ≥ **25 min²** (écart quadratique
moyen d'effet ≥ 5 minutes-soignant). Descriptif : taux de parents où le meilleur plan homologue
(moyenne sur k) diffère entre jumeaux. Non informatif ⇒ P5b s'arrête **avant** validation et
évaluation (économie budgétaire), résultat rapporté. Aucune sélection de paires « qui fonctionnent ».

### 6.4 Modèles (P5-M05)

`sklearn.ensemble.HistGradientBoostingRegressor`, même famille et même budget pour M_agg et M_ent.

| Paramètre | Valeur |
|---|---|
| grille | `max_depth` {3, 5} × `learning_rate` {0,05 ; 0,1} × `max_iter` {100, 200, 400} = 12 |
| `early_stopping` | **False** (explicite ; `max_iter` est déjà choisi sur la validation par structure) |
| `loss` | `squared_error` |
| `max_leaf_nodes` / `min_samples_leaf` / `l2_regularization` | 31 / 20 / 0.0 |
| `max_bins` / `max_features` | 255 / 1.0 |
| `categorical_features` / `monotonic_cst` / `interaction_cst` | None / None / None (one-hot explicite) |
| `warm_start` / `verbose` | False / 0 |
| `validation_fraction`, `n_iter_no_change`, `tol`, `scoring` | sans effet avec `early_stopping=False` ; consignés à leur valeur par défaut |
| `random_state` | graines d'ajustement {0, 1, 2} |
| fils d'exécution | `OMP_NUM_THREADS=1` (déterminisme et chronométrage comparables) |

**Graines d'ajustement.** Avec `early_stopping=False`, `max_features=1.0` et < 200 000 lignes (pas de
sous-échantillonnage du binning), la documentation n'attribue aucun effet à `random_state` : les
3 ajustements par configuration sont **attendus identiques** — à vérifier, non supposé. Règle : la
diversité réellement observée (écart absolu maximal des prédictions entre graines) est rapportée ;
la graine 0 est le modèle principal fixé à l'avance ; les graines 1 et 2 sont un contrôle de
reproductibilité, **jamais des répétitions indépendantes** dans un IC. Si elles diffèrent, le
critère de sélection est la moyenne sur les 3 graines et l'évaluation rapporte chacune.
72 ajustements = 2 familles × 12 configurations × 3 graines, sous R1 uniquement.

**Choix d'un plan** : argmin de la prédiction sur 𝒜(x), départage OBJ-LEX-1 (tolérance 15, heures
de renfort prévues, interventions). **Sélection** sur la validation (8 structures) : U réalisé
moyen des plans choisis (R1, moyenne sur k, pondération par structure) ; départage MAE pondérée,
puis modèle le plus simple (`max_iter`, puis `max_depth` plus petits). Pas de validation interne
non groupée. Version de scikit-learn : § 9.

## 7. Engagement, développement et gel (P5-M06)

| Étape | Contenu | Données accessibles |
|---|---|---|
| **E0 — engagement initial** | empreintes : P5-PROTO-2 et JSON v2 (ou version approuvée), code générateur v_g0, schéma de features, listes de graines par partition (tirées une fois, engagées par SHA-256 de la liste triée + sel, révélées dans le paquet final), graine de bootstrap ; référence au terminal P0–P4 `9056a4a1…b973` | aucune |
| **D — développement** | écriture et tests du générateur, de l'adaptateur, des variables, de l'analyse ; pilote ; précontrôle ; ajustements ; sélection | développement P5a, entraînement et validation P5b |
| **E_k — nouvel engagement** | à tout changement du générateur (ou des variables) après E0 : nouvelle version v_gk, nouvelle empreinte consignée **avant** la génération correspondante ; listes de graines **jamais retirées** ; aucun choix fondé sur des cas réservés | idem D |
| **F — gel final** | empreintes du protocole, du JSON, du code (générateur, adaptateur, variables, analyse), de la configuration choisie, des seuils, de δ ; consigné avant **toute** génération des évaluations réservées P5a et P5b | — |
| **Lecture** | génération et lecture des évaluations réservées | évaluations |

« Lecture unique » signifie : aucun réglage après inspection. Un rejeu reproductible (même code,
mêmes graines) pour audit reste permis et consigné. Toute modification après F = nouvelle version du
protocole ; les résultats déjà lus restent rapportés. **Aucun nouveau test réservé n'est ajouté après
lecture des résultats.**

## 8. Analyse et règles de décision

### 8.1 Inférence

Bootstrap hiérarchique à deux étages : rééchantillonnage des **structures** avec remise, puis des
**parents** avec remise dans chaque structure ; un parent emporte ses deux jumeaux, ses K
réalisations et tous ses plans (comparaisons appariées conservées). 2000 rééchantillonnages, IC
percentile 95 % bilatéral ; graine de bootstrap engagée en E0. Aucune pseudo-réplication par plan,
par heure, par réalisation ni par graine d'ajustement. R1 et R2 séparés. Deux critères principaux
(P5a-1, P5b-1) ; pas de revendication de contrôle familial ; secondaires descriptifs.

### 8.2 Seuils et verdicts

δ_P5a = δ_P5b = **15 minutes-soignant par épisode** : **convention technique** égale à la tolérance
d'équivalence de OBJ-LEX-1, **jamais un seuil clinique** ; tout changement exige un amendement
soumis explicitement.

| Borne IC 95 % de Δ | Verdict |
|---|---|
| supérieure < δ | bénéfice **insuffisant** pour ce périmètre |
| inférieure > δ **et** garde-fous respectés **et** précision déclarée suffisante | bénéfice **démontré dans ce protocole synthétique** |
| sinon | **non concluant** ; si la précision était déclarée insuffisante avant F : **exploratoire** |

### 8.3 Garde-fous

1. 0 violation d'admissibilité ou d'invariant ; plan choisi ∈ 𝒜(x) ; empreinte de 𝒜(x) invariante en (k, r).
2. 0 fuite : isolation T03/T04 sur 50 épisodes tirés ; F1 ; T-P5-R1.
3. Exclusions ≤ 5 % des parents candidats.
4. **Risque de dégradation limité.** Parent dégradé : E_k[U_comparé − U_hab] > δ (moyenne sur les
   réalisations). **Structure dégradée** : au moins un parent (un jumeau en P5b) dégradé. Borne :
   **Clopper–Pearson unilatérale 95 %** sur le nombre de structures dégradées parmi n structures
   réservées. Valide quelle que soit la dépendance entre parents d'une structure (structures
   i.i.d. par construction) ; conservatrice car P(structure dégradée) ≥ taux d'épisodes dégradés à
   poids égaux par structure ; **non dégénérée à zéro** : 0/30 → 9,50 % (le bootstrap de zéros
   donnerait 0, il n'est pas utilisé ici). Seuil proposé ≤ 10 %.

| n structures réservées | 0 dégradée | 1 dégradée | 2 dégradées |
|---:|---:|---:|---:|
| 8 | 31,23 % | 47,07 % | 59,97 % |
| 29 | 9,81 % | 15,34 % | 20,16 % |
| 30 | 9,50 % | 14,86 % | 19,53 % |
| 40 | 7,22 % | 11,32 % | 14,92 % |

Conséquence déclarée avant toute exécution : avec 30 structures, le garde-fou n'est atteignable
**qu'avec zéro structure dégradée** ; avec 8 structures (option v1 de P5b), il est **inatteignable**
et P5b ne peut pas dépasser « exploratoire ». Le taux observé par épisode est rapporté en descriptif.
Appliqué à P5a (planificateur vs habituel) et à P5b (M_ent vs habituel ; M_agg vs habituel
descriptif).

### 8.4 Précision projetée, avant F

P5a : variance de Δ_hab entre structures et entre parents sur le développement (10 × 10). P5b :
même calcul sur la validation (8 × 15), pour Δ_rep. Si la demi-largeur projetée de l'IC dépasse δ/2
avec la taille réservée, la faible précision est **déclarée avant F** (verdict plafonné à
« exploratoire ») ; une augmentation n'est possible qu'avant F, dans le budget approuvé, et consignée.
Aucune extension après lecture.

## 9. Environnement (correction P5-M06)

**Correction.** P5-PROTO-1 affirmait « Python 3.13.18 (environnement des suites vertes) ». Cette
formulation n'est pas établie par les sources citées et est retirée. Faits documentés :

| Interpréteur | Provenance | Rôle constaté |
|---|---|---|
| 3.13.18 | `BASE_MAP.json` (interpréteur de la session d'auteur) | exécutions d'auteur ; pytest 9.1.1 de la session hors de la borne `pytest<9` du `pyproject.toml` |
| 3.11.18 | `/usr/bin/python3.11`, environnement virtuel isolé de la session ; gel `py311_venv_freeze.txt` (SHA-256 `bf540981…b6da`) : pydantic 2.14.3, pydantic_core 2.50.4, numpy 2.4.6, pytest 8.4.2, jsonschema 4.26.0 | exécutions d'auteur citées par la clôture (181 réussis + 1 ignoré) |
| 3.13.5 | audit indépendant v6 (`AUDIT_SUMMARY.json`) | environnement de l'auditeur |
| 3.11.9 | `.python-version` | référence produit ; **porte ouverte**, non fermée par P5 |

**Proposition (décision D3, sans installation ni changement de référence produit)** : exécuter P5
sous **Python 3.11.18** avec les versions du gel `bf540981…`, plus scikit-learn et ses dépendances
(scipy, joblib, threadpoolctl) **à version exacte** choisie à l'installation dans la borne
`scikit-learn>=1.5,<1.9` (candidate : 1.7.2 ; disponibilité des roues **non vérifiée**, pas d'accès
réseau utilisé), puis `pip freeze` consigné. Chaque enregistrement du registre P5 porte
`sys.version` et l'empreinte du gel. Exécution locale CPU, 0 €, aucune donnée réelle, aucun SIH.
L'environnement virtuel est dans le dossier de travail éphémère de la session : s'il disparaît, sa
recréation est une installation à autoriser et à imputer.

**Dépendances.** P5a : pydantic, numpy (présents). P5b : scikit-learn **absent** ; installation
réseau soumise à accord distinct (D4) ; **la permission d'installer ne vaut pas permission
d'entraîner**, ni l'inverse.

## 10. Budget proposé (à approuver séparément, non activé)

**Proposition : 1200 s de temps mural cumulé, 30 s au plus par commande, 0 €** (alternative D2 :
1800 s sans échelle de repli). Registre distinct `evidence/decision_support/p5/BUDGET_LEDGER_P5.jsonl`,
même format chaîné et ancré ; premier enregistrement citant le terminal P0–P4
`9056a4a1…b973` ; jamais remis à zéro. **Le temps d'installation est imputé** (lot P5.I). Une
commande d'installation dépassant 30 s est tuée et comptée : installer paquet par paquet.

**Base d'estimation** (mesures existantes, non relancées) : recommandation complète 0,366 s
démarrage compris (#6) ; 2 à 6 ms par simulation (#124, #140, #151, #169). Hypothèses non mesurées :
recommandation en lot 0,15–0,35 s ; ajustement HGB mono-fil 0,3–4 s selon `max_iter` ; extraction
0,2–1 ms par ligne. **Ce sont des estimations, pas des durées démontrées.**

| Lot | Contenu | Volume | Estimation | Plafond |
|---|---|---|---:|---:|
| P5.0 | engagement E0, contrôles d'isolation | — | 10–20 s | 30 s |
| P5.I | installation scikit-learn + dépendances (si D4) | — | 15–60 s | 60 s |
| P5.1 | tests générateur, adaptateur (T-P5-R1/R2), variables (F1–F6) | — | 60–120 s | 130 s |
| P5.2 | **pilote chronométré** : 20 parents de développement, R1+R2, K=3, extraction, 2 ajustements les plus coûteux (`max_iter`=400, `max_depth`=5) sur données de développement, un bootstrap complet | — | 15–30 s | 40 s |
| P5.3 | P5a développement puis évaluation réservée | 38 400 sim. + 400 recommandations | 137–370 s | 330 s |
| P5.4 | P5b étiquettes (entraînement → précontrôle → validation → évaluation), 72 ajustements, sélection, planificateur sur l'évaluation | 69 120 sim. + 240 recomm. + 72 ajust. + 19 200 lignes × 2 | 232–707 s | 470 s |
| P5.5 | bootstrap, rapport, restauration neuve, paquet | — | 25–70 s | 90 s |
| Réserve | reprises après défaut, sans élargissement | — | — | 50 s |
| **Total** | | | **≈ 494–1377 s** | **1200 s** |

**Le haut de la fourchette dépasse 1200 s.** Échelle de repli **pré-enregistrée**, déclenchée par la
seule projection chronométrique du pilote P5.2 (jamais par un résultat), appliquée dans l'ordre
jusqu'à projection ≤ 1000 s :
1. **L1** — K = 3 → 2 pour les étiquettes d'entraînement/validation P5b et le développement P5a ;
2. **L2** — 72 → 24 ajustements (une graine) si le pilote montre des prédictions identiques entre
   graines (écart ≤ 1e-12) ; sinon L2 n'est pas applicable ;
3. **L3** — retrait de la comparaison secondaire « planificateur v6 sur l'évaluation P5b » ;
4. projection encore > 1000 s ⇒ **arrêt et demande** (D2 : 1800 s, ou P5a seul).
Un plafond de lot atteint ⇒ arrêt du lot, sauvegarde, rapport.

## 11. Règles d'arrêt

Arrêt immédiat, sauvegarde et rapport (sans conclusion inventée) si : empreinte invalide (dont arbre
v6 modifié) ; fuite ; violation d'admissibilité ou d'invariant ; non-déterminisme du générateur ;
exception du générateur ; catégorie hors vocabulaire ; plafond de lot ou global atteint ; projection
du pilote > 1000 s après échelle de repli ; besoin d'une dépense, d'une installation non autorisée ou
d'une écriture distante ; écart au protocole gelé. Une faible amélioration ne justifie aucun
élargissement silencieux.

## 12. Livrables de P5 (après exécution autorisée)

Protocole gelé et empreintes (E0, E_k, F) ; révélation des graines ; manifestes des corpus ;
comptes d'exclusions et d'abstentions par motif ; tous les résultats, graines, erreurs et résultats
négatifs ; R1 et R2 séparés ; décomposition à ressources comparables ; diversité observée des
graines d'ajustement ; registre P5 ancré ; rapport avec décision **poursuivre / arrêter / mesurer
davantage** ; paquet restaurable avec son propre manifeste. Aucune revendication réelle, aucune
promotion G2, aucune ouverture automatique de P6.

## 13. Autorisations séparées requises (aucune n'est donnée par ce document)

1. Approbation du protocole (P5-PROTO-2 ou amendement) et des décisions de `P5_CHANGES_v1_to_v2.md`.
2. Budget P5 (D2). 3. Environnement (D3). 4. Installation de scikit-learn (D4).
5. Mise en œuvre et pilote (P5.0–P5.2). 6. Évaluation réservée P5a. 7. Ajustements et évaluation P5b.
Le cockpit n'intervient pas : P5 est une étude hors interface ; la porte « rejeu React indépendant »
reste une porte produit séparée.
