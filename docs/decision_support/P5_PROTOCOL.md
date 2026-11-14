# P5 — Protocole de qualification expérimentale bornée (proposition, non exécutée)

**Version :** P5-PROTO-1, 14 novembre 2026. **Statut : `PROPOSED_NOT_AUTHORISED_NOT_EXECUTED`.**
Paramètres lisibles par machine : `P5_PROTOCOL_PARAMS.json` (même version). Ce document ne vaut
aucune autorisation : son exécution exige un accord explicite et distinct de l'utilisateur sur le
protocole **et** sur le budget du § 9. Aucun corpus n'a été généré, aucune simulation, aucun
chronométrage, aucun entraînement n'a été lancé pour le rédiger.

Statuts inchangés quoi qu'il arrive : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`,
`G2=NO-GO`. P5 reste **entièrement synthétique** ; aucun résultat ne pourra être présenté comme un
bénéfice hospitalier réel, une calibration réelle ou une promotion G2. P6 reste fermé.

## 1. Point de départ

- Moteur de référence : paquet v6 (`4fca8aec…7f90`, arbre `856a57c`), V5-R01 clos par audit
  indépendant. Portes P0–P4 encore ouvertes (Python 3.11.9 exact, rejeu React indépendant) : elles
  ne bloquent pas P5, qui n'utilise ni le cockpit ni une version Python différente de celle
  déclarée en § 8, mais elles restent ouvertes et le seront dans le rapport P5.
- Budget P0–P4 : 421,325 s consommées / 600 s (reliquat 178,675 s, réservé aux portes P0–P4).
  **Ni ce reliquat ni les anciens budgets AJ-H ne financent P5.**

## 2. Questions et hypothèses

**P5a — valeur potentielle du contrôle.** Sur un univers d'actions petit et énuméré
complètement, quelle part de l'écart entre la pratique habituelle et le meilleur plan
d'information parfaite le planificateur de référence (information publique) capture-t-il, sans
dégrader la pratique habituelle ?

**P5b — test de représentation.** À budget de modèle égal, un modèle qui voit les obstacles par
séjour et par ressource choisit-il de meilleurs plans qu'un modèle qui ne voit que les agrégats ?
L'écart mesuré est un **bénéfice empirique de représentation** dans ce protocole synthétique, pas
une quantité exacte d'information perdue.

Une partie de l'écart à l'oracle peut être irréductible (futur inaccessible). Un échec de P5a ou
P5b ne justifie pas l'arrêt de tout HospitalOS : il borne ce périmètre.

## 3. Population synthétique et réserve d'évaluation

**Générateur (à écrire, non écrit).** Familles paramétriques autour de `UNIT_PROFILE.json` :
une **structure** = configuration d'unité (6 à 8 lits ; planning IDE par poste ; capacités et
engagements extérieurs du transport et du nettoyage ; offres de renfort dont prêts `shared_unit`
de 1 à 2 prêteurs ; profils de soins ; motif d'arrivées). Un **épisode** = un instantané public à
`as_of` (heure pleine, horizon 24 h) et sa **vérité privée** (réalisation de toutes les
primitives : disponibilité, délai de transport, nettoyage, arrivée, présence effective d'un renfort
demandé non confirmé). Contraintes de construction : univers d'actions **≤ 16 plans** (complétude
de l'énumération exigée ; épisode hors borne = exclu et compté, jamais tronqué en silence),
≤ 8 séjours, ≤ 2 coordinations, ≤ 2 options de renfort par plan.

**Deux régimes de vérité**, pré-enregistrés :
- **R1 bien spécifié (analyse principale)** : la vérité est tirée des distributions publiques
  déclarées ;
- **R2 mal spécifié (robustesse, secondaire)** : délais de transport +1 h avec probabilité 0,3,
  nettoyage +1 h avec probabilité 0,2, renfort demandé présent avec probabilité 0,5 au lieu de la
  valeur déclarée. Rapporté séparément, jamais fusionné avec R1.

