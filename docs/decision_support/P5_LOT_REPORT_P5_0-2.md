# P5 — Rapport des lots P5.0 à P5.2 (mise en œuvre et pilote), 14 novembre 2026

Autorisation de l'utilisateur : « J'autorise la mise en œuvre et le pilote P5.0–P5.2 » (D11-i).
Protocole : P5-PROTO-2 approuvé (D1–D12, `P5_DECISIONS_v2.md`). Environnement : Python 3.11.18,
gel `bf540981…b6da` vérifié à chaque commande (D3). Aucune installation, aucun ajustement, aucune
génération de partition réservée, aucun push. Moteur v6 inchangé (vérifié par `git diff` contre
`856a57c` à E0 et par test).

**Statut : P5.0 et P5.1 terminés ; P5.2 `PILOT_PARTIAL_FITS_NOT_TIMED`.** Les statuts globaux sont
inchangés : `PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`,
`G2=NO-GO` ; P6 fermé.

## 1. Budget P5 (registre distinct)

`evidence/decision_support/p5/BUDGET_LEDGER_P5.jsonl` + ancre ; genèse citant le terminal P0–P4
`9056a4a1…b973` (175 enregistrements, 421,325 s, non prolongé). Lots autorisés codés dans le
compteur : P5.0, P5.1, P5.2 (tout autre lot est refusé).

| Lot | Plafond | Utilisé | Commandes |
|---|---:|---:|---|
| P5.0 | 30 s | 2,467 s | lint (×2), engagement E0, isolation T03/T04 v6 |
| P5.1 | 130 s | 3,392 s | tests P5 (×2) |
| P5.2 | 40 s | 2,524 s | pilote (2,024 s) + 0,5 s imputés pour un lint lancé hors compteur |
| **Total** | **1200 s** | **8,383 s** | reliquat 1191,617 s |

## 2. Code (paquet séparé, v6 intact)

| Fichier | Rôle |
|---|---|
| `src/hospitalos/p5/generator.py` | structures, parents, jumeaux (permutation σ des vecteurs logistiques entre séjours autorisés), annexe publique des renforts, exclusions publiques comptées avant filtrage |
| `src/hospitalos/p5/truth.py` | réalisations privées à clés stables ; R1/R2 ; présence des renforts (R2 : marginale 0,5, copule ρ = 0,5 par pool) |
| `src/hospitalos/p5/eval_adapter.py` | retire les renforts absents de la copie d'évaluation, puis simulation v6 sous vérité + contrôle d'invariants |
| `src/hospitalos/p5/features.py` | contrat `features` : M_agg 290 variables, M_ent 718 ; schéma statique `59fcd248…de95` |
| `src/hospitalos/p5/analysis.py` | Clopper–Pearson par structure, bootstrap à deux étages, part capturée sans écrêtage, θ, verdicts |
| `scripts/p5_budget_run.py`, `scripts/p5_commit.py`, `scripts/p5_pilot.py` | compteur P5, engagement E0/E_k, pilote |
| `tests/p5/test_p5_implementation.py` | 24 tests |

## 3. P5.0 — engagement E0 et isolation

