# HFWM-R0 M1A — point-in-time data-slice evidence

## Candidat construit

- Slice : `HFWM-R0-D0-SYNTHETIC-PIT`.
- Source unique : `hfwm_r0_internal_synthetic_fixture`, autorisée uniquement par la mission pour l'évaluation locale. Il ne s'agit pas de données hospitalières réelles et aucun claim d'externalité n'est permis.
- Grain : horaire ; horizon : 6 heures.
- Targets conjointes : occupation en fin d'horizon et somme des entrées sur l'horizon.
- 240 exemples : 168 train, 36 validation, 36 test ; 60 épisodes affectés avant le fenêtrage.
- Hash logique du dataset : `64e831ec1a3fbf6fdad2bd0ac716b675619216d3b4c180895ac6acdba2bbb965`.

Le builder compose le contrat `CanonicalEvent`, le ledger append-only et ses snapshots. Chaque feature provient d'un snapshot limité par `event_time <= as_of` et `available_at <= as_of`. Les labels proviennent strictement de `(as_of, as_of + 6h]`. Le build refuse une fuite temporelle, une contamination inter-split, une affectation de fenêtre incohérente ou deux épisodes qui se chevauchent dans une même unité.

## Artefacts

| Fichier | SHA-256 du fichier |
|---|---|
| `artifacts/hfwm-r0/data-slice/dataset.json` | `0665833d32b435324d1a8951474922ae0e5c4e677901089629f960705b8c8113` |
| `artifacts/hfwm-r0/data-slice/dataset_manifest.json` | `4b8a50d3719c654ea160fc1d788997c602429634bf657f1e30e5a2a771149b46` |
| `artifacts/hfwm-r0/data-slice/split_manifest.json` | `e5752e8eb349ac9493d9f2ea6dc4b185441803a62d8d609c0b0173435b79ded7` |
| `artifacts/hfwm-r0/data-slice/temporal_leakage_report.json` | `68520c4cd808d9250f805e176ff86f13a990db0bc3d65ea2de00fca5a7cdf082` |

Le manifest contient source, licence, période `2024-01-01`–`2025-05-07`, trois unités synthétiques, contrats temporels et versions de transformation. Le rapport de fuite est `PASS` avec zéro violation temporelle, zéro chevauchement et zéro contamination inter-split.

## Reproduction et gates observés

Commande unique :

```text
PYTHONPATH=src python scripts/hfwm/build_data_slice.py --output-dir artifacts/hfwm-r0/data-slice
```

Deux exécutions indépendantes ont produit le même hash logique et des quatre fichiers identiques octet par octet. Gate intégré : 42 tests réussis ; Ruff réussi ; Mypy strict réussi sur 19 fichiers. Les tests obligatoires `deterministic_dataset_build`, `temporal_leakage` et `split_before_windowing` sont présents et verts. Deux cycles de correction ont été consommés, uniquement pour les contrôles statiques. Aucun téléchargement, entraînement, subagent, modèle ou modification HGBR/CQR.

`HFWM_R0_DATA_FOUNDATION_READY`
