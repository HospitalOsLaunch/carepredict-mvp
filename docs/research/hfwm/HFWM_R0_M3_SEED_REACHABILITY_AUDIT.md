# HFWM-R0 M3D — Audit seed-reachability et pureté des hashes

## Conclusion

Les douze lignes M2 représentent **quatre configurations déterministes reproduites
trois fois**, et non douze fits stochastiques indépendants. Les prédictions sont
identiques sous les labels `1729`, `2718` et `3141` parce qu'aucun chemin aléatoire
atteignant le fit ou l'inférence n'est actif. Il n'y a ni checkpoint ni cache relu.

```yaml
mechanistic_queue_semimarkov: DETERMINISTIC_BY_DESIGN
local_joint_from_scratch: DETERMINISTIC_BY_DESIGN
shared_hfwm_multitask: DETERMINISTIC_BY_DESIGN
hgbr_cqr: DETERMINISTIC_BY_DESIGN
model_fit_seed_status: NOT_APPLICABLE_DETERMINISTIC_FIT
replication_policy: ONE_FIT_PER_CONFIGURATION
scientific_variance_sources:
  - episodes
  - hospital_sites
  - temporal_blocks
```

Source gelée : `artifacts/hfwm-r0/bakeoff-m2b/results.json`, SHA-256
`29ee6b878db5311dcbc8a51ca0a5f9100e4c30c6606bf66181bc9fb42dd974bd`.

## Amendement M3D.1 — preuve dédiée

Les tests M3D.1 atteignent le générateur final de la simulation et vérifient quatre
propriétés séparées : même seed et mêmes entrées donnent les mêmes bytes de tirage ; une
seed différente modifie ces bytes ; l'état du bit-generator change après tirage ; la seed
déclarée est celle passée au `numpy.random.default_rng` final. La simulation est refusée
si une de ces assertions échoue. Le `simulation_output_hash` couvre les sorties et non la
seule configuration.

Pour les bras M2, le nouveau test relit les quatre groupes de trois lignes et impose
l'identité de `prediction_hash`, `repeat_prediction_hash` et des prédictions non arrondies
entre labels. Il interdit leur comptage comme réplications. Il ne relance aucun fit : ce
serait un entraînement interdit par M3D.1.

## Traçage par composant

| component | deterministic_by_design | random_source | seed_parameter | seed_entrypoint | seed_reaches_component | expected_effect | observed_effect | evidence |
|---|---:|---|---|---|---:|---|---|---|
| génération des splits M1 | oui | aucune | seed de config sans usage | aucun | non | aucun : split chronologique gelé | même dataset/splits | `src/hfwm/data_slice/builder.py`; dataset SHA gelé |
| ordre local des données | oui | aucune | seed de config | aucun | non | aucun : tri d'épisodes et lignes | même ordre et prédictions | `src/hfwm/bakeoff/m2b.py` |
| ordre partagé des données | oui | aucune | seed de config | aucun | non | aucun : tri lexicographique par contenu | même ordre et prédictions | `SharedHFWMModel._content_sorted_rows` |
| initialisation ridge local/partagé | oui | aucune | `JointDynamicsConfig.seed` | configuration seulement | non | aucun poids initial aléatoire | prédictions identiques | `src/hfwm/models/local/model.py` |
| solveur ridge | oui | aucune | aucun | `numpy.linalg.solve` | non | solution déterministe pour mêmes matrices | prédictions identiques | `LocalJointDynamicsModel._fit_rows` |
| mécanistique | oui | aucune | aucun | aucun | non | calcul fermé identique | hash prédictions identique | bras `mechanistic_queue_semimarkov` M2 |
| HGBR/CQR | oui dans cette config | `random_state` disponible | seed M2 | constructeur HGBR | oui mais sans opération stochastique active | aucun effet avec `early_stopping=False` et données/ordre gelés | prédictions identiques | `src/hfwm/baselines/model.py`; trois hashes prédictions égaux |
| calibration M2 | oui | aucune | aucun | quantile déterministe validation | non | qhat identique | qhat et intervalles identiques | `src/hfwm/bakeoff/metrics.py` |
| bootstrap M2 | stochastique | `random.Random` | `8675309` constant | fonction IC bootstrap | oui | resampling reproductible | un seul IC persisté | `src/hfwm/bakeoff/m2b.py` |
| simulation de puissance M3D.1 | stochastique | `numpy.random.Generator` | `31082026` | `run_power_plan` → `_cell` → `simulation_draws` → `default_rng` | oui, assertion obligatoire | même seed = mêmes tirages et état final; seed distincte = tirages distincts; état consommé | couvert par test dédié de reachability | `src/hfwm/m3d/power.py`; `tests/hfwm/m3d/test_power.py` |
| sérialisation JSON M2 | oui | aucune | seed parfois inclus dans ancienne empreinte | JSON canonique | sans objet | bytes déterministes | hashes reproductibles | `src/hfwm/bakeoff/contracts.py` |
| hashing M3D | oui | aucune | selon type de hash | fonctions séparées | sans objet | domaines séparés | couvert par test de pureté | `src/hfwm/m3d/contracts.py` |