Graines tirées une fois (`secrets`), scellées dans `SEEDS_SEALED.json` (SHA-256 `dcfbca74…1d45`),
disjointes de 101–104 et 901–904 ; empreintes par partition (P5a_dev 10, P5a_eval 30, P5b_train
24, P5b_val 8, P5b_eval 30) et de la graine de bootstrap ; identifiant d'engagement
`276d965d…df45c` ; empreintes du code, du schéma de variables et des documents approuvés ;
moteur v6 identique au commit `856a57c`. Enregistré au registre (#4 commande, #5 note). Isolation
T03/T04 du moteur v6 : 2/2.

## 4. P5.1 — tests (24/24, `pytest_p5_1.xml`)

Déterminisme ; exclusions comptées avant filtrage avec motifs publics ; univers complet ≤ 16 avec
pratique habituelle ; jumeaux : B0 identique (F5), même taille d'univers, vecteurs logistiques
déplacés ; jumeau dégénéré détecté ; réalisations déterministes et univers invariant ; adaptateur =
`PrivateOracle` v6 quand toutes les offres sont présentes, 0 violation ; **T-P5-R1** (présence
différente ⇒ couverture réalisée différente, recommandation inchangée) ; **test de mutation** : un
adaptateur qui ignore la présence est aveugle, donc T-P5-R1 le détecte ; **T-P5-R2** (présences
par `offer_key`, indépendantes de l'ordre et des identifiants) ; marges R1/R2 et corrélation R2 ;
F1, F2 (renommage complet ⇒ mêmes vecteurs, même choix), F3, F4, F6 ; arrêt hors vocabulaire ;
table Clopper–Pearson du protocole retrouvée ; part capturée sans écrêtage et non définie sous
15 min ; bootstrap par structure ; θ non signé ; verdicts ; v6 intact.

## 5. P5.2 — pilote chronométré (20 parents P5a_dev, R1+R2, K = 3)

Mesures (développement, `PILOT_REPORT_P5_2.json`) : 20 parents, 0 exclusion sur 20 candidats ;
plans par parent 7,4 en moyenne (1 à 14) ; 888 simulations sous vérité à **0,77 ms** chacune ;
recommandation v6 **0,044 s** (max 0,106) ; extraction **0,09 ms** par ligne et par famille ;
génération 2,8 ms par parent, jumeau 1,7 ms ; bootstrap complet 2000 rééchantillonnages 0,054 s ;
commande entière 2,02 s. Garde-fous en développement : 0 violation, plan choisi toujours dans
l'univers, univers invariant, 0 abstention, 0 jumeau dégénéré. Les valeurs de U sont conservées
comme données de développement (`U_dev_only`) et **ne sont pas lues comme résultat**.

**Non mesuré : les ajustements.** scikit-learn est absent et son installation (D4) n'est pas
autorisée ; les deux ajustements les plus coûteux prévus au pilote n'ont pas pu être chronométrés.

### Projection

| Poste | Univers moyen (7,4) | Univers 16 | Plafond |
|---|---:|---:|---:|
| P5.3 (P5a dev + évaluation) | 32 s | 48 s | 330 s |
| P5.4 hors ajustements | 39 s | 70 s | 470 s |
| P5.4 : 72 ajustements, **non mesuré** (hypothèse 3–20 ns par ligne × variable × arbre) | 135–902 s | 293–1951 s | — |
| Total sans ajustements (installation, P5.5 et déjà utilisé compris) | ≈ 150–290 s | | |
| Total avec 72 ajustements | ≈ 285–2240 s | | 1200 s |

Les simulations coûtent 3 à 8 fois moins que l'hypothèse du protocole (2–6 ms) ; le devis est
désormais **dominé par les ajustements**, que le pilote n'a pas pu mesurer. L'échelle de repli ne
peut pas être tranchée : L1 et L3 économisent moins de 20 s ; L2 exige le contrôle d'identité des
graines, qui exige scikit-learn. **Aucun palier n'est appliqué, rien n'est lancé au-delà de P5.2.**

## 6. Écarts et précisions de lecture du protocole approuvé (sans changement d'analyse)

1. **Clé des innovations.** § 3 liste le régime r dans la clé, tout en exigeant que R1 et R2
   partagent les innovations uniformes. Mise en œuvre : r hors de la clé de base ; les décalages R2
   ont leurs propres primitives (`r2_transport`, `r2_cleaning`, …). À entériner dans une future
   révision documentaire.
2. **`not_requested`.** § 5.2 dit ces offres « non sélectionnables (comme en v6) » ; en v6,
   `option_admissibility` ne rejette que `unknown`, une offre `not_requested` serait admise comme
   conditionnelle. Le générateur n'émet jamais `not_requested` : aucun effet sur P5, erratum
   documentaire.
3. **Graine du bootstrap du pilote** : 12345, pour le chronométrage seulement ; la graine engagée en
   E0 reste réservée à l'analyse.
4. **Graines scellées** : le fichier est versionné localement (nécessaire à la reprise) et figure
   dans le paquet de livraison. Le protocole prévoyait leur révélation dans le paquet final ; leur
   empreinte est au registre depuis E0, avant toute génération, ce qui préserve l'engagement.
5. **Taille réelle des univers** : 7,4 plans en moyenne, contre la borne de 16 utilisée pour le
   devis : les volumes réels seront environ la moitié des maxima.

## 7. Décisions nécessaires pour continuer (aucune n'est prise ici)

1. **D4** : autoriser l'installation de scikit-learn (lot P5.I, plafond 60 s), sans autoriser
   d'ajustement de P5b.
2. **Finir P5.2** dans son reliquat (37,5 s) : chronométrer les 2 ajustements les plus coûteux et
   le contrôle d'identité des graines. Proposition : sur une matrice de la forme d'entraînement P5b
   construite à partir des lignes de développement P5a_dev ; durées seulement, modèles jetés.
3. Puis, selon la projection : ≤ 1000 s ⇒ poursuite possible quand (ii) puis (iii) sont
   autorisées ; sinon échelle de repli ; sinon arrêt et demande (1800 s, ou P5a seul).
4. P5a ne dépend pas des ajustements : son évaluation (ii) est projetée à ≈ 32–48 s et peut être
   autorisée indépendamment.
