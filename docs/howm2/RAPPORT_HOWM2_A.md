# HOWM-2 — Rapport de la tranche A (audit d'identifiabilité de HOWM-1)

Statuts inchangés : `PROTOTYPE_UNVALIDATED`, `clinical_validation=false`, `G2=NO-GO`.
Aucun entraînement, aucune descente de gradient. Monde synthétique uniquement ; aucun bénéfice
hospitalier réel n'est revendiqué. La réserve HOWM-1 est restée scellée. DEVTEST et DIAG-DEV n'ont
pas été relus. Les fichiers gelés en G0 et F1, v6, P5, `mvp/computer-use` et les résultats R1 livrés
n'ont pas été modifiés (test `test_g0_and_f1_frozen_code_unchanged`). Rien n'a été poussé.

Règles : `docs/howm2/NORME_HOWM2_A.md` (registre n° 5), addendum 1 (n° 6), addendum 2 (décision
n° 2 de l'utilisateur, n° 22). Toutes les règles ont été consignées avant les mesures qu'elles
régissent.

## 0. Verdicts

| Verdict | Résultat |
|---|---|
| Principal (§ 5, δ_id = 0,02 nat) | **`HOWM1_DISCRIMINANT`** selon les règles amendées (addendum 2). Selon les règles d'origine : **critère non calculable**, car toutes les familles sont exclues (§ 3). |
| État caché | **Aucune part récupérée.** Seuls transport et nettoyage ont un état caché mesurable. Pour eux, L4 est *moins bon* que L3 (π < 0), à cause de l'incertitude sur θ. |
| Décisionnel | **`MARGE_DECISIONNELLE_LT_15`**. U(règle) − U(planificateur L4) = **−28,7** [−51,8 ; −6,6] : le planificateur nourri par L4 fait *moins bien* que la règle renforcée. |
| Filtre de référence | (c) exact. (a′) : calibration acceptée pour ready, confirmation et arrivées, refusée pour transport et nettoyage. (b′) : aucune violation. |

**Lecture.**
- Sur HOWM-1, un prédicteur public bayésien exact (L4) bat la meilleure référence explicite
  (B0-local sur tout le passé, L2) de 0,10 nat à H6 et de 0,14 nat à H24, avec une marge largement
  détectable.
- Cette marge vient de la **connaissance structurelle des lois**, et non de la récupération d'un
  état caché : pour ready et confirmation, L3 = L5 et L4 ≈ L3.
- Elle **ne se convertit pas en valeur de décision** : partir de l'état public coûte plus que la
  meilleure prévision ne rapporte (§ 6–7).

## 1. Vérification des faits du § 2 (`evidence/howm2/FACTS_CHECK.json`)

| Fait | Statut | Détail |
|---|---|---|
| F1 effectifs d'items d'entraînement | conforme | auth 34 810, ready 1 534, transport 195, cleaning 217, confirmation 832, arrivées 73 728, soins 1 608 714 (TRAIN 0–31) |
| F2 avantage par famille à H24 | conforme | B0-local − B0-pool : ready −0,057, transport −0,084, cleaning −0,051 |
| **F3 courbes VAL** | **écart** | Gain du meilleur point sur la 1re époque : **0,000 à 0,014**, et non 0,004 à 0,009. Le maximum après le meilleur point monte à **7,489** (B2 lr 1e-3, graine 1), au-delà du « 7,45 » annoncé. |
| F4 perte d'entraînement non journalisée | conforme | le journal ne contient que les pertes VAL |
| **F5 T-INF-08** | **écart** | Gain de 0,0088 en 60 pas, sur 8 établissements TRAIN et 3 VAL. Les échelles étaient déjà celles de TRAIN 0–31 (registre n° 52–53 avant n° 54), pas « 48 contre 32 ». |
| F6 TRAIN = 32 | conforme | état du pilote : 2 instants, M_dec 8, train_n 32 |
| F7 confirmation H24 | conforme | B0-pool 3,167, B0-local 3,166, B2 3,165, H1 3,152 |
| F8 décision | conforme | gains contre l'habituel : C_full 214,3, règle 200,2, oracle 235,9 (DEVTEST livré, cité sans relecture) |

## 2. Échelle L0–L5 (`evidence/howm2/LADDER_A.json`, `evidence/howm2/ladder/`)

**Couverture.** Les 200 établissements HOWM2_REF et les 100 HOWM2_DIAG, plus les 12 VAL et
48 TRAIN existants. Les partitions neuves sont enregistrées à l'exécution
(`src/hospitalos/howm2/space.py`), avec les clés `key("HOWM1", part, i)`. L'espace de clés est
disjoint de G0 (testé), et le générateur n'est pas modifié (octets identiques, testé).

**Score.** Protocole R1 : NLL à hasard discret, compartiments de 15 min (auth 60), 192
compartiments plus la queue, censure à l'horizon ; arrivées NB ; soins par compartiments de 5 min ;
présence de Bernoulli. Le score L4 est égal au score R1 (`test_hazard_score_equals_r1_protocol`).

**Moyennes REF à H24 par famille (nat)**

| Famille | L0 | L1 | L2 | L3 | L4 | L5 |
|---|---:|---:|---:|---:|---:|---:|
| ready | 3,452 | 3,407 | 3,360 | 3,099 | 3,118 | 3,099 |
| transport | 2,513 | 2,449 | 2,429 | 2,286 | 2,310 | 2,254 |
| cleaning | 2,274 | 2,209 | 2,191 | 2,106 | 2,114 | 2,072 |
| confirmation | 3,007 | 3,005 | 3,001 | 2,658 | 2,702 | 2,658 |
| arrivées | 0,445 | 0,444 | 0,443 | 0,440 | 0,442 | 0,440 |
| soins | 1,539 | 1,541 | 1,546 | 1,525 | 1,525 | 1,525 |

- Autorisation : L0 à L2 seulement (≈ 1,03), conformément à l'addendum 1.
- Présence : aucun item dans les cohortes REF.

## 3. Validation du filtre de référence (§ 4), avant tout usage comme plafond

**(c) Exactitude de la postérieure de régime : réussie** (`VALIDATION_C.json`).

| Contrôle | Écart max |
|---|---:|
| Énumération des 2^12 chemins | 4e-15 |
| Énumération avec items réels relocalisés | 1,8e-12 |
| Forward-backward indépendant (200 items) | 8e-14 |

Les préfixes réels de 12 h ne contiennent aucun item. L'énumération avec relocalisation, déclarée,
fournit le cas non trivial.

**Règles d'origine : contradictoires, consignées telles quelles.**
- (a) KS sur tous les PIT, seuil 0,02 : il rejette aussi L5, le prédicteur vrai. Les PIT répétés
  d'un même item aux origines successives sont dépendants (`DIAG_PIT.json`).
- (b) « L4 ≤ L3 » est impossible par construction, puisque L3 connaît θ.

Application littérale : toutes les familles sont exclues, et le critère n'est pas calculable
(`criterion_literal_original_rules`). Arrêt, paquet `HOWM2_P2_A_BLOCKED_VALIDATION.zip`
(sha 7339252b…), puis question à l'utilisateur.

**Règles amendées (addendum 2, choisies par l'utilisateur).**
- (a′) un PIT par item, à sa première apparition, avec un seuil D ≤ max(0,02 ; 1,63/√n). L5 sert de
  témoin positif.
- (b′) violation seulement si l'IC à 95 % de L4 − L5 est entièrement sous 0.

| Famille | n | D(L4) | D(L5) | seuil | Décision |
|---|---:|---:|---:|---:|---|
| ready | 5 513 | 0,0079 | 0,0085 | 0,0220 | conservée |
| transport | 2 546 | **0,0363** | 0,0316 | 0,0323 | exclue |
| cleaning | 3 082 | **0,0306** | **0,0375** | 0,0294 | exclue (L5 échoue aussi : limite du test, signalée) |
| confirmation | 4 472 | 0,0107 | 0,0163 | 0,0244 | conservée |
| arrivées | 1 152 000 | 0,0022 | — | 0,02 | conservée |
| soins | — | — | — | — | aucun PIT collecté ; non exclue |
| présence | 0 | — | — | — | aucun item |

(b′) : aucune violation dans aucune famille.

## 4. Critère principal (200 REF, bootstrap par grappes, B = 2 000)

Familles : ready, confirmation, présence, arrivées, soins. Meilleure référence : **L2** à chaque
horizon, avec un choix refait à chaque réplique.

| Horizon | L2 | L4 | M_pub | IC 95 % | s_e | n pour 80 % à M_pub/2 |
|---|---:|---:|---:|---|---:|---:|
| H1 | 0,9909 | 0,9465 | 0,0443 | [0,0381 ; 0,0510] | 0,046 | 34 |
| H6 | 1,8998 | 1,8012 | **0,0986** | [**0,0873** ; 0,1097] | 0,082 | 22 |
| H24 | 2,0874 | 1,9466 | **0,1408** | [**0,1213** ; 0,1619] | 0,146 | 34 |

Les bornes basses dépassent 0,02 à H6 et à H24, d'où **`HOWM1_DISCRIMINANT`**.

**Note de puissance.** Pour détecter M_pub/2 avec une puissance de 80 % (α = 5 %), il faut environ
22 établissements à H6 et 34 à H24. Avec 200 établissements, la marge est mesurée avec une large
avance.

**Données descriptives, toutes familles.**

| Population | H6 | H24 |
|---|---|---|
| REF | 0,098 [0,088 ; 0,108] | 0,127 [0,112 ; 0,142] |
| HOWM2_DIAG | 0,205 [0,179 ; 0,235] | 0,264 [0,231 ; 0,299] |
| VAL (12) | 0,107 [0,066 ; 0,147] | 0,130 [0,078 ; 0,179] |
| TRAIN (48) | 0,038 [0,015 ; 0,060] | 0,036 [0,011 ; 0,064] |

La marge TRAIN est plus faible : B0 a été ajusté sur TRAIN 0–31.

## 5. État caché (part récupérée π_f = (L3 − L4)/(L3 − L5))

- **ready, confirmation, arrivées, soins** : IC de L3 − L5 contenant 0, donc **« sans état
  caché »**. L'état caché de m3 (charge) est public par construction en L3.
- **transport** : L3 − L5 = 0,032 [0,020 ; 0,045] à H24, avec **π = −0,75** [−1,32 ; −0,38].
- **cleaning** : L3 − L5 = 0,034 [0,025 ; 0,044], avec **π = −0,22** [−0,49 ; 0,01].

Pour ces deux familles, L4 perd plus à ignorer θ qu'il ne gagne à filtrer le régime. Sur HOWM-1, la
marge identifiable est donc **structurelle** : connaître la forme des lois (délais log-normaux
arrondis, recalage nocturne, retard de publication, mélange de mécanismes) et l'inférer. Elle n'est
pas « dynamique » au sens d'un état caché suivi dans le temps.

## 6. Marge décisionnelle accessible (`evidence/howm2/DECISION_A.json`)

**Dispositif.**
- 48 instants VAL : 12 établissements, à 07, 11, 15 et 19 h du jour 5.
- Planificateur R1 sur 16 candidats, sélection OBJ-LEX-1, M = 8.
- Chaque trajectoire tire (θ, mécanisme, régime à τ) dans la postérieure L4 et part de l'état
  public, avec les clés 201–208.
- Les U d'évaluation sont repris du précontrôle HOWM-1.

| Système | U moyen | Gain contre l'habituel |
|---|---:|---:|
| Habituel | 5 097,8 | 0 |
| Planificateur L4 | 5 002,8 | 95,0 |
| C_param (état public, θ vrai) | 5 007,0 | — |
| C_pub_snap (état public, centre a priori) | 4 999,5 | — |
| Règle renforcée | 4 974,1 | 123,7 |
| C_full (état vrai, régime vrai) | 4 945,2 | 152,6 |
| Oracle | 4 931,9 | 165,9 |

**Marge** = U(règle) − U(L4) = **−28,7** [−51,8 ; −6,6], d'où **`MARGE_DECISIONNELLE_LT_15`**.
L4 fait mieux que la règle sur 8 instants et moins bien sur 26.

**Lecture.**
- Les trois planificateurs partis de l'**état public** se tiennent à environ 8 unités les uns des
  autres : L4, C_param et C_pub_snap. Mieux connaître θ, le mécanisme ou le régime ne change
  presque rien.
- L'écart avec C_full (≈ 58) vient du **point de départ** : état vrai contre état public.
- OBJ-LEX-1 retient le plan le plus simple à 15 près. Avec un état public, il choisit souvent un
  plan sans coordination, alors que la règle coordonne toujours (candidats 13 et 14).

## 7. Défauts de mesure

### 7.1 Pertes TRAIN et VAL des checkpoints (`evidence/howm2/INSTR_LOSSES.json`)

Passe avant seule sur 1 536 origines TRAIN 0–31 et 1 440 origines VAL. Perte totale normalisée :

| Exécution | best TRAIN | best VAL | last TRAIN | last VAL | époque best / last |
|---|---:|---:|---:|---:|---|
| B2 lr 3e-4 s0 | 6,984 | 7,214 | 6,850 | 7,230 | 6 / 26 |
| B2 lr 1e-3 s0 | 6,955 | 7,210 | 6,600 | 7,451 | 6 / 26 |
| B2 lr 1e-3 s1 | 6,950 | 7,208 | 6,554 | 7,391 | 6 / 26 |
| H1 lr 3e-4 s0 | 6,979 | 7,211 | 6,892 | 7,211 | 6 / 26 |
| H1 lr 3e-4 s1 | 6,930 | 7,205 | 6,786 | 7,274 | 20 / 40 |
| H1 lr 1e-3 s0 | 6,991 | 7,215 | 6,816 | 7,285 | 1 / 21 |

**Verdict d'instrumentation : sur-apprentissage, pas non-apprentissage.**
- La perte TRAIN baisse de 0,09 à 0,40 entre best et last, tandis que la perte VAL monte.
- Les familles en cause sont transport et cleaning, avec respectivement 195 et 217 items
  d'entraînement : TRAIN passe de 2,21 à 1,88 quand VAL passe de 2,27 à 2,48.
- L'écart VAL − TRAIN est déjà présent au meilleur point, et dès l'époque 1 pour H1 lr 1e-3. Il
  porte sur auth (+0,43) et ready (+0,48) : c'est une différence de population d'origines entre
  TRAIN et VAL, non un effet d'apprentissage. Les origines TRAIN sont `range(24, 166, 3)` et
  atteignent les jours 6 et 7, alors que les origines VAL sont `range(24, 144)` (`corpus.ORIGINS`).

### 7.2 Couverture à 90 % à H1 (`evidence/howm2/DIAG_COVERAGE.json`)

Mesure sur VAL seulement, aux 48 origines de décision, avec B0-local, M = 16 et les clés de R1.

| Départ | H | cov90 | cov50 | intervalles dégénérés | cov90 non dégénérés | KS du PIT |
|---|---:|---:|---:|---:|---:|---:|
| public (R1) | 1 | **0,573** | 0,458 | 0,339 | **0,399** | 0,255 |
| public (R1) | 6 | 0,717 | 0,552 | 0,198 | 0,649 | 0,165 |
| public (R1) | 24 | 0,799 | 0,637 | 0,201 | 0,759 | 0,128 |
| vrai | 1 | **0,877** | 0,722 | 0,415 | 0,810 | 0,125 |
| vrai | 6 | 0,882 | 0,715 | 0,253 | 0,842 | 0,066 |
| vrai | 24 | 0,884 | 0,736 | 0,224 | 0,859 | 0,063 |

**Explication.**
- La sous-couverture à H1, commune à tous les systèmes, B0 compris, vient surtout de l'**état de
  départ public** : il retarde sur l'état vrai, à cause du retard de publication et des événements
  non encore publiés. Les déroulés ne peuvent donc pas atteindre la vérité à une heure.
- Le PIT en U (excès aux deux extrémités) le confirme.
- Les intervalles dégénérés (q05 = q95, cibles entières) couvrent 0,91 et masquent le problème.

**Correction proposée, non appliquée à R1 :**
- rapporter la couverture séparément sur les intervalles non dégénérés ;
- rapporter le PIT randomisé ;
- démarrer les déroulés depuis un état public complété par la postérieure des événements en
  attente de publication.

### 7.3 Indicateur « ne sait pas » (constant à 1,0)

- **Définition R1** : écart entre les deux meilleurs < écart-type marginal / √M. Taux observé ici :
  **1,00**. L'écart-type marginal de U inclut la variance commune aux candidats, que les nombres
  aléatoires communs (CRN) annulent dans les différences.
- **Redéfinition proposée** : écart < 1,96 × erreur type de la **différence appariée**. Taux sur les
  48 décisions L4 : **0,021**.

La redéfinition n'est pas appliquée aux résultats R1 livrés.

## 8. Coûts (registre `evidence/howm2/BUDGET_LEDGER_HOWM2.jsonl`)

Plafond total : 3 600 s de temps mural, CPU, 0 €. Consommé : **1 433,0 s** sur 31 commandes
(registre n° 1 à 31, chaîné et ancré). Les échecs sont comptés.

| Lot | Commandes | Échecs | Mural (s) | Plafond (s) |
|---|---:|---:|---:|---:|
| A.TEST | 3 | 0 | 45,2 | 400 |
| A.FACTS | 1 | 0 | 0,2 | 60 |
| A.LADDER | 6 | 0 | 1 093,8 | 1 600 |
| A.VALID | 7 | 1 | 81,9 | 300 |
| A.DEC | 1 | 0 | 30,7 | 300 |
| A.INSTR | 1 | 0 | 124,6 | 300 |
| A.DIAG | 2 | 1 (sans `keep_instants`, 2,8 s) | 11,2 | 240 |
| A.REST | 3 | 0 | 45,4 | 400 |

**Paquets et restauration**
- Paquet de blocage : `HOWM2_P2_A_BLOCKED_VALIDATION.zip` (sha 7339252b…), avant l'addendum 2.
- Paquet final : `HOWM2_P2_A_FINAL.zip`, sha256 `6826601c4a46143a679637e3df1b1ce282a6aa0022bd96628378e0f777d02b87`,
  55,5 Mo, commit c9969725.
- Reçu de restauration (`evidence/howm2/RESTORE_RECEIPT_A.json`), obtenu dans un répertoire neuf :
  - SHA256SUMS intègres ;
  - `tests/howm2` : 8 réussis ;
  - HOWM2_REF 0 et HOWM2_DIAG 0 régénérés à l'identique ;
  - analyse refaite, `LADDER_A.json` identique, même verdict.

## 9. Ce que la tranche A permet de conclure, et ce qu'elle ne permet pas

- HOWM-1 **peut** départager, en score, un prédicteur proche des lois vraies et la meilleure
  référence explicite. Le nul de R1 n'est donc pas une impossibilité du monde. Il est compatible
  avec un échec d'apprentissage : sur-apprentissage avec 195 à 217 items par famille de service.
- HOWM-1 **ne peut pas** montrer de valeur décisionnelle d'un meilleur prédicteur à partir de
  l'état public : la marge accessible est négative.
- La marge identifiable ne porte pas sur un état caché. Un world model qui réussirait sur HOWM-1
  aurait appris des **lois**, pas un **état**.
- Les règles (a) et (b) d'origine étaient contradictoires. Le verdict principal dépend de leur
  amendement, décidé par l'utilisateur avant la nouvelle mesure. Les deux résultats sont livrés.