## Audit des quatre bras

| Bras | Seed déclarée | Seed Python | Seed NumPy/framework | Données | Paramètres appris | Prédictions | Cache/checkpoint | Verdict |
|---|---|---|---|---|---|---|---|---|
| mécanistique | 1729/2718/3141 | non propagée | non applicable | SHA identique | aucun poids appris | SHA `0a55fa…0308` ×3 | aucun | `DETERMINISTIC_BY_DESIGN` |
| local | 1729/2718/3141 | non propagée | config seulement | SHA identique | non persistés; solve déterministe | SHA `da3f34…f944` ×3 | aucun | `DETERMINISTIC_BY_DESIGN` |
| partagé | 1729/2718/3141 | non propagée | config seulement | SHA identique | non persistés; solve déterministe | SHA `8382c7…bf42` ×3 | aucun | `DETERMINISTIC_BY_DESIGN` |
| HGBR/CQR | 1729/2718/3141 | non propagée | `random_state` reçu | SHA identique | non persistés | SHA `13c2ab…e269` ×3 | aucun | `DETERMINISTIC_BY_DESIGN` dans la configuration M2 |

Les artefacts M2 ne permettent pas de calculer un `weights_hash` rétrospectif : les
poids n'ont pas été persistés. Les anciennes valeurs `model_hash` local/partagé/HGBR
incluent le seed ou la configuration et ne sont donc **pas** des hashes purs de poids.
Elles sont requalifiées `legacy_qualified_model_configuration_hash` et ne constituent
pas une preuve d'indépendance des fits.

```yaml
model_fit_seed_status: NOT_APPLICABLE_DETERMINISTIC_FIT
replication_policy: ONE_FIT_PER_CONFIGURATION
historical_pure_weights_hash:
  mechanistic_queue_semimarkov: NOT_APPLICABLE_NO_LEARNED_WEIGHTS
  local_joint_from_scratch: UNAVAILABLE_NOT_PERSISTED
  shared_hfwm_multitask: UNAVAILABLE_NOT_PERSISTED
  hgbr_cqr: UNAVAILABLE_NOT_PERSISTED
historical_weight_equivalence_test: INCONCLUSIVE_WITHOUT_REFIT
allowed_evidence_use: INTERNAL_ARCHAEOLOGY_ONLY
robustness_claim_allowed: false
fundraising_evidence_allowed: false
```

Cette limite n'est pas réparée par un hash de configuration. La décision humaine M3D.1
confirme qu'elle **ne bloque pas** la revue documentaire partenaire : le paquet externe ne
revendique aucune robustesse inter-seeds M2. Le déterminisme M2 reste une affirmation par
conception, non une égalité de poids vérifiée ; il est interdit de le citer comme preuve de
robustesse, y compris en levée de fonds. Le rejeu des fits appartient au ticket séparé
`HFWM_R0_M2_SEED_AUDIT_TICKET.md`.

## Nomenclature figée pour M3

- `weights_hash` : seulement poids/paramètres appris, sérialisés canoniquement ;
- `configuration_hash` : configuration complète, seed inclus ;
- `prediction_hash` : sorties non arrondies seulement ;
- `simulation_output_hash` : sorties Monte-Carlo canoniques, hors champ de hash lui-même ;
- `model_hash` non qualifié : interdit s'il inclut seed, données ou configuration.

Tout run futur doit persister avant d'être recevable : configuration canonique, seed,
poids ou paramètres appris canoniques, prédictions non arrondies et leurs quatre hashes
séparés. L'absence de `weights_hash` est un hard fail de preuve pour le run futur.

Le test M3D démontre que changer uniquement le seed modifie
`configuration_hash`, sans modifier `weights_hash` à poids constants. La simulation de
puissance n'est recevable que si son assertion de reachability reste verte.

## Incidence scientifique

La mention « 0/3 seeds favorables » n'est pas une preuve et ne doit plus être utilisée.
M2 conserve sa décision procédurale fondée sur le point estimate gelé ; la répétition de
labels n'ajoute aucune précision. M3 alloue la variance et le budget à des sites, blocs
temporels et épisodes réellement distincts.
