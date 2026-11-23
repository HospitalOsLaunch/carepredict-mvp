# P5 — P5-PROTO-3 : amendement limité de P5-PROTO-2 (proposition, non approuvée)

**Version :** P5-PROTO-3, 14 novembre 2026. **Statut : `PROPOSED_NOT_APPROVED`.**
Paramètres : `P5_PROTOCOL_PARAMS_v3.json` (concordants). Base : P5-PROTO-2
(`P5_PROTOCOL_v2.md` `ad0fdaa5…881c`, `P5_PROTOCOL_PARAMS_v2.json` `1d284b0e…d0f7`), approuvé
par D1–D12 **pour ses seules empreintes** ; cette approbation n'est pas transférée à v3. Les
documents v2 et les décisions historiques sont conservés à l'identique.

P5-PROTO-3 = P5-PROTO-2 + les amendements A1–A11 ci-dessous, qui **remplacent** les passages cités
de v2. Tout le reste de v2 est inchangé. Origine : revue statique des lots P5.0–P5.2 (P5L-01 à
P5L-04) et prompt de reprise du 14 novembre 2026. Le fichier
`HospitalOS_Prompt_Amendement_P5_v3_20261114.txt` cité par la revue n'a pas été transmis : la
liste harmonisée ici est celle du § 4 de la revue et du point 1 du prompt de reprise.

Ce que cet amendement ne change pas : questions, métriques principales, δ = 15 (convention
technique), comparateurs, tailles, grille HGB, borne Clopper–Pearson par structure, plafond
global 1200 s, 30 s par commande, plafonds par lot (P5.4 = 470 s), 0 €, P6 fermé, moteur v6
inchangé, statuts `PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`,
`G2=NO-GO`.

## A1 — Clés des innovations (remplace v2 § 3, « Innovations privées à clés stables »)

u = H(engagement, partition, graine de structure, parent, réalisation k, primitive, entité).
**Ni le régime, ni le jumeau ne figurent dans la clé de base.** R1 et R2 partagent donc les mêmes
innovations uniformes ; seule la transformation diffère. Les chocs propres à R2 utilisent des
primitives distinctes (`r2_transport`, `r2_cleaning`, `r2_cleaning_remaining`). La présence des
renforts utilise `presence` (par offre) et `presence_pool` (par pool). « Engagement » désigne
l'identifiant des listes de graines scellées en E0 (`276d965d…df45c`), constant pour tous les
E_k. C'est déjà la mise en œuvre de E0 (`truth.py`) ; v2 contenait les deux formulations
contradictoires.

## A2 — Identité des offres (complète v2 § 5.2)

