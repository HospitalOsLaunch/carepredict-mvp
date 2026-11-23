# P5-PROTO-1 → P5-PROTO-2 : changements et décisions à approuver

14 novembre 2026. **Statut : `PROPOSED_NOT_AUTHORISED_NOT_EXECUTED`.** Amendement documentaire
seulement, en réponse au rapport `RAPPORT_REVUE_CLOTURE_P5.md` (P5-M01 à P5-M06 + complément sur les
ressources). Aucune exécution, simulation, génération, ajustement, test produit, installation ni
chargement de poids pour le produire. Le reliquat P0–P4 n'est pas utilisé. La v6 reste scellée et
inchangée ; aucune v7 n'est demandée. Les originaux v1 sont conservés à l'identique.

## 1. Tableau des changements

| # | Point de revue | P5-PROTO-1 (original) | P5-PROTO-2 (proposé) | Où (MD § / JSON) |
|---|---|---|---|---|
| C01 | M01 oracle ≠ plafond | Oracle = meilleur plan OBJ-LEX-1 sous la vérité ; part capturée = Σ Δ / Σ (U_hab − U_oracle) | Deux objets : **U\*** = minimum exact de U sur 𝒜(x) par réalisation (plafond, dénominateur) et **O_lex** (diagnostic, hors dénominateur). C ≤ 1 par construction, peut être < 0, aucun écrêtage ; « non défini » si marge moyenne < 15 ; regrets R_plan, R_hab, R_lex ; U_fix diagnostic biaisé | § 4, § 5.1 / `comparators`, `metrics` |
| C02 | M01 univers | Implicite | 𝒜(x) dépend du seul instantané public, identique pour toutes réalisations, régimes et comparateurs ; les futurs cachés ne changent ni autorisations ni univers ; garde-fou d'empreinte | § 2, § 8.3 / `hierarchy.plan_universe`, `guardrails` |
| C03 | M02 lien plan–entités | M_ent = M_agg + emplacements par séjour et offre, lien non spécifié | Contrat `features(PublicSnapshot, Plan, annexe)` : blocs B0–B4, champs de lien plan (ciblé, type, heure ; offre sélectionnée), jointures par identifiants sans les émettre, ordre canonique, masques, vocabulaires fixes, dépassement = exclusion ; tests futurs F1–F6 (dont renommage et distinguabilité) | § 6.2 / `P5b_design.features` |
| C04 | M03 vérité des renforts | « Présence effective aléatoire » ; R2 = 0,5 « au lieu de la valeur déclarée » (aucune valeur déclarée n'existe en v6) | Annexe publique `HOSPITALOS_P5_REINFORCEMENT_1` (p_pub, clé d'offre, pool) ; réalisation R1 Bernoulli(p_pub) indépendante ; R2 marginale 0,5 + copule ρ = 0,5 par pool ; coût prévu/réalisé ; règle d'exécution en boucle ouverte ; adaptateur `p5/eval_adapter.py` distinct, v6 inchangée et décrite comme conditionnelle ; tests futurs T-P5-R1/R2 | § 5.2 / `reinforcement_truth` |
| C05 | M04 hiérarchie | « Structure, puis épisode » ; « épisode » désignait aussi un jumeau | structure > parent > jumeau > réalisation (K = 3 par régime) > plan ; bootstrap structure puis parent, le parent emporte jumeaux, réalisations et plans | § 2, § 8.1 / `hierarchy`, `analysis.bootstrap` |
| C06 | M04 tailles et régimes | Non précisé (par régime ou total) | Tailles = instantanés publics ; K = 3 par régime évalué ; P5b entraîné et sélectionné sous R1 seul ; R2 = lecture d'évaluation, séparée, ne relève pas un verdict | § 2 / `population.regime_use` |
| C07 | M04 poids | Non précisé | Estimand à poids égaux structure → parent → jumeau → réalisation ; `sample_weight` = 1/n_plans × correction d'exclusions par structure | § 2, § 6.3 / `hierarchy`, `labels_and_weights` |
| C08 | M04 exclusions et abstentions | « Exclu et compté » | Comptées sur tous les candidats avant filtrage, motifs publics, remplacement par la graine engagée suivante ; abstentions évaluées comme pratique habituelle ; exception du générateur = arrêt | § 3 / `population.exclusions`, `abstentions` |
| C09 | M04 précontrôle des jumeaux | Différence des effets moyens, IC excluant 0, sur une partition de développement non définie | Partition = entraînement P5b, R1, K = 3, avant validation/évaluation ; actions = plans homologues non habituels ; statistique **non signée** θ = E[d²] corrigée de la variance des réalisations ; informatif si borne inférieure ≥ 25 min² (5 min RMS) ; aucune sélection de paires sur résultat | § 6.1, § 6.3 / `twin_precheck` |
| C10 | M04 construction des jumeaux | « Obstacles portés par d'autres séjours » | Permutation σ des vecteurs logistiques entre séjours autorisés, règle publique tirée du flux engagé ; actions homologues définies ; `twin_degenerate` ; population déclarée stress-test | § 6.1 / `P5b_design.twins` |
| C11 | M05 arrêt anticipé | Non réglé (automatique au-delà de 10 000 lignes ; jusqu'à 11 520 ici) | `early_stopping=False` explicite ; tous les hyperparamètres fixés ; `OMP_NUM_THREADS=1` ; pas de validation interne non groupée | § 6.4 / `models.fixed` |
| C12 | M05 graines d'ajustement | « 3 graines, toutes rapportées » | Graines {0,1,2} attendues identiques (à vérifier) ; graine 0 principale ; diversité observée rapportée ; jamais des répétitions indépendantes | § 6.4 / `models.fit_seeds` |
| C13 | M05 borne de dégradation | Borne sup. IC 95 % (bootstrap percentile) ≤ 10 % — dégénère à 0 si aucun cas | Clopper–Pearson unilatérale 95 % sur les **structures** dégradées (≥ 1 parent dégradé) : valide sous dépendance intra-structure, conservatrice, non dégénérée (0/30 → 9,50 %) ; table de référence ; formulation « risque de dégradation limité » | § 1, § 8.3 / `guardrails.harm` |
| C14 | M05 précision P5b | Projection de précision pour P5a seulement | Projection aussi pour P5b (validation) ; constat déclaré : 8 structures réservées → garde-fou inatteignable (31,2 %) ; option 30 × 4 à coût égal ; verdict plafonné à « exploratoire » si précision insuffisante déclarée avant F | § 2, § 8.3, § 8.4 / `population.P5b.evaluation_reserved`, `precision_projection_before_F` |
| C15 | M06 environnement | « Python 3.13.18 (environnement des suites vertes) » (MD et JSON) | Affirmation retirée ; tableau de provenance 3.13.18 / 3.11.18 / 3.13.5 / 3.11.9 ; proposition 3.11.18 + gel `bf540981…` + scikit-learn à version exacte fixée à l'installation ; porte 3.11.9 non fermée | § 9 / `environment` |
| C16 | M06 calendrier de gel | Gel unique avant lecture | E0 engagement initial → D développement → E_k nouvel engagement à chaque changement du générateur → F gel final avant génération des réservés → lecture ; « lecture unique » = pas de réglage après inspection, rejeu d'audit permis ; aucun nouveau test réservé après lecture | § 7 / `freeze_stages` |
| C17 | M06 devis | 310–810 s ; pilote = simulations seules | Devis recalculé avec réalisations, régimes, extraction, 72 ajustements, bootstrap, installation : **≈ 494–1377 s** ; pilote mesurant aussi extraction, ajustements les plus coûteux et bootstrap ; échelle de repli pré-enregistrée (L1–L3) déclenchée par chronométrage seul ; 1200 s = proposition non activée ; installation imputée | § 10 / `budget` |
| C18 | Complément ressources | Absent | Décomposition descriptive (renforts seuls / coordination à renforts égaux / coordination seule / interaction), U\* par classe, heures prévues/réalisées, effets prêteurs ; seule la coordination à renforts égaux est attribuable au choix des patients | § 5.3 / `metrics.resource_decomposition_descriptive` |
| C19 | δ = 15 | Convention de démonstration | Inchangé ; explicitement **convention technique, jamais clinique**, modifiable seulement par amendement soumis | § 8.2 / `analysis.delta_…` |
| C20 | Règles d'arrêt | Projection pilote > 900 s | Projection > 1000 s **après** échelle de repli ; ajout : arbre v6 modifié, exception du générateur, catégorie hors vocabulaire | § 11 / `stop_rules` |

Inchangé : séparation par structure, référence habituelle présente, vérité privée inaccessible au
produit, évaluation réservée après gel, R1/R2 séparés, résultats négatifs conservés, δ = 15, grille
HGB de 12 configurations, 30 structures P5a réservées, budget distinct de P0–P4, 30 s par commande,
0 €, P6 fermé.

## 2. Décisions à approuver (aucune n'est prise par ce document)

| # | Décision | Options | Recommandation |
|---|---|---|---|
| D1 | Protocole | Approuver P5-PROTO-2 comme base de gel / amender | Approuver après relecture ; tout amendement = P5-PROTO-3 |
| D2 | Budget P5 | (a) 1200 s + échelle de repli L1–L3 ; (b) 1800 s sans repli ; 30 s/commande, 0 € dans les deux cas | (a) ; (b) si l'on refuse le risque d'arrêt après pilote |
| D3 | Environnement | (a) Python 3.11.18 + gel `bf540981…` ; (b) 3.13.18 de la session (pytest hors borne) ; aucune ne ferme la porte 3.11.9 | (a) |
| D4 | Installation scikit-learn + scipy, joblib, threadpoolctl | Autoriser (version exacte fixée et consignée à l'installation, candidate 1.7.2, disponibilité non vérifiée ; temps imputé au lot P5.I) / refuser (P5a seul) | Décision distincte ; n'autorise pas les ajustements |
| D5 | Taille d'évaluation réservée P5b | (a) 30 structures × 4 parents × 2 jumeaux ; (b) 8 × 15 × 2 (v1) — même coût | (a) : garde-fou atteignable ; (b) laisse P5b exploratoire |
| D6 | Vérité des renforts | p_pub ∈ {0,4…0,9} indépendantes en R1 ; R2 marginale 0,5, ρ = 0,5 par pool ; tout ou rien par offre ; boucle ouverte | Approuver ou amender les valeurs avant E0 |
| D7 | Précontrôle des jumeaux | seuil 25 min² (5 min RMS), K = 3, partition d'entraînement | Approuver ; seuil = convention technique |
| D8 | Boosting | `early_stopping=False`, paramètres fixes du § 6.4, `OMP_NUM_THREADS=1` / validation interne groupée explicite | `early_stopping=False` |
| D9 | Borne de dégradation | Clopper–Pearson par structure (conservatrice) / autre méthode valide à déclarer avant E0 | Clopper–Pearson par structure |
| D10 | Décomposition ressources | Descriptive, sans coût supplémentaire / ajouter un critère décisionnel à ressources égales (coût et règle à définir) | Descriptive |
| D11 | Autorisations d'exécution | Séparées : (i) mise en œuvre et pilote P5.0–P5.2 ; (ii) évaluation réservée P5a ; (iii) ajustements et évaluation P5b | Séparées, dans cet ordre |
| D12 | Cockpit | Hors P5 ; la porte « rejeu React indépendant » reste une porte produit séparée | Approuver la séparation |

## 3. Ce que ce document ne change pas

Statuts : `PARTIAL_WITH_CHECKPOINT`, `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`,
`G2=NO-GO` ; V5-R01 clos sur les cas audités ; portes Python 3.11.9 exact et rejeu navigateur
indépendant **ouvertes**. Registre P0–P4 : 175 enregistrements, 421,325 s, terminal
`9056a4a1…b973`, non prolongé par cette rédaction. A_detached : authentifié à 2000 pour les graines
11/23/37, final 6000 non attesté — statut documentaire, pas un échec scientifique.
