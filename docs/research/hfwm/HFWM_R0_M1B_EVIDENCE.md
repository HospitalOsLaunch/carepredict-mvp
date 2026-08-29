# HFWM-R0 M1B — minimal candidate evidence

## Candidat exécuté

- Identifiant : `hfwm-r0-m1b-local-joint-ridge`.
- Famille réutilisée : `LocalJointDynamicsModel`, ridge multivarié CPU fermé.
- Périmètre : `synthetic-site-0-0`, 14 épisodes train, 3 validation et 3 test.
- Dataset : `64e831ec1a3fbf6fdad2bd0ac716b675619216d3b4c180895ac6acdba2bbb965`.
- Variables jointes : occupation et entrées, pas de 6 heures.
- Rollout : quatre pas free-running, soit 24 heures.
- Incertitude : variance résiduelle gaussienne, propagée et croissante avec l'horizon.
- Paramètres : 18 ; seed : 1729 ; entraînement CPU observé : 0,047 s.
- Hash du modèle : `29ea5b8306e564f9e489ab919fcea91bdbc384b37e91b9db7c2d1789c7b81484`.

Le candidat infère un `BeliefState` causal à partir de la dernière observation point-in-time et de son processus d'enregistrement. Il prédit les deux variables ensemble. Son checkpoint JSON canonique est restauré et son identité est vérifiée avant acceptation du run. Il s'agit d'un candidat expérimental sur fixture synthétique, pas d'un world model démontré.

## Résultats test observés

| Mesure | Teacher-forcing | Free-running, 4 pas |
|---|---:|---:|
| MAE agrégée | 2,5218 | 2,5727 |
| RMSE agrégée | 3,1039 | 3,1284 |
| MAE occupation | 2,9397 | 2,7067 |
| MAE entrées | 2,1039 | 2,4387 |
| Couverture intervalle 90 % | 0,7917 | 0,8750 |
| Écart-type prédictif moyen | 2,4915 | 3,6972 |
| Taux de sorties non finies | 0 | 0 |

MAE free-running par pas : `1,5956`, `2,9727`, `2,3016`, `3,4210`. Ces chiffres décrivent seulement les trois épisodes test synthétiques du site choisi ; aucune comparaison de modèle ni revendication d'efficacité opérationnelle n'est faite.

## Artefacts et identité

| Fichier | SHA-256 du fichier |
|---|---|
| `configs/hfwm/r0_m1b_minimal.yaml` | `e3700b5807dbf60c5ba4506391f0336a3d53d25080ffa394c17607935b820bed` |
| `artifacts/hfwm-r0/backbone/checkpoint.json` | `9f3e9284e85ecf7afba12e9bee9a074c09fddf0c27e3cb2ff165ec2a330e32c4` |
| `artifacts/hfwm-r0/backbone/metrics.json` | `bde3a92bdd09a2fbc40f8ddf456a66f1b39d4b9a244924fb0c8131fb0a24d106` |
| `artifacts/hfwm-r0/backbone/training_manifest.json` | `f9932f5f04d6725fe60c1859230d8dbd50661da39f0970a2b49be2fc4f9e00b4` |

Le manifest relie dataset, config, seed, modèle, checkpoint, métriques, versions Python/Numpy et hashes des fichiers de code. Checkpoint logique : `372198d6a3470f97786471655e6d73233312705869bea1b0340fac28359f4b33`.

## Commandes et gates

Smoke-test et reproduction du candidat :

```text
PYTHONPATH=src python scripts/hfwm/train_minimal_candidate.py --config configs/hfwm/r0_m1b_minimal.yaml --output-dir artifacts/hfwm-r0/backbone
```

Test de reproductibilité :

```text
PYTHONPATH=src pytest -p no:cacheprovider tests/hfwm/candidate/test_training.py -q
```

Deux entraînements contrôlés ont produit le même hash de modèle, le même checkpoint et les mêmes métriques prédictives ; seule la durée CPU est exclue de l'égalité. Gate intégré observé : 50 tests réussis, Ruff réussi, Mypy strict réussi sur 26 fichiers. Un cycle de correction statique consommé. Aucun sous-ensemble réduit, HPO, bake-off, reviewer ou action-conditioning.

`HFWM_R0_BACKBONE_READY_FOR_REVIEW`
