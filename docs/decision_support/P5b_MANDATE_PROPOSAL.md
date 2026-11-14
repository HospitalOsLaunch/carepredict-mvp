# P5b — Proposition de mandat (iii) et devis (14 novembre 2026)

**PROPOSITION NON APPROUVÉE. AUCUNE EXÉCUTION.** Ce document ne vaut autorisation que s'il est
adopté explicitement. Il ne rouvre pas P5a, reste `exploratory`, P5A-D02 clos avec réserve. Rédigé
sans calcul : arithmétique sur des mesures déjà consignées seulement, registre non prolongé.

**Question de P5b.** Un modèle qui voit les séjours et les ressources (M_ent) choisit-il de meilleurs
plans qu'un modèle limité aux agrégats (M_agg), à budget de modèle égal ?

Critère principal : Δ_rep = U(choix M_agg) − U(choix M_ent), apparié, sur l'évaluation réservée.
C'est un bénéfice empirique de représentation dans ce simulateur, pas une mesure exacte de
l'information perdue. Protocole applicable : P5-PROTO-3 + 3.1 (D13) ; tailles D5 ; HGB D8.

## 1. Déroulé proposé (chaque étape conditionne la suivante)

1. **Reprise de l'état.**
   - Registre P5 : 88 enregistrements, 134,580 s, terminal `9eb379d3…`.
   - Environnement 3.11.18 et gel post-D14 `bd5bc537…`. S'il est absent : arrêt, sans
     installation implicite.
   - Code P5b (étiquettes, précontrôle, ajustement et sélection, gel F_b, analyse) testé puis engagé
     (E_k) **avant** la génération correspondante.
2. **Étiquettes d'entraînement** (P5b_train, 24 × 15 parents × 2 jumeaux, R1, K = 3) et
   **précontrôle des jumeaux** :
   - θ ≥ 25 min² en borne inférieure, sur les plans homologues ;
   - **non informatif ⇒ arrêt** avant validation et évaluation, résultat rapporté.
3. **Validation** (8 × 15 × 2, R1, K = 3), puis **ajustements** M_agg et M_ent (grille de 12
   configurations, `early_stopping=False`, `OMP_NUM_THREADS=1`). Sélection sur la validation par le
   U réalisé des plans choisis.
4. **Projection de précision** de Δ_rep sur la validation, avec **son propre** écart-type entre
   structures, sans réutiliser celui de P5a. Si la demi-largeur projetée dépasse 7,5 sur
   30 structures, la lecture est **exploratoire, déclarée avant F_b**.
5. **Isolation sur 50 épisodes, avant F_b** (leçon de P5A-D02) :
   - épisodes tirés sur validation et entraînement ;
   - méthode v2 pré-enregistrée : les variables M_agg et M_ent sont invariantes sous les 5 vérités
     B ; T04-b/c/d ; T04-a = NON_INFORMATIF accepté et nommé d'avance s'il ne trouve pas de plan
     témoin.
6. **Gel F_b**, puis **évaluation réservée** P5b_eval (30 × 4 × 2 jumeaux, R1 et R2, K = 3) et
   analyse : Δ_rep avec IC, garde-fou de dégradation de M_ent contre HABITUAL-1 (borne de
   Clopper–Pearson par structure), décomposition, R2 en robustesse seulement.
7. **Livraison** vérifiée après extraction neuve, puis arrêt. D16, P6 et AJ-H restent fermés.

## 2. Devis depuis les mesures consignées

**Mesures de base :**
- simulation sous vérité : 0,77 ms ;
- recommandation : 0,044 s ;
- extraction : 0,09 ms par ligne et par famille ;
- génération : environ 4,5 ms par parent et son jumeau ;
- **7,9 plans par épisode** (300 parents réservés P5a) ;
- coût par arbre A5 à 1440 lignes : M_agg 4,42 ms, M_ent 11,55 ms, extrapolé linéairement en
  lignes.

**Lignes d'entraînement attendues : ≈ 5 690 par famille** (720 épisodes × 7,9).