`offer_key = source | lending_unit | skill | start | end` (sans `option_id`). Contrainte publique :
**unicité de `offer_key` dans chaque épisode**, contrôlée à la construction de l'annexe ; un
doublon est un défaut du générateur, donc une règle d'arrêt, pas une exclusion. Les gabarits
actuels (ORA, ORB, ORC, ORD et l'offre inadmissible ORX) ont des clés distinctes. Aucune collision
n'a été observée dans le pilote, et ce texte n'en revendique aucune.

## A3 — Gels F_a et F_b (remplace l'étape unique F de v2 § 7)

Les autorisations sont séparées et ordonnées : (ii) P5a réservé, puis (iii) P5b. Le gel est
donc dédoublé.
- **F_a**, avant toute génération du réservé P5a : empreintes du protocole, des paramètres, du
  générateur, de la vérité, de l'adaptateur, de l'analyse P5a, de δ et des seuils, plus la
  précision projetée P5a (sur le développement P5a).
- **F_b**, avant toute génération du réservé P5b : mêmes éléments pour P5b, plus le schéma de
  variables, la configuration retenue sur la validation et le résultat du précontrôle.
- Le code commun à P5a et P5b (générateur, vérité, adaptateur) est figé dès F_a. S'il change
  avant F_b, le changement est versionné (E_k), déclaré, et la lecture P5a déjà faite reste
  rapportée sous F_a, jamais réattribuée.
- Les règles E0, E_k, la « lecture unique » et l'interdiction d'ajouter un test réservé après
  lecture sont inchangées.

## A4 — K du précontrôle, des étiquettes et de l'évaluation (complète v2 §§ 2, 6.3, 10)

- **K_precheck = 3**, fixe, sur la partition d'entraînement P5b. Le palier L1 ne s'applique pas
  au précontrôle.
- **K_labels ∈ {3, 2}** : 2 seulement si L1 est déclenché. Les étiquettes utilisent les
  réalisations 1..K_labels, sous-ensemble emboîté des réalisations du précontrôle. L1 vaut aussi
  pour le développement P5a.
- **K_eval = 3**, fixe, pour toutes les évaluations réservées. Aucun palier de repli ne touche
  l'évaluation.

## A5 — Contenu exact de L2 et chronométrage des ajustements (remplace v2 § 10, L2 et pilote)

**Conditions préalables, non remplies aujourd'hui :** D4 (installation) et un accord explicite
pour les « ajustements de chronométrage ». L'installation ne vaut pas autorisation de P5b.

**Matrice de chronométrage** (fixée avant exécution) :
- lignes de variables des parents de développement d'une exécution pilote (P5a_dev), répétées
  par tuilage jusqu'à **n_b = 1440 lignes** par famille ;
- étiquettes = U moyen sous R1 de ces lignes de développement ;
- **limite déclarée** : des lignes répétées ne démontrent pas le coût sur un corpus divers ;
  l'extrapolation à 11 520 lignes est linéaire avec une marge de prudence ×1,5 et reste marquée
  « extrapolée ».

**Banc d'essai** :
- par famille F ∈ {M_agg, M_ent}, configuration la plus coûteuse (`max_depth` 5,
  `learning_rate` 0,1, `max_iter` 400), `random_state` ∈ {0, 1, 2} ;
- paramètres fixes du § 6.4 de v2, `OMP_NUM_THREADS=1`, mêmes données et même matrice de
  prédiction ;
- soit 6 ajustements, une commande par famille, dans le reliquat de P5.2 (37,476 s) ;
- ordre : M_agg (graines 0, 1, 2), puis M_ent (0, 1, 2) ; avant chaque graine k ≥ 1, le script
  refuse de lancer l'ajustement si le temps écoulé + la durée de la graine 0 dépasse le
  reliquat du lot ;
- modèles jetés, aucune prédiction conservée pour une évaluation.

**Critère L2** : écart absolu maximal des prédictions entre graines ≤ 1e-12, **pour les deux
familles**. Portée : l'identité n'est démontrée que pour cette configuration et ces données.
Si L2 s'applique, la sélection utilise `random_state = 0` pour les 24 configurations, plus un
contrôle de reproductibilité des graines 1 et 2 sur la configuration retenue de chaque famille,
soit 28 ajustements. Si une graine diffère, si un ajustement n'aboutit pas ou si le reliquat ne
suffit pas, **L2 est déclaré inapplicable**, sans changer les graines ni le critère après coup.

## A6 — Événement de dégradation (précise v2 § 8.3, garde-fou 4)

- **Parent dégradé** : la moyenne, sur les **K_eval = 3** réalisations du régime lu, de
  (U_comparé − U_hab) est > δ. En P5b, un parent est dégradé si au moins un de ses jumeaux l'est.
- **Structure dégradée** : au moins un parent dégradé.
- Borne de Clopper–Pearson unilatérale à 95 % sur les structures réservées, inchangée. Ce n'est
  pas un événement par réalisation.

## A7 — Interaction coordination × renforts (précise v2 § 5.3)

a\* = c\* ∪ r\* ; **I = U(c\*) + U(r\*) − U(a\*) − U_hab**, soit l'effet de la coordination à
renforts égaux moins l'effet de la coordination seule. I > 0 : la coordination vaut davantage
avec les renforts. Si c\* ou r\* est vide, I = 0. Moyenne et IC bootstrap rapportés en
descriptif, sans seuil.

## A8 — Support de population effectivement généré (complète v2 § 3)

Population **construite**, à déclarer comme telle :
- unité fixe : 6–8 lits, IDE seulement, instant de décision fixe (lundi 16 novembre 2026,
  20 h Paris) ;
- séjours : 2–3 autorisés, préparation à 8 h ou 11 h, départ prévu à 12 h ou 16 h ;
- obstacles pris dans 3 codes ; admissions : 1 à 3 ;
- transport : une seule plage de jour ; nettoyage : capacité 1 ;
- offres : 4 gabarits fixes, plus une offre inadmissible.

`choose_offers` **réduit le nombre d'offres admissibles selon le nombre d'ensembles de
coordination**, pour tenir ≤ 16 plans. Davantage de possibilités de coordination entraîne donc
moins de possibilités de renfort. Le taux d'exclusion mesure seulement le résidu de cette
population construite. Il ne mesure pas un dépassement dans une population tirée
indépendamment. « 0 exclusion sur 20 » ne démontre ni représentativité ni couverture des cas
difficiles. Aucun élargissement automatique du générateur ou du catalogue.

## A9 — Contrôles d'exécution normatifs (P5L-02, P5L-03)

1. **Avant lancement**, le compteur P5 refuse :
   - un lot non autorisé ;
   - un programme qui n'est ni un interpréteur de l'environnement approuvé (chemin exact) ni
     un outil statique autorisé ;
   - un gel de dépendances hors de la liste approuvée (gel D3, plus tout gel post-installation
     inscrit au registre par une note `environment_approved` après accord).
   Chaque refus est consigné.
2. **Avant toute génération ou reprise** sur une partition engagée, l'engagement effectif
   (dernière note `commitment` du registre) est vérifié contre les sources, les graines scellées
   et le moteur v6. Un écart entraîne un refus.
3. **Identité d'exécution du pilote** : engagement, code, partition, identifiants de structure
   stables (empreinte, sans la graine), parents, K, régimes, environnement. Chaque exécution a son
   répertoire. Une ligne d'une autre identité est refusée, jamais mélangée. Les anciens relevés,
   dont le pilote E0, sont conservés.
4. **Arrêt avec reçu d'échec** sur violation, univers modifié entre réalisations ou plan
   recommandé hors univers. Les véritables abstentions restent évaluées comme HABITUAL-1 et sont
   comptées.

## A10 — Erratum `not_requested`

v2 § 5.2 qualifie ces offres de « non sélectionnables (comme en v6) ». En v6,
`option_admissibility` ne rejette que `unknown`. Le générateur n'émet jamais `not_requested` :
aucun effet sur P5.

## A11 — Devis recalculé à partir des mesures (complète v2 § 10)

| Poste | Mesuré / extrapolé | Estimation |
|---|---|---|
| Simulation sous vérité | mesuré : 0,77 ms | — |
| Recommandation v6 | mesuré : 0,044 s | — |
| Extraction | mesuré : 0,09 ms par ligne et par famille | — |
| P5.3 (P5a dev + réservé) | extrapolé des mesures (univers moyen 7,4 ; borne 16) | 32–48 s |
| P5.4 hors ajustements | extrapolé des mesures | 39–70 s |
| 72 ajustements | **non mesuré** | 135–1951 s (hypothèse 3–20 ns) |
| Banc A5 | à mesurer après D4 et accord | ≈ 5–35 s + démarrages (hypothèse 3–20 ns) |

L1 et L3 économisent moins de 20 s. Seul L2 ou une mesure réelle peut changer l'ordre de
grandeur. Aucune augmentation du plafond, aucun palier silencieux.

## Décisions demandées (aucune n'est prise par ce document)

| # | Décision | Recommandation |
|---|---|---|
| D13 | Approuver P5-PROTO-3 (empreintes de ce document et du JSON v3) | approuver après relecture |
| D14 | = D4 : installer scikit-learn (+ scipy, joblib, threadpoolctl) en versions exactes dans l'environnement isolé, lot P5.I (60 s), gel post-installation consigné comme `environment_approved` | décision distincte, qui n'autorise pas P5b |
| D15 | Autoriser le banc A5 : 6 ajustements de chronométrage, matrice tuilée de 1440 lignes, dans le reliquat P5.2, modèles jetés | après D13 et D14 |
| D16 | Option : banc à 11 520 lignes en réaffectant jusqu'à 50 s de la réserve vers P5.2 | non recommandé avant le résultat de D15 |
| (ii), (iii) | Évaluation réservée P5a ; ajustements et évaluation P5b | inchangées, séparées, après F_a / F_b |
