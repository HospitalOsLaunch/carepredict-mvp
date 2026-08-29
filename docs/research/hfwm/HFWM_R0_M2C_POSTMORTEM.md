# HFWM-R0 M2C — Post-mortem du candidat partagé rejeté

## Décision

M2 a rejeté procéduralement le candidat parce que son point estimate
d'occupation a franchi le guardrail pré-enregistré. Le banc M1 est trop peu
puissant pour établir la direction ou l'amplitude vraie de cet effet. Le modèle
`local_joint_from_scratch` devient le contrôle de référence. Ce post-mortem ne
modifie aucun résultat, métrique ou seuil M2 et ne contient aucun nouveau run.

```yaml
candidate_status: REJECTED_BY_OCCUPANCY_GUARDRAIL
procedural_basis: PRE_REGISTERED_POINT_ESTIMATE_RULE
primary_superiority: INCONCLUSIVE
primary_inferiority: NOT_DEMONSTRATED
occupation_guardrail: FAILED_PROCEDURALLY
true_occupation_regression: NOT_ESTIMATED_WITH_DECISION_GRADE_PRECISION
world_model_advantage: NOT_TESTABLE_ON_M1
```

## 1. Audit des seeds

Source unique : `artifacts/hfwm-r0/bakeoff-m2b/results.json`, SHA-256
`29ee6b878db5311dcbc8a51ca0a5f9100e4c30c6606bf66181bc9fb42dd974bd`.
Les quatre configurations reproduites trois fois se trouvent dans
`raw_runs[0..11]`; le fichier a été écrit le
2026-08-29 à 01:03:18 +0200. Il n'existe ni timestamp ni chemin individuel par
run. Aucun cache ou checkpoint n'est lu par le runner; tous les modèles sont
ajustés en mémoire et aucun poids n'est persisté.

| # | Bras | Seed demandée | Propagation Python / NumPy / framework | Config SHA-256 | `model_hash` | Prédiction SHA-256 | NMAE; occupation; inflow |
|---:|---|---:|---|---|---|---|---|
| 0 | mécanistique | 1729 | non / non / aucune | d78f05fca1a3b7a8ca295e42e895fb1e2759163676a3c56675cffae6e3033287 | d78f05fca1a3b7a8ca295e42e895fb1e2759163676a3c56675cffae6e3033287 | 0a55fa2eb9b940363ca13ba3f755e3bb7fd768384b993b09dc01e92d40ac0308 | 1.5299627132266669; 1.8932587597866666; 1.1666666666666667 |
| 1 | local | 1729 | non / non / config seulement | acc01b5ad4c06c8bd1556c9af29d97521939f52954ce43e86c2c4959799b22ab | 2ef4339a7c2d26903be2d6501976231e1fcc5dd18b137434f90ad946a19b8e2a | da3f34661c93b20a60e0e0645864b98795c649046279eabe924aeb55b141f944 | 0.5180213134518407; 0.4463524620341881; 0.5896901648694934 |
| 2 | partagé | 1729 | non / non / config seulement | acc01b5ad4c06c8bd1556c9af29d97521939f52954ce43e86c2c4959799b22ab | 6e7990700ac0c804090ec9e334334ad2a04c0b20238744349048422466e52872 | 8382c7571efa24ea7f21a750ea5db8233f3b294d5b5f7db94d58e9bcc381bf42 | 0.5522654409743488; 0.5236052645201302; 0.5809256174285674 |
| 3 | HGBR/CQR | 1729 | non / non / `random_state=1729` | 11d3351ccd46c7a9309ccd7154f2b3672df60ff47119178b93ae6d82544bce88 | 25fd6c3e62d91567b5c67d47b1dbff7d3606dfd3244c778fca166f8a6d379952 | 13c2abd3523ae197940bbfb9b8d61dbb0fd06a193d3c71cf6d5042b67b9fe269 | 0.543554615093483; 0.5193646309157104; 0.5677445992712555 |
| 4 | mécanistique | 2718 | non / non / aucune | d78f05fca1a3b7a8ca295e42e895fb1e2759163676a3c56675cffae6e3033287 | d78f05fca1a3b7a8ca295e42e895fb1e2759163676a3c56675cffae6e3033287 | 0a55fa2eb9b940363ca13ba3f755e3bb7fd768384b993b09dc01e92d40ac0308 | 1.5299627132266669; 1.8932587597866666; 1.1666666666666667 |
| 5 | local | 2718 | non / non / config seulement | e1646869e99f208e139efd0b4e2140af09837bba4759eb22b28e32e77a9b0010 | 703e09b3de1998133193d2a9b14a8a0cc9571cd05b4df50578a31957f86e8f20 | da3f34661c93b20a60e0e0645864b98795c649046279eabe924aeb55b141f944 | 0.5180213134518407; 0.4463524620341881; 0.5896901648694934 |
| 6 | partagé | 2718 | non / non / config seulement | e1646869e99f208e139efd0b4e2140af09837bba4759eb22b28e32e77a9b0010 | fd0228a79ab5afc82a661032b17c7f695d46de00f4c13c07fc592423c5a73252 | 8382c7571efa24ea7f21a750ea5db8233f3b294d5b5f7db94d58e9bcc381bf42 | 0.5522654409743488; 0.5236052645201302; 0.5809256174285674 |
| 7 | HGBR/CQR | 2718 | non / non / `random_state=2718` | d95d3f41abd138b328404a7597ae0598961e390399c4811c5d6f3c0b6614df83 | b3af522bd74910e60278b9a443a019330d45bd4993fce1b9e7f2a4d6d4889883 | 13c2abd3523ae197940bbfb9b8d61dbb0fd06a193d3c71cf6d5042b67b9fe269 | 0.543554615093483; 0.5193646309157104; 0.5677445992712555 |
| 8 | mécanistique | 3141 | non / non / aucune | d78f05fca1a3b7a8ca295e42e895fb1e2759163676a3c56675cffae6e3033287 | d78f05fca1a3b7a8ca295e42e895fb1e2759163676a3c56675cffae6e3033287 | 0a55fa2eb9b940363ca13ba3f755e3bb7fd768384b993b09dc01e92d40ac0308 | 1.5299627132266669; 1.8932587597866666; 1.1666666666666667 |
| 9 | local | 3141 | non / non / config seulement | 75fed516b347854557694b7986c51682357dc30df1d52466b8bb20935baa95e5 | 6e6a60bfebce0112252323eb40ada935f9baaead577560a5e698d739c62600d2 | da3f34661c93b20a60e0e0645864b98795c649046279eabe924aeb55b141f944 | 0.5180213134518407; 0.4463524620341881; 0.5896901648694934 |
| 10 | partagé | 3141 | non / non / config seulement | 75fed516b347854557694b7986c51682357dc30df1d52466b8bb20935baa95e5 | af438f31893c8d73ec72db735f9158ae3ed3e8e611be2c3bb1efc547abfad99e | 8382c7571efa24ea7f21a750ea5db8233f3b294d5b5f7db94d58e9bcc381bf42 | 0.5522654409743488; 0.5236052645201302; 0.5809256174285674 |
| 11 | HGBR/CQR | 3141 | non / non / `random_state=3141` | 980e3e0cb1bc3662f49d6ac48b343305c380cab8e13804ad31f660900a275f1a | 69b210af819e991dd3a748f21113d871fa74c91f6ec71bf65d8a6604604514b7 | 13c2abd3523ae197940bbfb9b8d61dbb0fd06a193d3c71cf6d5042b67b9fe269 | 0.543554615093483; 0.5193646309157104; 0.5677445992712555 |