| Poste P5.4 | Brut | Marge ×1,5 |
|---|---:|---:|
| Hors ajustements : étiquettes 13,1 + 4,4 s ; évaluation 8,7 s ; planificateur sur l'évaluation 10,6 s ; génération 2,7 s ; extraction 1,7 s | 41 s | — |
| Démarrages des commandes d'ajustement (≈ 12–14 commandes de moins de 30 s) | ≈ 15–20 s | — |
| **Ajustements, voie L2 : 28** (24 sélection + 4 contrôles inter-graines) | **227 s** | **341 s** |
| Ajustements, plan complet : 72 | 530 s | 795 s |
| Un ajustement M_ent à 400 itérations | 18,3 s | — |

**Totaux P5.4 :**
- voie L2 : **≈ 290 s brut, ≈ 410 s avec marge**, sous le plafond de **470 s** ;
- 72 ajustements : **dépasse 470 s**, même sans marge.

À l'univers maximal (11 520 lignes), un seul ajustement M_ent dure environ **37 s, au-delà de
30 s par commande** : c'est la règle d'arrêt, et ce n'est pas contournable silencieusement.

Ces chiffres sont des extrapolations : banc A5 tuilé, coût linéaire supposé, profondeur 5 appliquée
à toute la grille. Ce ne sont pas des garanties.

**Reliquats :**
- global : 1065,420 s ;
- P5.4 : 470 s, intact ;
- P5.5 : 87,4 s, pour l'analyse et la livraison.

## 3. Le point qui exige votre décision : L2

Le protocole (A5 de v3, R4 de v3.1) ne déclenche L2 que si la **projection totale dépasse
1000 s**. Elle ne les dépasse pas : environ 560 s avec marge. Pourtant, 72 ajustements dépassent le
**plafond de lot P5.4**. Appliqué à la lettre, le protocole mènerait à un arrêt sur plafond de lot.

| Option | Effet | Recommandation |
|---|---|---|
| **A — appliquer L2 à P5b par décision explicite** (28 ajustements ; condition d'identité entre graines déjà satisfaite sur le banc A5, portée bornée à ce banc et déclarée) | tient dans 470 s ; graine 0 retenue, graines 1 et 2 en contrôle sur la configuration retenue | **recommandée** |
| B — réallouer des plafonds inutilisés vers P5.4 (par exemple une partie des ≈ 279 s inutilisées de P5.3) pour garder 72 ajustements | environ 590 s brut, 860 s avec marge ; exige une décision de réallocation | possible, plus coûteux |
| C — ne rien changer | arrêt prévisible sur plafond P5.4 pendant les ajustements | non recommandée |

Dans toutes les options : un ajustement dépassant 30 s ⇒ arrêt et reçu, sans découpage par
`warm_start` (fixé à False par D8).

## 4. Ce que P5b ne pourra pas établir

- Pas de causalité réelle ni de calibration réelle.
- Pas de généralisation hospitalière ni de preuve en faveur d'une architecture latente.
- La population de jumeaux est construite (stress-test).
- Le verdict peut rester « exploratoire » si la précision projetée est insuffisante, ou « non
  informatif » si le précontrôle échoue : ce sont des issues légitimes, pas des échecs à corriger.

## 5. Accord proposé, à adopter explicitement

« J'autorise (iii), P5b uniquement, selon P5-PROTO-3 + 3.1, dans le plafond P5.4 = 470 s, P5.5 pour
l'analyse et la livraison, 30 s par commande, 0 €, avec l'**option A** (L2 appliqué par décision
explicite : 28 ajustements). Isolation sur 50 épisodes avant F_b, méthode v2. Arrêt sur précontrôle
non informatif, plafond, ajustement de plus de 30 s ou violation. Pas de D16, P6, AJ-H, installation,
push, merge ou rebase. Arrêt après la livraison P5b. »

Statuts inchangés : `PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`,
`clinical_validation=false`, `G2=NO-GO`.
