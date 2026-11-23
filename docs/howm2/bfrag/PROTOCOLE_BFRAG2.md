# Protocole B-FRAG 2 — fragilité dynamique et interventions différées

**Version** P1 du 17 novembre 2026 (décision n° 7). Gelé dans le registre B (note `protocol_freeze_bfrag2`)
**avant toute mesure comparative**. Une seconde note (`freeze2_bfrag2`) gèlera, avant la campagne CONF unique,
les choix faits sur VAL et le code d'analyse.

**Statuts :** `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.

**Portée.** Benchmark **synthétique**. Apprentissage statistique léger autorisé uniquement : régression
logistique régularisée et gradient boosting borné (§ 6). Aucun réseau de neurones. Aucune boucle fermée.
Le world model latent appris (question D) est **NON TESTÉ** dans ce mandat.

Mesures déjà faites sur DEV, sans aucune comparaison : coûts, stabilité Monte-Carlo
(`MC_TOLERANCE_PREDECLARED.json`, `MC_STABILITY_DEV.json`, `MC_CHOICE.json`), taux de base descriptifs.
Révisions de conception sur DEV utilisées : **0 sur 2**.

## 0. Différences avec B-FRAG 1

| Élément | B-FRAG 1 (gelé, intact) | B-FRAG 2 |
|---|---|---|
| Unité | 1 monde = 1 instant T0 | **structure** (monde B-FRAG 1, plan D2) × **3 épisodes indépendants** × **15 origines** |
| Trajectoire | clone à T0, futurs tirés | trajectoire de référence **continue** (générateur dérivé `generate2`), sans plan de fond ; clones à chaque origine ; trace de dépendances par tick |
| Information | état public à T0 | vues **S0** (structure, calendrier), **S1** (état instantané), **S2** (historique public) |
| Références | R0, R1, F, O | + références **apprises** sur S0/S1/S2 (TRAIN), sélectionnées sur VAL |
| Interventions | plans HOWM-1 à T0 | renforts **différés** sur un créneau futur explicite de 8 h (nettoyage ou transport), action historique, aucune |
| Horizon de décision | 168 h | 168 h après la décision, observation terminale |
| Propagation | variante détendue par famille | contrôles **appariés à une dépendance à la fois** |

Inchangés : moteur et générateur HOWM-1 gelés (substitution de source seulement), loi d'arrivée B-FRAG
(capacité nominale, lits tampons publics), définition de rupture B-FRAG 1 (≥ `K_MIN = 5` patients attendant
≥ 24 h dans une unité, durée ≥ 4 ticks, fusion si écart < 8 ticks).

## 1. Définitions

- **Structure** `s` d'une partition `P` : `make_world(P, s, DESIGN_D2)` (famille = `s mod 6`).
- **Épisode** `e ∈ {0,1,2}` : même structure, tirages d'événements indépendants (`ekey = key("BF2-ep", P, s, e)`).
- **Origine** : heures 36, 42, …, 120 (15 origines). État d'origine = état **avant** le tick t0 ; état public =
  observations publiées strictement avant `15·t0` minutes.
- **Étiquette** `y72` : début d'une rupture dans `[t0, t0 + 72 h)` ; `y24` idem à 24 h. Épisode long de
  192 h : aucune origine n'est censurée à 72 h ; une origine censurée ne serait jamais étiquetée négative.
  168 h est **NON OBSERVABLE** pour l'anticipation (fenêtre au-delà de l'épisode).
- **Origine active** : une rupture est en cours à t0. Exclue de l'anticipation (la rupture n'est plus à
  anticiper) ; son nombre est publié.
- **Pression manifeste** (publique) : au moins 3 patients attendent ≥ 12 h dans une unité. Sous-ensemble
  « avant pression manifeste » = origines sans pression manifeste.
- **Origine de décision** : heure `[42, 54, 66][e mod 3]`.

## 2. Partitions (nouvelles, disjointes, affectées par structure)

| Partition | Structures | Épisodes | Usage |
|---|---|---|---|
| `BF2_DEV` | 6 | 3 | coûts, stabilité MC, tests ; aucune comparaison |
| `BF2_TRAIN` | 200 | 3 | apprentissage des références S0/S1/S2 (vues seulement) |
| `BF2_VAL` | 100 (vues) ; **VAL-S** = structures 0–17 en mode `val` | 3 | choix des configurations, du concurrent, des seuils, de la règle structurelle et du verrou S2 |
| `BF2_CONF` | 200 (vues) ; **CONF-S** = structures 0–23 en mode `full` | 3 | **campagne unique** après le gel 2 |

Mode `features` : étiquettes et vues. Mode `val` : + scores R0, R1, F, O à toutes les origines, planificateur
R1 et évaluation vraie des 10 actions. Mode `full` : + planificateurs F et O. CONF-S contient 4 structures
par famille ; VAL-S, 3.

**Sous-ensemble réalisable préenregistré.** Si le budget interrompt CONF-S, l'analyse retient les structures
dont les 3 épisodes sont complets, par indice croissant, jusqu'à la première incomplète. En dessous de 12
structures, les questions B et C sont déclarées **NON CONCLUANT (budget)**.

## 3. Vues

- **S0** (16 variables) : lits nominaux et physiques par unité, lits d'isolement, `c_tr`, `c_cl`, marge tampon,
  heure (sin, cos), jour, jour ouvré, baisses planifiées publiques dans 0–24, 24–48 et 48–72 h.
- **S1** (S0 + 30 variables) : par unité, occupation, lits libres, libres isolables, sales, en nettoyage, file,
  attente max, nombre ≥ 12 h, ≥ 24 h, isolement en file, sortants prêts en attente de transport, autorisés
  non prêts, transports demandés, acuité 3 ; transports et nettoyages en cours.
- **S2** (S1 + historique) : variations à 6 h et 24 h de 10 grandeurs S1 ; comptes d'événements publics sur 6 h
  et 24 h (7 types) ; durées observées de nettoyage et de transport sur 24 h ; délai moyen de publication ;
  taux d'arrivée cumulé.

Aucune variable ne porte d'identifiant (structure, épisode, famille, clé, θ, régime, mécanisme) — test T2-3.

## 4. Scores de risque à 72 h

| Méthode | Information | Calcul |
|---|---|---|
| R0 | publique | heuristique (file + lits sales − libres, rapportée aux lits ; + 0,5 si baisse planifiée < 48 h) |
| R1 | publique | modèle L2 (`LongModelProvider`), M = 32 déroulés |
| LR-Sk / HGB-Sk | publique, vue k | références apprises (§ 6) |
| F | publique | chaîne historique B-FRAG 1 (postérieur L4 + nowcast L4-N + simulateur), M = 32, clé dérivée de l'historique public |
| O | **privilégiée** | moteur vrai + régime vrai, M = 32 — diagnostic seulement, jamais concurrent |

M = 32 pour le risque et pour la décision (règle préenregistrée, `MC_CHOICE.json`). La tolérance de rang
n'est pas atteinte à M = 32 pour le risque : c'est une limite déclarée, qui atténue les AUC de R1, F et O.

## 5. Audit de spécification de F

Voir `AUDIT_F_BFRAG2.md`. La version historique de F est conservée à l'identique (seule la clé publique est
généralisée à toute origine et à la répétition). Aucune revendication de postérieur bayésien exact.

## 6. Références apprises

- Lignes d'apprentissage : origines non actives de TRAIN (200 × 3 × 15), cible `y72`. Normalisation
  (`StandardScaler`) apprise sur TRAIN seulement. Les scores F ne sont **ni entrées ni cibles**.
- Grille (8 configurations par vue) :
  - LR, pénalité L2, `C ∈ {0,01 ; 0,1 ; 1 ; 10}`, `lbfgs`, `max_iter = 2000` ;
  - HGB, `max_depth ∈ {2, 3}` × `learning_rate ∈ {0,05 ; 0,1}`, `max_iter = 200`, `min_samples_leaf = 20`,
    `l2_regularization = 1`, sans arrêt précoce, `random_state = 0`.
- Sélection sur VAL (100 structures) par AUC conditionnelle (§ 7).
  - **Meilleure configuration par vue** (secondaire) ;
  - **Configuration commune** pour la question A : configuration (famille + hyperparamètres) qui maximise la
    moyenne des AUC VAL des vues S1 et S2 ; égalités : LR avant HGB, puis la plus petite capacité.
- Rapportés : nombre de lignes, temps d'apprentissage, taille sérialisée.

## 7. Métriques

- **AUC conditionnelle à la structure (principale)** : paires (origine positive, origine négative) **de la
  même structure** (ses 3 épisodes), toutes paires poolées avec poids égal ; égalités = 1/2. Pondération
  fixée ici, avant toute mesure. Structures sans paire : comptées et publiées.
- Secondaires : AUC globale ; AUC conditionnelle à poids égal par structure ; AUC **même phase** (paires de
  même structure et même heure locale d'origine) ; AUC à 24 h ; AUC conditionnelle avant pression
  manifeste ; Brier.
- **Alertes** (secondaires), par méthode : état d'alerte à l'origine si score ≥ θ pendant au moins d origines
  consécutives (d ∈ {1, 2}) ; épisodes d'alerte = suites d'alertes, fusionnées si séparées d'une seule
  origine ; période réfractaire 12 h ; origines actives = hors alerte. Un épisode d'alerte est vrai si une
  rupture débute dans `[début, fin + 72 h)`, faux sinon. Fausses alertes par unité-jour (7,5 unités-jours par
  épisode) ; temps sous alerte ; épisodes de rupture détectés (alerte commencée dans les 72 h précédant le
  début), délai d'avance, détection avant pression manifeste. θ = plus petit seuil observé donnant ≤ 0,10
  fausse alerte par unité-jour sur VAL ; d choisi sur VAL pour maximiser la détection sous cette contrainte.
- Ré-échantillonnage : **structure** (bootstrap en grappes, B = 2000, graine 20261117, percentiles). Les AUC
  sont recalculées sur les paires des structures tirées, avec multiplicité.
- **Correction multiple** : Bonferroni sur les **3 comparaisons principales** (A, B, C) → IC à **98,33 %**.
  Tous les autres intervalles sont à 95 % et descriptifs.

## 8. Interventions différées

- Catalogue (10 actions, budget commun 8 heures-agents par décision) : `none` ; `hist_coord_compat`
  (action historique HOWM-1, coordination compatibilité) ; `cl+1_w1..w4` et `tr+1_w1..w4` (+1 agent de
  nettoyage ou de transport sur l'un des 4 premiers créneaux [06,14) ou [14,22) commençant ≥ 2 h après la
  décision).
- Chaque origine de décision est un **contrefactuel indépendant** : une action, puis déroulé de 168 h sous la
  politique de fond commune. Évaluation vraie : E = 8 futurs vrais, **communs** à toutes les actions.
- **Critère principal** : attente cumulée en patient-minutes sur 168 h après la décision (moyenne sur les
  8 futurs). Observation terminale : file et attente max à 168 h.
- **Garde-fous** : soins non couverts (min), rejets (au plan et totaux), minutes de rupture, file terminale,
  attente terminale max, heures-agents, **déplacement de charge** (part de l'attente portée par l'unité A).
- Politiques comparées :
  - inaction ; règle historique (toujours `hist_coord_compat`) ;
  - **règle structurelle** à budget égal choisie sur VAL-S parmi 14 candidates : une action fixe (10) ou
    « renforcer la ressource la plus rare (`c_cl` vs `c_tr`, égalité → nettoyage) sur le créneau w » (4) ;
  - **règle structurelle verrouillée S2** : la règle structurelle seulement si le risque S2 appris
    (configuration VAL-meilleure de S2) à la décision ≥ τ, τ ∈ quantiles {0,25 ; 0,5 ; 0,75} VAL-S ;
  - **planificateur statistique explicite R1** (déroulés L2, M = 32) ;
  - **planificateur F** (M = 32) ; **planificateur O** (privilégié, diagnostic).
  - Planificateur : argmin de l'attente moyenne (nombres aléatoires communs) ; égalités → moins
    d'heures-agents, puis indice.
- **Concurrent D\*** : meilleure politique publique non-F sur VAL-S (attente vraie moyenne) parmi inaction,
  historique, structurelle, verrouillée S2, R1.

## 9. Propagation

Traces de dépendances par tick (blocage compatibilité, nettoyage, transport ; patients ≥ 24 h). Contrôle
apparié : le **même épisode** (mêmes clés, mêmes arrivées) avec **une** dépendance relâchée — `cl` (+1
nettoyage), `tr` (+1 transport), `compat` (tous lits isolables à nombre total égal) — et l'interaction
`cl+tr`. Population : CONF, structures 0–59, 3 épisodes. Effets : minutes de rupture, ticks ≥ 24 h, nombre
de débuts, base − relâché, par famille, IC 95 % par grappes. Interaction `I = Δ(cl+tr) − Δcl − Δtr`.
Transmission entre unités (cascade A→B) : pas de contrôle apparié isolant ce canal → **NON ÉVALUABLE**.

## 10. Questions et règles de verdict (CONF)

- **A. Valeur de l'historique.** ΔAUC_cond(S2 − S1) à configuration commune, CONF 200 structures, IC 98,33 %.
  `AVANTAGE_HISTORIQUE` si borne basse > 0 ; `DESAVANTAGE` si borne haute < 0 ; `EQUIVALENT` si l'IC est
  dans [−0,02 ; +0,02] ; sinon `INDETERMINE`. Secondaires : S1 − S0, S2 − S0, meilleures configurations par
  vue, même phase, avant pression manifeste, 24 h.
- **B. Avantage de F.** Concurrent C\* = meilleure référence publique sur VAL-S par AUC conditionnelle parmi
  R0, R1, LR/HGB-S0/S1/S2 (configuration VAL-meilleure par vue). ΔAUC_cond(F − C\*) sur CONF-S, IC 98,33 %.
  `AVANTAGE_F` / `DESAVANTAGE_F` / `EQUIVALENT` (marge ±0,03) / `INDETERMINE`. Secondaires : F contre
  chaque référence, à identique famille non applicable (F n'est pas appris), O − F, alertes.
- **C. Bénéfice des interventions.** Δ = attente(D\*) − attente(planificateur F), moyenne par structure
  (moyenne de ses 3 décisions), CONF-S, IC 98,33 %. `GAIN_F` si borne basse > 0 et aucun garde-fou dégradé ;
  `GAIN_AVEC_DEGRADATION` si borne basse > 0 et un garde-fou dégradé (borne basse IC 98,33 % de
  l'augmentation > 0 pour soins non couverts, rejets totaux, minutes de rupture ou file terminale) ;
  `PERTE_F` si borne haute < 0 ; sinon `INDETERMINE`. Secondaires : F contre chaque politique, inaction
  contre meilleure action a posteriori, O, par famille.
- **D. World model latent appris : NON TESTÉ.**

## 11. Budget et exécution

CPU seulement, ≤ 540 s par commande, parallélisme 4 (mémoire ≈ 300 Mo par processus mesurée), journal
du registre B (début, fin, CPU, mur, concurrence, incidents), écritures atomiques et reprenables. Coûts
mesurés sur DEV : `features` ≈ 0,5 s CPU par épisode, `full` ≈ 170 s, `val` ≈ 100 s. Projection : TRAIN ≈ 100 s,
VAL ≈ 1 450 s, CONF ≈ 3 100 s de mur. Lots réalloués avant ce gel (note `lots_bfrag2`) : TRAIN 700 → 300 s,
VAL 1 600 → 1 800 s, CONF 2 600 → 3 800 s ; somme des lots BF2 = 8 500 s ≤ 9 355,654 s restants.

## 12. Tests de validité (avant toute comparaison)

T2-1 contrat as-of strict ; T2-2 vues invariantes à l'avenir non publié ; T2-3 aucun identifiant ; T2-4
étiquettes et censure ; T2-5 trace = observateur pur, état d'origine = trace t0−1 ; T2-6 catalogue, créneaux,
budget, surcharge de capacité sans mutation ; T2-7 contrôles appariés aux mêmes arrivées ; T2-8 partitions
nouvelles et disjointes (y compris de B-FRAG 1) ; T2-9 fichiers gelés intacts (B-FRAG 1, G0, F1).
Résultat : 20/20 (avec les tests B-FRAG 1), registre #64.

## 13. Règles d'arrêt

- Aucune mesure CONF avant le gel 2. Une seule campagne CONF ; aucun changement après.
- Un défaut d'implémentation découvert sur VAL peut être corrigé avant le gel 2, avec note au registre.
- Si une étape exige de dépasser le budget ou de changer un critère gelé : consigner, préparer des
  options, poursuivre seulement les travaux indépendants.