`model_hash` n'est pas un hash pur des poids : local/partagé y incluent le
seed de configuration, et HGBR y inclut le seed et le hash du train, pas les
arbres sérialisés. Les hashes de poids appris sont donc indisponibles. Le ridge
local/partagé utilise `numpy.linalg.solve` sans aléa; `sample_futures`, seul
chemin NumPy seedé, n'est jamais appelé. HGBR reçoit `random_state`, mais avec
`early_stopping=False` produit également des prédictions identiques.

Conclusion seeds : **DETERMINISTIC_BY_DESIGN**. Le comptage des seeds favorables
est retiré des preuves : il s'agit d'une seule issue déterministe répétée sous
trois labels, non de trois réplications indépendantes. Cette faiblesse réduit la
preuve de stabilité mais ne change pas la décision procédurale fondée sur le
point estimate d'occupation du cohort gelé.

## 2. Où apparaît la régression occupation

Sur 36 cellules : MAE locale 2.2317623101709407, partagée
2.6180263226006515, soit +17.307578440112875 % et +0.3862640124297106
par cellule. Le biais passe de -0.503561872314013 à -0.09146047029947645,
mais la variance résiduelle augmente de 7.031657014380838 à
11.864727131894833 : l'échec est une dispersion/hétérogénéité accrue, pas un
simple biais global. Le delta d'erreur partagé-local est positif sur 58.33 %
des cellules.

| Décomposition occupation | Local MAE | Partagé MAE | Régression |
|---|---:|---:|---:|
| Pas 1 / 00 h | 1.685863 | 1.820310 | +7.97 % |
| Pas 2 / 06 h | 1.890573 | 2.122238 | +12.25 % |
| **Pas 3 / 12 h** | **2.433515** | **3.415861** | **+40.37 %** |
| Pas 4 / 18 h | 2.917097 | 3.113697 | +6.74 % |
| Occupation basse, ≤24 (n=14) | 2.906888 | 3.009227 | +3.52 % |
| Occupation médiane, 24–31 (n=12) | 1.689833 | 1.588556 | -5.99 % |
| **Occupation haute, ≥31 (n=10)** | **1.936902** | **3.305710** | **+70.67 %** |
| Site/unité 0 (n=12) | 2.706713 | 2.958898 | +9.32 % |
| Site/unité 1 (n=12) | 1.907894 | 1.778628 | -6.78 % |
| **Site/unité 2 (n=12)** | **2.080681** | **3.116554** | **+49.79 %** |