**Tailles.**

| Volet | Structures | Épisodes / structure | Usage |
|---|---:|---:|---|
| P5a développement | 10 | 10 | pilote, variance, mise au point — jamais lu comme résultat |
| P5a évaluation réservée | 30 | 10 | lecture unique après gel |
| P5b entraînement | 24 | 15 × 2 (jumeaux) | ajustement des deux modèles |
| P5b validation | 8 | 15 × 2 | choix des hyperparamètres |
| P5b évaluation réservée | 8 | 15 × 2 | lecture unique après gel |

Partition **par structure** : branches, plans, répétitions et jumeaux d'un même épisode — et tous
les épisodes d'une même structure — restent dans la même partition. Aucune structure n'appartient
à deux volets.

**Réserve.** Les graines de génération (`generation_seeds`) sont tirées, puis **engagées par
empreinte** (SHA-256 de la liste triée + empreinte du code du générateur) dans le registre P5
**avant** toute génération. Elles sont disjointes des graines de sélection (101–104) et
d'évaluation des prévisions (901–904) du moteur. Le corpus d'évaluation n'est généré qu'après le
gel du § 7, et lu une seule fois.

## 4. Comparateurs

| Comparateur | Rôle |
|---|---|
| **HABITUAL-1** (pratique habituelle, plan vide) | référence principale ; « pas de recommandation » ≠ « ne rien faire » |
| **Planificateur de référence v6** (`recommend`, information publique, 4 graines de sélection) | objet évalué en P5a ; comparateur en P5b |
| **Oracle d'information parfaite** | évaluation seulement ; énumère tout l'univers sous la vérité privée et retient le meilleur selon OBJ-LEX-1. Plafond **certifié sur cet univers** (énumération complète), pas au-delà ; refusé comme backend produit (`reads_private`) |
| **M_agg / M_ent** (P5b) | voir § 6 |

Mêmes ressources, mêmes contraintes, même objectif pour tous ; la pratique habituelle est
toujours une option.

## 5. Métriques

**Principale (unité native) :** minutes-soignant de soins non couvertes sur 24 h, **réalisées sous
la vérité privée** de l'épisode (palier 1 de OBJ-LEX-1, travail d'admission dû compris).

- **P5a-1** : Δ_hab = U(habituel) − U(plan du planificateur), moyenne par épisode.
- **P5a-2** (descriptif) : part capturée = Σ Δ_hab / Σ (U(habituel) − U(oracle)), ratio de sommes.
- **P5b-1** : Δ_rep = U(plan choisi par M_agg) − U(plan choisi par M_ent), moyenne par épisode.

