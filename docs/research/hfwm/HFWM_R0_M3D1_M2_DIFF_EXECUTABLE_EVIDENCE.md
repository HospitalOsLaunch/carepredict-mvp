# HFWM-R0 M3D.1 — preuve exécutable des diffs M2 sensibles

Cette attestation est post-tag et ne modifie pas A3, B3 ni le tag.

## `preregistration.py`

- Commit d'introduction observé : `6cd4819ef342a2382213b5f51b0f4dde634fe7fa`.
- Auteur/message/date : `belaguy007`, `chore(hfwm): freeze M3D.1 release content`,
  `2026-08-29T15:10:49+02:00`.
- Diff exact : `git diff --unified=3 6cd4819^ 6cd4819 --
  src/hfwm/evaluation/preregistration.py` (94 lignes ajoutées, 10 supprimées),
  conservé dans `artifacts/hfwm-r0/m3d/m2-preregistration.diff` avec SHA-256
  `b518a4f3109927e1e4424a8a1e8e2c718d281211442672c7948acd55b77c33f6`.
- Nature observée : budgets CPU, `runs_per_seed`, périmètre de budget, validation
  M2A bornée, cohérence TSFM et cross-document. Aucun import de modèle et aucune
  écriture de poids/predictions/rollout.
- Comparaison exécutable : l'ancien validateur retourne `valid=false` avec 3 erreurs
  sur le contrat M2A ; le validateur A3 retourne `valid=true`, avec le même
  `manifest_sha256=384c4e5ae707edabcf19523b5fd782f4301ca405722aa71fab31d90e141c37e6`.
- Axes de classification : `fit_output_impact: NONE_DEMONSTRATED`,
  `preregistration_gate_semantics_impact: MATERIAL`,
  `temporal_relation_to_m2_execution: UNRESOLVED`,
  `m2_preregistration_conformance_at_execution: NOT_PROVEN`. La modification
  change l'autorisation/pré-enregistrement et peut changer l'acceptation d'un
  manifeste invalide ; voir l'audit de gate pour les trois messages littéraux.

## `local/model.py`

- Même commit d'introduction et même auteur/message/date.
- Diff exact : `git diff --unified=3 6cd4819^ 6cd4819 --
  src/hfwm/models/local/model.py` (52 lignes ajoutées, aucune suppression),
  conservé dans `artifacts/hfwm-r0/m3d/m2-local-model.diff` avec SHA-256
  `527266fea5b68f8ab40ba133fed8bba145349711670800b7b8d25b4414106d79`.
- Nature observée : ajout de `fitted_state()` et `restore_fitted_state()` uniquement.
  Les corps de `fit`, `predict_next`, `rollout` et `sample_futures` sont inchangés.
- Comparaison parent/A3 sur les mêmes données synthétiques, configuration et état :
  `backbone_hash=846c5b192abf1e9d426ca72a68a01f0064c1395112b7ce99c42c78ea3bf5322c`,
  `predict_hash=8760b67673de9948717eb28df936b04a3f7be1969b639f25a28c7fda7078c010`,
  `rollout_hash=f054657dc1cf65d07baab151d5ab7131b1b16a6f0489e809f5189aafe614751f`,
  `uncertainty_hash=a17f8f07b5106de29d08437699d531cb5d08adeba66a5bbe00fa84cb44bed6a6`.
- Test A3 de round-trip `fitted_state()`/`restore_fitted_state()` : `PASS` ; les
  tableaux `predict_next`, `rollout` et incertitude sont identiques.
- Axes de classification : `fit_output_impact: NONE_DEMONSTRATED` sur les
  chemins testés ; la relation temporelle à M2 et la conformité du validateur
  restent `UNRESOLVED` et `NOT_PROVEN`. Aucun poids M2 historique n'est
  reconstitué.

## Limite obligatoire

`M2_CODE_STATE_NOT_FULLY_RECOVERABLE` reste inchangé : les poids exécutés par M2 ne
  sont pas persistés. Les résultats M2 sont historiques. Le narratif autorisé est
  celui du manifeste B3 ; aucun claim robuste d'échec ou de succès d'un world model
  n'est ajouté.

Commandes et sorties détaillées sont conservées dans `/private/tmp` :
`/private/tmp/m2_prereg_parent.log`, `/private/tmp/m2_prereg_a3.log`,
`/private/tmp/m2_local_parent.log`, `/private/tmp/m2_local_a3.log` et
`/private/tmp/a3_local_roundtrip.log`.