Les trois épisodes de « forte tension » (au moins une occupation ≥31) sont
tous ceux du site/unité 2 : +49.79 %, delta d'erreur positif sur 11/12 cellules, biais
partagé -2.528148 contre -1.147488 local. Site et tension sont donc confondus;
les artefacts ne permettent pas de séparer leurs effets. Par missingness, la
régression est +45.88 % pour 2 h observées (n=2), +41.04 % pour 3 h (n=5),
-6.31 % pour 4 h (n=16), +37.37 % pour 5 h (n=12), et -56.45 % pour 6 h
(n=1) : signal compatible, mais effectifs trop faibles pour conclure.

Inflow s'améliore de 1.49 % (MAE 2.358761 → 2.323702). Les intervalles
occupation du partagé sont plus larges (13.512350 contre 12.504064) et couvrent
moins (91.67 % contre 94.44 %); inflow couvre 97.22 % dans les deux cas.
La dérive free-running est 1.049994 contre 1.041840. Les deltas appariés
d'occupation sont positifs dans 6/9 épisodes et particulièrement élevés sur
les épisodes site 2 (+1.126835, +1.734280, +0.246503 MAE).

## 3. Parité expérimentale

Parité confirmée : mêmes 240 lignes PIT et hash dataset, mêmes 42/9/9 épisodes,
mêmes fenêtres test, targets, transformations, observations disponibles,
rollout initial-only, calibration conformale validation-only, métriques et
variables futures connues (aucune). Compute observé comparable : local
0.081330 s CPU total, partagé 0.077793 s; même plafond 60 s/seed.

Différence pré-enregistrée : local entraîne trois modèles de 18 paramètres
(54 agrégés), routés par site; partagé entraîne un seul modèle de 18 paramètres
sur les trois sites, sans site ID ni adaptation. La parité existe par modèle
déployé, pas en capacité agrégée. Aucune différence non pré-enregistrée trouvée.

## 4. Diagnostic du partage

| Mécanisme | Statut | Preuve |
|---|---|---|
| Negative transfer occupation↔inflow | NOT_SUPPORTED | Les deux targets ont des solves ridge et coefficients séparés; pas de compétition de loss. |
| Pondération de loss défavorable | NOT_SUPPORTED | Aucune pondération; ridge séparé par target. |
| Échelle/normalisation | PLAUSIBLE | Valeurs brutes et ridge alpha commun; interaction avec pooling possible, non isolée. |
| Capacité partagée insuffisante | PLAUSIBLE | 18 paramètres partagés contre 54 agrégés locaux; aucune ablation de capacité. |
| État partagé non informatif | NOT_SUPPORTED | Même état et mêmes inputs que local; inflow ne régresse pas. |
| Heads marginales, dynamique non jointe | SUPPORTED_BY_EXISTING_EVIDENCE | Les targets sont ajustées séparément; aucune covariance jointe n'est apprise. Son rôle causal reste non testé. |
| Spécialisation locale légitime | SUPPORTED_BY_EXISTING_EVIDENCE | Échec concentré site 2/haute tension; modèle partagé sans adaptation, local routé par site. |
| Diversité insuffisante | SUPPORTED_BY_EXISTING_EVIDENCE | Trois pseudo-sites, une unité par site, neuf épisodes test; site et tension confondus. |
| Negative transfer entre sites/régimes | PLAUSIBLE | Pattern site 2 et occupation haute fort, mais aucune ablation leave-one-site/adaptation. |

Le pattern le mieux documenté est compatible avec un **pooling inter-site sans
adaptation face à une hétérogénéité site/régime**. Il ne permet pas de choisir
une cause et reste exploratoire, non démontré causalement.

## 5. Statut scientifique

- Ce candidat partagé n'est pas retenu.
- Le modèle local devient le contrôle de référence.
- `FOUNDATION_EVIDENCE_INSUFFICIENT` : aucune propriété Foundation démontrée.
- Capacité et conservation restent non évaluables dans le dataset gelé.
- Aucun claim causal, contre-factuel ou action-conditionné n'est autorisé.

## 6. Passage vers M3 — non exécuté

M1 ne permet pas de tester un avantage de world model : conservation, capacité
et transfert ne sont pas observables. La proposition d'un simple biais site est
donc retirée comme prochain test confirmatoire; elle ne distinguerait pas un
world model d'un forecaster calibré. Le seul draft retenu est
`HFWM_R0_M3_DRAFT.yaml`, bloqué sur l'enrichissement des stocks, flux, capacités
et unités indépendantes. Il pré-enregistre une seule modification principale :
une transition jointe stock–flux, comparée au contrôle local gelé et soumise au
même guardrail occupation.