**Secondaires (descriptives, sans seuil de décision)** : attente de lit (patients·h), heures de
renfort, interventions, lits remis à disposition, pic et temps au-dessus du seuil du score
expérimental PS-EXP-1, effets sur les unités prêteuses, erreur prédictive (MAE, RMSE) de M_agg et
M_ent, variance par structure, complexité (nombre de variables, temps d'ajustement).

## 6. Conception de P5b

**Jumeaux de représentation.** Pour chaque épisode, un jumeau aux **agrégats publics identiques**
(nombre de séjours autorisés, somme des minutes de soins, lits libres, effectifs, capacités) mais
dont les obstacles et besoins logistiques sont portés par d'autres séjours. Contrôles préalables :
égalité exacte des agrégats (assertion) ; **différence des effets moyens** entre jumeaux, mesurée
sur la vérité, avec un IC 95 % excluant 0 sur la partition de développement — sinon le test de
représentation est déclaré **non informatif** et P5b s'arrête sans lecture de l'évaluation.

**Modèles.** Même famille (`HistGradientBoostingRegressor`), même budget : grille identique de
12 configurations (`max_depth` {3, 5} × `learning_rate` {0,05 ; 0,1} × `max_iter`
{100, 200, 400}), 3 graines d'ajustement, mêmes lignes d'entraînement.
- **M_agg** : agrégats publics + descripteur du plan (actions par type, heures cibles, heures de
  renfort).
- **M_ent** : mêmes variables + emplacements fixes par séjour (≤ 8 × caractéristiques publiques :
  autorisation, besoin de transport, disponibilité estimée, obstacles, soins) et par offre de
  renfort. **Aucun identifiant de patient arbitraire** ne remplace les caractéristiques.
- Cible : U réalisé sous la vérité pour chaque (épisode, plan). Variables calculées **uniquement à
  partir du `PublicSnapshot`** (test : variables identiques sous deux vérités différentes).
- Choix d'un plan : argmin de la prédiction parmi les plans admissibles, avec les règles d'égalité
  de OBJ-LEX-1 (tolérance 15 min, puis moins d'heures de renfort, puis moins d'interventions).
- Hyperparamètres choisis sur la **validation**, par le critère principal (U réalisé des plans
  choisis), départage par la MAE ; les trois graines sont toutes rapportées.

## 7. Gel, analyse et règles de décision

**Gel avant toute lecture d'évaluation** : empreinte SHA-256 de ce document, de
`P5_PROTOCOL_PARAMS.json`, du code du générateur, des transformations de variables, de la grille,
des seuils δ et des graines. Toute modification après gel = nouvelle version du protocole,
déclarée, et l'évaluation déjà lue reste rapportée.

**Inférence.** Bootstrap hiérarchique (structures, puis épisodes dans la structure),
2000 rééchantillonnages, IC percentile à 95 %. Aucune pseudo-réplication par ligne horaire ou
par plan. Deux critères principaux (P5a-1, P5b-1), chacun avec sa règle propre ; pas de
revendication de contrôle familial ; les secondaires restent descriptifs.

**Seuils d'utilité fixés maintenant** : δ_P5a = δ_P5b = **15 minutes-soignant par épisode**
(égal à la tolérance d'équivalence de OBJ-LEX-1). Convention de démonstration, pas un seuil
clinique ; δ = 0 n'est utilisé que pour des contrôles techniques.

| Borne IC 95 % | Conclusion |
|---|---|
| borne supérieure < δ | bénéfice **insuffisant** pour ce périmètre |
| borne inférieure > δ **et** garde-fous respectés | bénéfice **démontré dans ce protocole synthétique** |
| sinon | **non concluant** |

**Garde-fous (tous requis)** : 0 violation d'admissibilité ou d'invariant ; 0 fuite (contrôle
d'isolation T03/T04 sur 50 épisodes tirés, plus le test de variables du § 6) ; part d'épisodes où
le plan choisi est pire que la pratique habituelle de plus de δ : borne supérieure IC 95 % ≤ 10 % ;
taux d'exclusion pour univers > 16 plans ≤ 5 % (sinon : rapporté et lecture « non concluant »).

**Précision attendue.** Avant le gel, la partition de développement P5a fournit la variance de
Δ_hab par structure. Si la demi-largeur projetée de l'IC dépasse δ/2 avec 30 structures
d'évaluation, l'augmentation éventuelle de la population est décidée **avant** la lecture, dans le
plafond du § 9, et consignée ; sinon la faible précision est déclarée à l'avance.

## 8. Environnement et dépendances

- Exécution locale CPU, Python **3.13.18** (environnement des suites vertes) ; données synthétiques
  seulement ; aucun GPU, aucune API payante, aucune donnée réelle, aucune action dans un SIH.
- **P5a** : dépendances déjà présentes (pydantic, numpy).
- **P5b** : nécessite **scikit-learn** (absent ici ; borne du `pyproject.toml` : ≥ 1.5, < 1.9) et
  ses dépendances (scipy, joblib, threadpoolctl). **Installation réseau soumise à un accord
  distinct** ; sans elle, P5b est bloqué et seul P5a peut être mené.
- Code nouveau requis (non écrit) : générateur, exécuteur oracle, extraction de variables,
  analyse. Chaque module est testé (déterminisme, isolation public/privé, borne d'univers, égalité
  des agrégats des jumeaux) avant toute génération du corpus d'évaluation.

## 9. Budget proposé (à approuver séparément)

**Plafond : 1200 s cumulées de temps mural d'exécution, 30 s au plus par commande, 0 €.**
Registre distinct `evidence/decision_support/p5/BUDGET_LEDGER_P5.jsonl` (même format chaîné et
ancré) dont le premier enregistrement cite l'empreinte terminale P0–P4
`9056a4a1…b973` ; jamais remis à zéro ; travaux découpés en lots reprenables de moins de 30 s.

**Base d'estimation (mesures existantes du registre, non relancées)** : une recommandation
automatique complète (12 plans × 4 graines) = 0,366 s démarrage compris (enr. #6) ; export de
11 documents (quelques centaines de simulations) = 0,52 à 0,62 s ici (#124, #151), 1,1 à 1,4 s
dans l'environnement de l'auditeur (#140, #169). Hypothèse retenue : **2 à 6 ms par simulation**,
soit 0,2 à 0,6 s par épisode P5a (≈ 64 simulations de prévision + 16 sous la vérité).

| Lot | Contenu | Estimation | Plafond du lot |
|---|---|---:|---:|
| P5.0 | engagement des graines, gel initial, contrôles d'isolation | 10–20 s | 40 s |
| P5.1 | tests du générateur et des extracteurs (développement) | 60–120 s | 150 s |
| P5.2 | **pilote chronométré** (20 épisodes de développement) | 10–20 s | 40 s |
| P5.3 | P5a : développement (100 épisodes) puis évaluation réservée (300) | 80–240 s | 300 s |
| P5.4 | P5b : étiquettes (1200 épisodes × 16 plans), 72 ajustements, sélection, évaluation, planificateur sur l'évaluation | 110–330 s | 400 s |
| P5.5 | bootstrap, rapport, restauration neuve, paquet | 40–80 s | 120 s |
| Réserve | reprises après défaut, sans élargissement | — | 150 s |
| **Total** | | **≈ 310–810 s** | **1200 s** |

L'installation éventuelle de scikit-learn est imputée au registre P5 comme les installations
précédentes (une note, pas un test), dans ce même plafond.

## 10. Règles d'arrêt

Arrêt immédiat, sauvegarde et rapport (sans conclusion inventée) si : empreinte invalide ; fuite
détectée ; violation d'admissibilité ou d'invariant ; non-déterminisme du générateur ; plafond d'un
lot ou plafond global atteint ; **projection du pilote P5.2 > 900 s pour l'ensemble** (demande
d'accord avant de continuer) ; besoin d'une dépense, d'une installation non autorisée ou d'une
écriture distante ; écart au protocole gelé. Une faible amélioration ne justifie pas un
élargissement silencieux de la population, de la grille ou de l'univers d'actions.

## 11. Livrables de P5 (après exécution autorisée)

Protocole gelé et ses empreintes ; engagement et révélation des graines ; manifestes des corpus
(développement, entraînement, validation, évaluation) ; partitions ; tous les résultats, graines,
erreurs et résultats négatifs ; R1 et R2 séparés ; registre P5 complet et ancré ; rapport avec
décision **poursuivre / arrêter / mesurer davantage** ; paquet restaurable. Aucune revendication
réelle, aucune promotion G2, aucune ouverture automatique de P6.

## 12. Décisions demandées à l'utilisateur

1. Approuver (ou amender) ce protocole et le gel des paramètres de `P5_PROTOCOL_PARAMS.json`.
2. Approuver le budget P5 distinct : 1200 s, 30 s par commande, 0 €.
3. Autoriser, ou non, l'installation de scikit-learn pour P5b (sinon : P5a seul).
